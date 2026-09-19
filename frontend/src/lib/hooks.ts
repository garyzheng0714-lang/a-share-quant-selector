import useSWR from "swr";
import { api, type ComposeJoin } from "./api";

export function useStats() {
  return useSWR("stats", () => api.getStats(), { refreshInterval: 600_000 });
}

export function useKline(code: string | null, period: string = "daily") {
  return useSWR(code ? `kline-${code}-${period}` : null, () => api.getKline(code!, period));
}

export function useStockProfile(code: string | null) {
  return useSWR(code ? `profile-${code}` : null, () => api.getStockProfile(code!));
}

export function useFactors() {
  return useSWR("factors", () => api.getFactors(), { refreshInterval: 600_000 });
}

/** 多因子组合（且/或）。keys 为空不请求；历史日期不自动刷新 */
export function useFactorCompose(keys: string[], join: ComposeJoin, date?: string) {
  return useSWR(
    keys.length ? `factor-compose-${join}-${keys.join(",")}-${date || "latest"}` : null,
    () => api.getFactorCompose(keys, join, date),
    { refreshInterval: date ? 0 : 600_000, revalidateOnFocus: false },
  );
}
