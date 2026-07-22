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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

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
)
from utils.market_filter import is_main_board, main_board_only  # noqa: E402
from utils.policy_engine import evaluate_policy, policy_manifest  # noqa: E402
from utils.probability_model import (  # noqa: E402
    BinaryLogit,
    ModelFitError,
    population_stability_index,
    probability_metrics,
)
from utils.reference_snapshots import load_reference_snapshots  # noqa: E402

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
DATASET_SCHEMA_VERSION = 6
MIN_REFERENCE_COVERAGE = 0.60
BOOTSTRAP_ITERATIONS = 10_000
FAMILYWISE_POSITIVE_PROBABILITY = 0.9875
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
MODEL_KEYS = ("market", "sector", "entry_risk", "exit_risk", "quality")


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


def _signals_one(args) -> list[dict]:
    code, name, frame, market, sector, snapshots, feature_snapshot_id = args
    from strategy.super_b1 import compute_super_b1
    from utils.technical import weekly_four_ma_bullish

    rows = []
    cap_by_date = {}
    security_states_by_date = {}
    for date, snapshot in snapshots.items():
        if code not in (
            snapshot.get("_universe_set") or snapshot.get("universe") or []
        ):
            continue
        cap = (snapshot.get("market_caps") or {}).get(code)
        if isinstance(cap, (int, float)) and cap > 0:
            cap_by_date[date] = float(cap)
        state = (snapshot.get("security_states") or {}).get(code)
        if isinstance(state, dict):
            security_states_by_date[date] = state
    hits = compute_super_b1(
        frame,
        code,
        return_history=True,
        market_cap_by_date=cap_by_date,
    )
    date_to_index = {date: i for i, date in enumerate(frame["date"])}
    for hit in hits if isinstance(hits, list) else []:
        date = hit["date"]
        i = date_to_index.get(date)
        if i is None or i >= len(frame) - 1:
            continue
        snapshot = snapshots.get(date)
        if not snapshot:
            continue
        sub = frame.iloc[: i + 1]
        ctx = FactorContext(sub)
        industry = (snapshot.get("industries") or {}).get(code) or "未知"
        if date not in market.index or (date, industry) not in sector.index:
            continue
        execution = evaluate_trade(
            frame,
            date,
            hold_days=5,
            code=code,
            security_states=security_states_by_date,
            require_pit_status=True,
        )
        if not execution.get("available"):
            continue
        label_end_date = execution.get("label_end_date")
        if not label_end_date:
            continue
        weekly_passed, weekly_detail = weekly_four_ma_bullish(sub)
        future_date = execution.get("exit_date")
        net_return = execution.get("net_return")
        return_mature = bool(
            execution.get("return_label_mature")
            and net_return is not None
            and future_date in market.index
        )
        market_forward = (
            (
                market.loc[future_date, "market_index"]
                / market.loc[date, "market_index"]
                - 1
            )
            * 100
            if return_mature
            else np.nan
        )
        excess = float(net_return - market_forward) if return_mature else np.nan
        entry_feasible = bool(execution.get("entry_feasible"))
        exit_feasible = execution.get("exit_feasible")
        entry_mature = bool(execution.get("entry_label_mature"))
        exit_mature = bool(execution.get("exit_label_mature"))
        y_entry_risk = int(not entry_feasible) if entry_mature else np.nan
        y_exit_risk = (
            int(exit_feasible is False) if entry_feasible and exit_mature else np.nan
        )
        y_risk: int | float
        if entry_mature and not entry_feasible:
            y_risk = 1
        elif entry_feasible and exit_mature and exit_feasible is False:
            y_risk = 1
        elif return_mature:
            y_risk = int(
                execution.get("one_word_limit_down_next_open", False)
                or (execution.get("next_open_gap_pct") or 0) <= -7
                or float(net_return) <= -10
            )
        else:
            y_risk = np.nan
        m = market.loc[date]
        s = sector.loc[(date, industry)]
        record = {
            "date": date,
            "code": code,
            "name": name,
            "industry": industry,
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "label_end_date": label_end_date,
            "reference_snapshot_date": date,
            "reference_snapshot_id": snapshot.get("market_snapshot_id"),
            "feature_snapshot_id": feature_snapshot_id,
            "universe_coverage": float(market.loc[date, "market_universe_coverage"]),
            "weekly_passed": int(weekly_passed),
            "weekly_aligned": int(bool(weekly_detail.get("aligned"))),
            "weekly_rising_count": int(weekly_detail.get("rising_count", 0)),
            "execution_status": execution.get("execution_status")
            or execution.get("reason"),
            "execution_policy_version": execution.get("execution_policy_version"),
            "entry_label_mature": int(entry_mature),
            "exit_label_mature": int(exit_mature),
            "return_label_mature": int(return_mature),
            "entry_feasible": int(entry_feasible),
            "exit_feasible": (
                int(bool(exit_feasible)) if exit_feasible is not None else np.nan
            ),
            "b1_signals": "|".join(hit.get("signals") or []),
            "net_return_5": float(net_return) if return_mature else np.nan,
            "market_forward_5": float(market_forward) if return_mature else np.nan,
            "excess_5": excess,
            "y_quality": int(excess > 0) if return_mature else np.nan,
            "y_entry_risk": y_entry_risk,
            "y_exit_risk": y_exit_risk,
            "y_risk": y_risk,
        }
        record.update({key: float(m.get(key, np.nan)) for key in MARKET_FEATURES})
        record.update({key: float(s.get(key, np.nan)) for key in SECTOR_FEATURES})
        record.update(_stock_features(ctx))
        rows.append(record)
    return rows


