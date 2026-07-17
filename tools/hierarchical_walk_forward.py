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
from utils.decision_ledger import register_model, register_policy_candidate  # noqa: E402
from utils.decision_versions import FEATURE_VERSION, strategy_version  # noqa: E402
from utils.execution_model import evaluate_trade  # noqa: E402
from utils.market_filter import is_main_board, main_board_only  # noqa: E402
from utils.probability_model import BinaryLogit, probability_metrics  # noqa: E402
from utils.reference_snapshots import load_reference_snapshots  # noqa: E402

logger = logging.getLogger(__name__)

MARKET_FEATURES = [
    "market_ret_1", "market_ret_5", "market_ret_20", "market_breadth",
    "market_amount_ratio", "market_limit_down_ratio", "market_vs_ma20", "market_vs_ma60",
]
SECTOR_FEATURES = [
    "sector_rel_1", "sector_rel_5", "sector_breadth", "sector_amount_ratio",
    "sector_dispersion", "sector_members",
]
STOCK_FEATURES = [
    "stock_pct", "stock_j", "stock_rsi", "stock_vol_ratio", "stock_vs_ma20",
    "stock_vs_ma60", "stock_vs_peak60", "stock_position20", "stock_amplitude",
]
DATASET_SCHEMA_VERSION = 3
MIN_REFERENCE_COVERAGE = 0.60
BOOTSTRAP_ITERATIONS = 400
FAMILYWISE_POSITIVE_PROBABILITY = 0.9875
REQUIRED_DATASET_COLUMNS = {
    "dataset_schema_version", "date", "label_end_date", "code", "industry",
    "reference_snapshot_date", "universe_coverage", "weekly_passed", "execution_status",
    "net_return_5", "excess_5", "y_quality", "y_risk",
} | set(MARKET_FEATURES) | set(SECTOR_FEATURES) | set(STOCK_FEATURES)
MIN_REFERENCE_MONTHS = 21


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
        loaded = pool.map(lambda c: (c, _read_stock(cm, c, industry_map.get(c, ""))), codes)
        for code, frame in loaded:
            if frame is not None:
                stock_frames[code] = frame
                frames.append(frame[["date", "code", "industry", "ret1", "amount_proxy"]])
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
                str(code) for code in snapshot.get("_universe_set") or snapshot.get("universe") or []
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

    market = panel.groupby("date").agg(
        market_ret_1=("ret1", "mean"),
        market_breadth=("ret1", lambda s: float((s > 0).mean())),
        market_amount=("amount_proxy", "sum"),
        market_limit_down_ratio=("ret1", lambda s: float((s <= -0.095).mean())),
        market_universe_coverage=("universe_coverage", "first"),
    ).sort_index()
    market["market_index"] = (1 + market["market_ret_1"]).cumprod()
    market["market_ret_5"] = market["market_index"].pct_change(5)
    market["market_ret_20"] = market["market_index"].pct_change(20)
    market["market_amount_ratio"] = (
        market["market_amount"].rolling(5).mean() / market["market_amount"].rolling(20).mean()
    )
    market["market_vs_ma20"] = market["market_index"] / market["market_index"].rolling(20).mean() - 1
    market["market_vs_ma60"] = market["market_index"] / market["market_index"].rolling(60).mean() - 1

    sector = panel.groupby(["industry", "date"]).agg(
        sector_ret_1=("ret1", "mean"),
        sector_breadth=("ret1", lambda s: float((s > 0).mean())),
        sector_amount=("amount_proxy", "sum"),
        sector_dispersion=("ret1", "std"),
        sector_members=("ret1", "size"),
    ).reset_index().sort_values(["industry", "date"])
    sector = sector.merge(market[["market_ret_1", "market_amount"]], left_on="date", right_index=True)
    sector["sector_rel_1"] = sector["sector_ret_1"] - sector["market_ret_1"]
    sector["sector_rel_5"] = sector.groupby("industry")["sector_rel_1"].transform(
        lambda s: s.rolling(5).sum()
    )
    sector["sector_share"] = sector["sector_amount"] / sector["market_amount"]
    sector["sector_amount_ratio"] = sector.groupby("industry")["sector_share"].transform(
        lambda s: s.rolling(5).mean() / s.rolling(20).mean()
    )
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
        "stock_amplitude": float(ctx.H.iloc[-1] / ctx.L.iloc[-1] - 1) if ctx.L.iloc[-1] > 0 else np.nan,
    }


