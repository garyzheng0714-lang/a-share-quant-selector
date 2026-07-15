"""每日荐一票 - 大模型基于候选票 + 市场温度 + 战绩数据推荐 1 只并给出人话理由

设计原则（WORKLOG.md 已确认）：
- 大模型不预测涨跌，只做综合判断：从技术面已筛出的候选里挑 1 只，
  结合市场温度、策略近期胜率、候选票各自的量化特征给出理由和风险提示
- 推荐结果只在 Web/命令行展示，不做任何推送
- 大模型的判断也进战绩考核：llm_picks 表与 performance 表按 (run_date, code)
  关联即可查到每次推荐的后续真实涨跌，无需重复回填
- 未配置 API Key 时优雅降级（available: false + 配置引导），绝不报错崩溃

支持两种大模型服务（config.yaml 的 llm.provider 切换）：
- ark（默认）：火山方舟 GLM 等 OpenAI 兼容接口，requests 直调，无额外依赖
- anthropic：Claude 官方 SDK

API Key 来源（按优先级）：config/config.yaml 的 llm.api_key > 环境变量 ANTHROPIC_API_KEY
"""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import orjson
import requests
import yaml

from views.view_manager import _get_conn

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.yaml"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-8"
DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

SYSTEM_PROMPT = (
    "你是一位资深A股分析师，服务的用户没有金融专业背景。"
    "请用简体中文回复，思考过程也用中文。"
    "你的任务：基于提供的宏观数据、行业板块数据和每只候选股的完整技术面数据，"
    "做真正的综合研判，从候选中选出相对最优的一只，回答'如果只买一只，买哪只'。"
    "分析要求："
    "1. 用户自己能看到所有原始数字——你的价值是跨维度交叉分析（量价关系、位置与趋势的矛盾、"
    "行业景气与个股形态的共振），说出数字背后的含义，不要复述数字本身；"
    "2. 以提供的量化数据为事实基础，可以结合你对A股运行规律、行业景气周期、资金轮动的经验做推断，"
    "但经验推断要用'从经验看''通常'这类措辞标明，禁止编造具体新闻、公告、业绩数据；"
    "3. '该不该出手、仓位多少'由系统温度计负责，不归你管——环境再差也要选出相对最优的一只，"
    "环境风险和应对（轻仓、止损位）写进风险提示。"
)

PICK_SCHEMA = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "推荐股票的6位代码，必须从候选列表中选"},
        "name": {"type": "string"},
        "macro_view": {"type": "string", "description": "宏观面研判：指数结构、板块轮动、市场风格对本次选择的影响，2-4句"},
        "technical_view": {"type": "string", "description": "技术面研判：所选个股的量价、位置、形态交叉分析，及与其他候选的关键对比，2-4句"},
        "reason": {"type": "string", "description": "综合结论：为什么是它，2-3句"},
        "risk": {"type": "string", "description": "风险提示（含环境风险和应对建议，如轻仓、止损位），1-3句"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["code", "name", "macro_view", "technical_view", "reason", "risk", "confidence"],
    "additionalProperties": False,
}


def _load_llm_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("llm", {}) or {}
    except Exception:
        return {}


def get_api_key():
    llm_cfg = _load_llm_config()
    return llm_cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")


_PICKS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS llm_picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pick_date TEXT NOT NULL,
        session TEXT NOT NULL DEFAULT 'close',
        code TEXT,
        name TEXT,
        macro_view TEXT,
        technical_view TEXT,
        reason TEXT,
        risk TEXT,
        confidence TEXT,
        skipped INTEGER DEFAULT 0,
        skip_reason TEXT,
        thermometer_json TEXT,
        model TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(pick_date, session)
    )
