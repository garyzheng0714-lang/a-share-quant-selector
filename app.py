"""A 股因子选股工具 - 只读 Web 服务。

只做三件事：列因子、按因子（且/或）出股票、看 K 线。所有数据由 updater.py 盘后写好，
这里不抓行情、不扫描、不落账，任何一个接口都不会改文件。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from utils import scan
from utils.kline import build_kline
from utils.store import Store

logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=None)
store = Store()
_DIST = Path(__file__).parent / "frontend" / "dist"
_CODE_RE = re.compile(r"^\d{6}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _bad(reason: str, status: int = 400):
    return jsonify({"available": False, "reason": reason}), status


def _decorate(hit: dict) -> dict:
    industry = store.industries().get(hit["code"], "")
    return {**hit, "industry": industry, "cap_yi": store.cap_yi(hit["code"])}


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.get("/api/stats")
def api_stats():
    dates = scan.cache_dates(store)
    return jsonify(
        {
            "latest_date": store.latest_date(),
            "scan_date": dates[0] if dates else None,
            "stock_count": len(store.list_stocks()),
        }
    )


@app.get("/api/factors")
def api_factors():
    from strategy.factors import FACTOR_REGISTRY, GROUP_ORDER, PLAIN_DESC, PRESETS

    dates = scan.cache_dates(store)
    trade_date = dates[0] if dates else ""
    cache = scan.load_cache(store, trade_date) if trade_date else {}

    def codes(key):
        bucket = cache.get(key)
        return None if bucket is None else {h["code"] for h in bucket.get("hits", [])}

    factors = []
    for key, meta in FACTOR_REGISTRY.items():
        doc = (meta["fn"].__doc__ or "").strip().splitlines()
        desc = doc[0].split("：", 1)[-1].strip() if doc else ""
        hits = codes(key)
        factors.append(
            {
                "key": key,
                "name": meta["name"],
                "group": meta["group"],
                "desc": desc,
                "plain": PLAIN_DESC.get(key, desc),
                "today_hits": None if hits is None else len(hits),
            }
        )
    factors.sort(
        key=lambda f: GROUP_ORDER.index(f["group"]) if f["group"] in GROUP_ORDER else 99
    )

    presets = []
    for preset in PRESETS:
        if not all(k in FACTOR_REGISTRY for k in preset["keys"]):
            continue
        sets = [codes(k) for k in preset["keys"]]
        hits = (
            None
            if any(s is None for s in sets)
            else len(scan.compose_codes(sets, preset["join"]))
        )
        presets.append({**preset, "today_hits": hits})

    return jsonify(
        {
            "factors": factors,
            "presets": presets,
            "groups": GROUP_ORDER,
            "trade_date": trade_date,
            "recent_dates": dates,
        }
    )


@app.get("/api/factor-scan")
def api_factor_scan():
    key = request.args.get("strategy", "").strip()
    date = request.args.get("date", "").strip()
    if date and not _DATE_RE.match(date):
        return _bad("日期格式不合法")
    dates = scan.cache_dates(store)
    trade_date = date or (dates[0] if dates else "")
    bucket = scan.load_cache(store, trade_date).get(key) if trade_date else None
    if bucket is None:
        return jsonify(
            {
                "available": False,
                "reason": f"{trade_date or '当日'} 没有 {key or '该因子'} 的扫描结果",
            }
        )
    return jsonify(
        {
            "available": True,
            "strategy": key,
            "trade_date": trade_date,
            "hits": [_decorate(h) for h in bucket.get("hits", [])],
            "total_scanned": bucket.get("total_scanned", 0),
        }
    )


@app.get("/api/factor-compose")
def api_factor_compose():
    """多因子组合：keys 逗号分隔，join=and|or。任一因子没有当日结果就整体不可用."""
    from strategy.factors import FACTOR_REGISTRY

    keys = list(
        dict.fromkeys(
            k.strip() for k in request.args.get("keys", "").split(",") if k.strip()
        )
    )
    join = request.args.get("join", "and").strip()
    date = request.args.get("date", "").strip()
    if not keys or any(k not in FACTOR_REGISTRY for k in keys):
        return _bad("缺少或未知的因子 keys")
    if join not in ("and", "or"):
        return _bad("join 只能是 and 或 or")
    if date and not _DATE_RE.match(date):
        return _bad("日期格式不合法")

    dates = scan.cache_dates(store)
    trade_date = date or (dates[0] if dates else "")
    cache = scan.load_cache(store, trade_date) if trade_date else {}
    missing = [k for k in keys if k not in cache]
    if missing:
        return jsonify(
            {
                "available": False,
                "reason": f"{trade_date or '当日'} 没有 {', '.join(missing)} 的扫描结果",
                "trade_date": trade_date,
            }
        )

    per_key = {k: {h["code"]: h for h in cache[k].get("hits", [])} for k in keys}
    codes = scan.compose_codes([set(v) for v in per_key.values()], join)

    # 连续命中：逐个往前看已缓存的交易日，缓存断档即停
    history = []
    for prev in [d for d in dates if d < trade_date]:
        prev_cache = scan.load_cache(store, prev)
        if any(k not in prev_cache for k in keys):
            break
        history.append(
            scan.compose_codes(
                [{h["code"] for h in prev_cache[k]["hits"]} for k in keys], join
            )
        )

    def streak(code):
        n = 1
        for prev in history:
            if code not in prev:
                break
            n += 1
        return n

    hits = []
    for code in codes:
        matched = [k for k in keys if code in per_key[k]]
        base = _decorate(per_key[matched[0]][code])
        spark = store.read_stock(code, nrows=20)
        hits.append(
            {
                **base,
                "matched": matched,
                "streak": streak(code),
                "streak_depth": len(history) + 1,
                "spark": [round(float(v), 2) for v in spark["close"].tolist()[::-1]]
                if not spark.empty
                else [],
            }
        )
    hits.sort(
        key=lambda h: (
            -len(h["matched"]),
            -h["streak"],
            h.get("J") if h.get("J") is not None else 999,
            h["code"],
        )
    )
    return jsonify(
        {
            "available": True,
            "keys": keys,
            "join": join,
            "trade_date": trade_date,
            "hits": hits,
            "per_key_counts": {k: len(v) for k, v in per_key.items()},
            "total_scanned": max(
                (cache[k].get("total_scanned", 0) for k in keys), default=0
            ),
        }
    )


@app.get("/api/stock/<code>/profile")
def api_stock_profile(code: str):
    if not _CODE_RE.match(code):
        return _bad("invalid_stock_code")
    return jsonify(
        {
            "code": code,
            "name": store.names().get(code, "未知"),
            "industry": store.industries().get(code, ""),
            "cap_yi": store.cap_yi(code),
            "latest_date": store.stock_date(code),
        }
    )


@app.get("/api/stock/<code>/kline")
def api_stock_kline(code: str):
    if not _CODE_RE.match(code):
        return jsonify({"success": False, "error": "invalid_stock_code"}), 400
    period = request.args.get("period", "daily")
    if period not in ("daily", "weekly"):
        return jsonify({"success": False, "error": "invalid_period"}), 400
    try:
        days = int(request.args.get("days", 200 if period == "daily" else 2000))
    except ValueError:
        return jsonify({"success": False, "error": "invalid_days"}), 400
    days = max(1, min(days, 5000))
    frame = store.read_stock(code, nrows=days)
    if frame.empty:
        return jsonify({"success": False, "error": "stock_not_found"}), 404
    from strategy.factors import FACTOR_REGISTRY

    signals = []
    for date in scan.cache_dates(store)[:60]:
        for key, bucket in scan.load_cache(store, date).items():
            if any(h["code"] == code for h in bucket.get("hits", [])):
                signals.append(
                    {
                        "date": date,
                        "category": FACTOR_REGISTRY.get(key, {}).get("name", key),
                    }
                )
    payload = build_kline(frame, period)
    return jsonify(
        {
            "success": True,
            "code": code,
            "name": store.names().get(code, "未知"),
            "period": period,
            "change_label": "本周涨跌" if period == "weekly" else "今日涨跌",
            "signals": signals,
            **payload,
        }
    )


@app.get("/")
@app.get("/<path:path>")
def serve_frontend(path: str = ""):
    if path.startswith("api/"):
        return jsonify({"error": "not_found"}), 404
    target = _DIST / path
    if path and target.is_file():
        return send_from_directory(_DIST, path)
    return send_from_directory(_DIST, "index.html")


def create_app():
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=18321)
