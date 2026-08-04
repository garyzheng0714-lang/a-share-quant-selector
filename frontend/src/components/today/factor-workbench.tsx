import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown, ChevronLeft, ChevronRight, ArrowLeft } from "lucide-react";
import { Skeleton, LoadError } from "@/components/ui";
import { useFactors, useFactorScan } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { FactorHit, FactorMeta, FactorsResponse, SignalStock } from "@/lib/api";

/**
 * 策略因子选股工作台，两级结构（用户反馈"不够直观"后重做）：
 * 1. 概览（默认）：28个因子按组摊开，每张卡直接亮出「当日命中数 + 大白话说明」，
 *    今天哪个公式有货一眼扫完，不用点28次。
 * 2. 详情：点卡片进入——日期导航（回看历史任意交易日）+ 结果按行业分组。
 *
 * 点个股走已有 stockNavList 机制：个股页左侧联动列表，看完一只切一只。
 */

/** FactorHit → SignalStock：联动导航只消费 code/name/close/industry，其余字段填缺省 */
function toNavStocks(hits: FactorHit[]): SignalStock[] {
  return hits.map((h) => ({
    code: h.code,
    name: h.name,
    strategy: "factor",
    category: h.industry || "",
    close: h.close,
    J: h.J ?? 0,
    volume_ratio: 0,
    market_cap: (h.cap_yi ?? 0) * 1e8,
    short_term_trend: 0,
    bull_bear_line: 0,
    reasons: [],
    similarity_score: null,
    matched_case: null,
    match_breakdown: null,
    industry: h.industry,
  }));
}

function pctColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-ink-muted";
  return v > 0 ? "text-bull" : v < 0 ? "text-bear" : "text-ink-muted";
}

/** 体检结论徽章：按持有周期分别评——短线公式用20天胜率评价本身就不公平 */
const GRADE_META = {
  short_robust: {
    label: "短线真金",
    cls: "bg-bull/15 text-bull",
    hint: "持有1天和5天，两段互不重叠的历史里都跑赢大盘",
  },
  short_ok: {
    label: "短线可用",
    cls: "bg-bull/10 text-bull/80",
    hint: "持有5天两段都跑赢，但超额很薄",
  },
  long_only: {
    label: "只适合长线",
    cls: "bg-elevated text-ink-secondary",
    hint: "要持有10天以上才有效，短线用它没意义",
  },
  unstable: {
    label: "只在一段有效",
    cls: "bg-elevated text-ink-muted",
    hint: "换一段行情就失效，大概率是运气",
  },
  negative: {
    label: "任何周期都不稳",
    cls: "bg-bear/15 text-bear",
    hint: "历史上不赚钱，建议无视",
  },
} as const;

/** 用户偏好短线（练盘感）→ 卡片默认展示持有5天的胜率 */
const DEFAULT_PERIOD = "ret_5";
const PERIODS = [
  { key: "ret_1", label: "持有1天" },
  { key: "ret_5", label: "持有5天" },
  { key: "ret_10", label: "持有10天" },
  { key: "ret_20", label: "持有20天" },
];