"""


def init_picks_table() -> None:
    with _get_conn() as conn:
        conn.execute(_PICKS_SCHEMA)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(llm_picks)")]
        # 幂等迁移：旧表（pick_date 列级 UNIQUE、无 session）→ 新表（UNIQUE(pick_date, session)）
        if "session" not in cols:
            conn.execute("ALTER TABLE llm_picks RENAME TO llm_picks_old")
            conn.execute(_PICKS_SCHEMA.replace("IF NOT EXISTS ", ""))
            old_cols = [r[1] for r in conn.execute("PRAGMA table_info(llm_picks_old)")]
            keep = [c for c in old_cols if c != "id"]
            conn.execute(
                f"INSERT INTO llm_picks ({', '.join(keep)}, session) "
                f"SELECT {', '.join(keep)}, 'close' FROM llm_picks_old"
            )
            conn.execute("DROP TABLE llm_picks_old")


def _latest_candidates() -> tuple:
    """取 results 表最新一天的选股结果（只保留用户有权限的板块）。返回 (run_date, stocks).

    同一天可能有多个活跃视图各写一行 results：全部合并、按 code 去重（保留先出现的），
    与 /api/ranking 的"今日候选"口径一致——AI 挑票的池子必须等于用户看到的池子。
    """
    from utils.market_filter import is_main_board, main_board_only

    with _get_conn() as conn:
        # 只看活跃视图：与 /api/ranking 一致，停用视图的旧结果不进 AI 候选池
        latest = conn.execute(
            """SELECT MAX(r.run_date) AS d FROM results r
               JOIN views v ON v.id = r.view_id AND v.is_active = 1"""
        ).fetchone()
        if latest is None or latest["d"] is None:
            return None, []
        rows = conn.execute(
            """SELECT r.stocks_json FROM results r
               JOIN views v ON v.id = r.view_id AND v.is_active = 1
               WHERE r.run_date = ? ORDER BY r.view_id""",
            (latest["d"],),
        ).fetchall()

    seen = set()
    stocks = []
    for row in rows:
        try:
            batch = orjson.loads(row["stocks_json"]) if row["stocks_json"] else []
        except Exception:
            continue
        for s in batch:
            code = s.get("code")
            if code and code not in seen:
                seen.add(code)
                stocks.append(s)
    if main_board_only():
        stocks = [s for s in stocks if is_main_board(s.get("code", ""))]
    return latest["d"], stocks


def _build_prompt(run_date, candidates, thermometer, perf_summary, csv_manager) -> str:
    """组装给大模型的完整上下文：宏观数据包 + 行业热度 + 每只候选的完整技术特征包."""
    from utils.market_context import build_macro_brief, get_industry_heat, match_industry
    from utils.stock_features import describe_features, extract_features

    # ---- 宏观面 ----
    lines = ["## 一、宏观面数据（实时真实行情）", ""]
    try:
        lines.append(build_macro_brief())
    except Exception as e:
        logger.warning("宏观数据包获取失败: %s", e)
        lines.append("（宏观数据暂不可用）")

    if thermometer.get("available"):
        fit = thermometer.get("fitness", {})
        if fit.get("available"):
            lines.append(
                f"\n### 本系统策略适应度\n- 最近{fit['samples']}个信号 T+5 胜率 {fit['win_rate_t5']}%"
                f"（{fit['status']}，failing=失效中/weak=偏弱/healthy=健康）"
            )

    # ---- 策略战绩 ----
    lines += ["", "## 二、本系统策略历史战绩（真实回填）", ""]
    for cat, agg in (perf_summary.get("by_category") or {}).items():
        a = agg.get("ret_20") or {}
        if a.get("count"):
            lines.append(f"- {cat}: T+20 胜率 {a['win_rate']}%，平均 {a['avg']:+.2f}%（{a['count']}条）")

    # ---- 候选票完整技术面 ----
    heat = get_industry_heat()
    lines += ["", f"## 三、今日候选股票（{run_date}，碗口反弹策略筛出）", ""]
    for s in candidates:
        sim = s.get("similarity_score")
        code = s.get("code")
        lines.append(
            f"### {code} {s.get('name')}"
            f"｜分类: {s.get('category')}｜J值: {s.get('J')}"
            f"｜B1相似度: {sim if sim is not None else '未评分'}"
        )
        try:
            feats = extract_features(csv_manager.read_stock(code)) if csv_manager else {}
            lines.append(f"- 技术面: {describe_features(feats)}")
        except Exception as e:
            logger.debug("提取 %s 技术特征失败: %s", code, e)
        ind = s.get("industry") or ""
        matched = match_industry(ind, heat)
        if matched:
            lines.append(
                f"- 所属行业 {ind}: 今日{matched['chg_pct']:+}%，"
                f"换手{matched['turnover']}%，主力净流入{matched['main_inflow_yi']:+}亿"
            )
        elif ind:
            lines.append(f"- 所属行业: {ind}（今日板块数据未匹配到）")
        lines.append("")

    lines += [
        "## 四、你的任务",
        "综合以上宏观面、行业面、技术面，从候选中选出【相对最优的 1 只】。",
        "要求：",
        "1. 必须选且只选 1 只，只能从候选列表中选",
        "2. macro_view 写宏观和板块层面的研判（当前市场风格/资金去向对选择的影响）",
        "3. technical_view 写所选个股的跨维度技术分析（量价、位置、形态的交叉解读）及与其他候选的关键对比",
        "4. 不要复述用户已能看到的数字，要给出数字背后的判断；用大白话",
        "5. 环境风险与应对（轻仓/止损位）写进 risk",
    ]
    return "\n".join(lines)


def _extract_json(text: str) -> dict:
    """从模型输出提取 JSON（容错处理 markdown 代码块和前后杂文字）."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"模型输出中未找到 JSON: {text[:200]}")
    return json.loads(text[start:end + 1])


