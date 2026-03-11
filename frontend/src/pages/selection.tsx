import { useState, useCallback, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { mutate } from "swr";
import { PageTransition } from "@/components/layout/page-transition";
import { Button, Card, Skeleton, Badge, ProgressBar, CopyButton } from "@/components/ui";
import { useViews } from "@/lib/hooks";
import { api } from "@/lib/api";
import type { ViewData, SignalStock, SelectionResult } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import { CATEGORY_LABELS, CATEGORY_BADGE_VARIANT, duration } from "@/lib/tokens";
import { useToastStore } from "@/lib/toast-store";
import { EmptyState } from "@/components/onboarding";

/* ------------------------------------------------------------------ */
/*  Parameter definitions                                              */
/* ------------------------------------------------------------------ */

interface ParamDef {
  min: number;
  max: number;
  step: number;
  unit?: string;
  label: string;
  display?: string;
  transform?: (v: number) => number;
  inverseTransform?: (v: number) => number;
}

const BASE_PARAMS: Record<string, ParamDef> = {
  N: { min: 1, max: 8, step: 0.1, unit: "x", label: "成交量倍数" },
  M: { min: 5, max: 60, step: 1, unit: "天", label: "回溯天数" },
  CAP: {
    min: 1e8,
    max: 5e10,
    step: 1e8,
    display: "亿",
    label: "市值门槛",
    transform: (v: number) => v / 1e8,
    inverseTransform: (v: number) => v * 1e8,
  },
  J_VAL: { min: -50, max: 60, step: 1, label: "J值上限" },
};

const MA_PARAMS: Record<string, ParamDef> = {
  M1: { min: 5, max: 60, step: 1, label: "MA周期1" },
  M2: { min: 10, max: 120, step: 1, label: "MA周期2" },
  M3: { min: 20, max: 200, step: 1, label: "MA周期3" },
  M4: { min: 30, max: 300, step: 1, label: "MA周期4" },
  duokong_pct: { min: 0.5, max: 8, step: 0.1, unit: "%", label: "靠近多空线" },
  short_pct: { min: 0.5, max: 8, step: 0.1, unit: "%", label: "靠近趋势线" },
};

const ALL_PARAM_KEYS = [...Object.keys(BASE_PARAMS), ...Object.keys(MA_PARAMS)];

function getParamDef(key: string): ParamDef | undefined {
  return BASE_PARAMS[key] ?? MA_PARAMS[key];
}

function formatParamValue(key: string, val: number): string {
  const def = getParamDef(key);
  if (!def) return String(val);
  const displayed = def.transform ? def.transform(val) : val;
  const rounded =
    def.step < 1
      ? Number(displayed.toFixed(1))
      : Math.round(displayed);
  const suffix = def.display ?? def.unit ?? "";
  return `${rounded}${suffix}`;
}

/* ------------------------------------------------------------------ */
/*  Category filter tabs                                               */
/* ------------------------------------------------------------------ */

const CATEGORY_FILTERS = [
  { key: "all", label: "全部" },
  { key: "bowl_center", label: "回落碗中" },
  { key: "near_duokong", label: "靠近多空线" },
  { key: "near_short_trend", label: "靠近趋势线" },
];

/* ------------------------------------------------------------------ */
/*  Signal Card component                                              */
/* ------------------------------------------------------------------ */

const BREAKDOWN_LABELS: Record<string, string> = {
  trend: "趋势",
  kdj: "KDJ",
  volume: "量能",
  shape: "形态",
};

interface SignalCardProps {
  stock: SignalStock;
  index: number;
  onNavigate: (code: string) => void;
}

function SignalCard({ stock, index, onNavigate }: SignalCardProps) {
  const badgeVariant =
    CATEGORY_BADGE_VARIANT[stock.category] ?? "inactive";
  const categoryLabel =
    CATEGORY_LABELS[stock.category] ?? stock.category;
  const capDisplay = (stock.market_cap / 1e8).toFixed(1);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: duration.fast, delay: Math.min(index * 0.03, 0.3) }}
    >
      <Card
        hoverable
        className="p-4"
        onClick={() => onNavigate(stock.code)}
      >
        <div className="flex items-start justify-between mb-3">
          <div>
            <p className="text-sm font-semibold text-ink">
              {stock.name}
            </p>
            <p className="text-xs text-ink-muted mt-0.5 flex items-center gap-1">
              {stock.code}
              <CopyButton text={stock.code} />
            </p>
          </div>
          <Badge variant={badgeVariant}>{categoryLabel}</Badge>
        </div>

        <div className="grid grid-cols-3 gap-2 text-xs mb-3">
          <div>
            <span className="text-ink-muted">价格</span>
            <p className="text-ink font-medium mt-0.5">
              {stock.close.toFixed(2)}
            </p>
          </div>
          <div>
            <span className="text-ink-muted">J值</span>
            <p className="text-ink font-medium mt-0.5">
              {stock.J.toFixed(1)}
            </p>
          </div>
          <div>
            <span className="text-ink-muted">市值</span>
            <p className="text-ink font-medium mt-0.5">{capDisplay}亿</p>
          </div>
        </div>

        {stock.similarity_score !== null && stock.match_breakdown && (
          <div className="border-t border-border pt-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-ink-muted">B1匹配度</span>
              <span className="text-xs font-semibold text-accent">
                {(stock.similarity_score * 100).toFixed(0)}%
              </span>
            </div>
            <div className="space-y-1.5">
              {Object.entries(BREAKDOWN_LABELS).map(([k, label]) => {
                const val = stock.match_breakdown?.[k] ?? 0;
                return (
                  <div key={k} className="flex items-center gap-2">
                    <span className="text-[10px] text-ink-muted w-7 shrink-0">
                      {label}
                    </span>
                    <ProgressBar
                      value={val * 100}
                      className="flex-1"
                      colorByValue
                    />
                    <span className="text-[10px] text-ink-muted w-7 text-right">
                      {(val * 100).toFixed(0)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </Card>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Param slider row                                                   */
/* ------------------------------------------------------------------ */

interface ParamSliderProps {
  paramKey: string;
  def: ParamDef;
  value: number;
  onChange: (key: string, val: number) => void;
}

function ParamSlider({ paramKey, def, value, onChange }: ParamSliderProps) {
  const displayValue = def.transform ? def.transform(value) : value;
  const displayMin = def.transform ? def.transform(def.min) : def.min;
  const displayMax = def.transform ? def.transform(def.max) : def.max;
  const displayStep = def.transform
    ? def.transform(def.min + def.step) - def.transform(def.min)
    : def.step;

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawDisplay = parseFloat(e.target.value);
    const rawVal = def.inverseTransform
      ? def.inverseTransform(rawDisplay)
      : rawDisplay;
    onChange(paramKey, rawVal);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const rawDisplay = parseFloat(e.target.value);
    if (Number.isNaN(rawDisplay)) return;
    const clamped = Math.max(displayMin, Math.min(displayMax, rawDisplay));
    const rawVal = def.inverseTransform
      ? def.inverseTransform(clamped)
      : clamped;
    onChange(paramKey, rawVal);
  };

  const suffix = def.display ?? def.unit ?? "";

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-ink-secondary w-24 shrink-0">
        {def.label}
      </span>
      <input
        type="range"
        min={displayMin}
        max={displayMax}
        step={displayStep}
        value={displayValue}
        onChange={handleSliderChange}
        className="flex-1 h-1.5 accent-[var(--color-accent)] cursor-pointer"
      />
      <div className="relative w-20 shrink-0">
        <input
          type="number"
          min={displayMin}
          max={displayMax}
          step={displayStep}
          value={
            displayStep < 1
              ? Number(displayValue.toFixed(1))
              : Math.round(displayValue)
          }
          onChange={handleInputChange}
          className="w-full h-8 px-2 bg-inset rounded-lg text-xs text-ink border border-border text-center focus:border-border-focus focus:ring-2 focus:ring-accent/10"
        />
        {suffix && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-ink-muted pointer-events-none">
            {suffix}
          </span>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Progress Ring SVG                                                  */
/* ------------------------------------------------------------------ */

function ProgressRing({ pct }: { pct: number }) {
  const r = 36;
  const c = 2 * Math.PI * r;
  const offset = c - (pct / 100) * c;

  return (
    <svg width="96" height="96" className="block mx-auto">
      <circle
        cx="48"
        cy="48"
        r={r}
        fill="none"
        stroke="var(--color-border)"
        strokeWidth="6"
      />
      <motion.circle
        cx="48"
        cy="48"
        r={r}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={c}
        animate={{ strokeDashoffset: offset }}
        transition={{ duration: duration.normal }}
        transform="rotate(-90 48 48)"
      />
      <text
        x="48"
        y="48"
        textAnchor="middle"
        dominantBaseline="central"
        className="text-sm font-semibold"
        fill="var(--color-ink)"
      >
        {Math.round(pct)}%
      </text>
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Create View Modal (inline form)                                    */
/* ------------------------------------------------------------------ */

interface CreateViewFormProps {
  views: ViewData[];
  onCreated: (v: ViewData) => void;
  onCancel: () => void;
}

function CreateViewForm({ views, onCreated, onCancel }: CreateViewFormProps) {
  const [name, setName] = useState("");
  const [sourceId, setSourceId] = useState<number | "">("");
  const [loading, setLoading] = useState(false);
  const toast = useToastStore((s) => s.add);

  const handleCreate = async () => {
    const trimmed = name.trim();
    if (!trimmed) {
      toast("请输入视图名称", "error");
      return;
    }
    setLoading(true);
    try {
      const body: { name: string; source_id?: number } = { name: trimmed };
      if (sourceId !== "") body.source_id = sourceId;
      const res = await api.createView(body);
      await mutate("views");
      onCreated(res.data);
      toast("视图已创建", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "创建失败",
        "error",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      className="overflow-hidden"
    >
      <Card className="p-4 border border-accent/30">
        <p className="text-sm font-medium text-ink mb-3">新建视图</p>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-ink-secondary">视图名称</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如: 低J值放量"
              className="w-full mt-1 h-9 px-3 bg-inset rounded-lg text-sm text-ink border border-border focus:border-border-focus focus:ring-2 focus:ring-accent/10 placeholder:text-ink-muted"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
              }}
            />
          </div>
          {views.length > 0 && (
            <div>
              <label className="text-xs text-ink-secondary">
                复制参数自（可选）
              </label>
              <select
                value={sourceId}
                onChange={(e) =>
                  setSourceId(
                    e.target.value === "" ? "" : Number(e.target.value),
                  )
                }
                className="w-full mt-1 h-9 px-3 bg-inset rounded-lg text-sm text-ink border border-border focus:border-border-focus"
              >
                <option value="">使用默认参数</option>
                {views.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex gap-2 justify-end">
            <Button
              variant="ghost"
              size="sm"
              onClick={onCancel}
              disabled={loading}
            >
              取消
            </Button>
            <Button size="sm" onClick={handleCreate} loading={loading}>
              创建
            </Button>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main page component                                                */
/* ------------------------------------------------------------------ */

export function Component() {
  const navigate = useNavigate();
  const { data: views, isLoading: viewsLoading } = useViews();
  const toast = useToastStore((s) => s.add);
  const { setStockNav, setSelectionResults } = useAppStore();

  const [selectedViewId, setSelectedViewId] = useState<number | null>(null);
  const [editParams, setEditParams] = useState<Record<string, number>>({});
  const [saving, setSaving] = useState(false);
  const [showCreate, setShowCreate] = useState(false);

  const [running, setRunning] = useState(false);
  const [runProgress, setRunProgress] = useState(0);
  const [runPhase, setRunPhase] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [results, setResults] = useState<SelectionResult | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("all");

  const selectedView = views?.find((v) => v.id === selectedViewId) ?? null;

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const handleSelectView = useCallback(
    (view: ViewData) => {
      if (selectedViewId === view.id) {
        setSelectedViewId(null);
        setEditParams({});
        setResults(null);
        return;
      }
      setSelectedViewId(view.id);
      const merged: Record<string, number> = {};
      for (const k of ALL_PARAM_KEYS) {
        merged[k] = view.params[k] ?? 0;
      }
      setEditParams(merged);
      setResults(null);
      setCategoryFilter("all");
    },
    [selectedViewId],
  );

  const handleParamChange = useCallback((key: string, val: number) => {
    setEditParams((prev) => ({ ...prev, [key]: val }));
  }, []);

  const handleSave = useCallback(async () => {
    if (!selectedViewId) return;
    setSaving(true);
    try {
      await api.updateView(selectedViewId, { params: editParams });
      await mutate("views");
      toast("参数已保存", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "保存失败",
        "error",
      );
    } finally {
      setSaving(false);
    }
  }, [selectedViewId, editParams, toast]);

  const handleRun = useCallback(async () => {
    if (!selectedViewId || running) return;
    setRunning(true);
    setRunProgress(0);
    setRunPhase("启动中...");
    setResults(null);

    try {
      await api.updateView(selectedViewId, { params: editParams });
      await mutate("views");

      const { task_id } = await api.runView(selectedViewId);

      pollRef.current = setInterval(async () => {
        try {
          const status = await api.getRunStatus(selectedViewId, task_id);
          const pct =
            status.total > 0
              ? Math.round((status.progress / status.total) * 100)
              : 0;
          setRunProgress(pct);
          setRunPhase(status.phase || "运行中...");

          if (status.status === "completed" && status.data) {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setRunning(false);
            setRunProgress(100);
            setResults(status.data);
            setSelectionResults(status.data);
            toast(
              `选股完成，共 ${status.data.total} 只`,
              "success",
            );
          } else if (status.status === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setRunning(false);
            toast(status.error ?? "运行失败", "error");
          }
        } catch {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setRunning(false);
          toast("状态查询失败", "error");
        }
      }, 300);
    } catch (err) {
      setRunning(false);
      toast(
        err instanceof Error ? err.message : "启动失败",
        "error",
      );
    }
  }, [selectedViewId, editParams, running, toast, setSelectionResults]);

  const handleNavigateStock = useCallback(
    (code: string) => {
      if (results) {
        const filtered =
          categoryFilter === "all"
            ? results.stocks
            : results.stocks.filter((s) => s.category === categoryFilter);
        const idx = filtered.findIndex((s) => s.code === code);
        setStockNav(filtered, idx >= 0 ? idx : 0);
      }
      navigate(`/stock/${code}`);
    },
    [results, categoryFilter, navigate, setStockNav],
  );

  const handleViewCreated = useCallback((v: ViewData) => {
    setShowCreate(false);
    setSelectedViewId(v.id);
    const merged: Record<string, number> = {};
    for (const k of ALL_PARAM_KEYS) {
      merged[k] = v.params[k] ?? 0;
    }
    setEditParams(merged);
  }, []);

  const filteredStocks =
    results && categoryFilter === "all"
      ? results.stocks
      : results?.stocks.filter((s) => s.category === categoryFilter) ?? [];

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */

  return (
    <PageTransition>
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-4 sm:py-8 space-y-6 sm:space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-ink">智能选股</h1>
            <p className="text-ink-secondary text-xs sm:text-sm mt-1">
              管理选股视图、调整参数并运行策略
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowCreate((p) => !p)}
          >
            {showCreate ? "取消" : "新建视图"}
          </Button>
        </div>

        {/* Create form */}
        <AnimatePresence>
          {showCreate && (
            <CreateViewForm
              views={views ?? []}
              onCreated={handleViewCreated}
              onCancel={() => setShowCreate(false)}
            />
          )}
        </AnimatePresence>

        {/* View cards grid */}
        <section>
          <h2 className="text-sm font-medium text-ink-secondary mb-3">
            选股视图
          </h2>
          {viewsLoading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-28 rounded-2xl" />
              ))}
            </div>
          ) : !views?.length ? (
            <EmptyState
              icon={
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                  <rect x="3" y="3" width="18" height="18" rx="3" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M12 8v8M8 12h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              }
              title="还没有选股视图"
              description="创建你的第一个视图，设定策略参数并运行选股"
              ctaLabel="新建视图"
              onCta={() => setShowCreate(true)}
            />
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {views.map((view) => {
                const isSelected = view.id === selectedViewId;
                const paramSummary = Object.entries(view.params)
                  .filter(([k]) => ALL_PARAM_KEYS.includes(k))
                  .slice(0, 4)
                  .map(([k, v]) => `${k}=${formatParamValue(k, v)}`)
                  .join("  ");

                return (
                  <motion.div
                    key={view.id}
                    layout
                    whileHover={{ scale: 1.01 }}
                    whileTap={{ scale: 0.98 }}
                  >
                    <Card
                      className={`p-4 cursor-pointer transition-all duration-150 border-2 ${
                        isSelected
                          ? "border-accent shadow-lg"
                          : "border-transparent"
                      }`}
                      onClick={() => handleSelectView(view)}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <p className="text-sm font-semibold text-ink truncate">
                          {view.name}
                        </p>
                        <Badge
                          variant={view.is_active ? "active" : "inactive"}
                        >
                          {view.is_active ? "启用" : "停用"}
                        </Badge>
                      </div>
                      <p className="text-xs text-ink-muted font-mono truncate">
                        {paramSummary || "默认参数"}
                      </p>
                      <p className="text-[10px] text-ink-muted mt-2">
                        更新于{" "}
                        {new Date(view.updated_at).toLocaleDateString("zh-CN")}
                      </p>
                    </Card>
                  </motion.div>
                );
              })}
            </div>
          )}
        </section>

        {/* Params editor */}
        <AnimatePresence>
          {selectedView && (
            <motion.section
              key="params-editor"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 16 }}
              transition={{ duration: duration.normal }}
              className="space-y-6"
            >
              <Card className="p-6">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-base font-semibold text-ink">
                    参数配置 - {selectedView.name}
                  </h2>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={handleSave}
                      loading={saving}
                      disabled={running}
                    >
                      保存参数
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleRun}
                      loading={running}
                      disabled={running}
                    >
                      运行选股
                    </Button>
                  </div>
                </div>

                {/* Section: 基础参数 */}
                <div className="mb-6">
                  <h3 className="text-xs font-medium text-ink-muted uppercase tracking-wide mb-3">
                    基础参数
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
                    {Object.entries(BASE_PARAMS).map(([key, def]) => (
                      <ParamSlider
                        key={key}
                        paramKey={key}
                        def={def}
                        value={editParams[key] ?? def.min}
                        onChange={handleParamChange}
                      />
                    ))}
                  </div>
                </div>

                {/* Section: 均线与位置 */}
                <div>
                  <h3 className="text-xs font-medium text-ink-muted uppercase tracking-wide mb-3">
                    均线与位置
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
                    {Object.entries(MA_PARAMS).map(([key, def]) => (
                      <ParamSlider
                        key={key}
                        paramKey={key}
                        def={def}
                        value={editParams[key] ?? def.min}
                        onChange={handleParamChange}
                      />
                    ))}
                  </div>
                </div>
              </Card>

              {/* Running progress */}
              <AnimatePresence>
                {running && (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                  >
                    <Card className="p-6 flex flex-col items-center gap-4">
                      <ProgressRing pct={runProgress} />
                      <p className="text-sm text-ink-secondary">
                        {runPhase}
                      </p>
                    </Card>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Results section */}
              <AnimatePresence>
                {results && !running && (
                  <motion.section
                    key="results"
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 16 }}
                    transition={{ duration: duration.normal }}
                    className="space-y-4"
                  >
                    {/* Summary + filters */}
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                      <div>
                        <h2 className="text-base font-semibold text-ink">
                          选股结果
                        </h2>
                        <p className="text-xs text-ink-muted mt-0.5">
                          {results.run_date} | {results.view_name} |
                          共 {results.total} 只
                        </p>
                      </div>
                      <div className="flex gap-1.5 bg-inset rounded-xl p-1">
                        {CATEGORY_FILTERS.map((f) => {
                          const count =
                            f.key === "all"
                              ? results.total
                              : results.category_count[f.key] ?? 0;
                          const isActive = categoryFilter === f.key;
                          return (
                            <button
                              key={f.key}
                              onClick={() => setCategoryFilter(f.key)}
                              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 ${
                                isActive
                                  ? "bg-surface text-ink shadow-sm"
                                  : "text-ink-muted hover:text-ink"
                              }`}
                            >
                              {f.label}
                              <span className="ml-1 opacity-60">
                                {count}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    {/* Signal cards grid */}
                    {filteredStocks.length === 0 ? (
                      <Card className="p-8 text-center">
                        <p className="text-sm text-ink-muted">
                          该分类下没有信号
                        </p>
                      </Card>
                    ) : (
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                        {filteredStocks.map((stock, i) => (
                          <SignalCard
                            key={stock.code}
                            stock={stock}
                            index={i}
                            onNavigate={handleNavigateStock}
                          />
                        ))}
                      </div>
                    )}
                  </motion.section>
                )}
              </AnimatePresence>
            </motion.section>
          )}
        </AnimatePresence>
      </div>
    </PageTransition>
  );
}
