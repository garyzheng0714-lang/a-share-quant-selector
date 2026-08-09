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
from zoneinfo import ZoneInfo

import requests

from utils.decision_ledger import save_event_evidence

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Shanghai")

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
POSITIVE_PATTERNS = {
    "earnings_growth": ("业绩预增", "扭亏为盈", "净利润增长", "业绩快报增长"),
    "major_contract": ("中标", "重大合同", "签订合同", "项目定点"),
    "shareholder_support": ("回购股份", "回购计划", "增持计划", "增持股份"),
    "approval": ("获得批准", "获批", "取得注册证", "取得专利"),
    "capacity": ("建成投产", "正式投产", "扩产", "新增产能"),
    "subsidy": ("政府补助", "专项补助"),
}


def _match(title: str, patterns: dict[str, tuple[str, ...]]) -> list[str]:
    negations = ("无", "未", "不存在", "不涉及", "未涉及", "没有")
    matched = []
    for code, words in patterns.items():
        for word in words:
            start = title.find(word)
            if start < 0:
                continue
            prefix = title[max(0, start - 5) : start]
            if any(prefix.endswith(token) for token in negations):
                continue
            matched.append(code)
            break
    return matched


def _classify_event(title: str, summary: str = "") -> dict:
    """把事件压缩成可追溯标签；只描述文本，不预测价格。"""
    text = f"{title} {summary}".strip()
    hard_tags = _match(text, HARD_PATTERNS)
    review_tags = _match(text, REVIEW_PATTERNS)
    positive_tags = _match(text, POSITIVE_PATTERNS)
    if positive_tags and (hard_tags or review_tags):
        sentiment = "mixed"
    elif hard_tags or review_tags:
        sentiment = "negative"
    elif positive_tags:
        sentiment = "positive"
    else:
        sentiment = "neutral"
    return {
        "sentiment": sentiment,
        "sentiment_label": {
            "positive": "利好线索",
            "negative": "利空风险",
            "mixed": "影响混合",
            "neutral": "中性信息",
        }[sentiment],
        "impact": "high"
        if hard_tags
        else "medium"
        if review_tags or positive_tags
        else "low",
        "hard_tags": hard_tags,
        "review_tags": review_tags,
        "positive_tags": positive_tags,
    }


def fetch_notice_events(
    codes: set[str],
    start_date: str,
    end_date: str,
    cache_dir: str | Path = "data/event_cache",
) -> dict:
    """按日抓取公告索引。源只给日期、不给分钟，故仅允许用于 preopen。"""
    import akshare as ak

    start, end = (
        datetime.fromisoformat(start_date).date(),
        datetime.fromisoformat(end_date).date(),
    )
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
                cache_file.write_text(
                    json.dumps(payload, ensure_ascii=False, default=str),
                    encoding="utf-8",
                )
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
            raw_id = (
                url.rsplit("/", 1)[-1].split(".")[0]
                if url
                else hashlib.sha256(title.encode()).hexdigest()[:16]
            )
            event_id = f"eastmoney-notice:{stamp}:{code}:{raw_id}"
            classification = _classify_event(title)
            event = {
                "event_id": event_id,
                "code": code,
                "name": str(row.get("名称", "")),
                "source": "eastmoney_notice_index",
                "source_name": "东方财富公告索引",
                "source_category": "announcement",
                "source_url": url,
                "published_at": f"{day.isoformat()}T00:00:00+08:00",
                "published_at_precision": "date",
                "eligible_stage": ["preopen"],
                "title": title,
                "summary": "",
                "notice_type": str(row.get("公告类型", "")),
                "text_hash": "sha256:" + hashlib.sha256(title.encode()).hexdigest(),
                "raw_ref": url,
                "fetched_at": fetched_at,
                **classification,
            }
            save_event_evidence(event)
            events.append(event)
        day += timedelta(days=1)
    return {
        "available": not errors,
        "events": events,
        "errors": errors,
        "source_refs": [f"eastmoney-notice:{start_date}:{end_date}"],
    }