def _call_ark(api_key: str, llm_cfg: dict, prompt: str) -> tuple:
    """调用火山方舟（OpenAI 兼容格式，GLM 等）. 返回 (result_dict, model_name)."""
    model = llm_cfg.get("model")
    if not model:
        raise ValueError("config.yaml 的 llm.model 未配置（火山方舟的接入点 ID，形如 ep-...）")
    base_url = (llm_cfg.get("base_url") or DEFAULT_ARK_BASE_URL).rstrip("/")

    schema_hint = (
        "\n\n请只输出一个 JSON 对象（不要 markdown 代码块、不要多余文字），字段如下：\n"
        '{"code": "6位股票代码（必须从候选列表中选）", "name": "股票名",'
        ' "macro_view": "宏观面研判2-4句", "technical_view": "所选个股技术面交叉分析2-4句",'
        ' "reason": "综合结论：为什么是它，2-3句",'
        ' "risk": "风险提示（含环境风险和应对建议）1-3句", "confidence": "high/medium/low"}'
    )
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt + schema_hint},
            ],
            "temperature": 0.3,
        },
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    return _extract_json(text), model


def _call_anthropic(api_key: str, llm_cfg: dict, prompt: str) -> tuple:
    """调用 Claude 官方 API（结构化输出）. 返回 (result_dict, model_name)."""
    import anthropic

    model = llm_cfg.get("model") or DEFAULT_ANTHROPIC_MODEL
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": PICK_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("模型拒绝了本次请求")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), model


def generate_daily_pick(force: bool = False, candidates: list = None,
                        run_date: str = None, session: str = "close") -> dict:
    """生成推荐。已有同日同场次推荐时直接返回（force=True 强制重新生成）.

    Args:
        candidates: 外部候选；None 时取 results 表最新一天的收盘候选池
        session: 保留字段，恒为 'close'（收盘版）
    """
    init_picks_table()

    api_key = get_api_key()
    if not api_key:
        return {
            "available": False,
            "reason": "未配置大模型 API Key。请在 config/config.yaml 添加:\n"
                      "llm:\n  provider: ark\n  api_key: ...\n  model: ep-...",
        }

    if candidates is None:
        run_date, candidates = _latest_candidates()
    if not candidates:
        return {"available": False, "reason": "暂无候选股票（今日策略未筛出票或未执行选股）"}

    # 已有同日同场次推荐则复用
    if not force:
        existing = get_pick(run_date, session=session)
        if existing:
            return {"available": True, "pick": existing, "cached": True}

    from utils.csv_manager import CSVManager
    from utils.market_thermometer import get_thermometer
    from utils.performance_tracker import get_summary

    thermometer = get_thermometer()
    perf_summary = get_summary()
    csv_manager = CSVManager("data")
    prompt = _build_prompt(run_date, candidates, thermometer, perf_summary, csv_manager)

    llm_cfg = _load_llm_config()
    provider = (llm_cfg.get("provider") or "ark").lower()

    try:
        if provider == "anthropic":
            result, model = _call_anthropic(api_key, llm_cfg, prompt)
        else:
            result, model = _call_ark(api_key, llm_cfg, prompt)
    except Exception as e:
        logger.error("大模型荐票失败: %s", e)
        return {"available": False, "reason": f"大模型调用失败: {e}"}

    # 防幻觉校验：推荐的票必须在候选列表里
    valid_codes = {str(s.get("code")) for s in candidates}
    if str(result.get("code")) not in valid_codes:
        logger.error("模型推荐了候选之外的股票 %s", result.get("code"))
        return {"available": False, "reason": "模型输出异常（推荐了候选之外的股票），请重试"}

    now = datetime.now().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM llm_picks WHERE pick_date = ? AND session = ?",
            (run_date, session),
        )
        conn.execute(
            """INSERT INTO llm_picks
               (pick_date, session, code, name, macro_view, technical_view, reason, risk,
                confidence, skipped, skip_reason, thermometer_json, model, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, ?)""",
            (
                run_date,
                session,
                result.get("code"),
                result.get("name"),
                result.get("macro_view"),
                result.get("technical_view"),
                result.get("reason"),
                result.get("risk"),
                result.get("confidence"),
                orjson.dumps(thermometer).decode(),
                model,
                now,
            ),
        )
    return {"available": True, "pick": get_pick(run_date, session=session), "cached": False}


