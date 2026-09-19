const API_BASE = import.meta.env.VITE_API_BASE || "";

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface StatsData {
  latest_date: string;
  scan_date: string | null;
  stock_count: number;
}

/** 结果列表里的一只票，供详情页左右切换 */
export interface SignalStock {
  code: string;
  name: string;
  industry?: string;
}

export interface StockProfile {
  code: string;
  name: string;
  industry: string;
  cap_yi: number | null;
  latest_date: string;
  /** 以下字段当前后端不再提供，保留为可选以兼容详情页渲染 */
  board?: string;
  business?: string;
  listing_date?: string;
}

/** 该票的历史因子命中（哪天命中了哪个因子），用于在 K 线上标记 */
export interface KlineSignal {
  date: string;
  category: string;
}

export interface KlineResponse {
  success: boolean;
  code: string;
  name: string;
  period: string;
  as_of: string;
  week_end?: string | null;
  current_week_partial?: boolean;
  change_label: "今日涨跌" | "本周涨跌";
  data: (string | number)[][];
  signals?: KlineSignal[];
}

export interface FactorMeta {
  key: string;
  name: string;
  group: string;
  desc: string;
  /** 大白话说明 */
  plain: string;
  /** 最新扫描日命中数；null=该因子还没扫过 */
  today_hits: number | null;
}

export type ComposeJoin = "and" | "or";

/** 常用组合（后端 strategy/factors PRESETS 配置） */
export interface FactorPreset {
  key: string;
  name: string;
  keys: string[];
  join: ComposeJoin;
  today_hits: number | null;
}

export interface FactorsResponse {
  factors: FactorMeta[];
  presets: FactorPreset[];
  groups: string[];
  trade_date: string;
  /** 有扫描结果的交易日（新→旧） */
  recent_dates: string[];
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
  [key: string]: unknown;
}

export interface ComposeHit extends FactorHit {
  /** 命中了哪几个因子 */
  matched: string[];
  /** 连续命中天数（含当日） */
  streak: number;
  /** 连命中最多能往前追溯的天数（缓存断档即停） */
  streak_depth: number;
  /** 近 20 日收盘（旧→新） */
  spark: number[];
}

export interface FactorComposeResponse {
  available: boolean;
  reason?: string;
  keys?: string[];
  join?: ComposeJoin;
  trade_date?: string;
  hits?: ComposeHit[];
  per_key_counts?: Record<string, number>;
  total_scanned?: number;
}

export const api = {
  getStats: () => request<StatsData>("/api/stats"),
  getStockProfile: (code: string) => request<StockProfile>(`/api/stock/${code}/profile`),
  getKline: (code: string, period: string = "daily", days?: number) =>
    request<KlineResponse>(`/api/stock/${code}/kline?period=${period}${days ? `&days=${days}` : ""}`),
  getFactors: () => request<FactorsResponse>("/api/factors"),
  getFactorCompose: (keys: string[], join: ComposeJoin, date?: string) =>
    request<FactorComposeResponse>(
      `/api/factor-compose?keys=${encodeURIComponent(keys.join(","))}&join=${join}${date ? `&date=${date}` : ""}`,
    ),
};
