import { useState, useCallback, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { PageTransition } from "@/components/layout/page-transition";
import { KlineChart, type KlineOverlay } from "@/components/charts/kline-chart";
import { CopyButton } from "@/components/ui";
import { useKline, useStockProfile } from "@/lib/hooks";
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

  const [profileOpen, setProfileOpen] = useState(false);
  // 联动列表当前项：只在切换股票时滚动到可见——内联 callback ref 会在每次
  // 重渲染（如鼠标划过K线触发 overlay 更新）都执行 scrollIntoView，
  // 用户手动滚列表会被不停拽回（review 确认的交互缺陷）
  const activeNavItemRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    activeNavItemRef.current?.scrollIntoView({ block: "nearest" });
  }, [stockNavIndex]);
  const { data: klineData, isLoading } = useKline(code ?? null, period);
  const { data: profile, isLoading: profileLoading } = useStockProfile(code ?? null);

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

  type TrendValues = {
    type: "trend";
    trend: number;
    dk: number | null;
    kdjK: number | null;
    kdjD: number | null;
    kdjJ: number | null;
  };
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
      return {
        type: "trend",
        trend: src.trendLine,
        dk: src.dkLine ?? null,
        kdjK: src.kdjK ?? null,
        kdjD: src.kdjD ?? null,
        kdjJ: src.kdjJ ?? null,
      };
    }
    if (src?.ma5 != null) {
      return { type: "ma", ma5: src.ma5, ma10: src.ma10 ?? null, ma20: src.ma20 ?? null, ma60: src.ma60 ?? null };
    }
    if (!latestRow) return null;
    if (period === "daily") {
      const t = latestRow[9] as number | null;
      const d = latestRow[10] as number | null;
      return t != null
        ? {
            type: "trend",
            trend: t,
            dk: d,
            kdjK: latestRow[6] as number | null,
            kdjD: latestRow[7] as number | null,
            kdjJ: latestRow[8] as number | null,
          }
        : null;
    }
    if (weeklyLineMode === "trend") {
      const t = latestRow[10] as number | null;
      const d = latestRow[11] as number | null;
      return t != null ? { type: "trend", trend: t, dk: d, kdjK: null, kdjD: null, kdjJ: null } : null;
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
      <div className="h-[calc(100vh-48px)] flex">
        {/* 桌面联动列表：从候选/因子/超级B1列表进来时，左侧保留整份名单，
            点一只切一只（知弈策行"翻牌式复盘"），不用回退页面 */}
        {hasNav && (
          <aside className="hidden lg:flex w-56 shrink-0 flex-col border-r border-border bg-surface">
            <div className="px-3 py-2 border-b border-border/60 text-[11px] text-ink-muted">
              候选名单 · {stockNavList.length}只
            </div>
            <div className="flex-1 overflow-y-auto py-1">
              {stockNavList.map((s, i) => (
                <button
                  key={s.code}
                  ref={i === stockNavIndex ? activeNavItemRef : undefined}
                  onClick={() => {
                    setStockNavIndex(i);
                    navigate(`/stock/${s.code}`, { replace: true });
                  }}
                  className={`w-full px-3 py-2 text-left transition-colors duration-100 ${
                    i === stockNavIndex
                      ? "bg-accent/10 border-l-2 border-accent"
                      : "hover:bg-elevated border-l-2 border-transparent"
                  }`}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className={`text-xs font-medium truncate ${i === stockNavIndex ? "text-accent" : "text-ink"}`}>
                      {s.name || s.code}
                    </span>
                    <span className="ml-auto text-[11px] text-ink-secondary tabular-nums shrink-0">
                      {s.close ? s.close.toFixed(2) : ""}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="font-mono text-[10px] text-ink-muted">{s.code}</span>
                    {s.industry && (
                      <span className="text-[10px] text-ink-muted/70 truncate min-w-0">
                        {s.industry}
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </aside>
        )}

        <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="px-3 sm:px-6 py-2 sm:py-3 border-b border-border bg-surface">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 sm:gap-3 min-w-0">
              <button
                onClick={() => navigate(-1)}
                className="text-sm text-ink-secondary hover:text-ink transition-colors shrink-0"
              >
                ←
              </button>

              <div className="flex items-center gap-1.5 sm:gap-2 min-w-0">
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
                {profileLoading ? (
                  <div className="hidden sm:flex items-center gap-1.5">
                    <span className="inline-block w-12 h-4 rounded bg-elevated animate-pulse" />
                    <span className="inline-block w-10 h-4 rounded bg-elevated animate-pulse" />
                  </div>
                ) : profile?.industry ? (
                  <div className="hidden sm:flex items-center gap-1.5">
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-accent/10 text-accent leading-tight">
                      {profile.industry}
                    </span>
                    {profile.board && (
                      <span className="px-1.5 py-0.5 text-[10px] rounded bg-elevated text-ink-muted leading-tight">
                        {profile.board}
                      </span>
                    )}
                  </div>
                ) : null}
                {hasNav && (
                  <span className="text-[10px] text-ink-muted tabular-nums shrink-0">
                    {stockNavIndex + 1}/{stockNavList.length}
                  </span>
                )}
              </div>

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
            <div className="flex items-center gap-0.5 bg-inset rounded-xl p-0.5">
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
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-xs text-ink-secondary truncate">
                  {stockName}
                </span>
                {profileLoading ? (
                  <span className="inline-block w-10 h-3.5 rounded bg-elevated animate-pulse shrink-0" />
                ) : profile?.industry ? (
                  <span className="px-1 py-px text-[9px] rounded bg-accent/10 text-accent leading-tight shrink-0">
                    {profile.industry}
                  </span>
                ) : null}
              </div>
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

        {/* Company info panel */}
        {profile && (
          <div className="bg-surface border-b border-border">
            <button
              onClick={() => setProfileOpen((v) => !v)}
              className="w-full px-3 py-2 flex items-center gap-1 text-xs text-ink-secondary hover:text-ink transition-colors"
            >
              <span>公司信息</span>
              <motion.span
                animate={{ rotate: profileOpen ? 90 : 0 }}
                transition={{ duration: 0.15 }}
                className="text-[10px]"
              >
                ▸
              </motion.span>
            </button>
            <AnimatePresence initial={false}>
              {profileOpen && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
                  className="overflow-hidden"
                >
                  <div className="px-3 pb-2.5 space-y-1.5">
                    {profile.business && (
                      <p className="text-xs text-ink-secondary leading-relaxed break-all">
                        <span className="text-ink-muted">主营业务：</span>
                        {profile.business}
                      </p>
                    )}
                    {profile.listing_date && (
                      <p className="text-xs text-ink-muted">
                        上市日期：{profile.listing_date}
                      </p>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

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
                      {lineValues.kdjK != null && (
                        <>
                          <span style={{ color: chartColors.kdjK }}>
                            K:{lineValues.kdjK.toFixed(1)}
                          </span>
                          {lineValues.kdjD != null && (
                            <span style={{ color: chartColors.kdjD }}>
                              D:{lineValues.kdjD.toFixed(1)}
                            </span>
                          )}
                          {lineValues.kdjJ != null && (
                            <span style={{ color: chartColors.kdjJ }}>
                              J:{lineValues.kdjJ.toFixed(1)}
                            </span>
                          )}
                        </>
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
              <div className="h-full px-2 sm:px-4">
                <KlineChart
                  data={klineData.data}
                  period={period}
                  weeklyLineMode={weeklyLineMode}
                  signals={period === "daily" ? klineData.signals : undefined}
                  onCrosshairMove={handleCrosshairMove}
                  className="h-full"
                />
              </div>

              {/* 信号点图例：金点 = 系统历史上选出过这只票的日子 */}
              {period === "daily" && (klineData.signals?.length ?? 0) > 0 && (
                <div className="absolute bottom-9 left-3 sm:left-5 z-10 text-[10px] text-ink-muted pointer-events-none">
                  <span className="text-accent">●</span> 系统历史信号{" "}
                  {klineData.signals!.length} 次
                </div>
              )}

              {/* Floating side nav buttons */}
              {hasNav && (
                <>
                  <button
                    onClick={() => goToStock(-1)}
                    disabled={stockNavIndex <= 0}
                    className="absolute left-0 top-1/2 -translate-y-1/2 z-10 w-8 h-16 sm:w-10 sm:h-20 flex items-center justify-center bg-surface/60 backdrop-blur-sm rounded-r-xl border border-l-0 border-border/30 text-ink-muted hover:text-ink hover:bg-surface/80 disabled:opacity-20 disabled:pointer-events-none transition-all active:scale-95"
                  >
                    <svg width="16" height="16" viewBox="0 0 14 14" fill="none">
                      <path d="M8.75 3.5L5.25 7l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                  <button
                    onClick={() => goToStock(1)}
                    disabled={stockNavIndex >= stockNavList.length - 1}
                    className="absolute right-0 top-1/2 -translate-y-1/2 z-10 w-8 h-16 sm:w-10 sm:h-20 flex items-center justify-center bg-surface/60 backdrop-blur-sm rounded-l-xl border border-r-0 border-border/30 text-ink-muted hover:text-ink hover:bg-surface/80 disabled:opacity-20 disabled:pointer-events-none transition-all active:scale-95"
                  >
                    <svg width="16" height="16" viewBox="0 0 14 14" fill="none">
                      <path d="M5.25 3.5L8.75 7l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                </>
              )}

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

        </div>
      </div>
    </PageTransition>
  );
}
