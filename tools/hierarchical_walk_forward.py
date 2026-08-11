"""市场 -> 板块 -> 个股的月度 walk-forward 与消融评估。

输出的模型默认是 shadow。walk-forward 只形成研究证据和完整策略候选，
无权直接改变生产策略。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.factor_lib import FactorContext  # noqa: E402
from utils.csv_manager import CSVManager  # noqa: E402
from utils.decision_ledger import (  # noqa: E402
    model_artifact_hash,
    register_model,
    register_policy_candidate,
)
from utils.decision_versions import FEATURE_VERSION, git_commit_sha, strategy_version  # noqa: E402
from utils.execution_model import (  # noqa: E402
    DEFAULT_EXECUTION_POLICY,
    evaluate_trade,
    execution_policy_manifest,
    load_exchange_sessions,
)
from utils.market_filter import is_main_board, main_board_only  # noqa: E402
from utils.policy_engine import evaluate_policy, policy_manifest  # noqa: E402
from utils.probability_model import (  # noqa: E402
    BinaryLogit,
    ModelFitError,
    population_stability_index,
    probability_metrics,
)
from utils.reference_snapshots import (  # noqa: E402
    load_reference_snapshots,
    validated_snapshot_payload,
)

logger = logging.getLogger(__name__)

MARKET_FEATURES = [
    "market_ret_1",
    "market_ret_5",
    "market_ret_20",
    "market_breadth",
    "market_amount_ratio",
    "market_limit_down_ratio",
    "market_vs_ma20",
    "market_vs_ma60",
]
SECTOR_FEATURES = [
    "sector_rel_1",
    "sector_rel_5",
    "sector_breadth",
    "sector_amount_ratio",
    "sector_dispersion",
    "sector_members",
]
STOCK_FEATURES = [
    "stock_pct",
    "stock_j",
    "stock_rsi",
    "stock_vol_ratio",
    "stock_vs_ma20",
    "stock_vs_ma60",
    "stock_vs_peak60",
    "stock_position20",
    "stock_amplitude",
]
DATASET_SCHEMA_VERSION = 8
MIN_REFERENCE_COVERAGE = 0.60
MIN_DAILY_SNAPSHOT_COVERAGE = 1.0
BOOTSTRAP_ITERATIONS = 10_000
FAMILYWISE_POSITIVE_PROBABILITY = 0.9875
QUALITY_TARGET_VERSION = "after-cost-open-open-vs-cash-v1"
REQUIRED_DATASET_COLUMNS = (
    {
        "dataset_schema_version",
        "date",
        "label_end_date",
        "code",
        "industry",
        "reference_snapshot_date",
        "reference_snapshot_id",
        "feature_snapshot_id",
        "label_snapshot_id",
        "label_snapshot_date",
        "quality_target_version",
        "universe_coverage",
        "weekly_passed",
        "execution_status",
        "execution_policy_version",
        "entry_label_mature",
        "exit_label_mature",
        "return_label_mature",
        "entry_feasible",
        "exit_feasible",
        "y_entry_risk",
        "y_exit_risk",
        "net_return_5",
        "excess_5",
        "y_quality",
        "y_risk",
    }
    | set(MARKET_FEATURES)
    | set(SECTOR_FEATURES)
    | set(STOCK_FEATURES)
)
MIN_REFERENCE_MONTHS = 21
FINAL_CALIBRATION_MONTHS = 3
DEFAULT_MIN_TRAIN_MONTHS = 12
DEFAULT_VALIDATION_MONTHS = 3
MIN_WALK_FORWARD_TRAIN_ROWS = 80
MIN_WALK_FORWARD_VALIDATION_ROWS = 20
MIN_WALK_FORWARD_TEST_ROWS = 3
MIN_MARKET_TRAINING_UNITS = 40
MIN_SECTOR_TRAINING_UNITS = 40
MIN_FINAL_TRAIN_ROWS = 80
MIN_FINAL_CALIBRATION_ROWS = 20
MODEL_KEYS = ("market", "sector", "entry_risk", "exit_risk", "quality")
PIT_FEATURE_LEDGER_SCHEMA_VERSION = "super-b1-pit-feature-ledger-v2"
PIT_FEATURE_SHARD_SEAL_SCHEMA_VERSION = "super-b1-pit-feature-shard-seal-v1"
PIT_SNAPSHOT_COHORT_VERSION = "latest-contiguous-full-month-suffix-v1"


@lru_cache(maxsize=1)
def pit_feature_ledger_version() -> str:
    """绑定所有会改变 PIT 特征或扫描宇宙的源码、配置与依赖。"""
    project_root = Path(__file__).resolve().parents[1]
    paths = [
        Path(__file__).resolve(),
        project_root / "utils" / "technical.py",
        project_root / "utils" / "market_filter.py",
        project_root / "utils" / "csv_manager.py",
        project_root / "config" / "strategy_params.yaml",
        project_root / "requirements.lock",
        *sorted((project_root / "strategy").rglob("*.py")),
    ]
    digest = hashlib.sha256(PIT_FEATURE_LEDGER_SCHEMA_VERSION.encode())
    for path in sorted(set(paths)):
        digest.update(path.relative_to(project_root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"{PIT_FEATURE_LEDGER_SCHEMA_VERSION}-{digest.hexdigest()[:20]}"


PIT_FEATURE_COLUMNS = [
    "dataset_schema_version",
    "date",
    "code",
    "name",
    "industry",
    "reference_snapshot_date",
    "reference_snapshot_id",
    "feature_snapshot_id",
    "feature_ledger_version",
    "universe_coverage",
    "weekly_passed",
    "weekly_aligned",
    "weekly_rising_count",
    "b1_signals",
    *MARKET_FEATURES,
    *SECTOR_FEATURES,
    *STOCK_FEATURES,
]


def _read_stock(cm: CSVManager, code: str, industry: str) -> pd.DataFrame | None:
    df = cm.read_stock(code)
    if df is None or len(df) < 220:
        return None
    d = df.copy().sort_values("date").reset_index(drop=True)
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close", "volume"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["open", "high", "low", "close"])
    d["code"], d["industry"] = code, industry or "未知"
    d["ret1"] = d["close"].pct_change()
    d["amount_proxy"] = d["close"] * d["volume"].fillna(0)
    return d


def build_panels(
    cm: CSVManager,
    codes: list[str],
    industry_map: dict,
    reference_snapshots: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if main_board_only():
        codes = [code for code in codes if is_main_board(code)]
    frames, stock_frames = [], {}
    with ThreadPoolExecutor(max_workers=min(12, max(1, len(codes)))) as pool:
        loaded = pool.map(
            lambda c: (c, _read_stock(cm, c, industry_map.get(c, ""))), codes
        )
        for code, frame in loaded:
            if frame is not None:
                stock_frames[code] = frame
                frames.append(
                    frame[["date", "code", "industry", "ret1", "amount_proxy"]]
                )
    if not frames:
        return pd.DataFrame(), pd.DataFrame(), stock_frames
    panel = pd.concat(frames, ignore_index=True).dropna(subset=["ret1"])

    if reference_snapshots is not None:
        dated = []
        for date, group in panel.groupby("date", sort=False):
            snapshot = reference_snapshots.get(str(date))
            if not snapshot:
                continue
            universe = {
                str(code)
                for code in snapshot.get("_universe_set")
                or snapshot.get("universe")
                or []
                if not main_board_only() or is_main_board(str(code))
            }
            if not universe:
                continue
            current = group[group["code"].isin(universe)].copy()
            coverage = current["code"].nunique() / len(universe)
            if coverage < MIN_REFERENCE_COVERAGE:
                continue
            industries = snapshot.get("industries") or {}
            current["industry"] = current["code"].map(industries).fillna("未知")
            current["universe_coverage"] = float(coverage)
            dated.append(current)
        if not dated:
            return pd.DataFrame(), pd.DataFrame(), stock_frames
        panel = pd.concat(dated, ignore_index=True)
    else:
        panel["universe_coverage"] = 1.0

    market = (
        panel.groupby("date")
        .agg(
            market_ret_1=("ret1", "mean"),
            market_breadth=("ret1", lambda s: float((s > 0).mean())),
            market_amount=("amount_proxy", "sum"),
            market_limit_down_ratio=("ret1", lambda s: float((s <= -0.095).mean())),
            market_universe_coverage=("universe_coverage", "first"),
        )
        .sort_index()
    )
    market["market_index"] = (1 + market["market_ret_1"]).cumprod()
    market["market_ret_5"] = market["market_index"].pct_change(5)
    market["market_ret_20"] = market["market_index"].pct_change(20)
    market["market_amount_ratio"] = (
        market["market_amount"].rolling(5).mean()
        / market["market_amount"].rolling(20).mean()
    )
    market["market_vs_ma20"] = (
        market["market_index"] / market["market_index"].rolling(20).mean() - 1
    )
    market["market_vs_ma60"] = (
        market["market_index"] / market["market_index"].rolling(60).mean() - 1
    )

    sector = (
        panel.groupby(["industry", "date"])
        .agg(
            sector_ret_1=("ret1", "mean"),
            sector_breadth=("ret1", lambda s: float((s > 0).mean())),
            sector_amount=("amount_proxy", "sum"),
            sector_dispersion=("ret1", "std"),
            sector_members=("ret1", "size"),
        )
        .reset_index()
        .sort_values(["industry", "date"])
    )
    sector = sector.merge(
        market[["market_ret_1", "market_amount"]], left_on="date", right_index=True
    )
    sector["sector_rel_1"] = sector["sector_ret_1"] - sector["market_ret_1"]
    sector["sector_rel_5"] = sector.groupby("industry")["sector_rel_1"].transform(
        lambda s: s.rolling(5).sum()
    )
    sector["sector_share"] = sector["sector_amount"] / sector["market_amount"]
    sector["sector_amount_ratio"] = sector.groupby("industry")[
        "sector_share"
    ].transform(lambda s: s.rolling(5).mean() / s.rolling(20).mean())
    sector = sector.set_index(["date", "industry"])
    return market, sector, stock_frames


def _stock_features(ctx: FactorContext) -> dict:
    c = float(ctx.C.iloc[-1])
    ma20, ma60 = float(ctx.ma(20).iloc[-1]), float(ctx.ma(60).iloc[-1])
    _, _, j = ctx.kdj()
    peak60 = float(ctx.H.iloc[-60:].max())
    low20, high20 = float(ctx.L.iloc[-20:].min()), float(ctx.H.iloc[-20:].max())
    vol5 = float(ctx.V.iloc[-6:-1].mean())
    return {
        "stock_pct": float(ctx.pct_change().iloc[-1]) / 100,
        "stock_j": float(j.iloc[-1]),
        "stock_rsi": float(ctx.rsi_tdx(6).iloc[-1]),
        "stock_vol_ratio": float(ctx.V.iloc[-1]) / vol5 if vol5 > 0 else np.nan,
        "stock_vs_ma20": c / ma20 - 1 if ma20 > 0 else np.nan,
        "stock_vs_ma60": c / ma60 - 1 if ma60 > 0 else np.nan,
        "stock_vs_peak60": c / peak60 - 1 if peak60 > 0 else np.nan,
        "stock_position20": (c - low20) / (high20 - low20) if high20 > low20 else 0.5,
        "stock_amplitude": float(ctx.H.iloc[-1] / ctx.L.iloc[-1] - 1)
        if ctx.L.iloc[-1] > 0
        else np.nan,
    }


def _features_one(args) -> list[dict]:
    """只固化当日可见特征，不在这一步读取未来成交结果。"""
    code, name, frame, market, sector, snapshot, feature_snapshot_id, date = args
    from strategy.super_b1 import compute_super_b1
    from utils.technical import weekly_four_ma_bullish

    cap = (snapshot.get("market_caps") or {}).get(code)
    if not isinstance(cap, (int, float)) or cap <= 0:
        return []
    sub = frame[frame["date"] <= date].copy()
    if sub.empty or str(sub.iloc[-1]["date"])[:10] != date:
        return []
    hit = compute_super_b1(sub, code, market_cap=float(cap))
    if not isinstance(hit, dict) or not hit.get("signals") or hit.get("date") != date:
        return []
    industry = (snapshot.get("industries") or {}).get(code) or "未知"
    if date not in market.index or (date, industry) not in sector.index:
        return []
    ctx = FactorContext(sub)
    weekly_passed, weekly_detail = weekly_four_ma_bullish(sub)
    m = market.loc[date]
    s = sector.loc[(date, industry)]
    record = {
        "date": date,
        "code": code,
        "name": name,
        "industry": industry,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "reference_snapshot_date": date,
        "reference_snapshot_id": snapshot.get("market_snapshot_id"),
        "feature_snapshot_id": feature_snapshot_id,
        "feature_ledger_version": pit_feature_ledger_version(),
        "universe_coverage": float(market.loc[date, "market_universe_coverage"]),
        "weekly_passed": int(weekly_passed),
        "weekly_aligned": int(bool(weekly_detail.get("aligned"))),
        "weekly_rising_count": int(weekly_detail.get("rising_count", 0)),
        "b1_signals": "|".join(hit.get("signals") or []),
    }
    record.update({key: float(m.get(key, np.nan)) for key in MARKET_FEATURES})
    record.update({key: float(s.get(key, np.nan)) for key in SECTOR_FEATURES})
    record.update(_stock_features(ctx))
    return [record]


def _feature_shard_path(
    data_root: Path, date: str, snapshot_id: str, *, limit: int = 0
) -> Path:
    ledger_root = pit_feature_ledger_version()
    if limit:
        ledger_root = f"{ledger_root}-debug-limit-{int(limit)}"
    return (
        data_root
        / "research_artifacts"
        / "model_evolution"
        / "pit_feature_ledger"
        / ledger_root
        / date
        / snapshot_id
        / "features.csv"
    )


def _feature_shard_seal_path(path: Path) -> Path:
    return path.parent / "manifest.json"


def _read_feature_shard_content(
    path: Path, date: str, snapshot_id: str
) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, dtype={"code": str})
    except (OSError, pd.errors.EmptyDataError) as exc:
        raise ValueError(f"PIT 特征分片不可读: {path}") from exc
    missing = set(PIT_FEATURE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"PIT 特征分片缺列: {sorted(missing)}")
    if list(frame.columns) != PIT_FEATURE_COLUMNS:
        raise ValueError(f"PIT 特征分片 schema 冲突: {path}")
    if frame.empty:
        return frame[PIT_FEATURE_COLUMNS]
    if not (
        (frame["date"].astype(str).str[:10] == date).all()
        and (frame["reference_snapshot_date"].astype(str).str[:10] == date).all()
        and (
            frame["reference_snapshot_id"].astype(str).str.lower() == snapshot_id
        ).all()
        and (frame["feature_snapshot_id"].astype(str).str.lower() == snapshot_id).all()
        and (
            frame["feature_ledger_version"].astype(str) == pit_feature_ledger_version()
        ).all()
        and (
            pd.to_numeric(frame["dataset_schema_version"], errors="coerce")
            == DATASET_SCHEMA_VERSION
        ).all()
    ):
        raise ValueError(f"PIT 特征分片身份冲突: {path}")
    return frame[PIT_FEATURE_COLUMNS]


def _canonical_feature_shard_bytes(frame: pd.DataFrame) -> bytes:
    canonical = frame[PIT_FEATURE_COLUMNS].copy()
    if not canonical.empty:
        canonical = canonical.sort_values(["date", "code"], kind="stable").reset_index(
            drop=True
        )
    return canonical.to_csv(
        index=False,
        float_format="%.17g",
        lineterminator="\n",
        na_rep="",
    ).encode("utf-8")


def _feature_shard_seal(frame: pd.DataFrame, date: str, snapshot_id: str) -> dict:
    canonical = _canonical_feature_shard_bytes(frame)
    sorted_codes = "\n".join(sorted(frame["code"].astype(str).tolist())).encode("utf-8")
    return {
        "schema_version": PIT_FEATURE_SHARD_SEAL_SCHEMA_VERSION,
        "ledger_schema_version": PIT_FEATURE_LEDGER_SCHEMA_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "feature_ledger_version": pit_feature_ledger_version(),
        "date": date,
        "reference_snapshot_id": snapshot_id,
        "feature_snapshot_id": snapshot_id,
        "row_count": int(len(frame)),
        "sorted_codes_sha256": hashlib.sha256(sorted_codes).hexdigest(),
        "canonical_content_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def _read_feature_shard(path: Path, date: str, snapshot_id: str) -> pd.DataFrame:
    """读取并验证不可变 PIT 特征分片。

    身份字段只能证明“这是哪天的分片”；seal 还要证明行数、
    股票集合与每个特征值都未在落盘后变化。零信号日也必须有 seal。
    """
    frame = _read_feature_shard_content(path, date, snapshot_id)
    seal_path = _feature_shard_seal_path(path)
    try:
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"PIT 特征分片缺少可验证 seal: {path}") from exc
    expected = _feature_shard_seal(frame, date, snapshot_id)
    mismatched = sorted(
        key for key, value in expected.items() if seal.get(key) != value
    )
    if mismatched:
        raise ValueError(f"PIT 特征分片 seal 冲突: {path}; fields={mismatched}")
    return frame


def _commit_feature_shard(
    frame: pd.DataFrame,
    target: Path,
    date: str,
    snapshot_id: str,
    guard: Callable[[], None],
) -> tuple[pd.DataFrame, str]:
    """在隐藏 generation 目录生成 CSV+seal，再一次原子发布目录。"""
    generation_dir = target.parent
    generation_parent = generation_dir.parent
    generation_parent.mkdir(parents=True, exist_ok=True)
    seal_path = _feature_shard_seal_path(target)
    temporary_dir = generation_parent / (
        f".{generation_dir.name}.{uuid4().hex}.generation"
    )
    temporary_dir.mkdir()
    temporary = temporary_dir / target.name
    temporary_seal = temporary_dir / seal_path.name
    try:
        frame.to_csv(temporary, index=False)
        staged = _read_feature_shard_content(temporary, date, snapshot_id)
        staged_seal = _feature_shard_seal(staged, date, snapshot_id)
        temporary_seal.write_text(
            json.dumps(staged_seal, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        guard()
        target_exists = target.exists()
        seal_exists = seal_path.exists()
        if target_exists and seal_exists:
            existing = _read_feature_shard(target, date, snapshot_id)
            if _feature_shard_seal(existing, date, snapshot_id) != staged_seal:
                raise ValueError(f"PIT 特征分片并发冲突: {target}")
            return existing, "existing"
        if target_exists:
            partial_frame = _read_feature_shard_content(target, date, snapshot_id)
            if _feature_shard_seal(partial_frame, date, snapshot_id) != staged_seal:
                raise ValueError(f"PIT 特征分片单边内容冲突: {target}")
        elif seal_exists:
            try:
                partial_seal = json.loads(seal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"PIT 特征分片单边 seal 不可验证: {target}") from exc
            if partial_seal != staged_seal:
                raise ValueError(f"PIT 特征分片单边 seal 冲突: {target}")
        elif generation_dir.exists():
            raise ValueError(f"PIT 特征 generation 为空: {target}")
        if generation_dir.exists():
            # 兼容修复旧实现在 CSV/seal 两步提交间掉电留下的单边产物。
            # 完整 pair 已在上面校验；只有不完整 generation 才允许隔离重建。
            partial_dir = generation_parent / (
                f".{generation_dir.name}.{uuid4().hex}.partial"
            )
            guard()
            generation_dir.replace(partial_dir)
        guard()
        temporary_dir.replace(generation_dir)
        return _read_feature_shard(target, date, snapshot_id), "materialized"
    finally:
        temporary.unlink(missing_ok=True)
        temporary_seal.unlink(missing_ok=True)
        try:
            temporary_dir.rmdir()
        except OSError:
            pass


def _snapshot_manager(
    data_root: Path,
    snapshot_id: str,
    *,
    reference: dict | None = None,
) -> CSVManager | None:
    from utils.market_snapshot import load_market_snapshot

    payload = validated_snapshot_payload(reference, data_root, snapshot_id)
    if payload is None:
        loaded = load_market_snapshot(data_root, snapshot_id, verify_files=True)
        if not loaded.get("available"):
            return None
        payload = Path(loaded["payload_dir"])
    manager = CSVManager(data_root, resolve_snapshot=False, writable=False)
    manager.data_dir = payload
    manager.snapshot_id = snapshot_id
    manager.read_only = True
    return manager


def _materialize_feature_shard(
    data_root: Path,
    date: str,
    snapshot: dict,
    *,
    limit: int = 0,
    commit_guard: Callable[[], None] | None = None,
) -> tuple[pd.DataFrame | None, str]:
    guard = commit_guard or (lambda: None)
    snapshot_id = str(snapshot.get("market_snapshot_id") or "").lower()
    if not snapshot_id or len(snapshot_id) != 64:
        return None, "invalid_snapshot_id"
    target = _feature_shard_path(data_root, date, snapshot_id, limit=limit)
    if target.exists() and _feature_shard_seal_path(target).exists():
        return _read_feature_shard(target, date, snapshot_id), "existing"

    manager = _snapshot_manager(data_root, snapshot_id, reference=snapshot)
    if manager is None:
        return None, "market_snapshot_unavailable"
    from utils.market_snapshot import read_snapshot_metadata

    names, names_snapshot_id = read_snapshot_metadata(
        "stock_names.json", data_root, snapshot_id=snapshot_id
    )
    if not isinstance(names, dict) or names_snapshot_id != snapshot_id:
        return None, "snapshot_names_unavailable"
    industries = snapshot.get("industries") or {}
    universe = snapshot.get("_universe_set") or set(snapshot.get("universe") or [])
    codes = [code for code in manager.list_all_stocks() if code in universe]
    if main_board_only():
        codes = [code for code in codes if is_main_board(code)]
    if limit:
        codes = codes[:limit]
    market, sector, stock_frames = build_panels(
        manager,
        codes,
        industries,
        reference_snapshots=None,
    )
    if market.empty or sector.empty:
        return None, "snapshot_panel_unavailable"
    tasks = [
        (
            code,
            names.get(code, code),
            frame,
            market,
            sector,
            snapshot,
            snapshot_id,
            date,
        )
        for code, frame in stock_frames.items()
    ]
    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(tasks)))) as pool:
        for result in pool.map(_features_one, tasks):
            rows.extend(result)
    shard = pd.DataFrame(rows, columns=PIT_FEATURE_COLUMNS)
    if not shard.empty:
        shard = shard.sort_values(["date", "code"]).reset_index(drop=True)
    guard()
    return _commit_feature_shard(shard, target, date, snapshot_id, guard)


def latest_complete_snapshot_cohort(
    snapshots: dict[str, dict],
    trading_sessions: list[str],
) -> tuple[dict[str, dict], dict]:
    """选取最新连续快照后缀，并从第一个完整自然交易月开始。

    缺失日之前的快照仍留在不可变目录中供审计，但不参与当前训练。
    如果连续后缀从月中开始，该月剩余会话也不参与训练；
    只有从交易所日历中该月第一个会话就有快照的自然月才能成为起点。
    """
    normalized = {str(date)[:10]: snapshot for date, snapshot in snapshots.items()}
    sessions = sorted(set(str(date)[:10] for date in trading_sessions))
    session_indexes = {date: index for index, date in enumerate(sessions)}
    observed_sessions = sorted(
        (date for date in normalized if date in session_indexes),
        key=session_indexes.__getitem__,
    )
    unexpected = sorted(set(normalized) - set(session_indexes))

    def evidence(
        *,
        reason: str,
        raw_suffix: list[str] | None = None,
        cohort_dates: list[str] | None = None,
        last_gap_session: str | None = None,
    ) -> dict:
        raw_suffix = raw_suffix or []
        cohort_dates = cohort_dates or []
        cohort_set = set(cohort_dates)
        excluded_dates = sorted(set(normalized) - cohort_set)
        return {
            "version": PIT_SNAPSHOT_COHORT_VERSION,
            "complete": bool(cohort_dates),
            "reason": reason,
            "catalog_snapshot_count": len(normalized),
            "eligible_session_snapshot_count": len(observed_sessions),
            "cohort_snapshot_count": len(cohort_dates),
            "cohort_months": len({date[:7] for date in cohort_dates}),
            "cohort_first_session": cohort_dates[0] if cohort_dates else None,
            "cohort_last_session": cohort_dates[-1] if cohort_dates else None,
            "raw_suffix_first_session": raw_suffix[0] if raw_suffix else None,
            "raw_suffix_last_session": raw_suffix[-1] if raw_suffix else None,
            "raw_suffix_session_count": len(raw_suffix),
            "trimmed_partial_month_sessions": len(raw_suffix) - len(cohort_dates),
            "last_gap_session": last_gap_session,
            "excluded_catalog_snapshot_count": len(excluded_dates),
            "excluded_catalog_first_date": (
                excluded_dates[0] if excluded_dates else None
            ),
            "excluded_catalog_last_date": excluded_dates[-1]
            if excluded_dates
            else None,
            "unexpected_snapshot_dates": unexpected,
        }

    if not observed_sessions or not sessions:
        return {}, evidence(reason="snapshot_or_calendar_unavailable")

    latest_index = session_indexes[observed_sessions[-1]]
    raw_start_index = latest_index
    while raw_start_index > 0 and sessions[raw_start_index - 1] in normalized:
        raw_start_index -= 1
    raw_suffix = sessions[raw_start_index : latest_index + 1]
    last_gap_session = sessions[raw_start_index - 1] if raw_start_index > 0 else None

    first_session_by_month: dict[str, str] = {}
    for session in sessions:
        first_session_by_month.setdefault(session[:7], session)
    cohort_start = next(
        (
            session
            for session in raw_suffix
            if first_session_by_month.get(session[:7]) == session
        ),
        None,
    )
    if cohort_start is None:
        return {}, evidence(
            reason="complete_natural_month_not_started",
            raw_suffix=raw_suffix,
            last_gap_session=last_gap_session,
        )

    cohort_start_index = session_indexes[cohort_start]
    cohort_dates = sessions[cohort_start_index : latest_index + 1]
    cohort = {date: normalized[date] for date in cohort_dates}
    return cohort, evidence(
        reason="latest_contiguous_suffix_selected",
        raw_suffix=raw_suffix,
        cohort_dates=cohort_dates,
        last_gap_session=last_gap_session,
    )


def materialize_pit_feature_ledger(
    cm: CSVManager,
    *,
    snapshots: dict[str, dict] | None = None,
    limit: int = 0,
    commit_guard: Callable[[], None] | None = None,
) -> dict:
    """从每个不可变日快照中只计算该日特征，形成可追加的 forward ledger。"""
    data_root = Path(getattr(cm, "base_data_dir", cm.data_dir))
    catalog = (
        snapshots if snapshots is not None else load_reference_snapshots(data_root)
    )
    snapshots, snapshot_cohort = latest_complete_snapshot_cohort(
        catalog,
        load_exchange_sessions(cm.data_dir),
    )
    summary: dict = {
        "schema_version": PIT_FEATURE_LEDGER_SCHEMA_VERSION,
        "shard_seal_schema_version": PIT_FEATURE_SHARD_SEAL_SCHEMA_VERSION,
        "version": pit_feature_ledger_version(),
        "snapshots": len(snapshots),
        "snapshot_cohort": snapshot_cohort,
        "materialized": 0,
        "existing": 0,
        "failed": [],
    }
    for date, snapshot in sorted(snapshots.items()):
        try:
            _frame, status = _materialize_feature_shard(
                data_root,
                str(date)[:10],
                snapshot,
                limit=limit,
                commit_guard=commit_guard,
            )
        except Exception as exc:
            logger.warning("PIT 特征分片失败 %s: %s", date, exc)
            summary["failed"].append({"date": date, "reason": str(exc)})
            continue
        if status in {"materialized", "existing"}:
            summary[status] += 1
        else:
            summary["failed"].append({"date": date, "reason": status})
    summary["complete"] = not summary["failed"]
    return summary


def _hydrate_outcomes(
    features: pd.DataFrame,
    cm: CSVManager,
    _industry_map: dict,
    snapshots: dict[str, dict],
) -> pd.DataFrame:
    if features.empty:
        return pd.DataFrame()
    data_root = Path(getattr(cm, "base_data_dir", cm.data_dir))
    ordered_snapshots = sorted(
        (str(date)[:10], snapshot) for date, snapshot in snapshots.items()
    )
    manager_cache: dict[str, CSVManager] = {}
    frame_cache: OrderedDict[tuple[str, str], pd.DataFrame] = OrderedDict()
    session_cache: dict[str, list[str]] = {}
    state_cache: dict[str, dict[str, dict]] = {}
    references_by_id = {
        str(snapshot.get("market_snapshot_id") or "").lower(): snapshot
        for _date, snapshot in ordered_snapshots
    }

    def unavailable(reason: str, **details) -> pd.DataFrame:
        result = pd.DataFrame()
        result.attrs.update({"reason": reason, **details})
        return result

    def snapshot_manager(snapshot_id: str) -> CSVManager | None:
        if snapshot_id not in manager_cache:
            manager = _snapshot_manager(
                data_root,
                snapshot_id,
                reference=references_by_id.get(snapshot_id),
            )
            if manager is not None:
                manager_cache[snapshot_id] = manager
        return manager_cache.get(snapshot_id)

    def security_states(code: str) -> dict[str, dict]:
        if code not in state_cache:
            state_cache[code] = {
                snapshot_date: state
                for snapshot_date, snapshot in ordered_snapshots
                if isinstance(
                    state := (snapshot.get("security_states") or {}).get(code), dict
                )
            }
        return state_cache[code]

    def stock_frame(manager: CSVManager, snapshot_id: str, code: str) -> pd.DataFrame:
        cache_key = (snapshot_id, code)
        cached = frame_cache.get(cache_key)
        if cached is not None:
            frame_cache.move_to_end(cache_key)
            return cached
        frame = manager.read_stock(code)
        frame_cache[cache_key] = frame
        if len(frame_cache) > 256:
            frame_cache.popitem(last=False)
        return frame

    def finite_number(value: object) -> float | None:
        if value is None:
            return None
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    def is_terminal(execution: dict) -> bool:
        if (
            execution.get("entry_label_mature")
            and execution.get("entry_feasible") is False
        ):
            return True
        if execution.get("return_label_mature"):
            if finite_number(execution.get("net_return")) is not None:
                return True
        return bool(
            execution.get("entry_feasible") is True
            and execution.get("exit_label_mature")
            and execution.get("exit_feasible") is False
        )

    def removal_execution(previous: dict | None, removal_date: str) -> dict:
        entry_mature = bool(previous and previous.get("entry_label_mature") is True)
        entry_feasible = (
            previous.get("entry_feasible") if entry_mature and previous else None
        )
        entered = entry_feasible is True
        entry_known = entry_feasible is not None
        return {
            **(previous or {}),
            "available": True,
            "reason": (
                "universe_removed_before_label"
                if entry_known
                else "universe_removed_with_entry_unknown"
            ),
            "execution_status": (
                "universe_removed_before_label"
                if entry_known
                else "universe_removed_with_entry_unknown"
            ),
            "execution_policy_version": DEFAULT_EXECUTION_POLICY.version,
            "entry_label_mature": entry_mature,
            "entry_feasible": entry_feasible,
            "exit_label_mature": entered,
            "exit_feasible": False if entered else None,
            "return_label_mature": False,
            "net_return": None,
            "label_end_date": removal_date,
        }

    def training_row(
        item: dict,
        code: str,
        execution: dict,
        label_snapshot_id: str,
        label_snapshot_date: str,
    ) -> dict:
        net_return = finite_number(execution.get("net_return"))
        return_mature = bool(
            execution.get("return_label_mature") and net_return is not None
        )
        entry_mature = bool(execution.get("entry_label_mature"))
        entry_feasible_raw = execution.get("entry_feasible")
        entry_feasible = entry_feasible_raw is True
        exit_mature = bool(execution.get("exit_label_mature"))
        exit_feasible = execution.get("exit_feasible")
        if entry_mature and entry_feasible_raw is False:
            y_risk: int | float = 1
        elif entry_feasible and exit_mature and exit_feasible is False:
            y_risk = 1
        elif return_mature:
            y_risk = int(
                execution.get("one_word_limit_down_next_open", False)
                or (execution.get("next_open_gap_pct") or 0) <= -7
                or (net_return is not None and net_return <= -10)
            )
        else:
            y_risk = np.nan
        # 质量层使用与个股完全一致的扣费后 open-open 收益，相对现金零收益。
        # 这避免把信号日/退出日收盘后才知道的指数走势混入标签。
        excess = net_return if return_mature and net_return is not None else np.nan
        return {
            **item,
            "code": code,
            "label_end_date": execution.get("label_end_date") or label_snapshot_date,
            "label_snapshot_id": label_snapshot_id,
            "label_snapshot_date": label_snapshot_date,
            "quality_target_version": QUALITY_TARGET_VERSION,
            "execution_status": execution.get("execution_status")
            or execution.get("reason"),
            "execution_policy_version": execution.get("execution_policy_version")
            or DEFAULT_EXECUTION_POLICY.version,
            "entry_label_mature": int(entry_mature),
            "exit_label_mature": int(exit_mature),
            "return_label_mature": int(return_mature),
            "entry_feasible": (
                int(entry_feasible) if entry_feasible_raw is not None else np.nan
            ),
            "exit_feasible": (
                int(bool(exit_feasible)) if exit_feasible is not None else np.nan
            ),
            "net_return_5": net_return if return_mature else np.nan,
            "market_forward_5": 0.0 if return_mature else np.nan,
            "excess_5": excess,
            "y_quality": int(excess > 0) if return_mature else np.nan,
            "y_entry_risk": (
                int(entry_feasible_raw is False) if entry_mature else np.nan
            ),
            "y_exit_risk": (
                int(exit_feasible is False)
                if entry_feasible and exit_mature
                else np.nan
            ),
            "y_risk": y_risk,
        }

    rows: list[dict] = []
    unresolved_mature: list[dict] = []
    global_sessions = load_exchange_sessions(cm.data_dir)
    snapshot_by_date = dict(ordered_snapshots)
    for item in features.to_dict("records"):
        date = str(item["date"])[:10]
        code = str(item["code"]).zfill(6)
        signal_snapshot = snapshots.get(date)
        expected_feature_snapshot = str(
            (signal_snapshot or {}).get("market_snapshot_id") or ""
        ).lower()
        if (
            signal_snapshot is None
            or code not in set(signal_snapshot.get("universe") or [])
            or str(item.get("feature_snapshot_id") or "").lower()
            != expected_feature_snapshot
        ):
            return unavailable(
                "pit_feature_identity_invalid", signal_date=date, code=code
            )

        latest_execution: dict | None = None
        label_snapshot_id = expected_feature_snapshot
        label_snapshot_date = date
        latest_sessions: list[str] = []
        try:
            signal_index = global_sessions.index(date)
        except ValueError:
            unresolved_mature.append(
                {"date": date, "code": code, "reason": "signal_session_missing"}
            )
            continue
        terminal_session_index = (
            signal_index
            + 1
            + DEFAULT_EXECUTION_POLICY.holding_sessions
            + DEFAULT_EXECUTION_POLICY.max_exit_delay_sessions
        )
        terminal_date = (
            global_sessions[terminal_session_index]
            if terminal_session_index < len(global_sessions)
            else None
        )
        last_observed_date = ordered_snapshots[-1][0]
        evidence_dates = [
            snapshot_date
            for snapshot_date, _snapshot in ordered_snapshots
            if date <= snapshot_date <= last_observed_date
        ]
        removal_date = next(
            (
                snapshot_date
                for snapshot_date in evidence_dates
                if (terminal_date is None or snapshot_date <= terminal_date)
                and code
                not in set(snapshot_by_date[snapshot_date].get("universe") or [])
            ),
            None,
        )
        entry_session_index = signal_index + 1
        target_session_index = (
            entry_session_index + DEFAULT_EXECUTION_POLICY.holding_sessions
        )
        candidate_indexes = [entry_session_index]
        candidate_indexes.extend(
            range(
                target_session_index,
                min(terminal_session_index, len(global_sessions) - 1) + 1,
            )
        )
        evaluation_dates = {
            global_sessions[index]
            for index in candidate_indexes
            if index < len(global_sessions)
            and global_sessions[index] in snapshot_by_date
        }
        if terminal_session_index >= len(global_sessions):
            evaluation_dates.add(last_observed_date)
        if removal_date is not None:
            evaluation_dates.add(removal_date)

        for evaluation_date in sorted(evaluation_dates):
            evaluation_snapshot = snapshot_by_date.get(evaluation_date)
            if evaluation_snapshot is None:
                unresolved_mature.append(
                    {
                        "date": date,
                        "code": code,
                        "reason": "label_snapshot_missing",
                    }
                )
                break
            evaluation_snapshot_id = str(
                evaluation_snapshot.get("market_snapshot_id") or ""
            ).lower()
            if code not in set(evaluation_snapshot.get("universe") or []):
                latest_execution = removal_execution(latest_execution, evaluation_date)
                label_snapshot_id = evaluation_snapshot_id
                label_snapshot_date = evaluation_date
                break
            manager = snapshot_manager(evaluation_snapshot_id)
            if manager is None:
                return unavailable(
                    "pit_label_snapshot_unavailable",
                    signal_date=date,
                    code=code,
                    label_snapshot_id=evaluation_snapshot_id,
                )
            if evaluation_snapshot_id not in session_cache:
                session_cache[evaluation_snapshot_id] = load_exchange_sessions(
                    manager.data_dir
                )
            latest_sessions = session_cache[evaluation_snapshot_id]
            history_frame = stock_frame(manager, evaluation_snapshot_id, code)
            if history_frame.empty:
                history_dates = [
                    snapshot_date
                    for snapshot_date in evidence_dates
                    if snapshot_date <= evaluation_date
                    and code
                    in set(snapshot_by_date[snapshot_date].get("universe") or [])
                ]
                for history_date in reversed(history_dates):
                    history_snapshot_id = str(
                        snapshot_by_date[history_date].get("market_snapshot_id") or ""
                    ).lower()
                    history_manager = snapshot_manager(history_snapshot_id)
                    if history_manager is None:
                        continue
                    history_frame = stock_frame(
                        history_manager, history_snapshot_id, code
                    )
                    if not history_frame.empty:
                        break
            latest_execution = evaluate_trade(
                history_frame,
                date,
                hold_days=5,
                code=code,
                security_states=security_states(code),
                trading_sessions=latest_sessions,
                require_pit_status=True,
            )
            label_snapshot_id = evaluation_snapshot_id
            label_snapshot_date = evaluation_date
            if is_terminal(latest_execution):
                break

        if latest_execution is None:
            unresolved_mature.append({"date": date, "code": code, "reason": "no_label"})
            continue
        if not is_terminal(latest_execution):
            if terminal_session_index < len(global_sessions):
                unresolved_mature.append(
                    {
                        "date": date,
                        "code": code,
                        "reason": latest_execution.get("reason"),
                    }
                )
                continue
        rows.append(
            training_row(
                item,
                code,
                latest_execution,
                label_snapshot_id,
                label_snapshot_date,
            )
        )
    if unresolved_mature:
        return unavailable(
            "pit_label_history_unavailable",
            unresolved_mature_count=len(unresolved_mature),
            first_unresolved=unresolved_mature[0],
        )
    return pd.DataFrame(rows)


def pit_snapshot_coverage(
    snapshots: dict[str, dict], trading_sessions: list[str]
) -> dict:
    """证明参考窗口内每个交易所会话都有不可变的当日快照。"""
    observed = sorted(str(date)[:10] for date in snapshots)
    sessions = sorted(set(str(date)[:10] for date in trading_sessions))
    if not observed or not sessions:
        return {
            "complete": False,
            "coverage_ratio": 0.0,
            "observed_sessions": len(observed),
            "expected_sessions": 0,
            "missing_sessions": [],
            "unexpected_snapshot_dates": observed,
        }
    expected = [date for date in sessions if observed[0] <= date <= observed[-1]]
    observed_set = set(observed)
    expected_set = set(expected)
    missing = sorted(expected_set - observed_set)
    unexpected = sorted(observed_set - expected_set)
    coverage_ratio = len(observed_set & expected_set) / max(len(expected_set), 1)
    return {
        "complete": bool(
            expected
            and coverage_ratio >= MIN_DAILY_SNAPSHOT_COVERAGE
            and not missing
            and not unexpected
        ),
        "coverage_ratio": round(coverage_ratio, 6),
        "observed_sessions": len(observed_set & expected_set),
        "expected_sessions": len(expected_set),
        "missing_sessions": missing,
        "unexpected_snapshot_dates": unexpected,
        "first_session": expected[0] if expected else None,
        "last_session": expected[-1] if expected else None,
    }


def build_dataset(
    cm: CSVManager,
    names: dict,
    industry_map: dict,
    limit: int = 0,
    *,
    snapshots: dict[str, dict] | None = None,
    feature_ledger: dict | None = None,
    commit_guard: Callable[[], None] | None = None,
) -> pd.DataFrame:
    def unavailable(reason: str, **details) -> pd.DataFrame:
        result = pd.DataFrame()
        result.attrs.update({"reason": reason, **details})
        return result

    data_root = Path(getattr(cm, "base_data_dir", cm.data_dir))
    catalog = (
        snapshots if snapshots is not None else load_reference_snapshots(data_root)
    )
    trading_sessions = load_exchange_sessions(cm.data_dir)
    snapshots, snapshot_cohort = latest_complete_snapshot_cohort(
        catalog,
        trading_sessions,
    )
    feature_ledger = (
        feature_ledger
        if feature_ledger is not None
        else materialize_pit_feature_ledger(
            cm,
            snapshots=snapshots,
            limit=limit,
            commit_guard=commit_guard,
        )
    )
    if len({date[:7] for date in snapshots}) < MIN_REFERENCE_MONTHS:
        return unavailable(
            "reference_history_insufficient",
            reference_months=len({date[:7] for date in snapshots}),
            minimum_reference_months=MIN_REFERENCE_MONTHS,
            snapshot_cohort=snapshot_cohort,
            feature_ledger=feature_ledger,
        )

    snapshot_coverage = pit_snapshot_coverage(snapshots, trading_sessions)
    if snapshot_coverage.get("complete") is not True:
        return unavailable(
            "pit_daily_snapshot_history_incomplete",
            snapshot_coverage=snapshot_coverage,
            snapshot_cohort=snapshot_cohort,
            feature_ledger=feature_ledger,
        )

    feature_snapshot_id = str(getattr(cm, "snapshot_id", "") or "")
    if len(feature_snapshot_id) != 64 or any(
        char not in "0123456789abcdef" for char in feature_snapshot_id.lower()
    ):
        return unavailable("feature_snapshot_unavailable")

    missing_dates = sorted(
        date
        for date, snapshot in snapshots.items()
        if not _feature_shard_path(
            data_root,
            date,
            str(snapshot.get("market_snapshot_id") or "").lower(),
            limit=limit,
        ).exists()
    )
    if missing_dates:
        return unavailable(
            "pit_feature_history_unavailable",
            feature_snapshot_id=feature_snapshot_id,
            mismatched_snapshot_count=len(missing_dates),
            first_mismatched_date=missing_dates[0],
            last_mismatched_date=missing_dates[-1],
            snapshot_cohort=snapshot_cohort,
            feature_ledger=feature_ledger,
        )

    feature_frames = []
    for date, snapshot in sorted(snapshots.items()):
        snapshot_id = str(snapshot.get("market_snapshot_id") or "").lower()
        feature_frames.append(
            _read_feature_shard(
                _feature_shard_path(
                    data_root,
                    date,
                    snapshot_id,
                    limit=limit,
                ),
                date,
                snapshot_id,
            )
        )
    features = pd.concat(feature_frames, ignore_index=True)
    frame = _hydrate_outcomes(features, cm, industry_map, snapshots)
    if not frame.empty:
        frame = frame.sort_values(["date", "code"]).reset_index(drop=True)
    else:
        if not frame.attrs.get("reason"):
            frame.attrs["reason"] = "training_dataset_empty"
        frame.attrs["feature_ledger"] = feature_ledger
        frame.attrs["snapshot_coverage"] = snapshot_coverage
    frame.attrs["snapshot_cohort"] = snapshot_cohort
    return frame


def _choose_threshold(
    frame: pd.DataFrame,
    probability: np.ndarray,
    keep_high: bool,
    min_coverage: float = 0.2,
) -> float:
    if frame.empty:
        return 0.5
    best = None
    for q in np.linspace(0.2, 0.8, 13):
        threshold = float(np.quantile(probability, q))
        mask = probability >= threshold if keep_high else probability <= threshold
        coverage = float(mask.mean())
        if coverage < min_coverage or not mask.any():
            continue
        returns = frame.loc[mask, "net_return_5"].dropna().to_numpy(float)
        if not len(returns):
            continue
        cvar = float(np.mean(np.sort(returns)[: max(1, int(len(returns) * 0.1))]))
        utility = float(np.mean(returns) + 0.35 * cvar - 0.2 * (1 - coverage))
        if best is None or utility > best[0]:
            best = (utility, threshold)
    return best[1] if best else 0.5


def _choose_risk_threshold(
    frame: pd.DataFrame,
    probability: np.ndarray,
    target: str,
    min_coverage: float = 0.2,
) -> float:
    """风险门不借用未定义的收益标签，只用成交风险事件校准。"""
    if frame.empty or not len(probability):
        return 0.5
    best = None
    labels = frame[target].to_numpy(float)
    for q in np.linspace(0.2, 0.8, 13):
        threshold = float(np.quantile(probability, q))
        mask = probability <= threshold
        coverage = float(mask.mean())
        if coverage < min_coverage or not mask.any():
            continue
        risk_rate = float(labels[mask].mean())
        utility = -risk_rate - 0.2 * (1 - coverage)
        if best is None or utility > best[0]:
            best = (utility, threshold)
    return best[1] if best else 0.5


def _summary(frame: pd.DataFrame, mask=None) -> dict:
    selected = frame if mask is None else frame.loc[mask]
    values = selected["net_return_5"].dropna().to_numpy(float)
    risk_values = selected["y_risk"].dropna().to_numpy(float)
    base = {
        "signals": int(len(selected)),
        "coverage": round(len(selected) / max(len(frame), 1), 4),
        "entry_unbuyable_rate": round(
            float(
                selected.loc[selected["entry_label_mature"] == 1, "y_entry_risk"].mean()
            ),
            4,
        )
        if (selected["entry_label_mature"] == 1).any()
        else None,
        "exit_unsellable_rate": round(
            float(
                selected.loc[selected["exit_label_mature"] == 1, "y_exit_risk"].mean()
            ),
            4,
        )
        if (selected["exit_label_mature"] == 1).any()
        else None,
    }
    if not len(values):
        return {
            **base,
            "n": 0,
            "avg": None,
            "median": None,
            "cvar10": None,
            "risk_rate": round(float(risk_values.mean()), 4)
            if len(risk_values)
            else None,
            "win_rate": None,
        }
    tail = np.sort(values)[: max(1, int(len(values) * 0.1))]
    return {
        **base,
        "n": len(values),
        "avg": round(float(np.mean(values)), 4),
        "median": round(float(np.median(values)), 4),
        "cvar10": round(float(np.mean(tail)), 4),
        "risk_rate": round(float(risk_values.mean()), 4) if len(risk_values) else None,
        "win_rate": round(float((values > 0).mean()), 4),
    }


def _aggregate_training_units(
    frame: pd.DataFrame,
    keys: list[str],
    feature_names: list[str],
    unit: str,
) -> pd.DataFrame:
    rows = []
    group_keys = keys[0] if len(keys) == 1 else keys
    for values, group in frame.groupby(group_keys, sort=True):
        values = (values,) if len(keys) == 1 else tuple(values)
        record = dict(zip(keys, values))
        record.update({name: float(group.iloc[0][name]) for name in feature_names})
        record.update(
            {
                "label_end_date": str(group["label_end_date"].max()),
                "net_return_5": float(group["net_return_5"].mean()),
                "excess_5": float(group["excess_5"].mean()),
                "y_quality": int(group["excess_5"].mean() > 0),
                "y_risk": int(group["y_risk"].mean() >= 0.5),
                "sample_count": int(len(group)),
                "training_unit": unit,
            }
        )
        rows.append(record)
    return pd.DataFrame(rows)


def _layer_frames(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    completed = frame[
        (frame["return_label_mature"] == 1)
        & frame["net_return_5"].notna()
        & frame["excess_5"].notna()
        & frame["y_quality"].notna()
    ].copy()
    entry = frame[
        (frame["entry_label_mature"] == 1) & frame["y_entry_risk"].notna()
    ].copy()
    exit_frame = frame[
        (frame["entry_feasible"] == 1)
        & (frame["exit_label_mature"] == 1)
        & frame["y_exit_risk"].notna()
    ].copy()
    return {
        "market": _aggregate_training_units(
            completed,
            ["date"],
            MARKET_FEATURES,
            "b1_signal_trade_date",
        ),
        "sector": _aggregate_training_units(
            completed,
            ["date", "industry"],
            MARKET_FEATURES + SECTOR_FEATURES,
            "b1_signal_date_sector",
        ),
        "entry_risk": entry,
        "exit_risk": exit_frame,
        "quality": completed,
    }


def _fit_models(train: pd.DataFrame) -> dict[str, BinaryLogit]:
    units = _layer_frames(train)
    if any(units[key].empty for key in MODEL_KEYS):
        raise ValueError("分层训练单元不足")

    def risk_weight(layer: pd.DataFrame, target: str) -> np.ndarray:
        positives = max(int(layer[target].sum()), 1)
        negatives = max(int((layer[target] == 0).sum()), 1)
        return np.where(
            layer[target].to_numpy() == 1,
            len(layer) / (2 * positives),
            len(layer) / (2 * negatives),
        )

    return {
        "market": BinaryLogit(MARKET_FEATURES).fit(units["market"], "y_quality"),
        "sector": BinaryLogit(MARKET_FEATURES + SECTOR_FEATURES).fit(
            units["sector"], "y_quality"
        ),
        "entry_risk": BinaryLogit(
            MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES
        ).fit(
            units["entry_risk"],
            "y_entry_risk",
            sample_weight=risk_weight(units["entry_risk"], "y_entry_risk"),
        ),
        "exit_risk": BinaryLogit(
            MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES
        ).fit(
            units["exit_risk"],
            "y_exit_risk",
            sample_weight=risk_weight(units["exit_risk"], "y_exit_risk"),
        ),
        "quality": BinaryLogit(MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES).fit(
            units["quality"],
            "y_quality",
        ),
    }


def _coefficient_stability(
    frame: pd.DataFrame,
    model: BinaryLogit,
    target: str,
) -> dict:
    """用按时间扩展的训练子窗检查标准化系数方向与幅度。"""
    ordered = frame.sort_values("date").reset_index(drop=True)
    coefficients = [np.asarray(model.coef[1:], dtype=float)]
    sample_sizes = [int(len(ordered))]
    for fraction in (0.60, 0.80):
        end = max(int(len(ordered) * fraction), 20)
        sample = ordered.iloc[: min(end, len(ordered))]
        if len(sample) < 20 or sample[target].nunique() < 2:
            continue
        sample_weight = None
        if target in {"y_entry_risk", "y_exit_risk"}:
            positives = max(int(sample[target].sum()), 1)
            negatives = max(int((sample[target] == 0).sum()), 1)
            sample_weight = np.where(
                sample[target].to_numpy() == 1,
                len(sample) / (2 * positives),
                len(sample) / (2 * negatives),
            )
        try:
            fitted = BinaryLogit(model.feature_names, l2=model.l2).fit(
                sample, target, sample_weight=sample_weight
            )
        except ModelFitError:
            continue
        if fitted.training_diagnostics.get("releaseable"):
            coefficients.append(np.asarray(fitted.coef[1:], dtype=float))
            sample_sizes.append(int(len(sample)))
    if len(coefficients) < 3:
        return {
            "method": "expanding_time_windows_v1",
            "stable": False,
            "fit_count": len(coefficients),
            "sample_sizes": sample_sizes,
            "sign_agreement": None,
            "normalized_dispersion": None,
        }
    matrix = np.vstack(coefficients)
    final = matrix[0]
    material = np.abs(final) > 1e-6
    sign_agreement = (
        float((np.sign(matrix[1:, material]) == np.sign(final[material])).mean())
        if material.any()
        else 1.0
    )
    scale = np.maximum(np.mean(np.abs(matrix), axis=0), 1e-4)
    normalized_dispersion = float(np.mean(np.std(matrix, axis=0) / scale))
    return {
        "method": "expanding_time_windows_v1",
        "stable": bool(sign_agreement >= 0.70 and normalized_dispersion <= 2.0),
        "fit_count": len(coefficients),
        "sample_sizes": sample_sizes,
        "sign_agreement": round(sign_agreement, 6),
        "normalized_dispersion": round(normalized_dispersion, 6),
    }


def _validation_thresholds(models: dict, validation: pd.DataFrame) -> dict[str, float]:
    units = _layer_frames(validation)
    market_p = models["market"].predict_proba(units["market"])
    sector_p = models["sector"].predict_proba(units["sector"])
    entry_risk_p = models["entry_risk"].predict_proba(units["entry_risk"])
    exit_risk_p = models["exit_risk"].predict_proba(units["exit_risk"])
    return {
        "market": _choose_threshold(units["market"], market_p, True),
        "sector": _choose_threshold(units["sector"], sector_p, True),
        "entry_risk": _choose_risk_threshold(
            units["entry_risk"],
            entry_risk_p,
            "y_entry_risk",
        ),
        "exit_risk": _choose_risk_threshold(
            units["exit_risk"],
            exit_risk_p,
            "y_exit_risk",
        ),
    }


def _apply(
    models: dict,
    frame: pd.DataFrame,
    thresholds: dict,
    *,
    weekly_gate_mode: str = "shadow",
) -> tuple[dict, dict]:
    p = {key: model.predict_proba(frame) for key, model in models.items()}
    masks: dict[str, np.ndarray] = {
        "baseline": np.ones(len(frame), dtype=bool),
        "weekly": frame["weekly_passed"].fillna(0).to_numpy(dtype=int) == 1,
    }
    masks["market"] = p["market"] >= thresholds["market"]
    masks["sector"] = masks["market"] & (p["sector"] >= thresholds["sector"])
    masks["entry_risk"] = masks["sector"] & (
        p["entry_risk"] <= thresholds["entry_risk"]
    )
    masks["exit_risk"] = masks["entry_risk"] & (
        p["exit_risk"] <= thresholds["exit_risk"]
    )
    quality = frame.assign(_p_quality=p["quality"], _keep=masks["exit_risk"])
    quality_mask = pd.Series(False, index=frame.index)
    for _, group in quality[quality["_keep"]].groupby("date"):
        quality_mask.loc[group.nlargest(3, "_p_quality").index] = True
    masks["quality"] = quality_mask.to_numpy(dtype=bool)
    manifest = policy_manifest(
        policy_version="walk-forward-runtime-parity",
        weekly_gate_mode=weekly_gate_mode,
        strict_unvalidated_market=False,
        top_n=3,
        components={
            key: {
                "mode": "active",
                "threshold": thresholds.get(key),
                "version": "fold-model",
            }
            for key in MODEL_KEYS
        },
    )
    evidence = [
        {
            "candidate_id": str(index),
            "code": str(row.get("code") or index),
            "decision_date": str(row.get("date") or ""),
            "weekly_passed": bool(row.get("weekly_passed") == 1),
            "probabilities": {key: float(p[key][offset]) for key in MODEL_KEYS},
        }
        for offset, (index, row) in enumerate(frame.iterrows())
    ]
    evaluated = {
        item["candidate_id"]: item for item in evaluate_policy(evidence, manifest)
    }
    masks["full"] = np.asarray(
        [evaluated[str(index)]["action"] == "buy" for index in frame.index], dtype=bool
    )
    return p, {**masks, "thresholds": thresholds}


def _aggregate_folds(folds: list[dict], layer: str) -> dict:
    rows = [f[layer] for f in folds if f[layer]["n"]]
    if not rows:
        return {"n": 0}
    risk_rows = [row for row in rows if row.get("risk_rate") is not None]
    return {
        "n": sum(r["n"] for r in rows),
        "months": len(rows),
        "avg": round(
            float(np.average([r["avg"] for r in rows], weights=[r["n"] for r in rows])),
            4,
        ),
        "median_month": round(float(np.median([r["avg"] for r in rows])), 4),
        "cvar10": round(
            float(
                np.average([r["cvar10"] for r in rows], weights=[r["n"] for r in rows])
            ),
            4,
        ),
        "risk_rate": round(
            float(
                np.average(
                    [row["risk_rate"] for row in risk_rows],
                    weights=[max(row.get("signals", row["n"]), 1) for row in risk_rows],
                )
            ),
            4,
        )
        if risk_rows
        else None,
        "coverage": round(float(np.mean([r["coverage"] for r in rows])), 4),
        "independent_n": sum(int(r.get("independent_n", r["n"])) for r in rows),
        "unit": rows[0].get("unit", "signal"),
    }


def _cluster_bootstrap_delta(
    frame: pd.DataFrame,
    selected: str,
    reference: str,
    cluster: str,
) -> dict:
    groups = []
    for _, group in frame.groupby(cluster):
        selected_values = (
            group.loc[group[selected], "net_return_5"].dropna().to_numpy(float)
        )
        reference_values = (
            group.loc[group[reference], "net_return_5"].dropna().to_numpy(float)
        )
        groups.append(
            (
                float(selected_values.sum()),
                len(selected_values),
                float(reference_values.sum()),
                len(reference_values),
            )
        )
    if len(groups) < 2:
        return {
            "clusters": len(groups),
            "ci_low": None,
            "ci_high": None,
            "positive_probability": None,
        }
    values = np.asarray(groups, dtype=float)
    rng = np.random.default_rng(20260717 + (0 if cluster == "date" else 1))
    deltas = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sample = values[rng.integers(0, len(values), size=len(values))]
        selected_n, reference_n = sample[:, 1].sum(), sample[:, 3].sum()
        if selected_n <= 0 or reference_n <= 0:
            continue
        deltas.append(
            sample[:, 0].sum() / selected_n - sample[:, 2].sum() / reference_n
        )
    if not deltas:
        return {
            "clusters": len(groups),
            "ci_low": None,
            "ci_high": None,
            "positive_probability": None,
        }
    delta = np.asarray(deltas)
    probability = float((delta > 0).mean())
    return {
        "clusters": len(groups),
        "iterations": BOOTSTRAP_ITERATIONS,
        "ci_low": round(float(np.quantile(delta, 0.0125)), 4),
        "ci_high": round(float(np.quantile(delta, 0.9875)), 4),
        "positive_probability": round(probability, 4),
        "monte_carlo_standard_error": round(
            float(np.sqrt(probability * (1 - probability) / len(delta))),
            6,
        ),
        "quantile_rank_resolution": round(1 / len(delta), 7),
    }


def _two_way_cluster_bootstrap_delta(
    frame: pd.DataFrame,
    selected: str,
    reference: str,
) -> dict:
    """Pigeonhole bootstrap：同时重采样交易日与股票，保留双向相关性。"""
    usable = frame[
        frame["net_return_5"].notna() & (frame[selected] | frame[reference])
    ].copy()
    if usable.empty:
        return {
            "date_clusters": 0,
            "stock_clusters": 0,
            "ci_low": None,
            "ci_high": None,
            "positive_probability": None,
        }
    date_index, dates = pd.factorize(usable["date"], sort=True)
    code_index, codes = pd.factorize(usable["code"], sort=True)
    if len(dates) < 2 or len(codes) < 2:
        return {
            "date_clusters": len(dates),
            "stock_clusters": len(codes),
            "ci_low": None,
            "ci_high": None,
            "positive_probability": None,
        }
    returns = usable["net_return_5"].to_numpy(float)
    selected_mask = usable[selected].to_numpy(bool)
    reference_mask = usable[reference].to_numpy(bool)
    rng = np.random.default_rng(20260719)
    deltas = []
    date_probability = np.full(len(dates), 1 / len(dates))
    code_probability = np.full(len(codes), 1 / len(codes))
    for _ in range(BOOTSTRAP_ITERATIONS):
        date_weights = rng.multinomial(len(dates), date_probability)
        code_weights = rng.multinomial(len(codes), code_probability)
        weights = date_weights[date_index] * code_weights[code_index]
        selected_weights = weights * selected_mask
        reference_weights = weights * reference_mask
        selected_n = selected_weights.sum()
        reference_n = reference_weights.sum()
        if selected_n <= 0 or reference_n <= 0:
            continue
        deltas.append(
            float(np.dot(returns, selected_weights) / selected_n)
            - float(np.dot(returns, reference_weights) / reference_n)
        )
    if not deltas:
        return {
            "date_clusters": len(dates),
            "stock_clusters": len(codes),
            "ci_low": None,
            "ci_high": None,
            "positive_probability": None,
        }
    delta = np.asarray(deltas)
    probability = float((delta > 0).mean())
    return {
        "date_clusters": len(dates),
        "stock_clusters": len(codes),
        "iterations": len(delta),
        "ci_low": round(float(np.quantile(delta, 0.0125)), 4),
        "ci_high": round(float(np.quantile(delta, 0.9875)), 4),
        "positive_probability": round(probability, 4),
        "monte_carlo_standard_error": round(
            float(np.sqrt(probability * (1 - probability) / len(delta))),
            6,
        ),
        "quantile_rank_resolution": round(1 / len(delta), 7),
        "method": "pigeonhole_date_x_stock_cluster_bootstrap",
    }


def _bootstrap_evidence(frame: pd.DataFrame, layer: str, reference: str) -> dict:
    by_date = _cluster_bootstrap_delta(frame, layer, reference, "date")
    by_stock = _cluster_bootstrap_delta(frame, layer, reference, "code")
    two_way = _two_way_cluster_bootstrap_delta(frame, layer, reference)
    evidence = (by_date, by_stock, two_way)
    lows = [item["ci_low"] for item in evidence if item["ci_low"] is not None]
    probabilities = [
        item["positive_probability"]
        for item in evidence
        if item["positive_probability"] is not None
    ]
    return {
        "date_cluster": by_date,
        "stock_cluster": by_stock,
        "date_x_stock_cluster": two_way,
        "worst_ci_low": min(lows) if lows else None,
        "worst_positive_probability": min(probabilities) if probabilities else None,
    }


def _with_label_availability(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["date"] = data["date"].astype(str).str[:10]
    data["label_end_date"] = data["label_end_date"].astype(str).str[:10]
    data["label_snapshot_date"] = data["label_snapshot_date"].astype(str).str[:10]
    if (data["label_snapshot_date"] < data["date"]).any():
        raise ValueError("训练样本的标签快照早于信号日")
    data["label_available_date"] = data[["label_end_date", "label_snapshot_date"]].max(
        axis=1
    )
    data["month"] = data["date"].str[:7]
    return data


def _purged_month_split(
    data: pd.DataFrame,
    train_months: list[str],
    validation_months: set[str],
    test_month: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, str]:
    # 使用月初边界而不是该月首个信号日，避免月初没有信号时把跨界标签误留在前窗。
    validation_start = f"{min(validation_months)}-01"
    test_start = f"{test_month}-01"
    label_available = (
        data["label_available_date"].fillna(data["label_end_date"])
        if "label_available_date" in data.columns
        else data["label_end_date"]
    )
    train = data[
        data["month"].isin(train_months) & (label_available < validation_start)
    ].copy()
    validation = data[
        data["month"].isin(validation_months) & (label_available < test_start)
    ].copy()
    test = data[data["month"] == test_month].copy()
    return train, validation, test, str(validation_start), str(test_start)


def _walk_forward_fold_gate(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    test: pd.DataFrame,
) -> tuple[str | None, dict]:
    row_counts = {
        "train": int(len(train)),
        "validation": int(len(validation)),
        "test": int(len(test)),
    }
    if (
        len(train) < MIN_WALK_FORWARD_TRAIN_ROWS
        or len(validation) < MIN_WALK_FORWARD_VALIDATION_ROWS
        or len(test) < MIN_WALK_FORWARD_TEST_ROWS
    ):
        return "walk_forward_sample_insufficient", row_counts
    train_units = _layer_frames(train)
    validation_units = _layer_frames(validation)
    layer_counts = {
        key: {
            "train": int(len(train_units[key])),
            "validation": int(len(validation_units[key])),
        }
        for key in MODEL_KEYS
    }
    if (
        len(train_units["market"]) < MIN_MARKET_TRAINING_UNITS
        or len(train_units["sector"]) < MIN_SECTOR_TRAINING_UNITS
        or any(
            train_units[key].empty or validation_units[key].empty for key in MODEL_KEYS
        )
    ):
        return "layer_label_coverage_insufficient", {
            **row_counts,
            "layers": layer_counts,
        }
    return None, {**row_counts, "layers": layer_counts}


def _final_calibration_split(
    data: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], str] | None:
    months = sorted(data["month"].unique())
    if len(months) <= FINAL_CALIBRATION_MONTHS:
        return None
    calibration_months = months[-FINAL_CALIBRATION_MONTHS:]
    calibration_start = f"{calibration_months[0]}-01"
    train = data[
        data["month"].isin(months[:-FINAL_CALIBRATION_MONTHS])
        & (data["label_available_date"] < calibration_start)
    ].copy()
    calibration = data[data["month"].isin(calibration_months)].copy()
    return train, calibration, calibration_months, calibration_start


def _final_calibration_gate(
    train: pd.DataFrame,
    calibration: pd.DataFrame,
) -> tuple[str | None, dict]:
    row_counts = {
        "train": int(len(train)),
        "calibration": int(len(calibration)),
    }
    if (
        len(train) < MIN_FINAL_TRAIN_ROWS
        or len(calibration) < MIN_FINAL_CALIBRATION_ROWS
    ):
        return "final_calibration_sample_insufficient", row_counts
    train_units = _layer_frames(train)
    calibration_units = _layer_frames(calibration)
    layer_counts = {
        key: {
            "train": int(len(train_units[key])),
            "calibration": int(len(calibration_units[key])),
        }
        for key in MODEL_KEYS
    }
    if any(
        train_units[key].empty or calibration_units[key].empty for key in MODEL_KEYS
    ):
        return "layer_label_coverage_insufficient", {
            **row_counts,
            "layers": layer_counts,
        }
    return None, {**row_counts, "layers": layer_counts}


def training_readiness(
    frame: pd.DataFrame,
    min_train_months: int = DEFAULT_MIN_TRAIN_MONTHS,
    val_months: int = DEFAULT_VALIDATION_MONTHS,
) -> dict:
    """在写模型产物前证明样本能形成真实训练折与独立校准窗。

    月份数只是历史长度，不代表有足够信号。这里复用 walk-forward
    和最终校准的同一组行数、分层单元与标签覆盖门槛。
    """
    missing = REQUIRED_DATASET_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"训练集缺少时点字段: {sorted(missing)}")
    data = _with_label_availability(frame)
    months = sorted(data["month"].unique())
    fold_diagnostics: list[dict] = []
    eligible_test_months: list[str] = []
    for test_i in range(min_train_months + val_months, len(months)):
        train_months = months[: test_i - val_months]
        val_set = set(months[test_i - val_months : test_i])
        train, validation, test, _, _ = _purged_month_split(
            data,
            train_months,
            val_set,
            months[test_i],
        )
        reason, evidence = _walk_forward_fold_gate(train, validation, test)
        fold_diagnostics.append(
            {"test_month": months[test_i], "reason": reason, **evidence}
        )
        if reason is None:
            eligible_test_months.append(months[test_i])
    if not eligible_test_months:
        candidate_reasons = {item["reason"] for item in fold_diagnostics}
        reason = (
            "layer_label_coverage_insufficient"
            if "layer_label_coverage_insufficient" in candidate_reasons
            else "walk_forward_sample_insufficient"
        )
        return {
            "ready": False,
            "reason": reason,
            "months": len(months),
            "candidate_folds": len(fold_diagnostics),
            "eligible_folds": 0,
            "folds": fold_diagnostics,
            "minimums": {
                "train_months": min_train_months,
                "validation_months": val_months,
                "walk_forward_train_rows": MIN_WALK_FORWARD_TRAIN_ROWS,
                "walk_forward_validation_rows": MIN_WALK_FORWARD_VALIDATION_ROWS,
                "walk_forward_test_rows": MIN_WALK_FORWARD_TEST_ROWS,
                "market_training_units": MIN_MARKET_TRAINING_UNITS,
                "sector_training_units": MIN_SECTOR_TRAINING_UNITS,
            },
        }
    calibration_split = _final_calibration_split(data)
    if calibration_split is None:
        return {
            "ready": False,
            "reason": "final_calibration_sample_insufficient",
            "months": len(months),
            "candidate_folds": len(fold_diagnostics),
            "eligible_folds": len(eligible_test_months),
            "eligible_test_months": eligible_test_months,
        }
    calibration_train, calibration, calibration_months, _ = calibration_split
    reason, calibration_evidence = _final_calibration_gate(
        calibration_train, calibration
    )
    return {
        "ready": reason is None,
        "reason": reason,
        "months": len(months),
        "candidate_folds": len(fold_diagnostics),
        "eligible_folds": len(eligible_test_months),
        "eligible_test_months": eligible_test_months,
        "calibration_months": calibration_months,
        "calibration": calibration_evidence,
        "minimums": {
            "final_train_rows": MIN_FINAL_TRAIN_ROWS,
            "final_calibration_rows": MIN_FINAL_CALIBRATION_ROWS,
        },
    }


def walk_forward(
    frame: pd.DataFrame,
    min_train_months: int = DEFAULT_MIN_TRAIN_MONTHS,
    val_months: int = DEFAULT_VALIDATION_MONTHS,
    *,
    weekly_gate_mode: str = "shadow",
) -> dict:
    missing = REQUIRED_DATASET_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(
            f"训练集缺少时点字段: {sorted(missing)}，请使用 --rebuild-dataset 重建"
        )
    versions = set(
        pd.to_numeric(frame["dataset_schema_version"], errors="coerce").dropna()
    )
    if versions != {DATASET_SCHEMA_VERSION}:
        raise ValueError(
            f"训练集版本不匹配: {sorted(versions)}，请使用 --rebuild-dataset 重建"
        )
    execution_versions = set(frame["execution_policy_version"].dropna().astype(str))
    if execution_versions != {DEFAULT_EXECUTION_POLICY.version}:
        raise ValueError(f"成交政策版本不匹配: {sorted(execution_versions)}")
    if not (
        frame["reference_snapshot_date"].astype(str).str[:10]
        == frame["date"].astype(str).str[:10]
    ).all():
        raise ValueError("训练样本的参考快照日期与信号日不一致")
    reference_ids = frame["reference_snapshot_id"].astype(str).str.lower()
    feature_ids = frame["feature_snapshot_id"].astype(str).str.lower()
    label_ids = frame["label_snapshot_id"].astype(str).str.lower()
    if (
        not reference_ids.str.fullmatch(r"[0-9a-f]{64}").all()
        or not feature_ids.str.fullmatch(r"[0-9a-f]{64}").all()
        or not label_ids.str.fullmatch(r"[0-9a-f]{64}").all()
    ):
        raise ValueError("训练样本缺少可验证的行情快照 ID")
    if not (reference_ids == feature_ids).all():
        raise ValueError("训练样本的特征快照与参考快照不一致")
    quality_targets = set(frame["quality_target_version"].dropna().astype(str))
    if quality_targets != {QUALITY_TARGET_VERSION}:
        raise ValueError(f"质量标签口径版本不匹配: {sorted(quality_targets)}")
    data = _with_label_availability(frame)
    months = sorted(data["month"].unique())
    folds, selected_thresholds, oos_rows = [], [], []
    for test_i in range(min_train_months + val_months, len(months)):
        train_months = months[: test_i - val_months]
        val_set = set(months[test_i - val_months : test_i])
        train, val, test, validation_start, test_start = _purged_month_split(
            data,
            train_months,
            val_set,
            months[test_i],
        )
        gate_reason, _ = _walk_forward_fold_gate(train, val, test)
        if gate_reason is not None:
            continue
        models = _fit_models(train)
        thresholds = _validation_thresholds(models, val)
        selected_thresholds.append(thresholds)
        probability, masks = _apply(
            models,
            test,
            thresholds,
            weekly_gate_mode=weekly_gate_mode,
        )
        fold = {
            "month": months[test_i],
            "thresholds": thresholds,
            "validation_months": sorted(val_set),
            "purged_before_validation": validation_start,
            "purged_before_test": test_start,
        }
        for layer in (
            "baseline",
            "weekly",
            "market",
            "sector",
            "entry_risk",
            "exit_risk",
            "quality",
            "full",
        ):
            fold[layer] = _summary(test, masks[layer])
            selected = test.loc[masks[layer]]
            if layer == "market":
                fold[layer].update(
                    {"independent_n": selected["date"].nunique(), "unit": "trade_date"}
                )
            elif layer == "sector":
                fold[layer].update(
                    {
                        "independent_n": selected[["date", "industry"]]
                        .drop_duplicates()
                        .shape[0],
                        "unit": "date_sector",
                    }
                )
            else:
                fold[layer].update({"independent_n": len(selected), "unit": "signal"})
        test_units = _layer_frames(test)
        fold["probability"] = {
            "market": probability_metrics(
                test_units["market"]["y_quality"],
                models["market"].predict_proba(test_units["market"]),
            ),
            "sector": probability_metrics(
                test_units["sector"]["y_quality"],
                models["sector"].predict_proba(test_units["sector"]),
            ),
            "entry_risk": probability_metrics(
                test_units["entry_risk"]["y_entry_risk"],
                models["entry_risk"].predict_proba(test_units["entry_risk"]),
            ),
            "exit_risk": probability_metrics(
                test_units["exit_risk"]["y_exit_risk"],
                models["exit_risk"].predict_proba(test_units["exit_risk"]),
            ),
            "quality": probability_metrics(
                test_units["quality"]["y_quality"],
                models["quality"].predict_proba(test_units["quality"]),
            ),
        }
        folds.append(fold)
        oos = test[
            [
                "date",
                "code",
                "industry",
                "net_return_5",
                "y_risk",
                "y_entry_risk",
                "y_exit_risk",
                "entry_label_mature",
                "exit_label_mature",
            ]
        ].copy()
        for layer in (
            "baseline",
            "weekly",
            "market",
            "sector",
            "entry_risk",
            "exit_risk",
            "quality",
            "full",
        ):
            oos[layer] = masks[layer]
        oos_rows.append(oos)

    layers = (
        "baseline",
        "weekly",
        "market",
        "sector",
        "entry_risk",
        "exit_risk",
        "quality",
        "full",
    )
    aggregate = {layer: _aggregate_folds(folds, layer) for layer in layers}
    oos_frame = pd.concat(oos_rows, ignore_index=True) if oos_rows else pd.DataFrame()
    references = {
        "weekly": "baseline",
        "market": "baseline",
        "sector": "market",
        "entry_risk": "sector",
        "exit_risk": "entry_risk",
        "quality": "exit_risk",
        "full": "quality",
    }
    bootstrap = (
        {
            layer: _bootstrap_evidence(oos_frame, layer, reference)
            for layer, reference in references.items()
        }
        if not oos_frame.empty
        else {}
    )
    status = {}
    for layer in ("weekly", "market", "sector", "entry_risk", "exit_risk", "quality"):
        reference = references[layer]
        current = aggregate[layer]
        previous = aggregate[reference]
        if not current.get("n") or not previous.get("n"):
            status[layer] = "shadow"
        else:
            improved_return = current["avg"] >= previous["avg"]
            improved_tail = current["cvar10"] >= previous["cvar10"]
            improved_risk = (
                current.get("risk_rate") is not None
                and previous.get("risk_rate") is not None
                and current["risk_rate"] <= previous["risk_rate"]
            )
            month_wins = sum(
                1
                for f in folds
                if f[layer]["n"]
                and f[reference]["n"]
                and f[layer]["avg"] >= f[reference]["avg"]
            )
            majority = month_wins >= max(1, int(np.ceil(len(folds) * 0.55)))
            evidence = bootstrap.get(layer, {})
            significant = (
                evidence.get("worst_ci_low") is not None
                and evidence["worst_ci_low"] >= 0
                and (evidence.get("worst_positive_probability") or 0)
                >= FAMILYWISE_POSITIVE_PROBABILITY
            )
            dependency_ready = (
                layer in {"weekly", "market"} or status.get(reference) == "active"
            )
            if layer in {"entry_risk", "exit_risk"}:
                passed = improved_risk and improved_tail and majority and significant
            else:
                passed = improved_return and improved_tail and majority and significant
            status[layer] = (
                "active"
                if passed and dependency_ready
                else ("shadow" if not dependency_ready else "rejected")
            )
    thresholds = (
        {
            key: round(float(np.median([item[key] for item in selected_thresholds])), 6)
            for key in ("market", "sector", "entry_risk", "exit_risk")
        }
        if selected_thresholds
        else {
            "market": 0.5,
            "sector": 0.5,
            "entry_risk": 0.5,
            "exit_risk": 0.5,
        }
    )
    return {
        "folds": folds,
        "aggregate": aggregate,
        "status": status,
        "thresholds": thresholds,
        "threshold_source": "median_of_purged_fold_thresholds" if folds else None,
        "fold_thresholds": selected_thresholds,
        "bootstrap": bootstrap,
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "bootstrap_comparison_plan": (
            "preregistered-layer-v2-date-stock-and-pigeonhole-two-way-clusters"
        ),
        "purge_horizon_trading_days": 11,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "runtime_policy_manifest": {
            "weekly_gate": {"mode": weekly_gate_mode, "version": "weekly-four-ma-v2"},
            "top_n": 3,
            "execution_policy_version": DEFAULT_EXECUTION_POLICY.version,
        },
    }


def _final_calibrated_models(frame: pd.DataFrame) -> tuple[dict, dict, dict]:
    """保留最后数月作为完全未参与拟合的阈值校准窗。"""
    data = _with_label_availability(frame)
    split = _final_calibration_split(data)
    if split is None:
        raise ValueError("独立阈值校准月份不足")
    train, calibration, calibration_months, calibration_start = split
    gate_reason, _ = _final_calibration_gate(train, calibration)
    if gate_reason == "final_calibration_sample_insufficient":
        raise ValueError("独立阈值校准窗样本不足")
    if gate_reason is not None:
        raise ValueError("独立校准窗的分层标签不完整")
    train_units = _layer_frames(train)
    calibration_units = _layer_frames(calibration)
    models = _fit_models(train)
    thresholds = _validation_thresholds(models, calibration)
    targets = {
        "market": "y_quality",
        "sector": "y_quality",
        "entry_risk": "y_entry_risk",
        "exit_risk": "y_exit_risk",
        "quality": "y_quality",
    }
    calibration_metrics = {
        key: probability_metrics(
            calibration_units[key][targets[key]],
            models[key].predict_proba(calibration_units[key]),
        )
        for key in MODEL_KEYS
    }
    for key, model in models.items():
        calibration_metric = calibration_metrics[key]
        calibration_releaseable = bool(
            calibration_metric.get("n", 0) >= 20
            and calibration_metric.get("brier") is not None
            and calibration_metric["brier"] <= 0.30
            and calibration_metric.get("expected_calibration_error") is not None
            and calibration_metric["expected_calibration_error"] <= 0.20
            and len(calibration_metric.get("calibration_curve") or []) >= 2
        )
        coefficient_stability = _coefficient_stability(
            train_units[key], model, targets[key]
        )
        feature_drift = population_stability_index(
            train_units[key],
            calibration_units[key],
            model.feature_names,
        )
        model.training_diagnostics.update(
            {
                "coefficient_stability": coefficient_stability,
                "calibration": {
                    "releaseable": calibration_releaseable,
                    **calibration_metric,
                },
                "feature_drift": feature_drift,
            }
        )
        model.training_diagnostics["releaseable"] = bool(
            model.training_diagnostics.get("releaseable")
            and coefficient_stability["stable"]
            and calibration_releaseable
            and feature_drift["releaseable"]
        )
    diagnostics = {key: model.training_diagnostics for key, model in models.items()}
    evidence = {
        "method": "purged_final_holdout_calibration_v1",
        "training_range": [str(train["date"].min()), str(train["date"].max())],
        "calibration_range": [
            str(calibration["date"].min()),
            str(calibration["date"].max()),
        ],
        "calibration_months": calibration_months,
        "calibration_rows": int(len(calibration)),
        "purged_before": calibration_start,
        "thresholds": thresholds,
        "probability_metrics": calibration_metrics,
        "optimizer_diagnostics": diagnostics,
    }
    return models, thresholds, evidence


def train_and_register(
    frame: pd.DataFrame,
    output: Path,
    *,
    commit_guard: Callable[[], None] | None = None,
    trained_as_of: str | None = None,
) -> dict:
    guard = commit_guard or (lambda: None)
    missing = REQUIRED_DATASET_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"训练集缺少时点字段: {sorted(missing)}，请重新构建")
    readiness = training_readiness(frame)
    if readiness.get("ready") is not True:
        raise ValueError(f"训练就绪门槛未满足: {readiness.get('reason')}")
    report = walk_forward(frame)
    if not report["folds"]:
        raise ValueError("没有满足 purge 和未来月份要求的 walk-forward 折")
    models, calibrated_thresholds, calibration_evidence = _final_calibrated_models(
        frame
    )
    canonical = frame.sort_values(["date", "code"]).to_csv(
        index=False, float_format="%.10g"
    )
    dataset_hash = hashlib.sha256(canonical.encode()).hexdigest()
    digest = hashlib.sha256(
        f"{strategy_version()}|{FEATURE_VERSION}|".encode() + canonical.encode()
    ).hexdigest()[:12]
    version = f"hierarchy-{digest}"
    trained = str(
        trained_as_of or datetime.now().astimezone().isoformat(timespec="seconds")
    )
    bundle = {
        "version": version,
        "policy_version": version,
        "trained_as_of": trained,
        "train_range": [str(frame.date.min()), str(frame.date.max())],
        "thresholds": calibrated_thresholds,
        "status": report["status"],
        "threshold_source": "independent_final_calibration_window",
        "calibration": calibration_evidence,
        "fold_threshold_medians": report["thresholds"],
        "metrics": report["aggregate"],
        "bootstrap": report["bootstrap"],
        "dataset_hash": dataset_hash,
        "code_sha": git_commit_sha(),
        "execution_policy": execution_policy_manifest(DEFAULT_EXECUTION_POLICY),
        "model_card": {
            "market_semantic_name": "b1_signal_day_candidate_quality_gate",
            "training_population": "trade dates containing at least one Super B1 signal",
            "out_of_domain": "general market timing on dates without a Super B1 signal",
        },
        "models": {key: model.to_dict() for key, model in models.items()},
        "source_refs": [
            "immutable-market-snapshots-v2",
            "point-in-time-reference-snapshots-v4",
            "point-in-time-feature-snapshots-v1",
            PIT_FEATURE_LEDGER_SCHEMA_VERSION,
            "pit-security-state-and-listing-regime-v2",
            "super-b1-original",
            "weekly-four-ma-shadow",
            DEFAULT_EXECUTION_POLICY.version,
            "purged-walk-forward-v2",
            "independent-final-calibration-v1",
        ],
    }
    guard()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for key, model in models.items():
        validation_status = report["status"].get(key, "shadow")
        optimizer_releaseable = bool(model.training_diagnostics.get("releaseable"))
        registry_status = (
            "shadow"
            if validation_status == "active" and optimizer_releaseable
            else "rejected"
        )
        guard()
        register_model(
            {
                # 训练通过也只进入 shadow；发布必须经过独立的完整策略审核窗口。
                "model_key": key,
                "version": version,
                "status": registry_status,
                "trained_as_of": trained,
                "train_range": "/".join(calibration_evidence["training_range"]),
                "test_range": "/".join(calibration_evidence["calibration_range"]),
                "feature_names": model.feature_names,
                "params": {
                    "threshold": calibrated_thresholds.get(key),
                    "l2": model.l2,
                    "validation_status": validation_status,
                    "calibration_status": "independent_holdout",
                    "dataset_hash": dataset_hash,
                    "code_sha": git_commit_sha(),
                    "artifact_hash": model_artifact_hash(model.to_dict()),
                    "optimizer_diagnostics": model.training_diagnostics,
                },
                "metrics": report["aggregate"].get(key, {}),
                "source_refs": bundle["source_refs"],
                "artifact": model.to_dict(),
            }
        )
    guard()
    register_policy_candidate(
        {
            "policy_version": version,
            "research_status": "shadow",
            "trained_as_of": trained,
            "train_range": "/".join(bundle["train_range"]),
            "test_range": "/".join([f["month"] for f in report["folds"]]),
            "component_versions": {key: version for key in models},
            "metrics": {
                "full": report["aggregate"].get("full", {}),
                "baseline": report["aggregate"].get("baseline", {}),
            },
            "evidence": {
                "state": "forward_observation_required",
                "bootstrap": report["bootstrap"].get("full", {}),
                "folds": len(report["folds"]),
                "calibration": calibration_evidence,
                "dataset_hash": dataset_hash,
                "code_sha": git_commit_sha(),
                "execution_policy_version": DEFAULT_EXECUTION_POLICY.version,
                "runtime_policy_manifest": report["runtime_policy_manifest"],
            },
            "source_refs": bundle["source_refs"],
        }
    )
    return {**report, "bundle": bundle}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/hierarchical_training.csv")
    parser.add_argument("--bundle", default="data/hierarchical_model_bundle.json")
    parser.add_argument("--report", default="data/hierarchical_walk_forward.json")
    parser.add_argument("--rebuild-dataset", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    dataset_path = Path(args.dataset)
    if args.rebuild_dataset or not dataset_path.exists():
        cm = CSVManager("data", writable=False)
        if cm.snapshot_id is None:
            raise SystemExit("没有已验证的不可变行情快照，无法重建训练集")
        from utils.market_snapshot import read_snapshot_metadata

        names, names_snapshot_id = read_snapshot_metadata(
            "stock_names.json",
            cm.base_data_dir,
            snapshot_id=cm.snapshot_id,
        )
        industries, industries_snapshot_id = read_snapshot_metadata(
            "stock_industry.json",
            cm.base_data_dir,
            snapshot_id=cm.snapshot_id,
        )
        if (
            not isinstance(names, dict)
            or not isinstance(industries, dict)
            or names_snapshot_id != cm.snapshot_id
            or industries_snapshot_id != cm.snapshot_id
        ):
            raise SystemExit("当前快照的股票池或行业元数据不可用，无法重建训练集")
        frame = build_dataset(cm, names, industries, args.limit)
        if frame.empty:
            raise SystemExit("时点参考快照不足或无 B1 历史信号，无法训练")
        dataset_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(dataset_path, index=False)
    else:
        try:
            frame = pd.read_csv(dataset_path)
        except pd.errors.EmptyDataError as exc:
            raise SystemExit("训练集为空，请使用 --rebuild-dataset 重建") from exc
    if frame.empty:
        raise SystemExit("无B1历史信号，无法训练")
    result = train_and_register(frame, Path(args.bundle))
    Path(args.report).write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "rows": len(frame),
                "range": [frame.date.min(), frame.date.max()],
                "status": result["status"],
                "aggregate": result["aggregate"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
