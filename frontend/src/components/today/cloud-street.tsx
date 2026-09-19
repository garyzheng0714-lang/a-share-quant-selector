import { useEffect, useRef, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Text } from "@astryxdesign/core/Text";
import { KlineChart } from "@/components/charts/kline-chart";
import { LoadError, Skeleton } from "@/components/ui";
import { useNavigate } from "@/lib/spa-router";
import { useKline, useQuantPick } from "@/lib/hooks";
import { useAppStore } from "@/lib/store";
import type { CloudStairStockHistory, QuantPickStock, SignalStock } from "@/lib/api";

type Period = "daily" | "weekly";

function signed(value?: number | null, digits = 2, suffix = "") {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

function heatText(stock: QuantPickStock) {
  const sector = stock.sector;
  if (!stock.industry && !sector) return "行业待补全";
  if (!sector || sector.score == null) return stock.industry || "行业待补全";
  return `${stock.industry} · 热度 ${Math.round(sector.score)} · 第 ${sector.rank}/${sector.total}`;
}

function capText(stock: QuantPickStock, withLabel = true) {
  const value = stock.cap_yi == null ? "待补全" : `${stock.cap_yi.toFixed(0)} 亿`;
  return withLabel ? `市值 ${value}` : value;
}

function historySummary(history?: CloudStairStockHistory | null) {
  if (!history || history.appear_count <= 0) return "还没有可回看的进场记录";
  const rate = history.t5.win_rate;
  const rateText = rate == null ? "T+5 胜率待结算" : `T+5 胜率 ${rate}%`;
  const span = history.first_date && history.last_date
    ? history.first_date === history.last_date
      ? history.first_date
      : `${history.first_date} 至 ${history.last_date}`
    : "";
  return span
    ? `进过 ${history.appear_count} 次 · ${rateText} · ${span}`
    : `进过 ${history.appear_count} 次 · ${rateText}`;
}

function toNav(list: QuantPickStock[]): SignalStock[] {
  return list.map((item) => ({
    code: item.code,
    name: item.name,
    strategy: "云阶",
    category: item.industry || "",
    close: item.close ?? 0,
    J: item.J ?? 0,
    volume_ratio: 0,
    market_cap: (item.cap_yi ?? 0) * 1e8,
    short_term_trend: 0,
    bull_bear_line: 0,
    reasons: [],
    similarity_score: null,
    matched_case: null,
    match_breakdown: null,
    industry: item.industry,
  }));
}

function StreetChart({ stock }: { stock: QuantPickStock }) {
  const [period, setPeriod] = useState<Period>("daily");
  const kline = useKline(stock.code, period);

  return (
    <div className="cloud-street-chart">
      <div className="cloud-street-chart-bar">
        <SegmentedControl
          value={period}
          onChange={(value) => setPeriod(value as Period)}
          label="K线周期"
          size="sm"
        >
          <SegmentedControlItem value="daily" label="日K" />
          <SegmentedControlItem value="weekly" label="周K" />
        </SegmentedControl>
        <Text type="supporting">
          {kline.data?.as_of ? `截至 ${kline.data.as_of}` : "正在读图"}
        </Text>
      </div>
      {kline.isLoading ? (
        <Skeleton className="cloud-street-chart-frame" />
      ) : kline.error || !kline.data?.data?.length ? (
        <LoadError label="K 线加载失败" onRetry={() => kline.mutate()} />
      ) : (
        <KlineChart
          data={kline.data.data}
          period={period}
          signals={period === "daily" ? kline.data.signals : undefined}
          className="cloud-street-chart-frame"
        />
      )}
    </div>
  );
}

function StreetRow({
  stock,
  list,
  open,
  onToggle,
}: {
  stock: QuantPickStock;
  list: QuantPickStock[];
  open: boolean;
  onToggle: () => void;
}) {
  const navigate = useNavigate();
  const setStockNav = useAppStore((state) => state.setStockNav);
  const rowRef = useRef<HTMLElement>(null);
  const up = (stock.pct_change ?? 0) >= 0;

  useEffect(() => {
    if (!open || !rowRef.current) return;
    rowRef.current.scrollIntoView({ block: "start", behavior: "smooth" });
  }, [open]);

  return (
    <article ref={rowRef} className={open ? "cloud-street-row is-open" : "cloud-street-row"}>
      <Button
        label={`${open ? "收起" : "展开"} ${stock.name} 的 K 线和历史`}
        variant="ghost"
        width="100%"
        aria-expanded={open}
        onClick={onToggle}
        className="cloud-street-trigger h-auto min-h-0 overflow-visible"
      >
        <span className="cloud-street-main">
          <span className="cloud-street-name">
            <strong>{stock.name || stock.code}</strong>
            <code>{stock.code}</code>
          </span>
          <span className="cloud-street-price">
            <b>{stock.close?.toFixed(2) ?? "—"}</b>
            <em className={up ? "text-bull" : "text-bear"}>{signed(stock.pct_change, 2, "%")}</em>
          </span>
        </span>
        <span className="cloud-street-facts">
          <span>{heatText(stock)}</span>
          <span>{capText(stock)}</span>
          <span>{historySummary(stock.history)}</span>
        </span>
      </Button>

      {open && (
        <div className="cloud-street-detail">
          <StreetChart stock={stock} />
          <dl className="cloud-street-stats">
            <div>
              <dt>历史进出</dt>
              <dd>
                {stock.history?.appear_count
                  ? `进过 ${stock.history.appear_count} 次`
                  : "还没有可回看的记录"}
              </dd>
            </div>
            <div>
              <dt>T+5 胜率</dt>
              <dd>
                {stock.history?.t5.win_rate == null
                  ? "还没结算完"
                  : `${stock.history.t5.win_rate}%（${stock.history.t5.settled} 次已结算）`}
              </dd>
            </div>
            <div>
              <dt>行业热度</dt>
              <dd>{heatText(stock)}</dd>
            </div>
            <div>
              <dt>市值</dt>
              <dd>{capText(stock, false)}</dd>
            </div>
          </dl>
          {stock.history?.recent_dates?.length ? (
            <p className="cloud-street-dates">
              最近几次：{stock.history.recent_dates.join("、")}
            </p>
          ) : null}
          <Button
            label={`打开 ${stock.name} 完整个股页`}
            variant="ghost"
            size="sm"
            onClick={() => {
              setStockNav(toNav(list), list.findIndex((item) => item.code === stock.code));
              navigate(`/stock/${stock.code}`);
            }}
          />
        </div>
      )}
    </article>
  );
}

export function CloudStreet() {
  const { data, error, isLoading, mutate } = useQuantPick();
  const [openCode, setOpenCode] = useState<string | null>(null);
  const picks = data?.today_buy ?? [];

  if (isLoading) {
    return (
      <section className="cloud-street" aria-label="云阶">
        <Skeleton className="h-24" />
        <Skeleton className="mt-3 h-24" />
      </section>
    );
  }

  if (error || !data?.available) {
    return (
      <section className="cloud-street" aria-label="云阶">
        <LoadError label="云阶暂时读不到" onRetry={() => mutate()} />
      </section>
    );
  }

  return (
    <section className="cloud-street" aria-label="云阶">
      <header className="cloud-street-head">
        <Heading level={2}>今日云阶</Heading>
        <Text type="supporting">
          {data.trade_date ? `${data.trade_date} 收盘` : ""}
          {picks.length ? ` · ${picks.length} 只` : ""}
        </Text>
      </header>

      {picks.length === 0 ? (
        <p className="cloud-street-empty">今天云阶没有票。空着是常态。</p>
      ) : (
        <div className="cloud-street-list">
          {picks.map((stock) => (
            <StreetRow
              key={stock.code}
              stock={stock}
              list={picks}
              open={openCode === stock.code}
              onToggle={() => setOpenCode((current) => current === stock.code ? null : stock.code)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