def build_dataset(
    cm: CSVManager, names: dict, industry_map: dict, limit: int = 0
) -> pd.DataFrame:
    def unavailable(reason: str, **details) -> pd.DataFrame:
        result = pd.DataFrame()
        result.attrs.update({"reason": reason, **details})
        return result

    data_root = Path(getattr(cm, "base_data_dir", cm.data_dir))
    snapshots = load_reference_snapshots(data_root)
    if len({date[:7] for date in snapshots}) < MIN_REFERENCE_MONTHS:
        return unavailable(
            "reference_history_insufficient",
            reference_months=len({date[:7] for date in snapshots}),
            minimum_reference_months=MIN_REFERENCE_MONTHS,
        )

    feature_snapshot_id = str(getattr(cm, "snapshot_id", "") or "")
    if len(feature_snapshot_id) != 64 or any(
        char not in "0123456789abcdef" for char in feature_snapshot_id.lower()
    ):
        return unavailable("feature_snapshot_unavailable")

    # 当前 CSV 快照里的前复权历史不能倒推为过去真实可见的特征。只有信号日的
    # 参考快照和计算特征的行情快照完全相同，样本才可作为发布证据。历史快照
    # 尚未按日重建时宁可停止训练，也不能用今天看到的历史曲线制造 PIT 证据。
    mismatched_dates = sorted(
        date
        for date, snapshot in snapshots.items()
        if snapshot.get("market_snapshot_id") != feature_snapshot_id
    )
    if mismatched_dates:
        return unavailable(
            "pit_feature_history_unavailable",
            feature_snapshot_id=feature_snapshot_id,
            mismatched_snapshot_count=len(mismatched_dates),
            first_mismatched_date=mismatched_dates[0],
            last_mismatched_date=mismatched_dates[-1],
        )

    codes = [c for c in cm.list_all_stocks() if c.isdigit() and len(c) == 6]
    if main_board_only():
        codes = [code for code in codes if is_main_board(code)]
    if limit:
        codes = codes[:limit]
    market, sector, stock_frames = build_panels(
        cm,
        codes,
        industry_map,
        reference_snapshots=snapshots,
    )
    if market.empty or sector.empty:
        return pd.DataFrame()
    tasks = [
        (
            code,
            names.get(code, code),
            frame,
            market,
            sector,
            snapshots,
            feature_snapshot_id,
        )
        for code, frame in stock_frames.items()
    ]
    rows = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(tasks)))) as pool:
        for result in pool.map(_signals_one, tasks):
            rows.extend(result)
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values(["date", "code"]).reset_index(drop=True)
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


def _purged_month_split(
    data: pd.DataFrame,
    train_months: list[str],
    validation_months: set[str],
    test_month: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, str]:
    # 使用月初边界而不是该月首个信号日，避免月初没有信号时把跨界标签误留在前窗。
    validation_start = f"{min(validation_months)}-01"
    test_start = f"{test_month}-01"
    train = data[
        data["month"].isin(train_months) & (data["label_end_date"] < validation_start)
    ].copy()
    validation = data[
        data["month"].isin(validation_months) & (data["label_end_date"] < test_start)
    ].copy()
    test = data[data["month"] == test_month].copy()
    return train, validation, test, str(validation_start), str(test_start)


def walk_forward(
    frame: pd.DataFrame,
    min_train_months: int = 12,
    val_months: int = 3,
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
    if (
        not reference_ids.str.fullmatch(r"[0-9a-f]{64}").all()
        or not feature_ids.str.fullmatch(r"[0-9a-f]{64}").all()
    ):
        raise ValueError("训练样本缺少可验证的行情快照 ID")
    if not (reference_ids == feature_ids).all():
        raise ValueError("训练样本的特征快照与参考快照不一致")
    data = frame.copy()
    data["date"] = data["date"].astype(str)
    data["label_end_date"] = data["label_end_date"].astype(str)
    data["month"] = data["date"].str[:7]
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
        if len(train) < 80 or len(val) < 20 or len(test) < 3:
            continue
        train_units = _layer_frames(train)
        validation_units = _layer_frames(val)
        if (
            len(train_units["market"]) < 40
            or len(train_units["sector"]) < 40
            or any(
                train_units[key].empty or validation_units[key].empty
                for key in MODEL_KEYS
            )
        ):
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
    data = frame.copy()
    data["date"] = data["date"].astype(str)
    data["label_end_date"] = data["label_end_date"].astype(str)
    data["month"] = data["date"].str[:7]
    months = sorted(data["month"].unique())
    if len(months) <= FINAL_CALIBRATION_MONTHS:
        raise ValueError("独立阈值校准月份不足")
    calibration_months = months[-FINAL_CALIBRATION_MONTHS:]
    calibration_start = f"{calibration_months[0]}-01"
    train = data[
        data["month"].isin(months[:-FINAL_CALIBRATION_MONTHS])
        & (data["label_end_date"] < calibration_start)
    ].copy()
    calibration = data[data["month"].isin(calibration_months)].copy()
    if len(train) < 80 or len(calibration) < 20:
        raise ValueError("独立阈值校准窗样本不足")
    train_units = _layer_frames(train)
    calibration_units = _layer_frames(calibration)
    if any(
        train_units[key].empty or calibration_units[key].empty for key in MODEL_KEYS
    ):
        raise ValueError("独立校准窗的分层标签不完整")
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


def train_and_register(frame: pd.DataFrame, output: Path) -> dict:
    missing = REQUIRED_DATASET_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"训练集缺少时点字段: {sorted(missing)}，请重新构建")
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
    trained = datetime.now().astimezone().isoformat(timespec="seconds")
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
            "pit-security-state-and-listing-regime-v2",
            "super-b1-original",
            "weekly-four-ma-shadow",
            DEFAULT_EXECUTION_POLICY.version,
            "purged-walk-forward-v2",
            "independent-final-calibration-v1",
        ],
    }
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