def fetch_stock_news_events(
    candidates: list[dict],
    start_date: str,
    as_of: str,
    cache_dir: str | Path,
) -> dict:
    """抓取每只云阶候选最近新闻；只在 worker 中调用并保留精确截止时间。"""
    import akshare as ak

    cutoff = datetime.fromisoformat(as_of)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=TZ)
    cutoff = cutoff.astimezone(TZ)
    start = datetime.fromisoformat(start_date).date()
    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(TZ).isoformat(timespec="seconds")
    events: list[dict] = []
    errors: list[dict] = []
    successful_codes: set[str] = set()

    for candidate in candidates:
        code = str(candidate.get("code") or "").zfill(6)
        name = str(candidate.get("name") or "")
        cache_file = cache_root / f"{cutoff.date().isoformat()}-{code}.json"
        rows = None
        if cache_file.is_file():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                rows = cached.get("rows") if isinstance(cached, dict) else None
            except (OSError, json.JSONDecodeError):
                rows = None
        if rows is None:
            try:
                frame = ak.stock_news_em(symbol=code)
                rows = frame.to_dict("records") if frame is not None else []
                cache_file.write_text(
                    json.dumps(
                        {"fetched_at": fetched_at, "rows": rows},
                        ensure_ascii=False,
                        default=str,
                    ),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.warning("个股新闻获取失败 %s: %s", code, exc)
                errors.append({"code": code, "error": type(exc).__name__})
                continue
        successful_codes.add(code)

        accepted = 0
        for row in rows:
            title = str(row.get("新闻标题") or "").strip()
            published_raw = str(row.get("发布时间") or "").strip()
            if not title or not published_raw:
                continue
            try:
                published = datetime.fromisoformat(published_raw)
            except ValueError:
                continue
            if published.tzinfo is None:
                published = published.replace(tzinfo=TZ)
            published = published.astimezone(TZ)
            if published.date() < start or published > cutoff:
                continue
            summary = " ".join(str(row.get("新闻内容") or "").split())[:500]
            url = str(row.get("新闻链接") or "").strip()
            raw_identity = url or f"{code}|{published.isoformat()}|{title}"
            raw_id = hashlib.sha256(raw_identity.encode("utf-8")).hexdigest()[:20]
            classification = _classify_event(title, summary)
            relevance = (
                "direct"
                if code in title or (name and name in title)
                else "mentioned"
                if code in summary or (name and name in summary)
                else "search_result"
            )
            event = {
                "event_id": f"eastmoney-news:{code}:{raw_id}",
                "code": code,
                "name": name,
                "source": "eastmoney_stock_news",
                "source_name": str(row.get("文章来源") or "东方财富资讯").strip(),
                "source_category": "media",
                "source_url": url,
                "published_at": published.isoformat(timespec="seconds"),
                "published_at_precision": "second",
                "eligible_stage": ["close", "preopen"],
                "title": title,
                "summary": summary,
                "relevance": relevance,
                "text_hash": "sha256:"
                + hashlib.sha256(f"{title}\n{summary}".encode("utf-8")).hexdigest(),
                "raw_ref": url,
                "fetched_at": fetched_at,
                **classification,
            }
            save_event_evidence(event)
            events.append(event)
            accepted += 1
            if accepted >= 30:
                break

    return {
        "available": not errors,
        "availability_by_code": {
            str(candidate.get("code") or "").zfill(6): str(
                candidate.get("code") or ""
            ).zfill(6)
            in successful_codes
            for candidate in candidates
        },
        "events": events,
        "errors": errors,
        "source_refs": [
            f"eastmoney-stock-news:{start_date}:{cutoff.isoformat(timespec='seconds')}"
        ]
        if candidates
        else [],
    }


def _call_event_llm(events: list[dict]) -> dict:
    """LLM 只做有引用的影子标签，不获得否决、排序或动作修改权。"""
    from utils.daily_pick import (
        DEFAULT_ANTHROPIC_MODEL,
        DEFAULT_ARK_BASE_URL,
        _extract_json,
        _get_llm_provider,
        _load_llm_config,
        get_api_key,
    )

    cfg = _load_llm_config()
    provider = _get_llm_provider(cfg)
    if provider is None:
        return {"available": False, "reason": "llm_provider_invalid", "decisions": []}
    api_key = get_api_key(cfg)
    if not api_key or not events:
        return {
            "available": False,
            "reason": "llm_unconfigured_or_no_events",
            "decisions": [],
        }
    compact = [
        {
            "event_id": e["event_id"],
            "code": e["code"],
            "published_at": e["published_at"],
            "title": e["title"],
            "source_url": e.get("source_url"),
        }
        for e in events
    ]
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
                model=model,
                max_tokens=4000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = next(
                block.text for block in response.content if block.type == "text"
            )
            result = _extract_json(text)
        else:
            model = cfg.get("model")
            if not model:
                return {
                    "available": False,
                    "reason": "llm_model_missing",
                    "decisions": [],
                }
            response = requests.post(
                f"{(cfg.get('base_url') or DEFAULT_ARK_BASE_URL).rstrip('/')}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                },
                timeout=120,
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
        if (
            not event
            or action not in {"veto", "no_veto", "unsure"}
            or title != event["title"]
        ):
            continue
        confidence = float(item.get("confidence", 0))
        valid.append(
            {
                **item,
                "confidence": max(0, min(confidence, 1)),
                "code": event["code"],
                "source_url": event.get("source_url"),
            }
        )
    return {"available": True, "model": model, "decisions": valid}


def review_candidates(
    candidates: list[dict], trade_date: str, as_of: str, llm_label_enabled: bool = False
) -> dict:
    codes = {str(c["code"]) for c in candidates}
    # 当前源只有日期精度。盘前不能抓取 as_of 当天的整日索引，否则会混入盘后公告。
    end_date = (datetime.fromisoformat(as_of).date() - timedelta(days=1)).isoformat()
    fetched = fetch_notice_events(codes, trade_date, end_date)
    events = fetched["events"]
    timestamped_events = [
        event
        for event in events
        if event.get("published_at_precision") not in {None, "date"}
        and event.get("published_at", "") <= as_of
    ]
    llm = (
        _call_event_llm(timestamped_events)
        if llm_label_enabled
        else {"available": False, "reason": "llm_label_disabled", "decisions": []}
    )
    events_by_code = {code: [] for code in codes}
    veto_codes, review_codes = set(), set()
    for event in events:
        events_by_code[event["code"]].append(event)
        timestamp_precise = event.get("published_at_precision") not in {None, "date"}
        if (
            event["hard_tags"]
            and timestamp_precise
            and event.get("published_at", "") <= as_of
        ):
            veto_codes.add(event["code"])
        elif event["hard_tags"] or event["review_tags"]:
            review_codes.add(event["code"])
    return {
        "available": fetched["available"],
        "events_by_code": events_by_code,
        "veto_codes": sorted(veto_codes),
        "review_codes": sorted(review_codes),
        "source_refs": fetched["source_refs"],
        "errors": fetched["errors"],
        "llm": llm,
        "llm_label_enabled": llm_label_enabled,
        "llm_action_applied": False,
    }