def _signals_one(args) -> list[dict]:
    code, name, frame, market, sector, snapshots = args
    from strategy.super_b1 import compute_super_b1
    from utils.technical import weekly_four_ma_bullish

    rows = []
    cap_by_date = {}
    for date, snapshot in snapshots.items():
        if code not in (snapshot.get("_universe_set") or snapshot.get("universe") or []):
            continue
        cap = (snapshot.get("market_caps") or {}).get(code)
        if isinstance(cap, (int, float)) and cap > 0:
            cap_by_date[date] = float(cap)
    hits = compute_super_b1(
        frame, code, return_history=True, market_cap_by_date=cap_by_date,
    )
    date_to_index = {date: i for i, date in enumerate(frame["date"])}
    for hit in hits if isinstance(hits, list) else []:
        date = hit["date"]
        i = date_to_index.get(date)
        if i is None or i >= len(frame) - 5:
            continue
        snapshot = snapshots.get(date)
        if not snapshot:
            continue
        sub = frame.iloc[:i + 1]
        ctx = FactorContext(sub)
        industry = (snapshot.get("industries") or {}).get(code) or "未知"
        if date not in market.index or (date, industry) not in sector.index:
            continue
        execution = evaluate_trade(frame, date, hold_days=5)
        if not execution.get("available"):
            continue
        future_date = execution.get("exit_date")
        if not future_date or future_date not in market.index:
            continue
        weekly_passed, weekly_detail = weekly_four_ma_bullish(sub)
        market_forward = (market.loc[future_date, "market_index"] / market.loc[date, "market_index"] - 1) * 100
        net_return = execution.get("net_return")
        if net_return is None:
            # 不可买、不可卖和标签尚未成熟不是投资亏损，不能塞入收益标签。
            continue
        m = market.loc[date]
        s = sector.loc[(date, industry)]
        record = {
            "date": date, "code": code, "name": name, "industry": industry,
            "dataset_schema_version": DATASET_SCHEMA_VERSION,
            "label_end_date": future_date,
            "reference_snapshot_date": date,
            "universe_coverage": float(market.loc[date, "market_universe_coverage"]),
            "weekly_passed": int(weekly_passed),
            "weekly_aligned": int(bool(weekly_detail.get("aligned"))),
            "weekly_rising_count": int(weekly_detail.get("rising_count", 0)),
            "execution_status": "filled_round_trip",
            "b1_signals": "|".join(hit.get("signals") or []),
            "net_return_5": float(net_return), "market_forward_5": float(market_forward),
            "excess_5": float(net_return - market_forward),
            "y_quality": int(net_return - market_forward > 0),
            "y_risk": int(
                execution.get("one_word_limit_down_next_open", False)
                or (execution.get("next_open_gap_pct") or 0) <= -7
                or net_return <= -10
                or not execution.get("entry_feasible", True)
                or execution.get("exit_feasible") is False
            ),
        }
        record.update({key: float(m.get(key, np.nan)) for key in MARKET_FEATURES})
        record.update({key: float(s.get(key, np.nan)) for key in SECTOR_FEATURES})
        record.update(_stock_features(ctx))
        rows.append(record)
    return rows


