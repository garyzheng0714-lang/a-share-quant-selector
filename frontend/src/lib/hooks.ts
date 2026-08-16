import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { api } from "./api";
import type { CloudStairHistoryRow, HistoryHorizon, HistoryResult } from "./api";
import { HISTORY_PAGE_SIZE, shouldPrefetchMore } from "./history-feed";

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

export function useCloudStairHistorySummary() {
  return useSWR("cloud-stair-history-summary", () => api.getCloudStairHistorySummary(), {
    revalidateOnFocus: false,
  });
}

export function useCloudStairHistoryFeed(
  query: string,
  date: string,
  horizon: HistoryHorizon = "t1",
  result: HistoryResult = "all",
) {
  const [rows, setRows] = useState<CloudStairHistoryRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const generation = useRef(0);
  const inflight = useRef(false);

  const load = useCallback(
    async (nextPage: number, expected: number, replace: boolean) => {
      if (inflight.current && !replace) return;
      inflight.current = true;
      setLoading(true);
      setFailed(false);
      try {
        const payload = await api.getCloudStairHistorySignals({
          q: query,
          date,
          horizon,
          result,
          page: nextPage,
          pageSize: HISTORY_PAGE_SIZE,
        });
        if (generation.current !== expected) return;
        setRows((current) => (replace ? payload.rows : current.concat(payload.rows)));
        setTotal(payload.total);
        setPage(nextPage);
      } catch {
        if (generation.current !== expected) return;
        setFailed(true);
      } finally {
        if (generation.current === expected) {
          inflight.current = false;
          setLoading(false);
        }
      }
    },
    [date, horizon, query, result],
  );

  useEffect(() => {
    const expected = generation.current + 1;
    generation.current = expected;
    inflight.current = false;
    setRows([]);
    setTotal(0);
    setPage(0);
    void load(1, expected, true);
  }, [load]);

  const hasMore = total === 0 ? page === 0 : rows.length < total;

  const ensureAhead = useCallback(
    (remainingPx: number) => {
      if (failed || inflight.current || !hasMore || page < 1) return;
      if (
        shouldPrefetchMore({
          loadedCount: rows.length,
          total,
          remainingPx,
        })
      ) {
        void load(page + 1, generation.current, false);
      }
    },
    [failed, hasMore, load, page, rows.length, total],
  );

  return {
    rows,
    total,
    loading,
    loadingMore: loading && rows.length > 0,
    failed,
    hasMore,
    ensureAhead,
    reload: () => {
      const expected = generation.current + 1;
      generation.current = expected;
      inflight.current = false;
      setRows([]);
      setTotal(0);
      setPage(0);
      void load(1, expected, true);
    },
  };
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
