import useSWR from "swr";
import { api } from "./api";

export function useKline(code: string | null, period: string = "daily") {
  return useSWR(code ? `kline-${code}-${period}` : null, () => api.getKline(code!, period));
}

export function useStockProfile(code: string | null) {
  return useSWR(code ? `profile-${code}` : null, () => api.getStockProfile(code!).then((r) => r.data));
}

export function useSectors() {
  return useSWR("sectors", () => api.getSectors(), { refreshInterval: 600_000 });
}

export function useSectorDetail(name: string | null) {
  return useSWR(name ? `sector-${name}` : null, () => api.getSectorDetail(name!), {
    refreshInterval: 600_000,
  });
}

export function useLatestDecision() {
  return useSWR("latest-decision", () => api.getLatestDecision(), {
    refreshInterval: 300_000,
    revalidateOnFocus: true,
  });
}

export function useSystemStatus() {
  return useSWR("decision-system-status", () => api.getSystemStatus(), {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });
}

export function usePipelineStatus() {
  return useSWR("data-pipeline-status", () => api.getPipelineStatus(), {
    refreshInterval: (data) => data?.state === "updating" ? 5_000 : 60_000,
    revalidateOnFocus: true,
  });
}

export function useCloudStairReview(limit = 300) {
  return useSWR(`cloud-stair-review-${limit}`, () => api.getCloudStairReview(limit), {
    refreshInterval: 600_000,
    revalidateOnFocus: false,
  });
}

export function useDailyStrategyReview() {
  return useSWR("daily-strategy-review", () => api.getDailyStrategyReview(), {
    refreshInterval: 300_000,
    revalidateOnFocus: true,
  });
}

export function useRecommend() {
  return useSWR("recommend", () => api.getRecommend(), { refreshInterval: 600_000 });
}
