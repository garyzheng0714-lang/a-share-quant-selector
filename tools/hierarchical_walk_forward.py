"""市场 -> 板块 -> 个股的月度 walk-forward 与消融评估。

输出的模型默认是 shadow。只有在多个真正未来月份中对纯规则
baseline 有增量的层，才会在 model_registry 中标为 active。
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
from utils.decision_ledger import register_model  # noqa: E402
from utils.execution_model import evaluate_trade  # noqa: E402
from utils.probability_model import BinaryLogit, probability_metrics  # noqa: E402

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


def build_panels(cm: CSVManager, codes: list[str], industry_map: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    frames, stock_frames = [], {}
    with ThreadPoolExecutor(max_workers=min(12, max(1, len(codes)))) as pool:
        loaded = pool.map(lambda c: (c, _read_stock(cm, c, industry_map.get(c, ""))), codes)
        for code, frame in loaded:
            if frame is not None:
                stock_frames[code] = frame
                frames.append(frame[["date", "code", "industry", "ret1", "amount_proxy"]])
    panel = pd.concat(frames, ignore_index=True).dropna(subset=["ret1"])

    market = panel.groupby("date").agg(
        market_ret_1=("ret1", "mean"),
        market_breadth=("ret1", lambda s: float((s > 0).mean())),
        market_amount=("amount_proxy", "sum"),
        market_limit_down_ratio=("ret1", lambda s: float((s <= -0.095).mean())),
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
    code, name, frame, market, sector, market_cap = args
    from strategy.super_b1 import compute_super_b1

    rows = []
    hits = compute_super_b1(frame, code, market_cap=market_cap, return_history=True)
    date_to_index = {date: i for i, date in enumerate(frame["date"])}
    for hit in hits if isinstance(hits, list) else []:
        date = hit["date"]
        i = date_to_index.get(date)
        if i is None or i >= len(frame) - 5:
            continue
        sub = frame.iloc[:i + 1]
        ctx = FactorContext(sub)
        industry = frame.iloc[i]["industry"]
        if date not in market.index or (date, industry) not in sector.index:
            continue
        execution = evaluate_trade(frame, date, hold_days=5)
        if not execution.get("available"):
            continue
        future_date = execution.get("exit_date")
        if not future_date or future_date not in market.index:
            continue
        market_forward = (market.loc[future_date, "market_index"] / market.loc[date, "market_index"] - 1) * 100
        net_return = execution.get("net_return")
        if net_return is None:
            net_return = -20.0
        m = market.loc[date]
        s = sector.loc[(date, industry)]
        record = {
            "date": date, "code": code, "name": name, "industry": industry,
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
    if limit:
        codes = codes[:limit]
    market, sector, stock_frames = build_panels(cm, codes, industry_map)
    cap_path = Path(cm.data_dir) / "stock_market_cap.json"
    caps = json.loads(cap_path.read_text(encoding="utf-8")) if cap_path.exists() else {}
    tasks = [
        (code, names.get(code, code), frame, market, sector,
         ((caps.get(code) or {}).get("circ_mv") or (caps.get(code) or {}).get("total_mv") or 0))
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


def _fit_models(train: pd.DataFrame) -> dict[str, BinaryLogit]:
    positives = max(int(train["y_risk"].sum()), 1)
    risk_weight = np.where(train["y_risk"].to_numpy() == 1, len(train) / (2 * positives), 1.0)
    return {
        "market": BinaryLogit(MARKET_FEATURES).fit(train, "y_quality"),
        "sector": BinaryLogit(MARKET_FEATURES + SECTOR_FEATURES).fit(train, "y_quality"),
        "risk": BinaryLogit(MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES).fit(
            train, "y_risk", sample_weight=risk_weight
        ),
        "quality": BinaryLogit(MARKET_FEATURES + SECTOR_FEATURES + STOCK_FEATURES).fit(train, "y_quality"),
    }


def _apply(models: dict, frame: pd.DataFrame, thresholds: dict | None = None) -> tuple[dict, dict]:
    p = {key: model.predict_proba(frame) for key, model in models.items()}
    if thresholds is None:
        thresholds = {
            "market": _choose_threshold(frame, p["market"], True),
            "sector": _choose_threshold(frame, p["sector"], True),
            "risk": _choose_threshold(frame, p["risk"], False),
        }
    masks = {}
    masks["baseline"] = np.ones(len(frame), dtype=bool)
    masks["market"] = p["market"] >= thresholds["market"]
    masks["sector"] = masks["market"] & (p["sector"] >= thresholds["sector"])
    masks["risk"] = masks["sector"] & (p["risk"] <= thresholds["risk"])
    quality = frame.assign(_p_quality=p["quality"], _keep=masks["risk"])
    top_codes = set()
    for _, group in quality[quality["_keep"]].groupby("date"):
        top_codes.update(group.nlargest(3, "_p_quality").index.tolist())
    masks["quality"] = np.asarray([idx in top_codes for idx in frame.index])
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
    }


def walk_forward(frame: pd.DataFrame, min_train_months: int = 12, val_months: int = 3) -> dict:
    data = frame.copy()
    data["month"] = data["date"].str[:7]
    months = sorted(data["month"].unique())
    folds, selected_thresholds = [], []
    for test_i in range(min_train_months + val_months, len(months)):
        train_months = months[:test_i - val_months]
        val_set = set(months[test_i - val_months:test_i])
        train = data[data["month"].isin(train_months)]
        val = data[data["month"].isin(val_set)].copy()
        test = data[data["month"] == months[test_i]].copy()
        if len(train) < 80 or len(val) < 20 or len(test) < 3:
            continue
        models = _fit_models(train)
        _, val_masks = _apply(models, val)
        thresholds = val_masks["thresholds"]
        selected_thresholds.append(thresholds)
        probability, masks = _apply(models, test, thresholds)
        fold = {"month": months[test_i], "thresholds": thresholds}
        for layer in ("baseline", "market", "sector", "risk", "quality"):
            fold[layer] = _summary(test, masks[layer])
        fold["probability"] = {
            "market": probability_metrics(test["y_quality"], probability["market"]),
            "sector": probability_metrics(test["y_quality"], probability["sector"]),
            "risk": probability_metrics(test["y_risk"], probability["risk"]),
            "quality": probability_metrics(test["y_quality"], probability["quality"]),
        }
        folds.append(fold)

    aggregate = {layer: _aggregate_folds(folds, layer) for layer in ("baseline", "market", "sector", "risk", "quality")}
    baseline = aggregate["baseline"]
    status = {}
    previous = baseline
    for layer in ("market", "sector", "risk", "quality"):
        current = aggregate[layer]
        if not current.get("n") or not previous.get("n"):
            status[layer] = "shadow"
        else:
            improved_return = current["avg"] >= previous["avg"]
            improved_tail = current["cvar10"] >= previous["cvar10"]
            improved_risk = current["risk_rate"] <= previous["risk_rate"]
            month_wins = sum(
                1 for f in folds
                if f[layer]["n"] and f["baseline"]["n"] and f[layer]["avg"] >= f["baseline"]["avg"]
            )
            majority = month_wins >= max(1, int(np.ceil(len(folds) * 0.55)))
            if layer == "risk":
                passed = improved_risk and improved_tail and majority
            else:
                passed = improved_return and improved_tail and majority
            status[layer] = "active" if passed else "rejected"
        if status[layer] == "active":
            previous = current
    med_thresholds = {
        key: float(np.median([t[key] for t in selected_thresholds])) if selected_thresholds else 0.5
        for key in ("market", "sector", "risk")
    }
    return {"folds": folds, "aggregate": aggregate, "status": status, "thresholds": med_thresholds}


def train_and_register(frame: pd.DataFrame, output: Path) -> dict:
    report = walk_forward(frame)
    models = _fit_models(frame)
    canonical = frame.sort_values(["date", "code"]).to_csv(index=False, float_format="%.10g")
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:12]
    version = f"hierarchy-{digest}"
    trained = datetime.now().astimezone().isoformat(timespec="seconds")
    bundle = {
        "version": version, "trained_as_of": trained,
        "train_range": [str(frame.date.min()), str(frame.date.max())],
        "thresholds": report["thresholds"], "status": report["status"],
        "metrics": report["aggregate"],
        "models": {key: model.to_dict() for key, model in models.items()},
        "source_refs": ["local-eod-csv", "super-b1-original", "execution-model-v1"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    for key, model in models.items():
        validation_status = report["status"].get(key, "shadow")
        register_model({
            # 训练通过也先进入 shadow；只有每日进化器能原子晋级整套模型。
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
        dataset_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(dataset_path, index=False)
    else:
        frame = pd.read_csv(dataset_path)
    if frame.empty:
        raise SystemExit("无B1历史信号，无法训练")
    result = train_and_register(frame, Path(args.bundle))
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rows": len(frame), "range": [frame.date.min(), frame.date.max()],
                      "status": result["status"], "aggregate": result["aggregate"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
