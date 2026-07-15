"""盘前公告事件抓取与有引用的风险否决。

数据源当前使用 AkShare 封装的东财公告索引，不冒充交易所原始 API。
每条记录保留来源 URL、抓取时间、文本指纹和时间精度。
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests

from utils.decision_ledger import save_event_evidence

logger = logging.getLogger(__name__)

HARD_PATTERNS = {
    "investigation": ("立案调查", "立案告知"),
    "penalty": ("行政处罚", "重大违法", "纪律处分"),
    "delisting": ("终止上市", "暂停上市", "退市风险警示"),
    "earnings_shock": ("业绩预亏", "大幅预减", "业绩预告修正", "减值准备"),
    "debt_or_fraud": ("债务逾期", "资金占用", "财务造假", "重大诉讼"),
    "deal_failed": ("重组终止", "交易终止", "收购终止"),
    "accident": ("重大事故", "停产整顿"),
}
REVIEW_PATTERNS = {
    "reduction": ("减持计划", "减持股份"),
    "inquiry": ("问询函", "监管函", "关注函"),
    "risk_notice": ("风险提示", "异常波动"),
    "pledge": ("质押", "冻结"),
}


def _match(title: str, patterns: dict[str, tuple[str, ...]]) -> list[str]:
    return [code for code, words in patterns.items() if any(word in title for word in words)]


def fetch_notice_events(codes: set[str], start_date: str, end_date: str,
                        cache_dir: str | Path = "data/event_cache") -> dict:
    """按日抓取公告索引。源只给日期、不给分钟，故仅允许用于 preopen。"""
    import akshare as ak

    start, end = datetime.fromisoformat(start_date).date(), datetime.fromisoformat(end_date).date()
    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    events, errors = [], []
    day = start
    while day <= end:
        stamp = day.strftime("%Y%m%d")
        cache_file = cache_root / f"{stamp}.json"
        payload = None
        if cache_file.exists():
            try:
                payload = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                payload = None
        if payload is None:
            try:
                frame = ak.stock_notice_report(symbol="全部", date=stamp)
                payload = frame.to_dict("records") if frame is not None else []
                cache_file.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
            except Exception as exc:
                logger.warning("公告索引获取失败 %s: %s", stamp, exc)
                errors.append({"date": day.isoformat(), "error": str(exc)})
                day += timedelta(days=1)
                continue
        for row in payload:
            code = str(row.get("代码", "")).zfill(6)
            if code not in codes:
                continue
            title = str(row.get("公告标题", "")).strip()
            url = str(row.get("网址", ""))
            raw_id = url.rsplit("/", 1)[-1].split(".")[0] if url else hashlib.sha256(title.encode()).hexdigest()[:16]
            event_id = f"eastmoney-notice:{stamp}:{code}:{raw_id}"
            event = {
                "event_id": event_id, "code": code, "name": str(row.get("名称", "")),
                "source": "eastmoney_notice_index", "source_url": url,
                "published_at": f"{day.isoformat()}T00:00:00+08:00",
                "published_at_precision": "date", "eligible_stage": ["preopen"],
                "title": title, "notice_type": str(row.get("公告类型", "")),
                "text_hash": "sha256:" + hashlib.sha256(title.encode()).hexdigest(),
                "raw_ref": url, "fetched_at": fetched_at,
                "hard_tags": _match(title, HARD_PATTERNS),
                "review_tags": _match(title, REVIEW_PATTERNS),
            }
            save_event_evidence(event)
            events.append(event)
        day += timedelta(days=1)
    return {"available": not errors, "events": events, "errors": errors,
            "source_refs": [f"eastmoney-notice:{start_date}:{end_date}"]}


def _call_event_llm(events: list[dict]) -> dict:
    """LLM 只做引用式标签与否决，不获得排序权。"""
    from utils.daily_pick import (
        DEFAULT_ANTHROPIC_MODEL, DEFAULT_ARK_BASE_URL, _extract_json,
        _load_llm_config, get_api_key,
    )

    api_key = get_api_key()
    if not api_key or not events:
        return {"available": False, "reason": "llm_unconfigured_or_no_events", "decisions": []}
    cfg = _load_llm_config()
    provider = (cfg.get("provider") or "ark").lower()
    compact = [{
        "event_id": e["event_id"], "code": e["code"], "published_at": e["published_at"],
        "title": e["title"], "source_url": e.get("source_url"),
    } for e in events]
    system = (
        "你是A股公告风险信息抽取器。你无权推荐、排序或预测涨跌。"
        "只能根据给定的公告标题输出 veto/no_veto/unsure。"
        "veto 仅用于立案、处罚、退市、重大业绩恶化、重大债务/诉讼、重组失败等明确负面事件。"
        "evidence_title 必须原样复制输入标题，不得补写未提供事实。"
    )
    prompt = json.dumps(compact, ensure_ascii=False) + (
        '\n只输出JSON: {"decisions":[{"event_id":"...","action":"veto|no_veto|unsure",'
        '"reason_code":"...","confidence":0.0,"evidence_title":"原标题"}]}'
    )
    try:
        if provider == "anthropic":
            import anthropic
            model = cfg.get("model") or DEFAULT_ANTHROPIC_MODEL
            response = anthropic.Anthropic(api_key=api_key).messages.create(
                model=model, max_tokens=4000, system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = next(block.text for block in response.content if block.type == "text")
            result = _extract_json(text)
        else:
            model = cfg.get("model")
            if not model:
                return {"available": False, "reason": "llm_model_missing", "decisions": []}
            response = requests.post(
                f"{(cfg.get('base_url') or DEFAULT_ARK_BASE_URL).rstrip('/')}/chat/completions",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json={"model": model, "messages": [
                    {"role": "system", "content": system}, {"role": "user", "content": prompt},
                ], "temperature": 0}, timeout=120,
            )
            response.raise_for_status()
            result = _extract_json(response.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.warning("公告 LLM 提取失败: %s", exc)
        return {"available": False, "reason": str(exc), "decisions": []}

    by_id = {e["event_id"]: e for e in events}
    valid = []
    for item in result.get("decisions", []):
        event = by_id.get(str(item.get("event_id", "")))
        action = item.get("action")
        title = item.get("evidence_title", "")
        if not event or action not in {"veto", "no_veto", "unsure"} or title != event["title"]:
            continue
        confidence = float(item.get("confidence", 0))
        valid.append({**item, "confidence": max(0, min(confidence, 1)),
                      "code": event["code"], "source_url": event.get("source_url")})
    return {"available": True, "model": model, "decisions": valid}


def review_candidates(candidates: list[dict], trade_date: str, as_of: str,
                      llm_veto_enabled: bool = False) -> dict:
    codes = {str(c["code"]) for c in candidates}
    end_date = datetime.fromisoformat(as_of).date().isoformat()
    fetched = fetch_notice_events(codes, trade_date, end_date)
    events = fetched["events"]
    llm = (
        _call_event_llm(events)
        if llm_veto_enabled
        else {"available": False, "reason": "llm_veto_disabled", "decisions": []}
    )
    events_by_code = {code: [] for code in codes}
    veto_codes, review_codes = set(), set()
    for event in events:
        events_by_code[event["code"]].append(event)
        if event["hard_tags"]:
            veto_codes.add(event["code"])
        elif event["review_tags"]:
            review_codes.add(event["code"])
    if llm_veto_enabled and llm.get("available"):
        for item in llm["decisions"]:
            if item["action"] == "veto" and item["confidence"] >= 0.8:
                veto_codes.add(item["code"])
    return {
        "available": fetched["available"], "events_by_code": events_by_code,
        "veto_codes": sorted(veto_codes), "review_codes": sorted(review_codes),
        "source_refs": fetched["source_refs"], "errors": fetched["errors"],
        "llm": llm, "llm_veto_enabled": llm_veto_enabled,
    }
