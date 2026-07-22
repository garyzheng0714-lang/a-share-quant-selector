import useSWR from "swr";
import { api } from "./api";

export function useStats() {
  return useSWR("stats", () => api.getStats().then((r) => r.data), { refreshInterval: 30_000 });
}

export function useStocks(page: number = 1) {
  return useSWR(`stocks-${page}`, () => api.getStocks(page));
}

export function useKline(code: string | null, period: string = "daily") {
  return useSWR(code ? `kline-${code}-${period}` : null, () => api.getKline(code!, period));
}

export function useStockProfile(code: string | null) {
  return useSWR(code ? `profile-${code}` : null, () => api.getStockProfile(code!).then((r) => r.data));
}

export function useRanking() {
  return useSWR("ranking", () => api.getRanking());
}

export function useThermometer() {
  return useSWR("thermometer", () => api.getThermometer(), { refreshInterval: 300_000 });
}

export function useSectors() {
  return useSWR("sectors", () => api.getSectors(), { refreshInterval: 600_000 });
}

export function useSectorDetail(name: string | null) {
  return useSWR(name ? `sector-${name}` : null, () => api.getSectorDetail(name!), {
    refreshInterval: 600_000,
  });
}

export function useCoverage() {
  return useSWR("data-coverage", () => api.getCoverage().then((r) => r.data), {
    refreshInterval: 30_000,
  });
}

export function useSuperB1() {
  return useSWR("super-b1", () => api.getSuperB1(), { refreshInterval: 600_000 });
}

export function useQuantPick() {
  return useSWR("quant-pick", () => api.getQuantPick(), { refreshInterval: 600_000 });
}

/** AI 点评单独拉：它要调大模型（首次可能几十秒），不能拖着选票结果一起等 */
export function useQuantComment() {
  return useSWR("quant-comment", () => api.getQuantComment(), {
    refreshInterval: 0,
    revalidateOnFocus: false,
  });
}

export function useLatestDecision() {
  return useSWR("latest-decision", () => api.getLatestDecision(), {
    refreshInterval: 300_000,
    revalidateOnFocus: true,
  });
}

export function useEvolutionStatus() {
  return useSWR("evolution-status", () => api.getEvolutionStatus(), {
    refreshInterval: 600_000,
    revalidateOnFocus: true,
  });
}

export function useSystemStatus() {
  return useSWR("decision-system-status", () => api.getSystemStatus(), {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });
}

export function useFactors() {
  // today_hits 随 16:00 预热更新，页面常开也能拿到新数字
  return useSWR("factors", () => api.getFactors(), { refreshInterval: 600_000 });
}

/** date 为空 = 最新交易日。历史日期结果不变，关掉自动刷新省请求 */
export function useFactorScan(strategy: string | null, date?: string) {
  return useSWR(
    strategy ? `factor-scan-${strategy}-${date || "latest"}` : null,
    () => api.getFactorScan(strategy!, date),
    { refreshInterval: date ? 0 : 600_000, revalidateOnFocus: false },
  );
}

export function usePerformanceSummary() {
  return useSWR("performance-summary", () => api.getPerformanceSummary());
}

export function usePerformanceRecords(limit = 200) {
  return useSWR(`performance-records-${limit}`, () => api.getPerformanceRecords(limit));
}
