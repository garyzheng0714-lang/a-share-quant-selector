import { useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { PageTransition } from "@/components/layout/page-transition";
import { KlineChart, type KlineOverlay } from "@/components/charts/kline-chart";
import { Button } from "@/components/ui";
import { useKline } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";

type Period = "daily" | "weekly";
type WeeklyLineMode = "trend" | "ma";

function formatVolume(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(1) + "万";
  return v.toFixed(0);
}

const BULL = "#ef4444";
const BEAR = "#22c55e";

export function Component() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const [period, setPeriod] = useState<Period>("daily");
  const [weeklyLineMode, setWeeklyLineMode] = useState<WeeklyLineMode>("trend");
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
  const isBull = changePercent >= 0;

  return (
    <PageTransition>
      <div className="h-[calc(100vh-48px)] flex flex-col bg-[#141414]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-[#2a2a2a] bg-[#1c1c1c]">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate(-1)}
              className="text-sm text-[#94a3b8] hover:text-[#e2e8f0] transition-colors"
            >
              ← 返回
            </button>
            <div className="flex items-center gap-3">
              <span className="text-base font-mono font-semibold text-[#e2e8f0]">
                {code}
              </span>
              <span className="text-base text-[#94a3b8]">{stockName}</span>
              {!isLoading && (
                <div className="flex items-center gap-2">
                  <span
                    className="text-lg font-mono font-semibold"
                    style={{ color: isBull ? BULL : BEAR }}
                  >
                    {latestClose.toFixed(2)}
                  </span>
                  <span
                    className="text-sm font-mono"
                    style={{ color: isBull ? BULL : BEAR }}
                  >
                    {isBull ? "+" : ""}
                    {changePercent.toFixed(2)}%
                  </span>
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Period tabs */}
            <div className="flex items-center gap-1 bg-[#0f0f0f] rounded-lg p-0.5">
              {(["daily", "weekly"] as Period[]).map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={`relative px-3 py-1 text-sm rounded-md transition-colors ${
                    period === p
                      ? "text-white font-medium"
                      : "text-[#94a3b8] hover:text-[#cbd5e1]"
                  }`}
                >
                  {p === "daily" ? "日K" : "周K"}
                  {period === p && (
                    <motion.div
                      layoutId="period-indicator"
                      className="absolute inset-0 bg-[#2a2a2a] rounded-md -z-10"
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

            {/* Weekly line mode toggle */}
            {period === "weekly" && (
              <button
                onClick={() =>
                  setWeeklyLineMode((m) => (m === "trend" ? "ma" : "trend"))
                }
                className="px-3 py-1 text-sm rounded-md bg-[#2a2a2a] text-[#e2e8f0] hover:bg-[#333] transition-colors"
              >
                {weeklyLineMode === "trend" ? "黄白线" : "均线"}
              </button>
            )}
          </div>
        </div>

        {/* Chart area */}
        <div className="flex-1 relative min-h-0">
          {isLoading ? (
            <div className="h-full flex items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <span className="text-sm text-[#94a3b8]">加载K线数据...</span>
              </div>
            </div>
          ) : klineData?.data?.length ? (
            <>
              <KlineChart
                data={klineData.data}
                period={period}
                weeklyLineMode={weeklyLineMode}
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
                    className="absolute top-3 left-3 rounded-xl px-4 py-3 shadow-lg pointer-events-none"
                    style={{
                      background: "rgba(28,37,57,0.9)",
                      backdropFilter: "blur(8px)",
                      border: "1px solid rgba(148,163,184,0.18)",
                    }}
                  >
                    {/* Line 1: OHLCV */}
                    <div className="flex items-center gap-4 text-xs font-mono">
                      <span className="text-[#94a3b8]">{overlay.date}</span>
                      <span className="text-[#94a3b8]">
                        开{" "}
                        <span className="text-[#e2e8f0]">
                          {overlay.open.toFixed(2)}
                        </span>
                      </span>
                      <span className="text-[#94a3b8]">
                        高{" "}
                        <span className="text-[#e2e8f0]">
                          {overlay.high.toFixed(2)}
                        </span>
                      </span>
                      <span className="text-[#94a3b8]">
                        低{" "}
                        <span className="text-[#e2e8f0]">
                          {overlay.low.toFixed(2)}
                        </span>
                      </span>
                      <span className="text-[#94a3b8]">
                        收{" "}
                        <span style={{ color: overlay.change >= 0 ? BULL : BEAR }}>
                          {overlay.close.toFixed(2)}
                        </span>
                      </span>
                      <span style={{ color: overlay.change >= 0 ? BULL : BEAR }}>
                        {overlay.change >= 0 ? "+" : ""}
                        {overlay.change.toFixed(2)}%
                      </span>
                      <span className="text-[#94a3b8]">
                        量{" "}
                        <span className="text-[#e2e8f0]">
                          {formatVolume(overlay.volume)}
                        </span>
                      </span>
                    </div>

                    {/* Line 2: contextual indicators */}
                    {period === "daily" ||
                    (period === "weekly" && weeklyLineMode === "trend") ? (
                      overlay.trendLine != null && (
                        <div className="flex items-center gap-3 text-xs font-mono mt-1.5">
                          <span className="text-[#94a3b8]">
                            趋势{" "}
                            <span className="text-[#e2e8f0]">
                              {overlay.trendLine.toFixed(2)}
                            </span>
                          </span>
                          {overlay.dkLine != null && (
                            <span className="text-[#94a3b8]">
                              多空{" "}
                              <span className="text-[#e2e8f0]">
                                {overlay.dkLine.toFixed(2)}
                              </span>
                            </span>
                          )}
                        </div>
                      )
                    ) : period === "weekly" && weeklyLineMode === "ma" ? (
                      <div className="flex items-center gap-3 text-xs font-mono mt-1.5">
                        {overlay.ma5 != null && (
                          <span style={{ color: "#f59e0b" }}>
                            MA5:{overlay.ma5.toFixed(2)}
                          </span>
                        )}
                        {overlay.ma10 != null && (
                          <span style={{ color: "#3b82f6" }}>
                            MA10:{overlay.ma10.toFixed(2)}
                          </span>
                        )}
                        {overlay.ma20 != null && (
                          <span style={{ color: "#a855f7" }}>
                            MA20:{overlay.ma20.toFixed(2)}
                          </span>
                        )}
                        {overlay.ma60 != null && (
                          <span style={{ color: "#22c55e" }}>
                            MA60:{overlay.ma60.toFixed(2)}
                          </span>
                        )}
                      </div>
                    ) : null}

                    {/* Line 3: KDJ (daily only) */}
                    {period === "daily" && overlay.kdjK != null && (
                      <div className="flex items-center gap-3 text-xs font-mono mt-1.5">
                        <span className="text-[#94a3b8]">KDJ</span>
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
              <p className="text-[#94a3b8]">暂无K线数据</p>
            </div>
          )}
        </div>

        {/* Bottom navigation */}
        {hasNav && (
          <div className="flex items-center justify-between px-6 py-3 border-t border-[#2a2a2a] bg-[#1c1c1c]">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => goToStock(-1)}
              disabled={stockNavIndex <= 0}
              className="text-[#94a3b8] hover:text-[#e2e8f0]"
            >
              ← 上一只
            </Button>
            <span className="text-xs text-[#94a3b8] font-mono">
              {stockNavIndex + 1} / {stockNavList.length}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => goToStock(1)}
              disabled={stockNavIndex >= stockNavList.length - 1}
              className="text-[#94a3b8] hover:text-[#e2e8f0]"
            >
              下一只 →
            </Button>
          </div>
        )}
      </div>
    </PageTransition>
  );
}