/** 概览卡：今天有没有货（命中数）+ 这个公式在等什么（白话）+ 它到底靠不靠谱（体检） */
function FactorCard({ f, onClick }: { f: FactorMeta; onClick: () => void }) {
  const n = f.today_hits;
  const hasHits = typeof n === "number" && n > 0;
  const g = f.track ? GRADE_META[f.track.grade] : null;
  const p5 = f.track?.periods?.[DEFAULT_PERIOD];
  const dim = !hasHits || f.track?.grade === "negative";
  return (
    <button
      onClick={onClick}
      className={`card-modern px-3.5 py-3 text-left transition-all duration-150 hover:ring-1 hover:ring-border-hover active:scale-[0.99] min-w-0 ${
        dim ? "opacity-55" : ""
      }`}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-sm font-medium text-ink truncate">{f.name}</span>
        <span
          className={`ml-auto shrink-0 px-2 py-0.5 rounded-full text-xs font-semibold tabular-nums ${
            hasHits
              ? "bg-accent/15 text-accent"
              : "bg-elevated text-ink-muted font-normal"
          }`}
        >
          {n === null || n === undefined ? "未算" : n === 0 ? "无" : `${n}只`}
        </span>
      </div>
      <p className="mt-1.5 text-[11px] text-ink-muted leading-relaxed line-clamp-2">
        {f.plain || f.desc}
      </p>
      {g && p5 && (
        <div className="mt-2 flex items-center gap-1.5 min-w-0" title={g.hint}>
          <span className={`px-1.5 py-0.5 rounded text-[10px] whitespace-nowrap ${g.cls}`}>
            {g.label}
          </span>
          <span className="text-[10px] text-ink-muted tabular-nums truncate">
            持有5天胜率 {p5.in.win}% / {p5.oos.win}%
          </span>
        </div>
      )}
    </button>
  );
}

export function FactorWorkbench() {
  const { data: meta, isLoading: metaLoading, error: metaError, mutate: retryMeta } = useFactors();
  const [factorKey, setFactorKey] = useState<string | null>(null);

  if (metaLoading) {
    return (
      <div className="grid grid-cols-2 gap-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-20 w-full rounded-2xl" />
        ))}
      </div>
    );
  }
  if (metaError || !meta) {
    return <LoadError label="策略因子清单加载失败" onRetry={() => retryMeta()} />;
  }

  const activeFactor = meta.factors.find((f) => f.key === factorKey) ?? null;
  if (activeFactor) {
    return (
      <FactorDetail
        factor={activeFactor}
        recentDates={meta.recent_dates}
        windows={meta.track_windows}
        onBack={() => setFactorKey(null)}
      />
    );
  }

  // 排序：短线真金 > 短线可用 > 其他 > 任何周期都不稳；同级再按今天有没有货。
  // 界面必须先回答"这公式靠不靠谱"，再回答"今天有几只"——顺序反了就是用命中数
  // 诱导用户去看一个历史上不赚钱的公式。
  const GRADE_ORDER: Record<string, number> = {
    short_robust: 4, short_ok: 3, unstable: 2, long_only: 1, negative: 0,
  };
  const gradeRank = (f: FactorMeta) =>
    f.track ? GRADE_ORDER[f.track.grade] ?? 2 : 2;
  const hitRank = (f: FactorMeta) =>
    f.today_hits === null || f.today_hits === undefined ? -1 : f.today_hits;
  const gold = meta.factors.filter((f) => f.track?.grade === "short_robust");
  const usable = meta.factors.filter((f) =>
    ["short_robust", "short_ok"].includes(f.track?.grade ?? ""),
  );
  const negative = meta.factors.filter((f) => f.track?.grade === "negative");

  return (
    <section data-testid="factor-workbench">
      <div className="mb-4 grid grid-cols-3 gap-2">
        <div className="rounded-xl bg-surface px-3 py-2.5">
          <div className="text-lg font-semibold text-ink tabular-nums">{meta.factors.length}</div>
          <div className="text-[10px] text-ink-muted">全部策略</div>
        </div>
        <div className="rounded-xl bg-surface px-3 py-2.5">
          <div className="text-lg font-semibold text-bull tabular-nums">{usable.length}</div>
          <div className="text-[10px] text-ink-muted">短线可用</div>
        </div>
        <div className="rounded-xl bg-surface px-3 py-2.5">
          <div className="text-lg font-semibold text-bear tabular-nums">{negative.length}</div>
          <div className="text-[10px] text-ink-muted">历史不稳</div>
        </div>
      </div>

      <p className="text-[11px] text-ink-muted leading-relaxed mb-3">
        {meta.trade_date ? `${meta.trade_date} / ` : ""}先看历史可靠性，再看今日命中数。
      </p>

      {gold.length > 0 && (
        <div className="card-modern px-3.5 py-3 mb-4">
          <div className="text-xs font-semibold text-ink mb-1">
            优先研究：{gold.map((f) => f.name).join("、")}
          </div>
          <p className="text-[11px] text-ink-muted leading-relaxed">
            这些策略在持有1天和5天时，两段独立历史都跑赢大盘。灰色策略仅供复盘，不参与今日决策。
          </p>
        </div>
      )}

      {meta.groups.map((g) => {
        const list = meta.factors
          .filter((f) => f.group === g)
          .sort((a, b) => gradeRank(b) - gradeRank(a) || hitRank(b) - hitRank(a));
        if (!list.length) return null;
        return (
          <div key={g} className="mb-4">
            <h3 className="text-xs font-semibold text-ink-secondary mb-2">{g}</h3>
            <div className="grid grid-cols-2 lg:grid-cols-3 gap-2">
              {list.map((f) => (
                <FactorCard key={f.key} f={f} onClick={() => setFactorKey(f.key)} />
              ))}
            </div>
          </div>
        );
      })}
    </section>
  );
}

