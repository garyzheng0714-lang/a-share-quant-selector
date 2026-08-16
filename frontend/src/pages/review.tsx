import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { Button, LoadError, Input, Skeleton } from "@/components/ui";
import type {
  CloudStairHistoryRow,
  CloudStairHorizonStat,
  HistoryHorizon,
  HistoryResult,
} from "@/lib/api";
import { groupHistoryRows, visibleWindow } from "@/lib/history-feed";
import { useCloudStairHistoryFeed, useCloudStairHistorySummary } from "@/lib/hooks";

function pct(value?: number | null, signed = true) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${signed && value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function rate(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function tone(value?: number | null) {
  if (value == null || value === 0) return "";
  return value > 0 ? "q-up" : "q-down";
}

function settledLabel(row: CloudStairHistoryRow, key: "t1" | "t5" | "t20") {
  const settled = row[`${key}_settled`];
  const value = row[`${key}_net_return_pct`];
  if (!settled) return "未走完";
  return pct(value);
}

function Kpi({
  label,
  value,
  hint,
  valueClass,
}: {
  label: string;
  value: string;
  hint: string;
  valueClass?: string;
}) {
  return (
    <div className="q-history-kpi">
      <span>{label}</span>
      <strong className={valueClass}>{value}</strong>
      <em>{hint}</em>
    </div>
  );
}

function FieldOptions<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="q-history-field">
      <span>{label}</span>
      <div className="q-history-field-options" role="group" aria-label={label}>
        {options.map((option) => (
          <Button
            key={option.value}
            type="button"
            size="sm"
            variant={value === option.value ? "primary" : "secondary"}
            label={option.label}
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
          />
        ))}
      </div>
    </div>
  );
}

function HistoryList({
  query,
  date,
  horizon,
  result,
}: {
  query: string;
  date: string;
  horizon: HistoryHorizon;
  result: HistoryResult;
}) {
  const feed = useCloudStairHistoryFeed(query, date, horizon, result);
  const { ensureAhead, rows, total } = feed;
  const scroller = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(560);
  const items = useMemo(() => groupHistoryRows(rows), [rows]);
  const view = useMemo(
    () => visibleWindow(items, scrollTop, viewport),
    [items, scrollTop, viewport],
  );

  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    setViewport(node.clientHeight);
    ensureAhead(node.scrollHeight - node.scrollTop - node.clientHeight);
  }, [ensureAhead, rows.length, total]);

  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    const frame = { id: 0 };
    const onScroll = () => {
      cancelAnimationFrame(frame.id);
      frame.id = requestAnimationFrame(() => {
        setScrollTop(node.scrollTop);
        ensureAhead(node.scrollHeight - node.scrollTop - node.clientHeight);
      });
    };
    node.addEventListener("scroll", onScroll, { passive: true });
    const observer = new ResizeObserver(() => {
      setViewport(node.clientHeight);
    });
    observer.observe(node);
    return () => {
      cancelAnimationFrame(frame.id);
      node.removeEventListener("scroll", onScroll);
      observer.disconnect();
    };
  }, [ensureAhead]);

  if (feed.loading && feed.rows.length === 0) {
    return <Skeleton className="q-history-list-skeleton" />;
  }
  if (feed.failed && feed.rows.length === 0) {
    return <LoadError label="名单加载失败" onRetry={feed.reload} />;
  }
  if (feed.rows.length === 0) {
    return <p className="q-history-empty">没有符合条件的云阶记录。</p>;
  }

  const slice = items.slice(view.start, view.end);

  return (
    <>
      <div
        ref={scroller}
        className="q-history-scroll"
        tabIndex={0}
        role="region"
        aria-label="全部历史云阶"
      >
        <table className="q-history-table">
          <thead>
            <tr>
              <th>股票</th>
              <th className="is-num">T+1</th>
              <th className="is-num">T+5</th>
              <th className="is-num">T+20</th>
            </tr>
          </thead>
          <tbody>
            {view.padTop > 0 ? (
              <tr className="q-history-spacer" aria-hidden="true">
                <td colSpan={4} style={{ height: view.padTop }} />
              </tr>
            ) : null}
            {slice.map((item) =>
              item.kind === "group" ? (
                <tr key={item.key} className="q-history-group">
                  <th scope="rowgroup" colSpan={4}>
                    {item.date}
                    <span> · {item.count.toLocaleString()} 次</span>
                  </th>
                </tr>
              ) : (
                <tr key={item.key}>
                  <td>
                    <Link to={`/stock/${item.row.code}`} className="q-history-code">
                      {item.row.code} {item.row.name}
                    </Link>
                  </td>
                  <td className={`is-num ${item.row.t1_settled ? tone(item.row.t1_net_return_pct) : ""}`}>
                    {settledLabel(item.row, "t1")}
                    {item.row.t1_win === true ? " 赚" : item.row.t1_win === false ? " 亏" : ""}
                  </td>
                  <td className={`is-num ${item.row.t5_settled ? tone(item.row.t5_net_return_pct) : ""}`}>
                    {settledLabel(item.row, "t5")}
                  </td>
                  <td className={`is-num ${item.row.t20_settled ? tone(item.row.t20_net_return_pct) : ""}`}>
                    {settledLabel(item.row, "t20")}
                  </td>
                </tr>
              ),
            )}
            {view.padBottom > 0 ? (
              <tr className="q-history-spacer" aria-hidden="true">
                <td colSpan={4} style={{ height: view.padBottom }} />
              </tr>
            ) : null}
          </tbody>
        </table>
        {feed.loadingMore ? (
          <p className="q-history-loading">正在加载后面的记录</p>
        ) : null}
      </div>
      <p className="q-history-status">
        已加载 {feed.rows.length.toLocaleString()} / {feed.total.toLocaleString()} 次
        {feed.hasMore ? "，继续下拉会自动补后面的。" : "，已经到底。"}
      </p>
      {feed.failed ? (
        <LoadError label="后面的记录没加载上" onRetry={() => feed.ensureAhead(0)} />
      ) : null}
    </>
  );
}

