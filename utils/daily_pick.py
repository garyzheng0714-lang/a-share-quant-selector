"""受控 LLM 解释器。

生产中的 LLM 只能解释已落账的量化候选，不能挑票、排序或改变动作。旧版
``llm_picks``/多视图荐股链已经移出生产实现；兼容入口只返回永久停用状态。

API Key 只从 ``ARK_API_KEY[_FILE]`` 或 ``ANTHROPIC_API_KEY[_FILE]`` 读取，
不从仓库配置文件读取真值。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import orjson
import pandas as pd
import requests
import yaml

from views.view_manager import _get_conn, _get_migration_conn, _get_read_conn


logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_ARK_MODEL = "ep-20260708193245-4l9ft"
COMMENT_PROMPT_VERSION = "cloud-stair-explainer-v1"


def _load_llm_config() -> dict:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as file:
            config = yaml.safe_load(file) or {}
        return config.get("llm", {}) or {}
    except (OSError, TypeError, yaml.YAMLError):
        return {}


def _get_llm_provider(llm_cfg: dict | None = None) -> str | None:
    llm_cfg = _load_llm_config() if llm_cfg is None else llm_cfg
    provider = str(llm_cfg.get("provider") or "ark").strip().lower()
    return provider if provider in {"ark", "anthropic"} else None


def get_api_key(llm_cfg: dict | None = None) -> str | None:
    llm_cfg = _load_llm_config() if llm_cfg is None else llm_cfg
    provider = _get_llm_provider(llm_cfg)
    env_name = {
        "ark": "ARK_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(provider)
    if env_name is None:
        return None
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    secret_path = os.environ.get(f"{env_name}_FILE", "").strip()
    if not secret_path:
        return None
    try:
        return Path(secret_path).read_text(encoding="utf-8").strip() or None
    except OSError:
        logger.error("Cannot read secret file configured by %s_FILE", env_name)
        return None


def _extract_json(text: str) -> dict:
    """从模型输出中提取一个 JSON 对象。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("llm_response_missing_json_object")
    return json.loads(text[start : end + 1])


def generate_daily_pick(
    force: bool = False,
    candidates: list | None = None,
    run_date: str | None = None,
    session: str = "close",
) -> dict:
    """旧 LLM 自主荐股入口永久停用；参数只用于兼容旧调用签名。"""
    del force, candidates, run_date, session
    return {
        "available": False,
        "reason": "legacy_generation_disabled",
        "replacement": "canonical_decision_plus_explanation",
    }


def _call_ark(*_args, **_kwargs):
    """保留旧私有符号，任何直接调用都会明确失败。"""
    raise RuntimeError("legacy_generation_disabled")


def _call_anthropic(*_args, **_kwargs):
    """保留旧私有符号，任何直接调用都会明确失败。"""
    raise RuntimeError("legacy_generation_disabled")


def get_pick(*_args, **_kwargs):
    """旧荐股档案不再由生产代码读取。"""
    return None


def get_pick_history(*_args, **_kwargs) -> list:
    """旧荐股档案不再由生产代码读取。"""
    return []


_COMMENTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS quant_comment_runs (
        comment_id TEXT PRIMARY KEY,
        trade_date TEXT NOT NULL,
        decision_run_id TEXT,
        payload_json TEXT NOT NULL,
        model TEXT,
        created_at TEXT NOT NULL
    )
