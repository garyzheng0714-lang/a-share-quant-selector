import { useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { PageTransition } from "@/components/layout/page-transition";
import { KlineChart } from "@/components/charts/kline-chart";
import { Button } from "@/components/ui";
import { useKline } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";

type Period = "daily" | "weekly";

interface KlineOverlay {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change: number;
  kdjK?: number;
  kdjD?: number;
  kdjJ?: number;
  trendLine?: number;
  dkLine?: number;
}

function formatVolume(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(1) + "万";
  return v.toFixed(0);
}

export function Component() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const [period, setPeriod] = useState<Period>("daily");
  const [overlay, setOverlay] = useState<KlineOverlay | null>(null);

  const stockNavList = useAppStore((s) => s.stockNavList);
  const stockNavIndex = useAppStore((s) => s.stockNavIndex);
  const setStockNavIndex = useAppStore((s) => s.setStockNavIndex);

  const { data: klineData, isLoading } = useKline(code ?? null, period);

  const currentStock = stockNavList[stockNavIndex];
  const stockName = klineData?.name ?? currentStock?.name ?? "";
  const hasNav = stockNavList.length > 1;

  const handleCrosshairMove = useCallback((data: KlineOverlay | null) => {
    setOverlay(data);
  }, []);

  const goToStock = (direction: -1 | 1) => {
    const newIdx = stockNavIndex + direction;
    if (newIdx < 0 || newIdx >= stockNavList.length) return;
    setStockNavIndex(newIdx);
    navigate(`/stock/${stockNavList[newIdx].code}`, { replace: true });
  };

  const lastCandle = klineData?.data?.length
    ? klineData.data[klineData.data.length - 1]
    : null;
  const latestClose = lastCandle ? (lastCandle[2] as number) : 0;
  const prevClose =
    klineData?.data?.length && klineData.data.length > 1
      ? (klineData.data[klineData.data.length - 2][2] as number)
      : latestClose;
  const changePercent = prevClose
    ? ((latestClose - prevClose) / prevClose) * 100
    : 0;
  const changeColor = changePercent >= 0 ? "text-bull" : "text-bear";

  return (
    <PageTransition>
      <div className="h-[calc(100vh-48px)] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-border bg-surface/50">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate(-1)}
              className="text-sm text-ink-muted hover:text-ink transition-colors"
            >
              ← 返回
            </button>
            <div className="flex items-center gap-3">
              <span className="text-base font-mono font-semibold text-ink">
                {code}
              </span>
              <span className="text-base text-ink-secondary">{stockName}</span>
              {!isLoading && (
                <div className="flex items-center gap-2">
                  <span
                    className={`text-lg font-mono font-semibold ${changeColor}`}
                  >
                    {latestClose.toFixed(2)}
                  </span>
                  <span className={`text-sm font-mono ${changeColor}`}>
                    {changePercent >= 0 ? "+" : ""}
                    {changePercent.toFixed(2)}%
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Period tabs */}
          <div className="flex items-center gap-1 bg-inset rounded-lg p-0.5">
            {(["daily", "weekly"] as Period[]).map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`relative px-3 py-1 text-sm rounded-md transition-colors ${
                  period === p
                    ? "text-ink font-medium"
                    : "text-ink-muted hover:text-ink-secondary"
                }`}
              >
                {p === "daily" ? "日K" : "周K"}
                {period === p && (
                  <motion.div
                    layoutId="period-indicator"
                    className="absolute inset-0 bg-surface rounded-md shadow-card -z-10"
                    transition={{
                      type: "spring",
                      damping: 25,
                      stiffness: 300,
                    }}
                  />
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Chart area */}
        <div className="flex-1 relative min-h-0">
          {isLoading ? (
            <div className="h-full flex items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                <span className="text-sm text-ink-muted">加载K线数据...</span>
              </div>
            </div>
          ) : klineData?.data?.length ? (
            <>
              <KlineChart
                data={klineData.data}
                period={period}
                onCrosshairMove={handleCrosshairMove}
                className="h-full"
              />

              {/* Data overlay */}
              <AnimatePresence>
                {overlay && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    className="absolute top-3 left-3 glass rounded-xl px-4 py-3 border border-border shadow-card pointer-events-none"
                  >
                    <div className="flex items-center gap-4 text-xs font-mono">
                      <span className="text-ink-muted">{overlay.date}</span>
                      <span className="text-ink-secondary">
                        开{" "}
                        <span className="text-ink">
                          {overlay.open.toFixed(2)}
                        </span>
                      </span>
                      <span className="text-ink-secondary">
                        高{" "}
                        <span className="text-ink">
                          {overlay.high.toFixed(2)}
                        </span>
                      </span>
                      <span className="text-ink-secondary">
                        低{" "}
                        <span className="text-ink">
                          {overlay.low.toFixed(2)}
                        </span>
                      </span>
                      <span className="text-ink-secondary">
                        收{" "}
                        <span
                          className={
                            overlay.change >= 0 ? "text-bull" : "text-bear"
                          }
                        >
                          {overlay.close.toFixed(2)}
                        </span>
                      </span>
                      <span
                        className={
                          overlay.change >= 0 ? "text-bull" : "text-bear"
                        }
                      >
                        {overlay.change >= 0 ? "+" : ""}
                        {overlay.change.toFixed(2)}%
                      </span>
                      <span className="text-ink-secondary">
                        量{" "}
                        <span className="text-ink">
                          {formatVolume(overlay.volume)}
                        </span>
                      </span>
                    </div>
                    {period === "daily" && overlay.kdjK != null && (
                      <div className="flex items-center gap-3 text-xs font-mono mt-1.5">
                        <span className="text-ink-muted">KDJ</span>
                        <span style={{ color: "#3b82f6" }}>
                          K:{overlay.kdjK.toFixed(1)}
                        </span>
                        <span style={{ color: "#f59e0b" }}>
                          D:{overlay.kdjD?.toFixed(1)}
                        </span>
                        <span style={{ color: "#ef4444" }}>
                          J:{overlay.kdjJ?.toFixed(1)}
                        </span>
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </>
          ) : (
            <div className="h-full flex items-center justify-center">
              <p className="text-ink-muted">暂无K线数据</p>
            </div>
          )}
        </div>

        {/* Bottom navigation */}
        {hasNav && (
          <div className="flex items-center justify-between px-6 py-3 border-t border-border bg-surface/50">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => goToStock(-1)}
              disabled={stockNavIndex <= 0}
            >
              ← 上一只
            </Button>
            <span className="text-xs text-ink-muted font-mono">
              {stockNavIndex + 1} / {stockNavList.length}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => goToStock(1)}
              disabled={stockNavIndex >= stockNavList.length - 1}
            >
              下一只 →
            </Button>
          </div>
        )}
      </div>
    </PageTransition>
  );
}
