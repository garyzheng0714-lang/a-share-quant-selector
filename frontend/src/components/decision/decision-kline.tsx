import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, CandlestickChart, LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type {
  BarSeriesOption,
  CandlestickSeriesOption,
  LineSeriesOption,
} from "echarts/charts";
import type { KlineSignal } from "@/lib/api";

echarts.use([
  CandlestickChart,
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkPointComponent,
  CanvasRenderer,
]);

export type DecisionPeriod = "daily" | "weekly" | "monthly";
export type DecisionSubPanel = "kdj" | "volume" | "none";

interface DecisionKlineProps {
  data: (string | number)[][];
  period: DecisionPeriod;
  ma: Record<"ma5" | "ma10" | "ma20" | "ma60", boolean>;
  overlays: Record<"trend" | "dk" | "signals", boolean>;
  subPanel: DecisionSubPanel;
  signals?: KlineSignal[];
}

const colors = {
  bull: "#dc2626",
  bear: "#16803b",
  grid: "rgba(25,25,24,0.08)",
  axis: "#a39e98",
  tooltip: "rgba(255,255,255,0.98)",
  ma5: "#f59e0b",
  ma10: "#3b82f6",
  ma20: "#0891b2",
  ma60: "#16a34a",
  trend: "#31302e",
  dk: "#d97706",
  signal: "#0075de",
  k: "#3b82f6",
  d: "#f59e0b",
  j: "#dc2626",
};

type ComposeOption = echarts.ComposeOption<
  | import("echarts/charts").CandlestickSeriesOption
  | import("echarts/charts").BarSeriesOption
  | import("echarts/charts").LineSeriesOption
  | import("echarts/components").GridComponentOption
  | import("echarts/components").LegendComponentOption
  | import("echarts/components").TooltipComponentOption
  | import("echarts/components").DataZoomComponentOption
  | import("echarts/components").MarkLineComponentOption
  | import("echarts/components").MarkPointComponentOption
>;

type DecisionSeriesOption = CandlestickSeriesOption | BarSeriesOption | LineSeriesOption;

function line(name: string, data: Array<number | null>, color: string, xAxisIndex = 0, yAxisIndex = 0) {
  return {
    type: "line" as const,
    name,
    data,
    xAxisIndex,
    yAxisIndex,
    showSymbol: false,
    connectNulls: false,
    lineStyle: { color, width: 1.4 },
    itemStyle: { color },
    emphasis: { disabled: true },
    animation: false,
    z: 3,
  };
}

