"""全策略每日复盘的受控 AI 解释器。

AI 只读取已由量化模型确定的评分、排名和证据状态，不得改权重、
改排名或生成买卖动作。LLM 未配置时，仍返回完整的确定性复盘。
"""

from __future__ import annotations

import hashlib
import re
import orjson
import requests


PROMPT_VERSION = "strategy-daily-review-v2"
FORBIDDEN_ACTION_TERMS = (
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "清仓",
    "抄底",
    "保证收益",
    "必涨",
    "稳赚",
)
SYSTEM_PROMPT = (
    "你是 A 股量化系统的复盘解释器，请使用简体中文。"
    "量化模型已经确定所有指标、排名和证据状态；你无权更改它们。"
    "你只能解释今日证据、样本不确定性、输入中明确给出的前日变化，并提出后续影子实验建议。"
    "不得给出买入、卖出、保证收益或擅自提升策略的结论。"
    "不得输出任何数字、胜率、收益率、排名或‘最优/领先/冠军’等未受结构化字段校验的断言。"
    "样本不足时必须明确说‘预热中’，不得宣称已找到最优策略。"
)


def _num(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def deterministic_conclusion(report: dict) -> dict:
    """无需 LLM 也能产出的完整、可追溯结论。"""
    strategies = list(report.get("strategies") or [])
    eligible = [row for row in strategies if row.get("status") == "eligible"]
    today_hits_complete = report.get("today_hits_complete") is True
    signal_count = (
        sum(int(row.get("today_hit_count") or 0) for row in strategies)
        if today_hits_complete
        else None
    )
    primary = int(report.get("primary_horizon") or 5)
    leader = report.get("leader") if eligible else None

    provisional = sorted(
        (
            row
            for row in strategies
            if _num(((row.get("windows") or {}).get("T+1") or {}).get("sample_count"))
            > 0
        ),
        key=lambda row: (
            _num(
                ((row.get("windows") or {}).get("T+1") or {}).get(
                    "bayesian_win_rate_pct"
                )
            ),
            _num(
                ((row.get("windows") or {}).get("T+1") or {}).get(
                    "daily_avg_net_return_pct"
                )
            ),
        ),
        reverse=True,
    )
    provisional_name = provisional[0].get("name") if provisional else None
    signal_summary = (
        f"共记录 {signal_count} 次当日命中。"
        if signal_count is not None
        else "当日命中仍待因子快照补齐。"
    )
    if leader:
        headline = f"T+{primary} 影子评分已形成，当前领先为 {leader.get('name')}"
        summary = (
            f"今日 {len(strategies)} 个策略完成复盘，{signal_summary}"
            f"{len(eligible)} 个策略达到样本门槛；评分仍只用于影子反馈。"
        )
    else:
        headline = "多策略模型预热中，今日不宣称胜率冠军"
        summary = (
            f"今日 {len(strategies)} 个策略完成复盘，{signal_summary}"
            f"目前没有策略同时满足 T+{primary} 的成熟信号日和票级样本门槛。"
        )

    observations = []
    if provisional_name and not leader:
        observations.append(
            f"{provisional_name} 的 T+1 早期数据目前居前，但它只是短周期预览，不是 T+{primary} 胜率结论。"
        )
    if not today_hits_complete:
        observations.append("当日因子快照尚未齐全，当前不把未知命中数显示为 0。")
    if not observations:
        observations.append("目前只保留可核验的成熟窗口，未成熟收益不进入评分。")

    return {
        "headline": headline,
        "summary": summary,
        "observations": observations,
        "risks": [
            "不同股票在同一信号日高度相关，系统已按信号日等权，但日数过少仍会导致误差很大。",
            "当日命中和今日涨跌不用来给当日策略打分，必须等后续窗口成熟。",
        ],
        "next_actions": [
            f"继续每日积累前向信号，优先补足 T+{primary} 成熟信号日。",
            "只在达到样本门槛后生成影子权重，生产选股逻辑暂不受其影响。",
        ],
        "feedback": "shadow_only",
        "source": "deterministic_model",
    }


def _prompt(report: dict, previous_report: dict | None = None) -> str:
    compact = {
        "trade_date": report.get("trade_date"),
        "primary_horizon": report.get("primary_horizon"),
        "status": report.get("status"),
        "leader": report.get("leader"),
        "eligibility": report.get("eligibility"),
        "strategies": report.get("strategies"),
        "methodology": report.get("methodology"),
        "feedback_mode": report.get("feedback_mode"),
        "previous_day": (
            {
                "trade_date": previous_report.get("trade_date"),
                "status": previous_report.get("status"),
                "leader": previous_report.get("leader"),
                "eligible_strategy_count": previous_report.get(
                    "eligible_strategy_count"
                ),
            }
            if previous_report
            else None
        ),
    }
    return (
        "请只补充以下量化日报的通用证据风险与后续影子实验。"
        "不得改动排名或数值，不得给出买卖、配置、采用、权重或实盘建议；"
        "不要点名任何策略，不要输出数字、胜率、收益率或排名断言。\n"
        "只输出一个 JSON 对象，字段为 risks 和 next_actions，"
        "两项均为字符串数组。\n\n"
        + orjson.dumps(compact, option=orjson.OPT_SORT_KEYS).decode()
    )


def _normalize_payload(value: dict, fallback: dict) -> dict:
    def texts(key: str) -> list[str]:
        raw = value.get(key)
        if not isinstance(raw, list):
            return list(fallback.get(key) or [])
        clean = [str(item).strip() for item in raw if str(item).strip()]
        return clean[:5] or list(fallback.get(key) or [])

    return {
        "headline": str(fallback.get("headline") or ""),
        "summary": str(fallback.get("summary") or ""),
        "observations": list(fallback.get("observations") or []),
        "risks": texts("risks"),
        "next_actions": texts("next_actions"),
        "feedback": "shadow_only",
        "source": "llm_explanation",
    }


def _contains_forbidden_action(payload: dict) -> bool:
    text = orjson.dumps(payload).decode("utf-8")
    return any(term in text for term in FORBIDDEN_ACTION_TERMS)


def _contains_unverified_claim(payload: dict) -> bool:
    text = orjson.dumps(payload).decode("utf-8")
    return bool(
        re.search(r"\d|百分之|胜率|收益率|排名|第[一二三四五六七八九十]", text)
        or any(term in text for term in ("最优", "领先", "冠军", "最高胜率"))
    )


def _contains_strategy_recommendation(payload: dict, report: dict) -> bool:
    """LLM 只能给通用实验建议，不能点名或调整任何策略。"""
    text = orjson.dumps(payload).decode("utf-8")
    names = {
        str(row.get("name") or "").strip()
        for row in report.get("strategies") or []
        if str(row.get("name") or "").strip()
    }
    names.update(
        str(row.get("strategy") or "").strip()
        for row in report.get("strategies") or []
        if str(row.get("strategy") or "").strip()
    )
    if any(name in text for name in names):
        return True
    governance = (
        "配置|采用|启用|权重|上调|下调|提高|降低|替换|淘汰|推荐|值得|看多|看空|实盘"
    )
    return bool(
        re.search(rf"(策略|因子|模型).{{0,10}}({governance})", text)
        or re.search(rf"({governance}).{{0,10}}(策略|因子|模型)", text)
    )


def run_strategy_review_ai(
    report: dict,
    *,
    previous_report: dict | None = None,
) -> dict:
    """解释确定性报告；AI 失败不阻断日报。"""
    from utils.daily_pick import (
        _extract_json,
        _get_llm_provider,
        _llm_error_code,
        _load_llm_config,
        get_api_key,
    )

    fallback = deterministic_conclusion(report)
    prompt = _prompt(report, previous_report)
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    llm_cfg = _load_llm_config()
    provider = _get_llm_provider(llm_cfg)
    key = get_api_key(llm_cfg)
    base = {
        "ai_prompt_version": PROMPT_VERSION,
        "prompt_hash": prompt_hash,
        "ai_payload": {"conclusion": fallback},
    }
    if provider is None:
        return {
            **base,
            "ai_status": "not_called",
            "reason_codes": ["unsupported_llm_provider"],
        }
    if not key:
        return {
            **base,
            "ai_status": "not_called",
            "reason_codes": ["llm_unconfigured"],
        }

    try:
        if provider == "anthropic":
            import anthropic

            model = str(llm_cfg.get("model") or "claude-opus-4-8")
            client = anthropic.Anthropic(api_key=key, timeout=60.0)
            response = client.messages.create(
                model=model,
                max_tokens=1200,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.stop_reason == "refusal":
                raise RuntimeError("llm_refused")
            body = next(
                block.text for block in response.content if block.type == "text"
            )
            result = _extract_json(body)
        else:
            model = str(llm_cfg.get("model") or "ep-20260708193245-4l9ft")
            base_url = str(
                llm_cfg.get("base_url") or "https://ark.cn-beijing.volces.com/api/v3"
            ).rstrip("/")
            response = requests.post(
                f"{base_url}/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                },
                timeout=60,
            )
            response.raise_for_status()
            body = response.json()["choices"][0]["message"]["content"]
            result = _extract_json(body)
        additions = {
            "risks": result.get("risks"),
            "next_actions": result.get("next_actions"),
        }
        if _contains_forbidden_action(additions):
            return {
                **base,
                "ai_status": "failed",
                "ai_model": model,
                "reason_codes": ["llm_policy_violation"],
            }
        if _contains_unverified_claim(additions):
            return {
                **base,
                "ai_status": "failed",
                "ai_model": model,
                "reason_codes": ["llm_unverified_claim"],
            }
        if _contains_strategy_recommendation(additions, report):
            return {
                **base,
                "ai_status": "failed",
                "ai_model": model,
                "reason_codes": ["llm_strategy_authority_violation"],
            }
        conclusion = _normalize_payload(additions, fallback)
        return {
            **base,
            "ai_status": "explained",
            "ai_model": model,
            "ai_payload": {
                "conclusion": conclusion,
                "deterministic_fallback": fallback,
            },
            "reason_codes": [],
        }
    except Exception as exc:
        return {
            **base,
            "ai_status": "failed",
            "reason_codes": [_llm_error_code(exc)],
        }