"""

COMMENT_SYSTEM_PROMPT = (
    "你是A股云阶战法的研究解释器，服务的用户没有金融专业背景。"
    "请用简体中文回复。"
    "股票及其买点已经由云阶公式确定；你无权增删、排序或改变规则动作。"
    "你的唯一任务是结合云阶结构、K线特征与行业热度，解释当前优势和具体失效风险。"
    "不得保证收益，也不得以你自己的判断覆盖云阶规则结论。"
    "只能使用输入里截至决策日的量化证据，禁止编造新闻、公告或业绩数据。"
)

COMMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "market_note": {"type": "string"},
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "comment": {"type": "string"},
                    "risk": {"type": "string"},
                },
                "required": ["code", "comment", "risk"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["market_note", "comments"],
    "additionalProperties": False,
}


def init_comments_table() -> None:
    with _get_migration_conn() as connection:
        connection.execute(_COMMENTS_SCHEMA)
        connection.executescript("""
            CREATE TRIGGER IF NOT EXISTS quant_comment_runs_no_update
            BEFORE UPDATE ON quant_comment_runs
            BEGIN
                SELECT RAISE(ABORT, 'immutable_quant_comment_run');
            END;
            CREATE TRIGGER IF NOT EXISTS quant_comment_runs_no_delete
            BEFORE DELETE ON quant_comment_runs
            BEGIN
                SELECT RAISE(ABORT, 'immutable_quant_comment_run');
            END;
        """)


def _build_comment_prompt(
    trade_date: str,
    stocks: list,
    csv_manager,
    decision_run_id: str,
) -> str:
    """只从绑定快照构造候选解释输入。"""
    from utils.stock_features import describe_features, extract_features

    lines = [
        f"## 决策截止日 {trade_date}",
        f"- 决策 run_id: {decision_run_id}",
        "",
        "以下股票已通过云阶的突破确认。不得重排、增删或改变规则动作。",
        "",
    ]
    for stock in stocks:
        code = str(stock.get("code") or "")
        lines.append(
            f"### {code} {stock.get('name')}｜现价 {stock.get('close')}｜"
            f"行业 {stock.get('industry') or '未知'}"
        )
        signal_bits = []
        if stock.get("peak_date"):
            signal_bits.append(f"前高峰日 {stock.get('peak_date')}")
        if stock.get("wave_gain_pct") is not None:
            signal_bits.append(f"第一波涨幅 {stock.get('wave_gain_pct')}%")
        if stock.get("pct_change") is not None:
            signal_bits.append(f"信号日涨跌 {stock.get('pct_change')}%")
        if signal_bits:
            lines.append(f"- 云阶证据: {'；'.join(signal_bits)}；突破确认已成立")
        sector = stock.get("sector") or {}
        if sector:
            delta = sector.get("delta3")
            delta_text = f"{delta:+}" if isinstance(delta, (int, float)) else "未知"
            lines.append(
                f"- 所属板块热度: {sector.get('score')} 分（{sector.get('stage')}，"
                f"排名 {sector.get('rank')}/{sector.get('total')}，近3日变化 {delta_text}）"
            )
        try:
            frame = csv_manager.read_stock(code)
            if not frame.empty:
                frame = frame[
                    pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d") <= trade_date
                ]
            features = extract_features(frame) if not frame.empty else {}
            lines.append(f"- 技术面: {describe_features(features)}")
        except Exception as exc:
            logger.debug("提取 %s 技术特征失败: %s", code, exc)
        lines.append("")

    lines.extend(
        [
            "## 输出要求",
            "1. market_note：用一句话说明今日云阶候选整体特征，不做收益保证；",
            "2. comments：逐一覆盖上面的每只股票；comment 解释云阶结构与行业环境是否相互支持，risk 必须给出可观察的失效条件；",
            "3. 不得挑选、排序、增加或遗漏股票。",
        ]
    )
    return "\n".join(lines)


def _call_ark_comment(api_key: str, llm_cfg: dict, prompt: str) -> tuple[dict, str]:
    model = llm_cfg.get("model") or DEFAULT_ARK_MODEL
    base_url = (llm_cfg.get("base_url") or DEFAULT_ARK_BASE_URL).rstrip("/")
    schema_hint = (
        "\n\n只输出 JSON 对象："
        '{"market_note":"...","comments":['
        '{"code":"6位代码","comment":"...","risk":"..."}]}。'
        "comments 必须完整覆盖输入股票。"
    )
    response = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": COMMENT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt + schema_hint},
            ],
            "temperature": 0.3,
        },
        timeout=180,
    )
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"]
    return _extract_json(text), str(model)


def _call_anthropic_comment(
    api_key: str,
    llm_cfg: dict,
    prompt: str,
) -> tuple[dict, str]:
    import anthropic

    model = str(llm_cfg.get("model") or DEFAULT_ANTHROPIC_MODEL)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=COMMENT_SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": COMMENT_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("llm_refused")
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text), model


def _llm_error_code(exc: Exception) -> str:
    """把供应商异常压缩成不含响应正文和密钥的可观测错误码。"""
    if isinstance(exc, requests.Timeout):
        return "llm_timeout"
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status in {400, 401, 403, 404, 409, 422, 429}:
            return f"llm_http_{status}"
        if status is not None and status >= 500:
            return "llm_http_5xx"
        return "llm_http_error"
    if isinstance(exc, (json.JSONDecodeError, KeyError, TypeError, ValueError)):
        return "llm_response_invalid"
    return "llm_call_failed"


def get_quant_comment(trade_date: str) -> dict | None:
    """只读取当前不可变点评表，不混入旧荐股档案。"""
    with _get_read_conn() as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='quant_comment_runs'"
        ).fetchone()
        if not exists:
            return None
        row = connection.execute(
            "SELECT payload_json, model, created_at FROM quant_comment_runs "
            "WHERE trade_date = ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    payload = orjson.loads(row["payload_json"])
    payload["model"] = row["model"]
    payload["created_at"] = row["created_at"]
    return payload


def _verify_comment_snapshot(csv_manager, trade_date: str) -> tuple[bool, str | None]:
    from utils.market_snapshot import load_market_snapshot

    snapshot_id = getattr(csv_manager, "snapshot_id", None)
    data_dir = getattr(csv_manager, "base_data_dir", None)
    if not snapshot_id or data_dir is None:
        return False, "market_snapshot_unavailable"
    snapshot = load_market_snapshot(data_dir, snapshot_id, verify_files=True)
    if not snapshot.get("available"):
        return False, str(snapshot.get("reason") or "market_snapshot_unavailable")
    if (snapshot.get("manifest") or {}).get("trade_date") != trade_date:
        return False, "decision_snapshot_trade_date_mismatch"
    return True, None


def generate_quant_comment(
    trade_date: str,
    stocks: list,
    force: bool = False,
    decision_run_id: str | None = None,
    csv_manager=None,
) -> dict:
    """解释已确定的候选；输入、快照或输出不完整时失败关闭。"""
    if not stocks:
        return {"available": False, "reason": "no_candidates"}
    if not decision_run_id:
        return {"available": False, "reason": "decision_run_id_required"}

    if not force:
        existing = get_quant_comment(trade_date)
        if (
            existing
            and existing.get("decision_run_id") == decision_run_id
            and set(existing.get("by_code", {}))
            == {str(stock.get("code")) for stock in stocks}
        ):
            return {"available": True, "cached": True, **existing}

    llm_cfg = _load_llm_config()
    provider = _get_llm_provider(llm_cfg)
    if provider is None:
        return {"available": False, "reason": "unsupported_llm_provider"}
    api_key = get_api_key(llm_cfg)
    if not api_key:
        return {"available": False, "reason": "llm_unconfigured"}

    if csv_manager is None:
        from utils.csv_manager import CSVManager

        csv_manager = CSVManager("data", writable=False)
    verified, reason = _verify_comment_snapshot(csv_manager, trade_date)
    if not verified:
        return {"available": False, "reason": reason}

    prompt = _build_comment_prompt(
        trade_date,
        stocks,
        csv_manager,
        decision_run_id,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    try:
        if provider == "anthropic":
            result, model = _call_anthropic_comment(api_key, llm_cfg, prompt)
        else:
            result, model = _call_ark_comment(api_key, llm_cfg, prompt)
    except Exception as exc:
        error_code = _llm_error_code(exc)
        logger.error(
            "AI 点评失败: error_code=%s type=%s", error_code, type(exc).__name__
        )
        return {"available": False, "reason": error_code}

    valid_codes = {str(stock.get("code") or "") for stock in stocks}
    by_code: dict[str, dict[str, str]] = {}
    for comment in result.get("comments") or []:
        code = str(comment.get("code") or "")
        if code in valid_codes:
            by_code[code] = {
                "comment": str(comment.get("comment") or ""),
                "risk": str(comment.get("risk") or ""),
            }
    if set(by_code) != valid_codes:
        return {"available": False, "reason": "llm_output_incomplete"}

    verified, reason = _verify_comment_snapshot(csv_manager, trade_date)
    if not verified:
        return {"available": False, "reason": reason}

    payload = {
        "market_note": str(result.get("market_note") or ""),
        "by_code": by_code,
        "decision_run_id": decision_run_id,
        "prompt_version": COMMENT_PROMPT_VERSION,
        "prompt_hash": prompt_hash,
        "snapshot_id": csv_manager.snapshot_id,
    }
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with _get_conn() as connection:
        connection.execute(
            "INSERT INTO quant_comment_runs "
            "(comment_id, trade_date, decision_run_id, payload_json, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                uuid4().hex[:24],
                trade_date,
                decision_run_id,
                orjson.dumps(payload).decode(),
                model,
                created_at,
            ),
        )
    return {
        "available": True,
        "cached": False,
        "model": model,
        "created_at": created_at,
        **payload,
    }