function numberAt(row: (string | number)[], index: number): number | null {
  const value = row[index];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function optionFor(
  raw: (string | number)[][],
  period: DecisionPeriod,
  ma: DecisionKlineProps["ma"],
  overlays: DecisionKlineProps["overlays"],
  subPanel: DecisionSubPanel,
  signals?: KlineSignal[],
): ComposeOption {
  const dates = raw.map((row) => String(row[0] ?? ""));
  const isDaily = period === "daily";
  const hasSub = subPanel !== "none";
  const maIndexes = isDaily
    ? { ma5: 11, ma10: 12, ma20: 13, ma60: 14 }
    : { ma5: 6, ma10: 7, ma20: 8, ma60: 9 };
  const trendIndex = isDaily ? 9 : 10;
  const dkIndex = isDaily ? 10 : 11;
  const latest = raw.at(-1);
  const latestClose = latest ? numberAt(latest, 2) : null;
  const series: DecisionSeriesOption[] = [
    {
      type: "candlestick",
      name: "K线",
      data: raw.map((row) => [row[1], row[2], row[3], row[4]]),
      xAxisIndex: 0,
      yAxisIndex: 0,
      itemStyle: {
        color: colors.bull,
        color0: colors.bear,
        borderColor: colors.bull,
        borderColor0: colors.bear,
      },
      markLine: latestClose == null ? undefined : {
        silent: true,
        symbol: "none",
        lineStyle: { color: "rgba(0,117,222,0.45)", type: "dashed", width: 1 },
        label: {
          show: true,
          formatter: latestClose.toFixed(2),
          color: colors.bull,
          backgroundColor: "#fff",
          borderColor: colors.bull,
          borderWidth: 1,
          borderRadius: 4,
          padding: [2, 5],
          fontSize: 10,
        },
        data: [{ yAxis: latestClose }],
      },
      markPoint: overlays.signals && signals?.length ? {
        silent: true,
        symbol: "circle",
        symbolSize: 6,
        label: { show: false },
        itemStyle: { color: colors.signal },
        data: signals.flatMap((signal) => {
          const index = dates.indexOf(signal.date);
          const low = index >= 0 ? numberAt(raw[index], 3) : null;
          return index >= 0 && low != null
            ? [{ name: signal.category || "历史信号", coord: [index, low] }]
            : [];
        }),
      } : undefined,
      animation: false,
      z: 2,
    },
  ];

  const maConfig = [
    ["ma5", "MA5", colors.ma5],
    ["ma10", "MA10", colors.ma10],
    ["ma20", "MA20", colors.ma20],
    ["ma60", "MA60", colors.ma60],
  ] as const;
  for (const [key, label, color] of maConfig) {
    if (ma[key]) series.push(line(label, raw.map((row) => numberAt(row, maIndexes[key])), color));
  }
  if (overlays.dk) series.push(line("多空线", raw.map((row) => numberAt(row, dkIndex)), colors.dk));
  if (overlays.trend) series.push(line("趋势线", raw.map((row) => numberAt(row, trendIndex)), colors.trend));

  if (hasSub && (subPanel === "volume" || !isDaily)) {
    series.push({
      type: "bar",
      name: "成交量",
      data: raw.map((row) => numberAt(row, 5) ?? 0),
      xAxisIndex: 1,
      yAxisIndex: 1,
      barMaxWidth: 8,
      itemStyle: {
        color: ({ dataIndex }: { dataIndex: number }) =>
          (numberAt(raw[dataIndex], 2) ?? 0) >= (numberAt(raw[dataIndex], 1) ?? 0)
            ? colors.bull
            : colors.bear,
      },
      animation: false,
    });
  } else if (hasSub && subPanel === "kdj") {
    series.push(line("K", raw.map((row) => numberAt(row, 6)), colors.k, 1, 1));
    series.push(line("D", raw.map((row) => numberAt(row, 7)), colors.d, 1, 1));
    series.push(line("J", raw.map((row) => numberAt(row, 8)), colors.j, 1, 1));
  }

  const grid = hasSub
    ? [
        { left: 48, right: 52, top: 33, height: "61%" },
        { left: 48, right: 52, top: "81%", height: "14%" },
      ]
    : [{ left: 48, right: 52, top: 33, bottom: 32 }];
  const xAxis = [
    {
      type: "category" as const,
      data: dates,
      gridIndex: 0,
      boundaryGap: true,
      axisLabel: { color: colors.axis, fontSize: 10, hideOverlap: true },
      axisTick: { show: false },
      axisLine: { show: false },
      splitLine: { show: true, lineStyle: { color: colors.grid } },
    },
    ...(hasSub ? [{
      type: "category" as const,
      data: dates,
      gridIndex: 1,
      boundaryGap: true,
      axisLabel: { show: false },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: colors.grid } },
      splitLine: { show: true, lineStyle: { color: colors.grid } },
    }] : []),
  ];
  const yAxis = [
    {
      type: "value" as const,
      gridIndex: 0,
      scale: true,
      axisLabel: { color: colors.axis, fontSize: 10 },
      axisTick: { show: false },
      axisLine: { show: false },
      splitLine: { show: true, lineStyle: { color: colors.grid } },
    },
    ...(hasSub ? [{
      type: "value" as const,
      gridIndex: 1,
      scale: true,
      axisLabel: { color: colors.axis, fontSize: 10 },
      axisTick: { show: false },
      axisLine: { show: false },
      splitLine: { show: false },
    }] : []),
  ];

  const visible = period === "daily" ? 100 : period === "weekly" ? 70 : 48;
  const start = Math.max(0, ((raw.length - visible) / Math.max(raw.length, 1)) * 100);
  const legendNames = [
    ...maConfig.filter(([key]) => ma[key]).map(([, label]) => label),
    ...(overlays.dk ? ["多空线"] : []),
    ...(overlays.trend ? ["趋势线"] : []),
  ];
  return {
    animation: false,
    backgroundColor: "transparent",
    grid,
    xAxis,
    yAxis,
    series,
    legend: {
      data: legendNames,
      left: 20,
      top: 2,
      itemWidth: 10,
      itemHeight: 2,
      itemGap: 14,
      textStyle: { color: colors.axis, fontSize: 10 },
      selectedMode: false,
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      backgroundColor: colors.tooltip,
      borderColor: "#e6e6e6",
      textStyle: { color: "#31302e", fontSize: 11 },
    },
    dataZoom: [{
      type: "inside",
      xAxisIndex: hasSub ? [0, 1] : [0],
      start,
      end: 100,
    }],
  };
}

export function DecisionKline({ data, period, ma, overlays, subPanel, signals }: DecisionKlineProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || data.length === 0) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.setOption(optionFor(data, period, ma, overlays, subPanel, signals), true);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [data, period, ma, overlays, subPanel, signals]);

  return (
    <div
      ref={ref}
      className="q-decision-chart"
      role="img"
      aria-label={`${period === "daily" ? "日" : period === "weekly" ? "周" : "月"}K线图`}
    />
  );
}
