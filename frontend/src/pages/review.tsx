import { useState } from "react";
import { Link } from "react-router";
import { Button, LoadError, Input, Skeleton } from "@/components/ui";
import type { CloudStairHistoryRow, CloudStairHorizonStat } from "@/lib/api";
import { useCloudStairHistorySignals, useCloudStairHistorySummary } from "@/lib/hooks";

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

export function Component() {
  const summary = useCloudStairHistorySummary();
  const [query, setQuery] = useState("");
  const [draft, setDraft] = useState("");
  const [date, setDate] = useState("");
  const [page, setPage] = useState(1);
  const list = useCloudStairHistorySignals({ q: query, date, page });
  const data = summary.data;
  const rows = list.data?.rows || [];

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
  const pageCount = list.data?.page_count || 0;
  const total = list.data?.total ?? 0;

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
            setPage(1);
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
              setPage(1);
            }}
          />
        </form>

        {list.isLoading && !list.data ? (
          <Skeleton className="q-history-list-skeleton" />
        ) : list.error ? (
          <LoadError label="名单加载失败" onRetry={() => list.mutate()} />
        ) : rows.length === 0 ? (
          <p className="q-history-empty">没有符合条件的云阶记录。</p>
        ) : (
          <>
            <div className="q-history-table-wrap">
              <table className="q-history-table">
                <thead>
                  <tr>
                    <th>日期</th>
                    <th>股票</th>
                    <th className="is-num">T+1</th>
                    <th className="is-num">T+5</th>
                    <th className="is-num">T+20</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.signal_id}>
                      <td>{row.signal_date}</td>
                      <td>
                        <Link to={`/stock/${row.code}`} className="q-history-code">
                          {row.code} {row.name}
                        </Link>
                      </td>
                      <td className={`is-num ${row.t1_settled ? tone(row.t1_net_return_pct) : ""}`}>
                        {settledLabel(row, "t1")}
                        {row.t1_win === true ? " 赚" : row.t1_win === false ? " 亏" : ""}
                      </td>
                      <td className={`is-num ${row.t5_settled ? tone(row.t5_net_return_pct) : ""}`}>
                        {settledLabel(row, "t5")}
                      </td>
                      <td className={`is-num ${row.t20_settled ? tone(row.t20_net_return_pct) : ""}`}>
                        {settledLabel(row, "t20")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="q-history-pager">
              <span>
                第 {page} / {Math.max(pageCount, 1)} 页，共 {total.toLocaleString()} 条
              </span>
              <div>
                <Button
                  label="上一页"
                  variant="secondary"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                />
                <Button
                  label="下一页"
                  variant="secondary"
                  size="sm"
                  disabled={page >= pageCount}
                  onClick={() => setPage((current) => current + 1)}
                />
              </div>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