def build_dataset(cm: CSVManager, names: dict, industry_map: dict, limit: int = 0) -> pd.DataFrame:
    codes = [c for c in cm.list_all_stocks() if c.isdigit() and len(c) == 6]
    if main_board_only():
        codes = [code for code in codes if is_main_board(code)]
    if limit:
        codes = codes[:limit]
    snapshots = load_reference_snapshots(cm.data_dir)
    if len({date[:7] for date in snapshots}) < MIN_REFERENCE_MONTHS:
        return pd.DataFrame()
    market, sector, stock_frames = build_panels(
        cm, codes, industry_map, reference_snapshots=snapshots,
    )
    if market.empty or sector.empty:
        return pd.DataFrame()
    tasks = [
        (code, names.get(code, code), frame, market, sector, snapshots)
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


def _choose_threshold(frame: pd.DataFrame, probability: np.ndarray, keep_high: bool,
                      min_coverage: float = 0.2) -> float:
    if frame.empty:
        return 0.5
    best = None
    for q in np.linspace(0.2, 0.8, 13):
        threshold = float(np.quantile(probability, q))
        mask = probability >= threshold if keep_high else probability <= threshold
        coverage = float(mask.mean())
        if coverage < min_coverage or not mask.any():
            continue
        returns = frame.loc[mask, "net_return_5"].to_numpy(float)
        cvar = float(np.mean(np.sort(returns)[:max(1, int(len(returns) * 0.1))]))
        utility = float(np.mean(returns) + 0.35 * cvar - 0.2 * (1 - coverage))
        if best is None or utility > best[0]:
            best = (utility, threshold)
    return best[1] if best else 0.5


def _summary(frame: pd.DataFrame, mask=None) -> dict:
    selected = frame if mask is None else frame.loc[mask]
    values = selected["net_return_5"].to_numpy(float)
    if not len(values):
        return {"n": 0, "coverage": 0, "avg": None, "median": None, "cvar10": None, "risk_rate": None}
    tail = np.sort(values)[:max(1, int(len(values) * 0.1))]
    return {
        "n": len(values), "coverage": round(len(values) / max(len(frame), 1), 4),
        "avg": round(float(np.mean(values)), 4), "median": round(float(np.median(values)), 4),
        "cvar10": round(float(np.mean(tail)), 4),
        "risk_rate": round(float(selected["y_risk"].mean()), 4),
        "win_rate": round(float((values > 0).mean()), 4),
    }


def _aggregate_training_units(
    frame: pd.DataFrame, keys: list[str], feature_names: list[str], unit: str,
) -> pd.DataFrame:
    rows = []
    group_keys = keys[0] if len(keys) == 1 else keys
    for values, group in frame.groupby(group_keys, sort=True):
        values = (values,) if len(keys) == 1 else tuple(values)
        record = dict(zip(keys, values))
        record.update({name: float(group.iloc[0][name]) for name in feature_names})
        record.update({
            "label_end_date": str(group["label_end_date"].max()),
            "net_return_5": float(group["net_return_5"].mean()),
            "excess_5": float(group["excess_5"].mean()),
            "y_quality": int(group["excess_5"].mean() > 0),
            "y_risk": int(group["y_risk"].mean() >= 0.5),
            "sample_count": int(len(group)),
            "training_unit": unit,
        })
        rows.append(record)
    return pd.DataFrame(rows)


def _layer_frames(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "market": _aggregate_training_units(frame, ["date"], MARKET_FEATURES, "trade_date"),
        "sector": _aggregate_training_units(
            frame, ["date", "industry"], MARKET_FEATURES + SECTOR_FEATURES, "date_sector",
        ),
        "risk": frame.copy(),
        "quality": frame.copy(),
    }


def _fit_models(train: pd.DataFrame) -> dict[str, BinaryLogit]:
    units = _layer_frames(train)
    if any(units[key].empty for key in ("market", "sector", "risk", "quality")):
        raise ValueError("分层训练单元不足")
    risk_frame = units["risk"]
    positives = max(int(risk_frame["y_risk"].sum()), 1)
    risk_weight = np.where(
        risk_frame["y_risk"].to_numpy() == 1,
        len(risk_frame) / (2 * positives),
        1.0,
    )
    return {
        "market": BinaryLogit(MARKET_FEATURES).fit(units["market"], "y_quality"),
        "sector": BinaryLogit(MARKET_FEATURES + SECTOR_FEATURES).fit(units["sector"], "y_quality"),
        "risk": BinaryLogit(MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES).fit(
            risk_frame, "y_risk", sample_weight=risk_weight,
        ),
        "quality": BinaryLogit(MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES).fit(
            units["quality"], "y_quality",
        ),
    }


def _validation_thresholds(models: dict, validation: pd.DataFrame) -> dict[str, float]:
    units = _layer_frames(validation)
    market_p = models["market"].predict_proba(units["market"])
    sector_p = models["sector"].predict_proba(units["sector"])
    risk_p = models["risk"].predict_proba(units["risk"])
    return {
        "market": _choose_threshold(units["market"], market_p, True),
        "sector": _choose_threshold(units["sector"], sector_p, True),
        "risk": _choose_threshold(units["risk"], risk_p, False),
    }


def _apply(models: dict, frame: pd.DataFrame, thresholds: dict) -> tuple[dict, dict]:
    p = {key: model.predict_proba(frame) for key, model in models.items()}
    masks: dict[str, np.ndarray] = {
        "baseline": np.ones(len(frame), dtype=bool),
        "weekly": frame["weekly_passed"].fillna(0).to_numpy(dtype=int) == 1,
    }
    masks["market"] = p["market"] >= thresholds["market"]
    masks["sector"] = masks["market"] & (p["sector"] >= thresholds["sector"])
    masks["risk"] = masks["sector"] & (p["risk"] <= thresholds["risk"])
    quality = frame.assign(_p_quality=p["quality"], _keep=masks["risk"])
    quality_mask = pd.Series(False, index=frame.index)
    for _, group in quality[quality["_keep"]].groupby("date"):
        quality_mask.loc[group.nlargest(3, "_p_quality").index] = True
    masks["quality"] = quality_mask.to_numpy(dtype=bool)
    masks["full"] = masks["weekly"] & masks["quality"]
    return p, {**masks, "thresholds": thresholds}


def _aggregate_folds(folds: list[dict], layer: str) -> dict:
    rows = [f[layer] for f in folds if f[layer]["n"]]
    if not rows:
        return {"n": 0}
    return {
        "n": sum(r["n"] for r in rows),
        "months": len(rows),
        "avg": round(float(np.average([r["avg"] for r in rows], weights=[r["n"] for r in rows])), 4),
        "median_month": round(float(np.median([r["avg"] for r in rows])), 4),
        "cvar10": round(float(np.average([r["cvar10"] for r in rows], weights=[r["n"] for r in rows])), 4),
        "risk_rate": round(float(np.average([r["risk_rate"] for r in rows], weights=[r["n"] for r in rows])), 4),
        "coverage": round(float(np.mean([r["coverage"] for r in rows])), 4),
        "independent_n": sum(int(r.get("independent_n", r["n"])) for r in rows),
        "unit": rows[0].get("unit", "signal"),
    }


def _cluster_bootstrap_delta(
    frame: pd.DataFrame, selected: str, reference: str, cluster: str,
) -> dict:
    groups = []
    for _, group in frame.groupby(cluster):
        selected_values = group.loc[group[selected], "net_return_5"].to_numpy(float)
        reference_values = group.loc[group[reference], "net_return_5"].to_numpy(float)
        groups.append((
            float(selected_values.sum()), len(selected_values),
            float(reference_values.sum()), len(reference_values),
        ))
    if len(groups) < 2:
        return {"clusters": len(groups), "ci_low": None, "ci_high": None, "positive_probability": None}
    values = np.asarray(groups, dtype=float)
    rng = np.random.default_rng(20260717 + (0 if cluster == "date" else 1))
    deltas = []
    for _ in range(BOOTSTRAP_ITERATIONS):
        sample = values[rng.integers(0, len(values), size=len(values))]
        selected_n, reference_n = sample[:, 1].sum(), sample[:, 3].sum()
        if selected_n <= 0 or reference_n <= 0:
            continue
        deltas.append(sample[:, 0].sum() / selected_n - sample[:, 2].sum() / reference_n)
    if not deltas:
        return {"clusters": len(groups), "ci_low": None, "ci_high": None, "positive_probability": None}
    delta = np.asarray(deltas)
    return {
        "clusters": len(groups),
        "ci_low": round(float(np.quantile(delta, 0.0125)), 4),
        "ci_high": round(float(np.quantile(delta, 0.9875)), 4),
        "positive_probability": round(float((delta > 0).mean()), 4),
    }


def _bootstrap_evidence(frame: pd.DataFrame, layer: str, reference: str) -> dict:
    by_date = _cluster_bootstrap_delta(frame, layer, reference, "date")
    by_stock = _cluster_bootstrap_delta(frame, layer, reference, "code")
    lows = [item["ci_low"] for item in (by_date, by_stock) if item["ci_low"] is not None]
    probabilities = [
        item["positive_probability"] for item in (by_date, by_stock)
        if item["positive_probability"] is not None
    ]
    return {
        "date_cluster": by_date,
        "stock_cluster": by_stock,
        "worst_ci_low": min(lows) if lows else None,
        "worst_positive_probability": min(probabilities) if probabilities else None,
    }


def _purged_month_split(
    data: pd.DataFrame, train_months: list[str], validation_months: set[str], test_month: str,
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


def walk_forward(frame: pd.DataFrame, min_train_months: int = 12, val_months: int = 3) -> dict:
    missing = REQUIRED_DATASET_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"训练集缺少时点字段: {sorted(missing)}，请使用 --rebuild-dataset 重建")
    versions = set(pd.to_numeric(frame["dataset_schema_version"], errors="coerce").dropna())
    if versions != {DATASET_SCHEMA_VERSION}:
        raise ValueError(
            f"训练集版本不匹配: {sorted(versions)}，请使用 --rebuild-dataset 重建"
        )
    data = frame.copy()
    data["date"] = data["date"].astype(str)
    data["label_end_date"] = data["label_end_date"].astype(str)
    data["month"] = data["date"].str[:7]
    months = sorted(data["month"].unique())
    folds, selected_thresholds, oos_rows = [], [], []
    for test_i in range(min_train_months + val_months, len(months)):
        train_months = months[:test_i - val_months]
        val_set = set(months[test_i - val_months:test_i])
        train, val, test, validation_start, test_start = _purged_month_split(
            data, train_months, val_set, months[test_i],
        )
        if len(train) < 80 or len(val) < 20 or len(test) < 3:
            continue
        train_units = _layer_frames(train)
        if len(train_units["market"]) < 40 or len(train_units["sector"]) < 40:
            continue
        models = _fit_models(train)
        thresholds = _validation_thresholds(models, val)
        selected_thresholds.append(thresholds)
        probability, masks = _apply(models, test, thresholds)
        fold = {
            "month": months[test_i], "thresholds": thresholds,
            "validation_months": sorted(val_set),
            "purged_before_validation": validation_start,
            "purged_before_test": test_start,
        }
        for layer in ("baseline", "weekly", "market", "sector", "risk", "quality", "full"):
            fold[layer] = _summary(test, masks[layer])
            selected = test.loc[masks[layer]]
            if layer == "market":
                fold[layer].update({"independent_n": selected["date"].nunique(), "unit": "trade_date"})
            elif layer == "sector":
                fold[layer].update({
                    "independent_n": selected[["date", "industry"]].drop_duplicates().shape[0],
                    "unit": "date_sector",
                })
            else:
                fold[layer].update({"independent_n": len(selected), "unit": "signal"})
        test_units = _layer_frames(test)
        fold["probability"] = {
            "market": probability_metrics(
                test_units["market"]["y_quality"], models["market"].predict_proba(test_units["market"]),
            ),
            "sector": probability_metrics(
                test_units["sector"]["y_quality"], models["sector"].predict_proba(test_units["sector"]),
            ),
            "risk": probability_metrics(test["y_risk"], probability["risk"]),
            "quality": probability_metrics(test["y_quality"], probability["quality"]),
        }
        folds.append(fold)
        oos = test[["date", "code", "industry", "net_return_5", "y_risk"]].copy()
        for layer in ("baseline", "weekly", "market", "sector", "risk", "quality", "full"):
            oos[layer] = masks[layer]
        oos_rows.append(oos)

    layers = ("baseline", "weekly", "market", "sector", "risk", "quality", "full")
    aggregate = {layer: _aggregate_folds(folds, layer) for layer in layers}
    oos_frame = pd.concat(oos_rows, ignore_index=True) if oos_rows else pd.DataFrame()
    references = {
        "weekly": "baseline", "market": "baseline", "sector": "market",
        "risk": "sector", "quality": "risk", "full": "quality",
    }
    bootstrap = {
        layer: _bootstrap_evidence(oos_frame, layer, reference)
        for layer, reference in references.items()
    } if not oos_frame.empty else {}
    status = {}
    for layer in ("weekly", "market", "sector", "risk", "quality"):
        reference = references[layer]
        current = aggregate[layer]
        previous = aggregate[reference]
        if not current.get("n") or not previous.get("n"):
            status[layer] = "shadow"
        else:
            improved_return = current["avg"] >= previous["avg"]
            improved_tail = current["cvar10"] >= previous["cvar10"]
            improved_risk = current["risk_rate"] <= previous["risk_rate"]
            month_wins = sum(
                1 for f in folds
                if f[layer]["n"] and f[reference]["n"] and f[layer]["avg"] >= f[reference]["avg"]
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
                layer in {"weekly", "market"}
                or status.get(reference) == "active"
            )
            if layer == "risk":
                passed = improved_risk and improved_tail and majority and significant
            else:
                passed = improved_return and improved_tail and majority and significant
            status[layer] = "active" if passed and dependency_ready else (
                "shadow" if not dependency_ready else "rejected"
            )
    thresholds = selected_thresholds[-1] if selected_thresholds else {
        "market": 0.5, "sector": 0.5, "risk": 0.5,
    }
    return {
        "folds": folds, "aggregate": aggregate, "status": status,
        "thresholds": thresholds,
        "threshold_source": folds[-1]["validation_months"] if folds else None,
        "bootstrap": bootstrap,
        "purge_horizon_trading_days": 5,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
    }


def train_and_register(frame: pd.DataFrame, output: Path) -> dict:
    missing = REQUIRED_DATASET_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"训练集缺少时点字段: {sorted(missing)}，请重新构建")
    report = walk_forward(frame)
    if not report["folds"]:
        raise ValueError("没有满足 purge 和未来月份要求的 walk-forward 折")
    models = _fit_models(frame)
    canonical = frame.sort_values(["date", "code"]).to_csv(index=False, float_format="%.10g")
    digest = hashlib.sha256(
        f"{strategy_version()}|{FEATURE_VERSION}|".encode() + canonical.encode()
    ).hexdigest()[:12]
    version = f"hierarchy-{digest}"
    trained = datetime.now().astimezone().isoformat(timespec="seconds")
    bundle = {
        "version": version, "policy_version": version, "trained_as_of": trained,
        "train_range": [str(frame.date.min()), str(frame.date.max())],
        "thresholds": report["thresholds"], "status": report["status"],
        "threshold_source": report["threshold_source"],
        "metrics": report["aggregate"],
        "bootstrap": report["bootstrap"],
        "models": {key: model.to_dict() for key, model in models.items()},
        "source_refs": [
            "local-eod-csv", "point-in-time-reference-snapshots-v1",
            "super-b1-original", "weekly-four-ma-shadow",
            "execution-model-v1", "purged-walk-forward-v2",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    for key, model in models.items():
        validation_status = report["status"].get(key, "shadow")
        register_model({
            # 训练通过也只进入 shadow；发布必须经过独立的完整策略审核窗口。
            "model_key": key, "version": version,
            "status": "shadow" if validation_status == "active" else validation_status,
            "trained_as_of": trained, "train_range": "/".join(bundle["train_range"]),
            "test_range": "/".join([f["month"] for f in report["folds"][-2:]]) if report["folds"] else None,
            "feature_names": model.feature_names,
            "params": {
                "threshold": report["thresholds"].get(key), "l2": model.l2,
                "validation_status": validation_status,
            },
            "metrics": report["aggregate"].get(key, {}), "source_refs": bundle["source_refs"],
            "artifact": model.to_dict(),
        })
    register_policy_candidate({
        "policy_version": version,
        "research_status": "shadow",
        "trained_as_of": trained,
        "train_range": "/".join(bundle["train_range"]),
        "test_range": "/".join([f["month"] for f in report["folds"]]),
        "component_versions": {key: version for key in models},
        "metrics": {"full": report["aggregate"].get("full", {}),
                    "baseline": report["aggregate"].get("baseline", {})},
        "evidence": {
            "state": "forward_observation_required",
            "bootstrap": report["bootstrap"].get("full", {}),
            "folds": len(report["folds"]),
        },
        "source_refs": bundle["source_refs"],
    })
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
        cm = CSVManager("data")
        names = json.loads(Path("data/stock_names.json").read_text(encoding="utf-8"))
        industries = json.loads(Path("data/stock_industry.json").read_text(encoding="utf-8"))
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
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(frame), "range": [frame.date.min(), frame.date.max()],
                      "status": result["status"], "aggregate": result["aggregate"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
