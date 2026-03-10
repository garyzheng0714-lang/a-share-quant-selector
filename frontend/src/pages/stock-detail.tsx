import { useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { PageTransition } from "@/components/layout/page-transition";
import { KlineChart, type KlineOverlay } from "@/components/charts/kline-chart";
import { Button, CopyButton } from "@/components/ui";
import { useKline } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import { chartColors, ease } from "@/lib/tokens";

type Period = "daily" | "weekly";
type WeeklyLineMode = "trend" | "ma";

function formatVolume(v: number): string {
  if (v >= 1e8) return (v / 1e8).toFixed(2) + "亿";
  if (v >= 1e4) return (v / 1e4).toFixed(1) + "万";
  return v.toFixed(0);
}

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

  // Extract latest trend/DK line values from raw data
  const latestRow = klineData?.data?.length
    ? klineData.data[klineData.data.length - 1]
    : null;

  type TrendValues = { type: "trend"; trend: number; dk: number | null };
  type MaValues = {
    type: "ma";
    ma5: number | null;
    ma10: number | null;
    ma20: number | null;
    ma60: number | null;
  };

  const getLineValues = (): TrendValues | MaValues | null => {
    const src = overlay ?? null;
    if (src?.trendLine != null) {
      return { type: "trend", trend: src.trendLine, dk: src.dkLine ?? null };
    }
    if (src?.ma5 != null) {
      return { type: "ma", ma5: src.ma5, ma10: src.ma10 ?? null, ma20: src.ma20 ?? null, ma60: src.ma60 ?? null };
    }
    if (!latestRow) return null;
    if (period === "daily") {
      const t = latestRow[9] as number | null;
      const d = latestRow[10] as number | null;
      return t != null ? { type: "trend", trend: t, dk: d } : null;
    }
    if (weeklyLineMode === "trend") {
      const t = latestRow[10] as number | null;
      const d = latestRow[11] as number | null;
      return t != null ? { type: "trend", trend: t, dk: d } : null;
    }
    return {
      type: "ma",
      ma5: latestRow[6] as number | null,
      ma10: latestRow[7] as number | null,
      ma20: latestRow[8] as number | null,
      ma60: latestRow[9] as number | null,
    };
  };
  const lineValues = getLineValues();

  return (
    <PageTransition>
      <div className="h-[calc(100vh-48px-4rem)] sm:h-[calc(100vh-48px)] flex flex-col">
        {/* Header */}
        <div className="px-3 sm:px-6 py-2 sm:py-3 border-b border-border glass-elevated">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 sm:gap-4 min-w-0">
              <button
                onClick={() => navigate(-1)}
                className="text-sm text-ink-secondary hover:text-ink transition-colors shrink-0"
              >
                ←
              </button>
              <span className="text-sm sm:text-base font-mono font-semibold text-ink shrink-0">
                {code}
              </span>
              {code && (
                <CopyButton
                  text={code}
                  className="text-ink-secondary hover:text-ink"
                />
              )}
              <span className="text-sm text-ink-secondary truncate hidden sm:block">
                {stockName}
              </span>
              {!isLoading && (
                <div className="hidden sm:flex items-center gap-1.5">
                  <span
                    className={`text-lg font-mono font-semibold ${isBull ? "text-bull" : "text-bear"}`}
                  >
                    {latestClose.toFixed(2)}
                  </span>
                  <span
                    className={`text-sm font-mono ${isBull ? "text-bull" : "text-bear"}`}
                  >
                    {isBull ? "+" : ""}
                    {changePercent.toFixed(2)}%
                  </span>
                </div>
              )}
            </div>
            <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
            <div className="flex items-center gap-0.5 bg-inset rounded-lg p-0.5">
              {(["daily", "weekly"] as Period[]).map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={`relative px-2 sm:px-3 py-1 text-xs sm:text-sm rounded-md transition-colors ${
                    period === p
                      ? "text-ink font-medium"
                      : "text-ink-secondary hover:text-ink"
                  }`}
                >
                  {p === "daily" ? "日K" : "周K"}
                  {period === p && (
                    <motion.div
                      layoutId="period-indicator"
                      className="absolute inset-0 bg-elevated rounded-md -z-10"
                      transition={ease.spring}
                    />
                  )}
                </button>
              ))}
            </div>

            {period === "weekly" && (
              <button
                onClick={() =>
                  setWeeklyLineMode((m) => (m === "trend" ? "ma" : "trend"))
                }
                className="px-2 sm:px-3 py-1 text-xs sm:text-sm rounded-md bg-elevated text-ink hover:bg-border-hover transition-colors"
              >
                {weeklyLineMode === "trend" ? "黄白线" : "均线"}
              </button>
            )}
            </div>
          </div>
          {/* Mobile: second row with name + price */}
          {!isLoading && (
            <div className="flex items-center justify-between mt-1.5 sm:hidden">
              <span className="text-xs text-ink-secondary truncate">
                {stockName}
              </span>
              <div className="flex items-center gap-1.5 shrink-0">
                <span
                  className={`text-sm font-mono font-semibold ${isBull ? "text-bull" : "text-bear"}`}
                >
                  {latestClose.toFixed(2)}
                </span>
                <span
                  className={`text-xs font-mono ${isBull ? "text-bull" : "text-bear"}`}
                >
                  {isBull ? "+" : ""}
                  {changePercent.toFixed(2)}%
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Chart area */}
        <div className="flex-1 relative min-h-0">
          {isLoading ? (
            <div className="h-full flex items-center justify-center">
              <div className="flex flex-col items-center gap-3">
                <div className="w-8 h-8 border-2 border-accent border-t-transparent rounded-full animate-spin" />
                <span className="text-sm text-ink-secondary">加载K线数据...</span>
              </div>
            </div>
          ) : klineData?.data?.length ? (
            <>
              {/* Persistent indicator values */}
              {lineValues && !isLoading && (
                <div className="absolute top-1 left-11 sm:left-16 z-10 flex items-center gap-2 sm:gap-3 text-[10px] sm:text-xs font-mono pointer-events-none">
                  {lineValues.type === "trend" ? (
                    <>
                      <span>
                        <span className="text-ink-muted">趋势 </span>
                        <span style={{ color: chartColors.trend }}>
                          {lineValues.trend.toFixed(2)}
                        </span>
                      </span>
                      {lineValues.dk != null && (
                        <span>
                          <span className="text-ink-muted">多空 </span>
                          <span style={{ color: chartColors.dk }}>
                            {lineValues.dk.toFixed(2)}
                          </span>
                        </span>
                      )}
                    </>
                  ) : (
                    <>
                      {lineValues.ma5 != null && (
                        <span style={{ color: chartColors.ma5 }}>
                          MA5:{lineValues.ma5.toFixed(2)}
                        </span>
                      )}
                      {lineValues.ma10 != null && (
                        <span style={{ color: chartColors.ma10 }}>
                          MA10:{lineValues.ma10.toFixed(2)}
                        </span>
                      )}
                      {lineValues.ma20 != null && (
                        <span style={{ color: chartColors.ma20 }}>
                          MA20:{lineValues.ma20.toFixed(2)}
                        </span>
                      )}
                      {lineValues.ma60 != null && (
                        <span style={{ color: chartColors.ma60 }}>
                          MA60:{lineValues.ma60.toFixed(2)}
                        </span>
                      )}
                    </>
                  )}
                </div>
              )}
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
                    className="absolute top-2 left-2 sm:top-3 sm:left-3 glass-elevated rounded-lg sm:rounded-xl px-2 py-1.5 sm:px-4 sm:py-3 shadow-float pointer-events-none max-w-[calc(100%-16px)]"
                  >
                    {/* Line 1: OHLCV */}
                    <div className="flex flex-wrap items-center gap-x-2 sm:gap-x-4 gap-y-0.5 text-[10px] sm:text-xs font-mono">
                      <span className="text-ink-secondary">{overlay.date}</span>
                      <span className="text-ink-secondary">
                        开 <span className="text-ink">{overlay.open.toFixed(2)}</span>
                      </span>
                      <span className="text-ink-secondary">
                        高 <span className="text-ink">{overlay.high.toFixed(2)}</span>
                      </span>
                      <span className="text-ink-secondary">
                        低 <span className="text-ink">{overlay.low.toFixed(2)}</span>
                      </span>
                      <span className="text-ink-secondary">
                        收{" "}
                        <span className={overlay.change >= 0 ? "text-bull" : "text-bear"}>
                          {overlay.close.toFixed(2)}
                        </span>
                      </span>
                      <span className={overlay.change >= 0 ? "text-bull" : "text-bear"}>
                        {overlay.change >= 0 ? "+" : ""}
                        {overlay.change.toFixed(2)}%
                      </span>
                      <span className="text-ink-secondary">
                        量 <span className="text-ink">{formatVolume(overlay.volume)}</span>
                      </span>
                    </div>

                    {/* Line 2: contextual indicators */}
                    {period === "daily" ||
                    (period === "weekly" && weeklyLineMode === "trend") ? (
                      overlay.trendLine != null && (
                        <div className="flex items-center gap-2 sm:gap-3 text-[10px] sm:text-xs font-mono mt-1">
                          <span className="text-ink-secondary">
                            趋势 <span className="text-ink">{overlay.trendLine.toFixed(2)}</span>
                          </span>
                          {overlay.dkLine != null && (
                            <span className="text-ink-secondary">
                              多空 <span className="text-ink">{overlay.dkLine.toFixed(2)}</span>
                            </span>
                          )}
                        </div>
                      )
                    ) : period === "weekly" && weeklyLineMode === "ma" ? (
                      <div className="flex flex-wrap items-center gap-2 sm:gap-3 text-[10px] sm:text-xs font-mono mt-1">
                        {overlay.ma5 != null && (
                          <span style={{ color: chartColors.ma5 }}>MA5:{overlay.ma5.toFixed(2)}</span>
                        )}
                        {overlay.ma10 != null && (
                          <span style={{ color: chartColors.ma10 }}>MA10:{overlay.ma10.toFixed(2)}</span>
                        )}
                        {overlay.ma20 != null && (
                          <span style={{ color: chartColors.ma20 }}>MA20:{overlay.ma20.toFixed(2)}</span>
                        )}
                        {overlay.ma60 != null && (
                          <span style={{ color: chartColors.ma60 }}>MA60:{overlay.ma60.toFixed(2)}</span>
                        )}
                      </div>
                    ) : null}

                    {/* Line 3: KDJ (daily only) */}
                    {period === "daily" && overlay.kdjK != null && (
                      <div className="flex items-center gap-2 sm:gap-3 text-[10px] sm:text-xs font-mono mt-1">
                        <span className="text-ink-secondary">KDJ</span>
                        <span style={{ color: chartColors.kdjK }}>K:{overlay.kdjK.toFixed(1)}</span>
                        <span style={{ color: chartColors.kdjD }}>D:{overlay.kdjD?.toFixed(1)}</span>
                        <span style={{ color: chartColors.kdjJ }}>J:{overlay.kdjJ?.toFixed(1)}</span>
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </>
          ) : (
            <div className="h-full flex items-center justify-center">
              <p className="text-ink-secondary">暂无K线数据</p>
            </div>
          )}
        </div>

        {/* Bottom navigation */}
        {hasNav && (
          <div className="flex items-center justify-between px-3 sm:px-6 py-2 sm:py-3 border-t border-border glass-elevated">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => goToStock(-1)}
              disabled={stockNavIndex <= 0}
            >
              ←
            </Button>
            <span className="text-xs text-ink-secondary font-mono">
              {stockNavIndex + 1} / {stockNavList.length}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => goToStock(1)}
              disabled={stockNavIndex >= stockNavList.length - 1}
            >
              →
            </Button>
          </div>
        )}
      </div>
    </PageTransition>
  );
}