export function Component() {
  const summary = useCloudStairHistorySummary();
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [date, setDate] = useState("");
  const [horizon, setHorizon] = useState<HistoryHorizon>("t1");
  const [result, setResult] = useState<HistoryResult>("all");
  const data = summary.data;

  if (summary.isLoading) {
    return (
      <main className="q-review-page">
        <Skeleton className="q-review-skeleton" />
      </main>
    );
  }
  if (summary.error || data?.available === false) {
    return (
      <main className="q-review-page">
        <LoadError
          label="云阶历史复盘还读不到"
          onRetry={() => summary.mutate()}
        />
      </main>
    );
  }
  if (!data) {
    return (
      <main className="q-review-page">
        <LoadError label="云阶历史复盘还读不到" onRetry={() => summary.mutate()} />
      </main>
    );
  }

  const t1 = data.t1;
  const t5 = data.t5;
  const t20 = data.t20;

  return (
    <main className="q-review-page">
      <header className="q-review-header">
        <h1>云阶复盘</h1>
        <p>
          {data.rule} 截止 {data.cutoff}，共 {data.signal_count.toLocaleString()} 次、
          {data.stock_count.toLocaleString()} 只股票。
        </p>
      </header>

      <section className="q-history-kpis" aria-label="核心结果">
        <Kpi
          label="T+1 胜率"
          value={rate(t1.win_rate)}
          hint={`${t1.settled_count.toLocaleString()} 次已走完`}
        />
        <Kpi
          label="T+1 平均幅度"
          value={pct(t1.mean_net_return_pct)}
          hint="扣费后"
          valueClass={tone(t1.mean_net_return_pct)}
        />
        <Kpi
          label="T+5 平均幅度"
          value={pct(t5.mean_net_return_pct)}
          hint="扣费后"
          valueClass={tone(t5.mean_net_return_pct)}
        />
        <Kpi
          label="T+20 平均幅度"
          value={pct(t20.mean_net_return_pct)}
          hint="扣费后"
          valueClass={tone(t20.mean_net_return_pct)}
        />
      </section>

      <section className="q-history-board" aria-labelledby="horizon-table-title">
        <header className="q-history-board-head">
          <h2 id="horizon-table-title">各持有天数</h2>
          <p>胜率和幅度只统计已经完成买卖的样本。第二天就是 T+1。</p>
        </header>
        <div className="q-history-table-wrap">
          <table className="q-history-table">
            <thead>
              <tr>
                <th>拿几天</th>
                <th className="is-num">已走完</th>
                <th className="is-num">胜率</th>
                <th className="is-num">平均幅度</th>
                <th className="is-num">中位数</th>
              </tr>
            </thead>
            <tbody>
              {data.horizons.map((row: CloudStairHorizonStat) => (
                <tr key={row.horizon_sessions}>
                  <td>{row.label}</td>
                  <td className="is-num">{row.settled_count.toLocaleString()}</td>
                  <td className="is-num">{rate(row.win_rate)}</td>
                  <td className={`is-num ${tone(row.mean_net_return_pct)}`}>
                    {pct(row.mean_net_return_pct)}
                  </td>
                  <td className={`is-num ${tone(row.median_net_return_pct)}`}>
                    {pct(row.median_net_return_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="q-history-board" aria-labelledby="signal-table-title">
        <header className="q-history-board-head">
          <h2 id="signal-table-title">全部历史云阶</h2>
          <p>
            当天收盘后才确认，次日才能买。{data.cutoff} 当天 {data.today_count} 次还没走出 T+1。
          </p>
        </header>
        <form
          className="q-history-toolbar"
          onSubmit={(event) => {
            event.preventDefault();
            setQuery(draft.trim());
          }}
        >
          <Input
            label="搜代码或名称"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="例如 002612 或 朗姿"
          />
          <Button type="submit" label="查找" size="sm" />
          <Button
            type="button"
            label={date === data.cutoff ? "看全部日期" : `只看 ${data.cutoff}`}
            variant="secondary"
            size="sm"
            onClick={() => {
              setDate((current) => (current === data.cutoff ? "" : data.cutoff));
            }}
          />
        </form>
        <div className="q-history-fields">
          <FieldOptions
            label="看哪一段"
            value={horizon}
            onChange={setHorizon}
            options={[
              { value: "t1", label: "T+1" },
              { value: "t5", label: "T+5" },
              { value: "t20", label: "T+20" },
            ]}
          />
          <FieldOptions
            label="结果"
            value={result}
            onChange={setResult}
            options={[
              { value: "all", label: "全部" },
              { value: "win", label: "赚钱" },
              { value: "loss", label: "亏" },
              { value: "unsettled", label: "未走完" },
            ]}
          />
        </div>
        <HistoryList
          key={`${query}|${date}|${horizon}|${result}`}
          query={query}
          date={date}
          horizon={horizon}
          result={result}
        />
      </section>
    </main>
  );
}
