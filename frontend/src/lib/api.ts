const API_BASE = import.meta.env.VITE_API_BASE || "";

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface ApiResponse<T> {
  success: boolean;
  data: T;
}

export interface StatsData {
  total_stocks: number;
  latest_date: string;
  total_views: number;
  active_views: number;
  scheduler_running: boolean;
}

export interface ViewData {
  id: number;
  name: string;
  params: Record<string, number>;
  b1_params: Record<string, number>;
  b1_enabled: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface StockItem {
  code: string;
  name: string;
  latest_price: number;
  latest_date: string;
  market_cap: number;
  data_count: number;
}

export interface SignalStock {
  code: string;
  name: string;
  strategy: string;
  category: string;
  close: number;
  J: number;
  volume_ratio: number;
  market_cap: number;
  short_term_trend: number;
  bull_bear_line: number;
  reasons: string[];
  similarity_score: number | null;
  matched_case: string | null;
  match_breakdown: Record<string, number> | null;
  industry?: string;
}

export interface SelectionResult {
  view_id: number;
  view_name: string;
  run_date: string;
  total: number;
  category_count: Record<string, number>;
  stocks: SignalStock[];
}

export interface RankingStock {
  code: string;
  name: string;
  category: string;
  close: number | null;
  J: number | null;
  volume_ratio: number | null;
  market_cap: number | null;
  similarity_score: number | null;
  matched_case: string | null;
  match_breakdown: Record<string, number> | null;
  views: string[];
  run_date: string;
  industry?: string;
}

export interface IndustryItem {
  name: string;
  count: number;
}

export interface StockProfile {
  code: string;
  name: string;
  industry: string;
  board: string;
  business: string;
  listing_date: string;
  total_shares: string;
  circ_shares: string;
}

export interface KlineDataPoint {
  date: string;
  open: number;
  close: number;
  low: number;
  high: number;
  volume: number;
  [key: string]: string | number;
}

/** 该票的历史信号点（系统在哪天选出过它），用于在K线上标记 */
export interface KlineSignal {
  date: string;
  category: string;
}

export interface KlineResponse {
  success: boolean;
  code: string;
  name: string;
  period: string;
  snapshot_id?: string | null;
  source_id?: string | null;
  history_source_id?: string | null;
  adjustment?: "qfq" | string | null;
  stored_from?: string | null;
  stored_rows?: number | null;
  as_of: string;
  week_end?: string | null;
  current_week_partial?: boolean;
  change_label: "今日涨跌" | "本周涨跌";
  data: (string | number)[][];
  signals?: KlineSignal[];
}

export interface TaskStatus {
  success: boolean;
  status: string;
  progress: number;
  total: number;
  phase: string;
  data?: SelectionResult;
  error?: string;
}

export interface ThermometerData {
  available: boolean;
  reason?: string;
  heat?: {
    methodology: "cross_sectional_sector_heat_v1";
    breadth_score: number;
    warming_sector_ratio: number;
    cooling_sector_ratio: number;
    delta3_mean: number;
    trend: "bull" | "bear" | "sideways";
    level: "hot" | "cold" | "normal";
    sector_count: number;
    as_of: string;
  };
  fitness?: {
    available: boolean;
    reason?: string;
    source?: string;
    samples?: number;
    win_rate_t5?: number;
    status?: "failing" | "weak" | "healthy";
  };
  signal?: "caution" | "opportunity" | "neutral" | "normal";
  conclusion?: string;
}

export interface SectorHot {
  name: string;
  score: number;
  delta3: number;
  stage: string;
  trend: "up" | "down" | "flat";
  breadth_ma10: number;
  turn_ratio: number;
  heat_series?: number[];
  relative_strength?: number;
  breadth?: number;
}

export interface SectorRelay {
  name: string;
  score: number;
  heat: number;
  reasons: string[];
}

export interface SectorsData {
  available: boolean;
  reason?: string;
  snapshot_id?: string | null;
  trade_date?: string;
  computed_at?: string;
  series_dates?: string[];
  industries?: number;
  stocks?: number;
  hot?: SectorHot[];
  relay?: SectorRelay[];
  ranking?: Array<SectorHot & { rank: number; total: number }>;
}

export interface SectorDetailStock {
  rank: number;
  code: string;
  name: string;
  close: number;
  ret1: number | null;
  ret5: number | null;
  b1: boolean;
  b1_signals: string[];
  confirmation_count: number;
  confirmations: string[];
  action: DecisionAction;
  reason_codes?: string[];
  weekly?: WeeklyFourLineState | null;
  decision_run_id?: string | null;
  decision_as_of?: string | null;
  data_status?: "complete" | "partial";
  risk_status?: "passed" | "blocked" | "not_evaluated";
}

export interface SectorDetailData {
  available: boolean;
  reason?: string;
  trade_date?: string;
  sector?: SectorState & { name: string };
  stocks?: SectorDetailStock[];
  recommended?: SectorDetailStock[];
  total?: number;
}

export interface CoverageStatus {
  universe_count: number;
  covered_count: number;
  coverage_ratio: number;
  trainable_count: number;
  trainable_eligible_count: number;
  trainable_ratio: number;
  short_history_count: number;
  remaining_count: number;
  failure_count: number;
  running: boolean;
  updated_at?: string | null;
}

/** 超级B1（知行公式独立模块）命中信号 */
export interface WeeklyFourLineState {
  passed?: boolean;
  aligned?: boolean;
  rising?: boolean;
  rising_count?: number;
  directions?: Partial<Record<"MA5" | "MA10" | "MA20" | "MA60", boolean>>;
  ma_values?: Partial<Record<"MA5" | "MA10" | "MA20" | "MA60", number>>;
  reason?: string;
  weeks?: number;
  as_of?: string;
  week_end?: string;
  current_week_partial?: boolean;
  gate_mode?: "off" | "shadow" | "active";
}

export interface SuperB1Hit {
  code: string;
  name: string;
  date: string;
  close: number;
  J: number;
  RSI: number;
  market_cap_yi: number;
  signals: string[];
  signal_labels: string[];
  weekly?: WeeklyFourLineState;
  /** 所属行业板块（展示层由后端附带） */
  industry?: string;
}

/** 超级B1独立战绩记录 */
export interface SuperB1PerfRecord {
  id: number;
  run_date: string;
  code: string;
  name: string | null;
  signals: string[];
  J: number | null;
  RSI: number | null;
  sel_close: number | null;
  buy_price: number | null;
  ret_1: number | null;
  ret_5: number | null;
  ret_10: number | null;
  ret_20: number | null;
  max_gain: number | null;
  max_drawdown: number | null;
  days_tracked: number;
  status: string;
}

export interface SuperB1Performance {
  total_recorded: number;
  total_records: number;
  overall: PerfAgg;
  by_signal: Record<string, PerfAgg>;
  benchmark?: BenchmarkAgg | null;
  records: SuperB1PerfRecord[];
}

export interface SuperB1Data {
  available: boolean;
  reason?: string;
  trade_date?: string;
  total_scanned?: number;
  cap_note?: string;
  /** 因缺市值数据未纳入判定的股票数（显式暴露，不静默吞掉） */
  cap_missing?: number;
  /** 因K线日期陈旧（停牌/断更）被丢弃的命中数 */
  stale_dropped?: number;
  errors?: number;
  hits?: SuperB1Hit[];
}

export interface WindowAgg {
  count: number;
  win_rate: number | null;
  avg: number | null;
}

export interface PerfAgg {
  ret_1: WindowAgg;
  ret_5: WindowAgg;
  ret_10: WindowAgg;
  ret_20: WindowAgg;
  /** 持有期内最大回撤统计（止损参考）：均值/中位数，% */
  drawdown?: { avg: number | null; median: number | null; count: number };
}

/** 同期上证指数基准：各窗口指数平均收益，用于算"超额" */
export interface BenchmarkAgg {
  ret_1: number | null;
  ret_5: number | null;
  ret_10: number | null;
  ret_20: number | null;
}

export interface PerformanceSummary {
  total_records: number;
  overall: PerfAgg;
  by_category: Record<string, PerfAgg>;
  by_similarity: Record<string, PerfAgg>;
  /** 同期上证基准（接口失败时缺省，前端不显示超额行） */
  benchmark?: BenchmarkAgg | null;
}

export interface PerformanceRecord {
  id: number;
  view_id: number;
  run_date: string;
  code: string;
  name: string;
  category: string;
  similarity_score: number | null;
  sel_close: number | null;
  buy_price: number | null;
  ret_1: number | null;
  ret_5: number | null;
  ret_10: number | null;
  ret_20: number | null;
  max_gain: number | null;
  max_drawdown: number | null;
  days_tracked: number;
  status: string;
}

export interface DailyPick {
  pick_date: string;
  // 场次：尾盘版（intraday）已下线，现仅收盘版（close），每交易日 16:00 一次。
  // 类型保留 "intraday" 仅为兼容历史数据，新数据一律为 "close"。
  session?: "intraday" | "close";
  code: string | null;
  name: string | null;
  macro_view: string | null;
  technical_view: string | null;
  reason: string;
  risk: string;
  confidence: "high" | "medium" | "low";
  skipped: boolean;
  skip_reason: string | null;
  model: string;
  /** 该票在候选池中的信号分类（回落碗中等），来自 performance 表关联 */
  category?: string | null;
  /** 该票的 B1 相似度分（若有） */
  similarity_score?: number | null;
  /** 荐票当时的市场温度计快照 */
  thermometer?: ThermometerData | null;
  performance: {
    buy_price: number | null;
    ret_1: number | null;
    ret_5: number | null;
    ret_10: number | null;
    ret_20: number | null;
    max_gain: number | null;
    max_drawdown: number | null;
    status: string;
  } | null;
}

export interface DailyPickResponse {
  configured: boolean;
  pick: DailyPick | null;
}

export interface DailyPickHistoryResponse {
  configured: boolean;
  picks: DailyPick[];
}

// ---- 策略因子选股（第三期）----

/** 单段窗口的真实战绩：信号次日开盘买入、持有N天卖出 */
export interface TrackWindow {
  win: number;
  /** 超额 = 该因子均值 − 同期全体信号基准 */
  excess: number;
  n: number;
}

export interface PeriodTrack {
  in: TrackWindow;
  oos: TrackWindow;
  /** 该持有周期上两段历史都跑赢 */
  robust: boolean;
}

export type FactorGrade =
  | "short_robust"  // 短线真金：T+1 与 T+5 两段都跑赢
  | "short_ok"      // 短线可用：T+5 两段都跑赢
  | "long_only"     // 只适合长线持有
  | "unstable"      // 只在某段行情有效，多半是运气
  | "negative";     // 任何周期都不稳，历史上亏钱

export interface FactorTrack {
  grade: FactorGrade;
  dd: number | null;
  /** 按持有周期分别统计：ret_1 / ret_5 / ret_10 / ret_20 */
  periods: Record<string, PeriodTrack>;
}

/** 个股所属板块的冷热状态（全行业热度榜，不只是前8名） */
export interface SectorState {
  score: number;
  delta3: number;
  stage: string;
  rank: number;
  total: number;
  relative_strength?: number;
  turn_ratio?: number;
  breadth?: number;
  breadth_ma10?: number;
}

/** 量化今日一票：今天买什么 / 明天盯什么（纯规则，无模型主观发挥） */
export interface QuantPickStock {
  code: string;
  name: string;
  close: number;
  industry: string;
  cap_yi: number | null;
  sector: SectorState | null;
  J?: number | null;
  RSI?: number | null;
  pct_change?: number | null;
  /** 按板块热度排序后的名次（1-based，rank_total 为当日命中总数） */
  rank?: number;
  rank_total?: number;
  /** 推荐理由：云阶结构 + 板块热度/排名/趋势 */
  reason?: string;
  /** 预备队专属：距突破线还差几个点 / 突破价 */
  gap_pct?: number;
  target?: number;
  peak_date?: string;
  wave_gain_pct?: number;
}

export interface QuantPickResponse {
  available: boolean;
  reason?: string;
  trade_date?: string;
  core_factor?: {
    key: string;
    name: string;
    plain: string;
    why: string;
    track: PeriodTrack | null;
  };
  today_buy?: QuantPickStock[];
  tomorrow_watch?: QuantPickStock[];
  honest_note?: string;
}

/** AI 点评：只解释量化已选定的票，不挑票、不排序 */
export interface QuantComment {
  available: boolean;
  reason?: string;
  decision_run_id?: string | null;
  market_note?: string;
  by_code?: Record<string, { comment: string; risk: string }>;
}

export type DecisionAction = "buy" | "observe" | "avoid" | "none";

export interface DecisionModel {
  model_key: string;
  version: string;
  status: "active" | "shadow" | "rejected";
  trained_as_of: string;
  train_range?: string | null;
  test_range?: string | null;
  metrics: Record<string, unknown>;
  params: Record<string, unknown>;
  source_refs: string[];
  mode?: "off" | "shadow" | "active";
  active_version?: string | null;
  latest_attempt_version?: string;
  latest_attempt_status?: "active" | "shadow" | "rejected";
}

export interface DecisionCandidate {
  code: string;
  name: string;
  industry: string;
  rank: number;
  tie_group: number;
  action: DecisionAction;
  baseline: {
    signal?: string;
    signals?: string[];
    signal_labels?: string[];
    confirmations?: string[];
    confirmation_count?: number;
    close?: number | null;
    J?: number | null;
    RSI?: number | null;
    cap_yi?: number | null;
    weekly?: WeeklyFourLineState | null;
  };
  market: { probability?: number | null; threshold?: number | null };
  sector: SectorState & { probability?: number | null; threshold?: number | null };
  stock: {
    risk_probability?: number | null;
    risk_threshold?: number | null;
    quality_probability?: number | null;
  };
  events: Array<{
    event_id: string;
    title: string;
    source_url?: string;
    published_at: string;
    hard_tags?: string[];
    review_tags?: string[];
  }>;
  reason_codes: string[];
  explanation?: string;
}

export interface DecisionResponse {
  available: boolean;
  reason?: string;
  warning_reason?: string | null;
  is_stale?: boolean;
  data_status?: "fresh" | "stale";
  run_id?: string;
  trade_date?: string;
  stage?: "close" | "preopen";
  as_of?: string;
  status?: "complete" | "degraded";
  final_action?: DecisionAction;
  strategy_version?: string;
  feature_version?: string;
  model_version?: string;
  data_version?: string;
  source_refs?: string[];
  market?: {
    models_active?: string[];
    layer_modes?: Record<string, "off" | "shadow" | "active">;
    gate_order?: string[];
    decision_for_date?: string;
  };
  evaluation?: Record<string, unknown>;
  reason_codes?: string[];
  candidates?: DecisionCandidate[];
  models?: DecisionModel[];
  freshness?: {
    fresh: boolean;
    local_date: string | null;
    expected_date: string;
    anchor_dates?: Record<string, number>;
  };
}

export interface EvolutionStatus {
  evolution_id: string;
  trade_date: string;
  status: "complete" | "failed";
  universe_count: number;
  covered_count: number;
  coverage_ratio: number;
  labels_updated: number;
  dataset_rows: number;
  challenger_version?: string | null;
  promotion_status: "promoted" | "shadow_registered" | "kept_champion" | "not_evaluated";
  reason_codes: string[];
  outcomes?: {
    buy?: { count: number; win_rate: number | null; avg_net_ret_5: number | null };
    observe?: { count: number; win_rate: number | null; avg_net_ret_5: number | null };
    avoid?: { count: number; win_rate: number | null; avg_net_ret_5: number | null };
    missed_winner_rate?: number | null;
  };
}

export interface EvolutionResponse {
  available: boolean;
  data: EvolutionStatus | null;
}

export interface SystemStatusResponse {
  available: boolean;
  as_of?: string;
  market_data?: {
    fresh: boolean;
    local_date: string | null;
    expected_date: string;
  };
  decision?: {
    available: boolean;
    run_id?: string | null;
    trade_date?: string | null;
    status?: string | null;
    final_action?: DecisionAction | null;
    model_version: string;
    candidate_counts: Record<"buy" | "observe" | "avoid", number>;
    reason_codes: string[];
  };
  ai?: {
    ai_run_id?: string;
    status: "not_called" | "abstained" | "explained" | "shadow_ranked" | "failed";
    model?: string | null;
    reason_codes: string[];
    created_at?: string;
  };
  evolution?: {
    evolution_id?: string;
    status: string;
    promotion_status: string;
    reason_codes: string[];
    trade_date?: string;
  };
  paper?: {
    established: boolean;
    reason?: string;
    account_id?: string;
    rule_version?: string;
    cash?: number;
    market_value?: number;
    total_equity?: number;
    net_return?: number | null;
    nav_days?: number;
    pending_orders?: number;
    track_record_state?: string;
    benchmark_state?: string;
    latest_nav_date?: string | null;
  };
  policy?: {
    active_policy_version: string;
    release_id?: string | null;
    state: "active" | "baseline_only";
    daily_auto_promotion: boolean;
  };
}

export type PipelineState = "healthy" | "updating" | "attention" | "unavailable";
export type PipelineStageStatus = "running" | "complete" | "attention" | "failed";

export interface PipelineAttention {
  code: string;
  level: "warning" | "critical";
  message: string;
}

export interface PipelineStage {
  key: string;
  label: string;
  status: PipelineStageStatus;
  started_at?: string;
  finished_at?: string;
  detail?: {
    reason?: string | null;
    trade_date?: string | null;
    snapshot_id?: string | null;
    coverage_ratio?: number | null;
    updated?: number;
    processed?: number;
    total?: number;
    pending?: number;
    run_id?: string | null;
    stage?: string | null;
  };
}

export interface PipelineStatusResponse {
  available: boolean;
  state: PipelineState;
  as_of?: string;
  reason?: string;
  market: {
    fresh: boolean;
    reason?: string | null;
    reason_codes?: string[];
    local_date: string | null;
    expected_date: string | null;
    snapshot_id: string | null;
    coverage_ratio: number;
    source_set?: Array<string | { source_id?: string }>;
    stock_count: number;
    captured_at?: string | null;
  };
  scheduler: {
    running: boolean;
    heartbeat_at?: string | null;
    next_close_at?: string | null;
    close_schedule: string;
    preopen_schedule: string;
  };
  run: {
    task_id: string;
    task_type: "full_market_rebuild" | "daily_market_ingestion" | "daily_close_pipeline" | string;
    task_label: string;
    status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
    trade_date?: string | null;
    current_stage?: string | null;
    attempt_count: number;
    max_attempts: number;
    created_at?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
    next_attempt_at?: string | null;
    error_code?: string | null;
    progress?: {
      status?: string | null;
      processed: number;
      total: number;
      remaining: number;
      current?: string | null;
      updated_at?: string | null;
    } | null;
    stages: PipelineStage[];
  } | null;
  decision: {
    available: boolean;
    run_id?: string | null;
    trade_date?: string | null;
    final_action?: DecisionAction | null;
    candidate_counts: Record<"buy" | "observe" | "avoid", number>;
  };
  sources: {
    kline: {
      primary: string;
      fallback: string;
      validation_fallback?: string;
      adjustment: string;
    };
    universe: {
      source_id?: string | null;
      discovery_source_id?: string | null;
      verification_source_id?: string | null;
      count: number;
    };
    industry: { source_id?: string | null; count?: number; coverage_ratio?: number };
    market_cap: { source_id?: string | null; count?: number; coverage_ratio?: number };
    security_status: { source_id?: string | null; count: number; suspended_count: number };
  };
  attention: PipelineAttention[];
  alerts: {
    summary: {
      window_hours: number;
      warning: number;
      critical: number;
      total: number;
      latest_at?: string | null;
    };
    latest: Array<{
      alert_id: string;
      occurred_at: string;
      severity: "warning" | "critical";
      message: string;
    }>;
  };
  storage: {
    data_root: string;
    state_root: string;
    snapshot_directory: string;
    snapshot_count: number;
    staging_count: number;
    retention_state: "configured" | "not_configured";
    retention_policy: "indefinite";
    retention_days: number | null;
    retention_summary: string;
  };
}

export interface FactorMeta {
  key: string;
  name: string;
  group: string;
  desc: string;
  /** 大白话说明（概览卡片主文案） */
  plain: string;
  /** 最新交易日命中数；null=该因子当日还没算过 */
  today_hits: number | null;
  /** 双周期真实战绩；null=样本不足未评级 */
  track: FactorTrack | null;
}

export interface FactorsResponse {
  factors: FactorMeta[];
  groups: string[];
  trade_date: string;
  /** 最近交易日（新→旧），日期导航用 */
  recent_dates: string[];
  track_windows?: {
    in: { label: string; n_stocks: number };
    oos: { label: string; n_stocks: number };
  };
  /** 各持有周期的全体信号基准（对比用） */
  baseline?: Record<string, { in: { win: number; avg: number }; oos: { win: number; avg: number } }>;
  track_note?: string;
}

export interface FactorHit {
  code: string;
  name: string;
  date: string;
  close: number;
  pct_change: number | null;
  J: number | null;
  RSI: number | null;
  industry: string;
  cap_yi: number | null;
  /** 所属行业板块的冷热（全行业热度榜；只读展示，不参与排序） */
  sector?: SectorState | null;
  /** 策略特有附加字段（detail 等） */
  [key: string]: unknown;
}

export interface FactorScanResponse {
  available: boolean;
  reason?: string;
  strategy?: string;
  trade_date?: string;
  hits?: FactorHit[];
  total_scanned?: number;
  errors?: number;
}

/** 云阶当日候选：规则决定入选，行业热度只决定展示顺序。 */
export interface RecommendStock {
  code: string;
  name: string;
  close: number;
  industry: string;
  cap_yi: number | null;
  sector: SectorState | null;
  J?: number | null;
  RSI?: number | null;
  pct_change?: number | null;
  /** 按板块热度排序后的名次（1-based，rank_total 为当日命中总数） */
  rank?: number;
  rank_total?: number;
  /** 推荐理由：云阶结构 + 板块热度/排名/趋势 */
  reason?: string;
  evidence?: string[];
  action: "buy";
  action_label: string;
  action_detail: string;
  industry_available?: boolean;
  peak_date?: string;
  peak_high?: number;
  breakout_price?: number;
  wave_gain_pct?: number;
  ai_analysis?: { comment: string; risk: string } | null;
}

export interface RecommendResponse {
  available: boolean;
  reason?: string;
  trade_date?: string;
  snapshot_id?: string;
  signal_count?: number;
  has_signal?: boolean;
  summary?: string;
  core_factor?: {
    key: string;
    name: string;
    plain: string;
    why?: string;
    decision_rule?: string;
    track?: {
      name: string;
      hold_days: number;
      in_win: number;
      in_excess: number;
      oos_win: number;
      oos_excess: number;
    };
  };
  candidates?: RecommendStock[];
  today_buy?: RecommendStock[];
  honest_note?: string;
  ranking_note?: string;
  decision_run_id?: string | null;
  freshness?: {
    fresh?: boolean;
    local_date?: string | null;
    expected_date?: string | null;
    coverage_ratio?: number;
  };
  ai?: {
    available: boolean;
    status: "not_called" | "abstained" | "explained" | "shadow_ranked" | "failed";
    reason_codes: string[];
    model?: string | null;
    created_at?: string | null;
    market_note?: string | null;
  };
}

/** 策略复盘：单窗口汇总 */
export interface StrategyWindowAgg {
  count: number;
  win_rate: number | null;
  avg: number | null;
  median?: number | null;
  best?: number | null;
  worst?: number | null;
}

export interface StrategyHoldPathPoint {
  session: number;
  date: string;
  open_ret: number | null;
  high_ret: number | null;
  low_ret: number | null;
  close_ret: number | null;
  close: number | null;
}

export interface StrategyReviewPick {
  pick_date: string;
  code: string;
  name: string;
  industry?: string;
  strategy?: string;
  strategy_name?: string;
  entry_date: string | null;
  entry_price: number | null;
  entry_gap_pct?: number | null;
  next_day_chg: number | null;
  next_open_chg?: number | null;
  ret_to_date: number | null;
  mfe_to_date?: number | null;
  mae_to_date?: number | null;
  holding_sessions_to_date: number | null;
  latest_close?: number | null;
  ret_1: number | null;
  ret_5: number | null;
  ret_10: number | null;
  ret_20: number | null;
  max_gain_1?: number | null;
  max_gain_5?: number | null;
  max_gain_10?: number | null;
  max_gain_20?: number | null;
  max_dd_1?: number | null;
  max_dd_5?: number | null;
  max_dd_10?: number | null;
  max_dd_20?: number | null;
  exit_date_1?: string | null;
  exit_date_5?: string | null;
  exit_date_10?: string | null;
  exit_date_20?: string | null;
  status: string;
  as_of?: string | null;
  signal_close?: number | null;
  signal?: Record<string, unknown>;
  path?: StrategyHoldPathPoint[];
  windows?: Record<string, unknown>;
  id?: string;
  [key: string]: unknown;
}

export interface StrategyReviewSummary {
  pick_count: number;
  next_day: StrategyWindowAgg;
  to_date: StrategyWindowAgg;
  windows: Record<string, StrategyWindowAgg>;
  mfe?: StrategyWindowAgg;
  mae?: StrategyWindowAgg;
  recommended_hold: {
    hold_sessions: number;
    label: string;
    avg: number;
    win_rate: number | null;
    median?: number | null;
    count: number;
  } | null;
  avg_holding_sessions_observed: number | null;
  by_date?: Array<{
    pick_date: string;
    count: number;
    next_day: StrategyWindowAgg;
    to_date: StrategyWindowAgg;
    ret_5: StrategyWindowAgg;
  }>;
  top_picks?: Array<{
    code: string;
    name: string;
    pick_date: string;
    ret_to_date: number | null;
    next_day_chg: number | null;
  }>;
  bottom_picks?: Array<{
    code: string;
    name: string;
    pick_date: string;
    ret_to_date: number | null;
    next_day_chg: number | null;
  }>;
  execution_note: string;
}

export interface StrategyReviewResponse {
  available: boolean;
  reason?: string;
  strategy?: string;
  strategy_name?: string;
  group?: string;
  picks: StrategyReviewPick[];
  summary: StrategyReviewSummary;
  date_span?: { from: string; to: string } | null;
  cache_dates?: number;
  truncated?: boolean;
  total_cached_picks?: number;
  source?: string;
}

export interface StrategyReviewCatalogItem {
  key: string;
  name: string;
  group: string;
  pick_count: number;
  date_span?: { from: string; to: string } | null;
  has_data: boolean;
}

export interface StrategyReviewCatalogResponse {
  available: boolean;
  catalog: StrategyReviewCatalogItem[];
  default_strategy: string;
}

/** @deprecated 使用 StrategyReviewResponse */
export type CloudStairReviewResponse = StrategyReviewResponse;
export type CloudStairPick = StrategyReviewPick;
export type CloudStairWindowAgg = StrategyWindowAgg;

export const api = {
  getStats: () => request<ApiResponse<StatsData>>("/api/stats"),
  getStocks: (page: number = 1, perPage: number = 50) => {
    const safePerPage = Math.min(Math.max(perPage, 1), 100);
    return request<ApiResponse<StockItem[]> & { total: number; page: number; total_pages: number }>(
      `/api/stocks?page=${page}&per_page=${safePerPage}`,
    );
  },
  getStockProfile: (code: string) =>
    request<ApiResponse<StockProfile>>(`/api/stock/${code}/profile`),
  getKline: (code: string, period: string = "daily", days?: number) =>
    request<KlineResponse>(`/api/stock/${code}/kline?period=${period}${days ? `&days=${days}` : ""}`),
  getRanking: () =>
    request<ApiResponse<RankingStock[]> & { total: number; run_date: string }>("/api/ranking"),
  getIndustries: () =>
    request<ApiResponse<IndustryItem[]> & { total: number }>("/api/industries"),
  updateData: () => request<{ success: boolean; message: string }>("/api/data/update", { method: "POST" }),
  getThermometer: () => request<ThermometerData>("/api/thermometer"),
  getSectors: () => request<SectorsData>("/api/sectors"),
  getSectorDetail: (name: string) =>
    request<SectorDetailData>(`/api/sectors/${encodeURIComponent(name)}`),
  getCoverage: () => request<ApiResponse<CoverageStatus>>("/api/data/coverage"),
  startBootstrap: () => request<{ success: boolean; started: boolean; message: string }>(
    "/api/data/bootstrap", { method: "POST" },
  ),
  getSuperB1: () => request<SuperB1Data>("/api/super-b1"),
  getFactors: () => request<FactorsResponse>("/api/factors"),
  getQuantPick: () => request<QuantPickResponse>("/api/quant-pick"),
  getRecommend: () => request<RecommendResponse>("/api/recommend"),
  getQuantComment: () => request<QuantComment>("/api/quant-comment"),
  getLatestDecision: () => request<DecisionResponse>("/api/decision/latest"),
  getEvolutionStatus: () => request<EvolutionResponse>("/api/decision/evolution"),
  getSystemStatus: () => request<SystemStatusResponse>("/api/decision/system-status"),
  getPipelineStatus: () => request<PipelineStatusResponse>("/api/data-pipeline/status"),
  getFactorScan: (strategy: string, date?: string) =>
    request<FactorScanResponse>(
      `/api/factor-scan?strategy=${encodeURIComponent(strategy)}${date ? `&date=${date}` : ""}`,
    ),
  getPerformanceSummary: () => request<PerformanceSummary>("/api/performance/summary"),
  getPerformanceRecords: (limit = 200) =>
    request<{ total: number; records: PerformanceRecord[] }>(`/api/performance/records?limit=${limit}`),
  refreshPerformance: () =>
    request<{ success: boolean; synced: number; updated: number }>("/api/performance/refresh", { method: "POST" }),
  getCloudStairReview: (limit = 300) =>
    request<StrategyReviewResponse>(`/api/review/cloud-stair?limit=${limit}`),
  getReviewCatalog: () => request<StrategyReviewCatalogResponse>("/api/review/catalog"),
  getStrategyReview: (strategy: string, limit = 300) =>
    request<StrategyReviewResponse>(
      `/api/review/strategy?strategy=${encodeURIComponent(strategy)}&limit=${limit}`,
    ),
};
