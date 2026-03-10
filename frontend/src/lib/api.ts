const API_BASE = import.meta.env.VITE_API_BASE || "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
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
  close: number;
  J: number;
  volume_ratio: number;
  market_cap: number;
  similarity_score: number;
  matched_case: string;
  match_breakdown: Record<string, number>;
  views: string[];
  run_date: string;
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

export interface KlineResponse {
  success: boolean;
  code: string;
  name: string;
  period: string;
  data: (string | number)[][];
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

export const api = {
  getStats: () => request<ApiResponse<StatsData>>("/api/stats"),
  getViews: () => request<ApiResponse<ViewData[]>>("/api/views"),
  getView: (id: number) => request<ApiResponse<ViewData>>(`/api/views/${id}`),
  createView: (body: { name: string; source_id?: number }) =>
    request<ApiResponse<ViewData>>("/api/views", { method: "POST", body: JSON.stringify(body) }),
  updateView: (id: number, body: Partial<ViewData>) =>
    request<ApiResponse<ViewData>>(`/api/views/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  duplicateView: (id: number, name: string) =>
    request<ApiResponse<ViewData>>(`/api/views/${id}/duplicate`, { method: "POST", body: JSON.stringify({ name }) }),
  runView: (id: number) =>
    request<{ success: boolean; task_id: string }>(`/api/views/${id}/run`, { method: "POST" }),
  getRunStatus: (viewId: number, taskId: string) =>
    request<TaskStatus>(`/api/views/${viewId}/run/status?task_id=${taskId}`),
  getViewResults: (viewId: number, limit?: number) =>
    request<ApiResponse<SelectionResult[]>>(`/api/views/${viewId}/results${limit ? `?limit=${limit}` : ""}`),
  getViewResultByDate: (viewId: number, date: string) =>
    request<ApiResponse<SelectionResult>>(`/api/views/${viewId}/results/${date}`),
  getStocks: (page: number = 1, perPage: number = 500) =>
    request<ApiResponse<StockItem[]> & { total: number; page: number; total_pages: number }>(
      `/api/stocks?page=${page}&per_page=${perPage}`,
    ),
  getKline: (code: string, period: string = "daily", days?: number) =>
    request<KlineResponse>(`/api/stock/${code}/kline?period=${period}${days ? `&days=${days}` : ""}`),
  getRanking: () =>
    request<ApiResponse<RankingStock[]> & { total: number; run_date: string }>("/api/ranking"),
  getSchedulerStatus: () =>
    request<ApiResponse<{ running: boolean; running_tasks: Record<string, string> }>>("/api/scheduler/status"),
  startScheduler: () => request<{ success: boolean }>("/api/scheduler/start", { method: "POST" }),
  stopScheduler: () => request<{ success: boolean }>("/api/scheduler/stop", { method: "POST" }),
  updateData: () => request<{ success: boolean; message: string }>("/api/data/update", { method: "POST" }),
};
