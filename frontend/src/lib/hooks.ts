import useSWR from "swr";
import { api } from "./api";

export function useStats() {
  return useSWR("stats", () => api.getStats().then((r) => r.data), { refreshInterval: 30_000 });
}

export function useViews() {
  return useSWR("views", () => api.getViews().then((r) => r.data));
}

export function useView(id: number | null) {
  return useSWR(id !== null ? `view-${id}` : null, () => api.getView(id!).then((r) => r.data));
}

export function useStocks(page: number = 1) {
  return useSWR(`stocks-${page}`, () => api.getStocks(page));
}

export function useKline(code: string | null, period: string = "daily") {
  return useSWR(code ? `kline-${code}-${period}` : null, () => api.getKline(code!, period));
}

export function useRanking() {
  return useSWR("ranking", () => api.getRanking());
}

export function useSchedulerStatus() {
  return useSWR("scheduler-status", () => api.getSchedulerStatus().then((r) => r.data), { refreshInterval: 5_000 });
}

export function useViewResults(viewId: number | null, limit?: number) {
  return useSWR(
    viewId !== null ? `view-results-${viewId}-${limit}` : null,
    () => api.getViewResults(viewId!, limit).then((r) => r.data),
  );
}