function FactorDetail({
  factor,
  recentDates,
  windows,
  onBack,
}: {
  factor: FactorMeta;
  recentDates: string[];
  windows?: FactorsResponse["track_windows"];
  onBack: () => void;
}) {
  // undefined = 最新交易日；点◀▶后为具体日期
  const [date, setDate] = useState<string | undefined>(undefined);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const { data, isLoading, error, mutate } = useFactorScan(factor.key, date);
  const navigate = useNavigate();
  const setStockNav = useAppStore((s) => s.setStockNav);

  const shownDate = data?.trade_date ?? date ?? recentDates[0] ?? "";
  const dateIdx = recentDates.indexOf(shownDate);
  // date=undefined 本身就是"最新"——跨日窗口内旧数据的 trade_date 可能落后于
  // recent_dates[0]，此时若按 dateIdx 判定会亮起一个点了没反应的"下一日"按钮
  const canNewer = date !== undefined && dateIdx > 0;
  const canOlder = dateIdx >= 0 && dateIdx < recentDates.length - 1;

  // 宽松因子（如波段）全市场可命中上千只，渲染全量会卡死页面；
  // 后端按 J 升序排（越超卖越靠前），截前 300 只保留的是最有参考价值的部分
  const MAX_SHOW = 300;
  const allHits = useMemo(() => (data?.available ? data.hits ?? [] : []), [data]);
  const hits = useMemo(() => allHits.slice(0, MAX_SHOW), [allHits]);
  const byIndustry = useMemo(() => {
    const map = new Map<string, FactorHit[]>();
    for (const h of hits) {
      const key = h.industry || "未分类";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(h);
    }
    return [...map.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [hits]);

  const openStock = (h: FactorHit) => {
    // 行业分组展示顺序 = 导航顺序，翻下一只时跟着分组走
    const flat = byIndustry.flatMap(([, list]) => list);
    setStockNav(toNavStocks(flat), flat.findIndex((x) => x.code === h.code));
    navigate(`/stock/${h.code}`);
  };

  return (
    <section data-testid="factor-detail">
      {/* 返回 + 因子名 + 白话说明 */}
      <div className="flex items-start gap-2 mb-3">
        <button
          onClick={onBack}
          aria-label="返回全部因子"
          className="mt-0.5 p-1.5 rounded-full text-ink-muted hover:text-ink hover:bg-elevated transition-colors shrink-0"
        >
          <ArrowLeft size={15} />
        </button>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink">{factor.name}</h3>
          <p className="text-[11px] text-ink-muted leading-relaxed mt-0.5">
            {factor.plain || factor.desc}
          </p>
        </div>
      </div>

      {/* 这个公式的历史真相：4个持有周期 × 两段独立时间，买之前先看它 */}
      {factor.track && windows && (
        <div className="card-modern px-3.5 py-3 mb-3">
          <div className="flex items-center gap-1.5 mb-2 flex-wrap">
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] ${GRADE_META[factor.track.grade].cls}`}
            >
              {GRADE_META[factor.track.grade].label}
            </span>
            <span className="text-[10px] text-ink-muted">
              {GRADE_META[factor.track.grade].hint}
            </span>
          </div>

          <div className="overflow-x-auto scrollbar-none -mx-1 px-1">
            <table className="w-full text-[11px] tabular-nums">
              <thead>
                <tr className="text-ink-muted">
                  <th className="text-left font-normal pb-1 pr-2">持有</th>
                  <th className="text-right font-normal pb-1 px-2 whitespace-nowrap">
                    {windows.in.label.slice(5)}
                  </th>
                  <th className="text-right font-normal pb-1 px-2 whitespace-nowrap">
                    {windows.oos.label.slice(5)}
                  </th>
                  <th className="text-right font-normal pb-1 pl-2 whitespace-nowrap">结论</th>
                </tr>
              </thead>
              <tbody>
                {PERIODS.map((p) => {
                  const t = factor.track!.periods?.[p.key];
                  if (!t) return null;
                  const cell = (w: typeof t.in) => (
                    <span className="whitespace-nowrap">
                      <span className="text-ink font-medium">{w.win}%</span>
                      <span className={w.excess > 0 ? "text-bull" : "text-bear"}>
                        {" "}
                        {w.excess > 0 ? "+" : ""}
                        {w.excess}%
                      </span>
                    </span>
                  );
                  return (
                    <tr key={p.key} className="border-t border-border/30">
                      <td className="py-1 pr-2 text-ink-secondary whitespace-nowrap">
                        {p.label}
                      </td>
                      <td className="py-1 px-2 text-right">{cell(t.in)}</td>
                      <td className="py-1 px-2 text-right">{cell(t.oos)}</td>
                      <td className="py-1 pl-2 text-right whitespace-nowrap">
                        {t.robust ? (
                          <span className="text-bull">✓ 两段都赢</span>
                        ) : (
                          <span className="text-ink-muted">-</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <p className="text-[10px] text-ink-muted mt-2 leading-relaxed">
            胜率 + 超额（相对同期全市场信号基准）。信号次日开盘买入、持有N天收盘卖出的真实结果。
            {factor.track.dd !== null &&
              ` 期间平均最大浮亏 ${factor.track.dd}%（止损参考）。`}
          </p>
        </div>
      )}

      {/* 日期导航 + 结果统计（窄屏允许换行，绝不横向溢出） */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-3">
        <div className="flex items-center gap-0.5 bg-surface rounded-full px-1 py-0.5">
          <button
            onClick={() => canOlder && setDate(recentDates[dateIdx + 1])}
            disabled={!canOlder}
            aria-label="上一交易日"
            className="p-1 rounded-full text-ink-muted enabled:hover:text-ink enabled:hover:bg-elevated disabled:opacity-30 transition-colors"
          >
            <ChevronLeft size={14} />
          </button>
          <span className="text-xs text-ink-secondary tabular-nums px-1">
            {shownDate || "…"}
          </span>
          <button
            onClick={() => canNewer && setDate(dateIdx === 1 ? undefined : recentDates[dateIdx - 1])}
            disabled={!canNewer}
            aria-label="下一交易日"
            className="p-1 rounded-full text-ink-muted enabled:hover:text-ink enabled:hover:bg-elevated disabled:opacity-30 transition-colors"
          >
            <ChevronRight size={14} />
          </button>
        </div>
        {data?.available && (
          <span className="text-[11px] text-ink-muted">
            命中 {allHits.length} 只 / 扫描 {data.total_scanned}
          </span>
        )}
      </div>

      {/* 结果区 */}
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-14 w-full rounded-xl" />
          <Skeleton className="h-14 w-full rounded-xl" />
          <p className="text-[11px] text-ink-muted leading-relaxed">
            正在计算。该日期首次计算需要全市场扫描，约 1-3 分钟，完成后可直接打开。
          </p>
        </div>
      ) : error ? (
        <LoadError label="选股结果加载失败" onRetry={() => mutate()} />
      ) : !data?.available ? (
        <p className="text-xs text-ink-muted leading-relaxed py-2">
          {data?.reason ?? "数据准备中"}
        </p>
      ) : hits.length === 0 ? (
        <p className="text-xs text-ink-muted leading-relaxed py-2">
          {shownDate} 全市场无「{factor.name}」命中。选股条件较严格，空结果是正常现象。
        </p>
      ) : (
        <div className="space-y-2">
          {allHits.length > MAX_SHOW && (
            <p className="text-[11px] text-ink-muted leading-relaxed px-1">
              该因子当日命中 {allHits.length} 只，信号偏宽，参考价值有限；
              下面只展示 J 值最低（最超卖）的 {MAX_SHOW} 只。
            </p>
          )}
          {byIndustry.map(([industry, list]) => {
            const isCollapsed = collapsed.has(industry);
            return (
              <div key={industry} className="card-modern px-1 py-1">
                <button
                  onClick={() => {
                    const next = new Set(collapsed);
                    if (isCollapsed) next.delete(industry);
                    else next.add(industry);
                    setCollapsed(next);
                  }}
                  className="w-full flex items-center gap-1.5 px-3 py-2 text-left"
                >
                  <ChevronDown
                    size={13}
                    className={`text-ink-muted transition-transform duration-150 ${isCollapsed ? "-rotate-90" : ""}`}
                  />
                  <span className="text-xs font-semibold text-ink">{industry}</span>
                  <span className="text-[11px] text-ink-muted num">{list.length}只</span>
                </button>
                {!isCollapsed && (
                  <div className="divide-y divide-border/40">
                    {list.map((h) => (
                      <button
                        key={h.code}
                        onClick={() => openStock(h)}
                        className="w-full px-3 sm:px-4 py-2.5 hover:bg-elevated active:bg-inset rounded-xl transition-colors duration-100 text-left"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="text-sm font-medium text-ink truncate">
                            {h.name || h.code}
                          </span>
                          <span className="font-mono text-xs text-ink-muted shrink-0">
                            {h.code}
                          </span>
                          <span className={`ml-auto text-sm font-medium tabular-nums shrink-0 ${pctColor(h.pct_change)}`}>
                            {h.pct_change !== null && h.pct_change !== undefined
                              ? `${h.pct_change > 0 ? "+" : ""}${h.pct_change.toFixed(2)}%`
                              : "-"}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 mt-1 text-xs text-ink-muted tabular-nums whitespace-nowrap min-w-0">
                          <span className="text-ink-secondary font-medium shrink-0">
                            {h.close.toFixed(2)}
                          </span>
                          {h.J !== null && <span className="shrink-0">J {h.J.toFixed(1)}</span>}
                          {h.RSI !== null && <span className="shrink-0">RSI {h.RSI.toFixed(1)}</span>}
                          {h.cap_yi !== null && h.cap_yi !== undefined && (
                            <span className="shrink-0">{h.cap_yi.toFixed(0)}亿</span>
                          )}
                          {h.sector && (
                            <span
                              className="shrink-0 rounded-full bg-surface px-1.5 py-0.5 text-[10px] text-ink-secondary"
                              title={`板块热度 ${h.sector.score}（第 ${h.sector.rank}/${h.sector.total} 名）`}
                            >
                              板块 {h.sector.score.toFixed(0)}
                              <span className="text-ink-muted"> · {h.sector.rank}/{h.sector.total}</span>
                              {h.sector.delta3 !== 0 && (
                                <span className={h.sector.delta3 > 0 ? "text-bull" : "text-bear"}>
                                  {h.sector.delta3 > 0 ? ` +${h.sector.delta3.toFixed(0)}` : ` ${h.sector.delta3.toFixed(0)}`}
                                </span>
                              )}
                            </span>
                          )}
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