def get_pick(pick_date: str, session: str = None):
    """取某日推荐（session=None 时取当日最新一条），关联战绩表带出后续真实涨跌."""
    init_picks_table()
    with _get_conn() as conn:
        if session:
            row = conn.execute(
                "SELECT * FROM llm_picks WHERE pick_date = ? AND session = ?",
                (pick_date, session),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM llm_picks WHERE pick_date = ? ORDER BY created_at DESC LIMIT 1",
                (pick_date,),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["skipped"] = bool(d["skipped"])
        d["thermometer"] = (
            orjson.loads(d.pop("thermometer_json")) if d.get("thermometer_json") else None
        )
        if d.get("code"):
            perf = conn.execute(
                """SELECT buy_price, ret_1, ret_5, ret_10, ret_20,
                          max_gain, max_drawdown, status,
                          category, similarity_score
                   FROM performance WHERE run_date = ? AND code = ? LIMIT 1""",
                (pick_date, d["code"]),
            ).fetchone()
            if perf:
                p = dict(perf)
                # 分类/B1分提到顶层：前端用它查"同类信号历史战绩"（证据链）
                d["category"] = p.pop("category", None)
                d["similarity_score"] = p.pop("similarity_score", None)
                d["performance"] = p
            else:
                d["performance"] = None
    return d


def get_pick_history(limit: int = 30) -> list:
    """推荐历史（含每次推荐的后续表现，用于考核大模型）."""
    init_picks_table()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT pick_date, session FROM llm_picks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [get_pick(r["pick_date"], r["session"]) for r in rows]


# ============================================================================
# AI 点评（取代 AI 自主荐票）
#
# 用户 2026-07-14：「主页塞那么多信息没有用」——页面上同时存在两个「今日一票」
# （量化版推丸美生物、AI 版推密尔克卫），互相打架，等于没给答案。
#
# 定位改变：**AI 不再挑票，只解释量化系统已经挑出的票**。
# - 挑票是数学的活：云阶是 28 个因子里唯一经双周期验证的，凭什么让模型推翻它？
# - 解释是语言的活：用户看不懂"缩量横盘18天后放量突破"，这才是模型该干的。
# 所以 AI 的输入是「已确定的票」，输出只有点评和风险，**没有选择权**——
# 它连推荐哪只都不能改，从结构上杜绝了它和量化结论打架。
# ============================================================================

_COMMENTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS quant_comments (
        trade_date TEXT PRIMARY KEY,
        payload_json TEXT NOT NULL,
        model TEXT,
        created_at TEXT NOT NULL
    )
"""

COMMENT_SYSTEM_PROMPT = (
    "你是一位资深A股分析师，服务的用户没有金融专业背景。"
    "请用简体中文回复，思考过程也用中文。"
    "重要：股票及其动作已经由分层量化系统确定。你无权挑选、排序或改变 buy/observe/avoid 动作。"
    "你的唯一任务是解释既定动作的依据和风险；不得把观察或回避写成值得买。"
    "要求："
    "1. 讲人话。不要甩术语——非用不可的词（如'缩量''突破前高'）要顺手解释成生活比喻；"
    "2. 说数字背后的含义，不要复述用户已经能看到的数字；"
    "3. 可以结合你对A股规律的经验做推断，但要用'从经验看''通常'标明，"
    "禁止编造具体新闻、公告、业绩数据；"
    "4. 风险提示要具体可执行（跌破哪个位置该走、仓位建议多少），不要说'注意风险'这种废话。"
)

COMMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "market_note": {
            "type": "string",
            "description": "今天整体该怎么做（仓位建议），结合市场温度和策略适应度，1-2句大白话",
        },
        "comments": {
            "type": "array",
            "description": "对每只已选定股票的点评，必须每只都有，顺序不限",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "6位股票代码，必须是给定列表里的"},
                    "comment": {"type": "string", "description": "解释系统既定动作，2-3句大白话，不得擅自荐买"},
                    "risk": {"type": "string", "description": "具体的风险与应对（止损位、仓位），1-2句"},
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
    with _get_conn() as conn:
        conn.execute(_COMMENTS_SCHEMA)


def _build_comment_prompt(trade_date, stocks, thermometer, csv_manager) -> str:
    """组装点评上下文：市场环境 + 选股逻辑 + 每只已选定票的技术面."""
    from utils.market_context import build_macro_brief
    from utils.stock_features import describe_features, extract_features

    lines = [f"## 一、今天是 {trade_date}，市场环境", ""]
    try:
        lines.append(build_macro_brief())
    except Exception as e:
        logger.warning("宏观数据包获取失败: %s", e)
        lines.append("（宏观数据暂不可用）")

    if thermometer.get("available"):
        fit = (thermometer.get("fitness") or {})
        if fit.get("available"):
            lines.append(
                f"\n### 本系统策略近期适应度\n- 最近{fit['samples']}个信号 T+5 胜率 "
                f"{fit['win_rate_t5']}%（{fit['status']}，failing=失效中/weak=偏弱/healthy=健康）"
            )

    lines += [
        "",
        "## 二、这些票是怎么选出来的（你不能推翻这个逻辑）",
        "",
        "选股规则叫「云阶」，是 28 个通达信公式里唯一一个经得起双周期检验的：",
        "在两段互不重叠的历史中，持有1天和持有5天都跑赢大盘（持有5天：样本内胜率 56.0%、",
        "超额 +2.72%；样本外胜率 49.3%、超额 +1.11%）。",
        "它的形态是三段式：第一波大涨 → 缩量横盘不破位（洗掉浮筹）→ 再次放量突破前高。",
        "",
        "## 三、今天选中的票（已确定，请逐只点评）",
        "",
    ]
    for s in stocks:
        code = s.get("code")
        lines.append(f"### {code} {s.get('name')}｜现价 {s.get('close')}｜行业 {s.get('industry') or '未知'}")
        sec = s.get("sector") or {}
        if sec:
            lines.append(
                f"- 所属板块热度: {sec.get('score')} 分（{sec.get('stage')}，"
                f"在全部 {sec.get('total')} 个行业里排第 {sec.get('rank')}，近3日变化 {sec.get('delta3'):+}）"
            )
        try:
            feats = extract_features(csv_manager.read_stock(code)) if csv_manager else {}
            lines.append(f"- 技术面: {describe_features(feats)}")
        except Exception as e:
            logger.debug("提取 %s 技术特征失败: %s", code, e)
        lines.append("")

    lines += [
        "## 四、你的任务",
        "1. market_note：今天这个大环境下，整体该怎么做（该不该出手、仓位多少），1-2句；",
        "2. comments：对上面**每一只**票各写一段——为什么它现在值得买（讲人话，"
        "把'缩量横盘''突破前高'翻译成人能懂的话）+ 具体风险与应对（跌破哪个价该走、仓位建议）；",
        "3. 不许挑选、不许排序、不许说'这几只里我更看好X'——量化系统已经验证过无法区分优劣。",
    ]
    return "\n".join(lines)


def _call_ark_comment(api_key: str, llm_cfg: dict, prompt: str) -> tuple:
    """火山方舟（OpenAI 兼容）出点评。返回 (result_dict, model)."""
    model = llm_cfg.get("model")
    if not model:
        raise ValueError("config.yaml 的 llm.model 未配置（火山方舟的接入点 ID，形如 ep-...）")
    base_url = (llm_cfg.get("base_url") or DEFAULT_ARK_BASE_URL).rstrip("/")

    schema_hint = (
        "\n\n请只输出一个 JSON 对象（不要 markdown 代码块、不要多余文字），字段如下：\n"
        '{"market_note": "今天整体怎么做1-2句",'
        ' "comments": [{"code": "6位代码", "comment": "为什么值得买2-3句大白话",'
        ' "risk": "具体风险与应对1-2句"}]}\n'
        "comments 必须覆盖上面列出的每一只票。"
    )
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
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
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(text), model


def _call_anthropic_comment(api_key: str, llm_cfg: dict, prompt: str) -> tuple:
    """Claude 官方 API（结构化输出）出点评。返回 (result_dict, model)."""
    import anthropic

    model = llm_cfg.get("model") or DEFAULT_ANTHROPIC_MODEL
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
        raise RuntimeError("模型拒绝了本次请求")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), model


def get_quant_comment(trade_date: str):
    """取某日的 AI 点评（没有则 None）."""
    init_comments_table()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT payload_json, model, created_at FROM quant_comments WHERE trade_date = ?",
            (trade_date,),
        ).fetchone()
    if row is None:
        return None
    payload = orjson.loads(row["payload_json"])
    payload["model"] = row["model"]
    payload["created_at"] = row["created_at"]
    return payload


def generate_quant_comment(trade_date: str, stocks: list, force: bool = False) -> dict:
    """为量化选出的票生成 AI 点评。同日已生成则复用（force=True 强制重算）.

    stocks: 量化系统已选定的票（云阶今日命中），每只需含 code/name/close/industry/sector。
    今天没有命中时不调用模型——没有票可点评，硬生成一段小作文是浪费和噪音。
    """
    init_comments_table()

    if not stocks:
        return {"available": False, "reason": "今天没有命中的票，无需点评"}

    if not force:
        existing = get_quant_comment(trade_date)
        if existing:
            # 票变了（盘中重扫出新票）就重算，否则复用
            if set(existing.get("by_code", {})) == {str(s.get("code")) for s in stocks}:
                return {"available": True, "cached": True, **existing}

    api_key = get_api_key()
    if not api_key:
        return {"available": False, "reason": "未配置大模型 API Key"}

    from utils.csv_manager import CSVManager
    from utils.market_thermometer import get_thermometer

    prompt = _build_comment_prompt(trade_date, stocks, get_thermometer(), CSVManager("data"))
    llm_cfg = _load_llm_config()
    provider = (llm_cfg.get("provider") or "ark").lower()

    try:
        if provider == "anthropic":
            result, model = _call_anthropic_comment(api_key, llm_cfg, prompt)
        else:
            result, model = _call_ark_comment(api_key, llm_cfg, prompt)
    except Exception as e:
        logger.error("AI 点评失败: %s", e)
        return {"available": False, "reason": f"大模型调用失败: {e}"}

    # 防幻觉：只保留确实在选定名单里的点评，模型编出来的代码一律丢弃
    valid = {str(s.get("code")) for s in stocks}
    by_code = {}
    for c in (result.get("comments") or []):
        code = str(c.get("code", ""))
        if code in valid:
            by_code[code] = {"comment": c.get("comment", ""), "risk": c.get("risk", "")}
    if not by_code:
        return {"available": False, "reason": "模型输出异常（没有一条点评对应到选定的票）"}

    payload = {"market_note": result.get("market_note", ""), "by_code": by_code}
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO quant_comments (trade_date, payload_json, model, created_at) "
            "VALUES (?, ?, ?, ?)",
            (trade_date, orjson.dumps(payload).decode(), model, now),
        )
    return {"available": True, "cached": False, "model": model, "created_at": now, **payload}
