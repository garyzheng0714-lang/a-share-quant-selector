import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { StrategyReviewPick, StrategyReviewSummary } from "@/lib/api";
import { chartColors } from "@/lib/tokens";

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

function useChart(option: echarts.EChartsCoreOption | null) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<echarts.EChartsType | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current, undefined, { renderer: "canvas" });
    }
    const chart = chartRef.current;
    if (option) chart.setOption(option, true);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
    };
  }, [option]);

  useEffect(
    () => () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    },
    [],
  );

  return ref;
}

/** 持有窗口：均收益 + 胜率双轴 */
export function WindowStatsChart({ summary }: { summary: StrategyReviewSummary }) {
  const labels = ["T+1", "T+5", "T+10", "T+20"] as const;
  const keys = ["ret_1", "ret_5", "ret_10", "ret_20"] as const;
  const avgs = keys.map((key) => summary.windows[key]?.avg ?? null);
  const wins = keys.map((key) => summary.windows[key]?.win_rate ?? null);

  const option: echarts.EChartsCoreOption = {
    grid: { left: 44, right: 44, top: 28, bottom: 28 },
    tooltip: { trigger: "axis" },
    legend: {
      data: ["均收益%", "胜率%"],
      textStyle: { color: chartColors.axisText, fontSize: 11 },
      top: 0,
    },
    xAxis: {
      type: "category",
      data: [...labels],
      axisLabel: { color: chartColors.axisText },
      axisLine: { lineStyle: { color: chartColors.gridLine } },
    },
    yAxis: [
      {
        type: "value",
        name: "%",
        axisLabel: { color: chartColors.axisText },
        splitLine: { lineStyle: { color: chartColors.gridLine } },
      },
      {
        type: "value",
        min: 0,
        max: 100,
        axisLabel: { color: chartColors.axisText, formatter: "{value}%" },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "均收益%",
        type: "bar",
        data: avgs.map((v) => ({
          value: v,
          itemStyle: { color: v != null && v >= 0 ? chartColors.bull : chartColors.bear },
        })),
        barMaxWidth: 36,
      },
      {
        name: "胜率%",
        type: "line",
        yAxisIndex: 1,
        data: wins,
        smooth: true,
        itemStyle: { color: chartColors.priceLine },
        lineStyle: { width: 2 },
      },
    ],
  };
  const ref = useChart(option);
  return <div ref={ref} className="h-52 w-full" />;
}

/** 按选出日的隔日 / 持有至今均值 */
export function ByDateChart({ summary }: { summary: StrategyReviewSummary }) {
  const rows = summary.by_date ?? [];
  const option: echarts.EChartsCoreOption = {
    grid: { left: 44, right: 16, top: 28, bottom: 40 },
    tooltip: { trigger: "axis" },
    legend: {
      data: ["隔日均%", "持有至今均%"],
      textStyle: { color: chartColors.axisText, fontSize: 11 },
      top: 0,
    },
    xAxis: {
      type: "category",
      data: rows.map((row) => row.pick_date.slice(5)),
      axisLabel: { color: chartColors.axisText, rotate: rows.length > 8 ? 35 : 0 },
      axisLine: { lineStyle: { color: chartColors.gridLine } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: chartColors.axisText },
      splitLine: { lineStyle: { color: chartColors.gridLine } },
    },
    series: [
      {
        name: "隔日均%",
        type: "bar",
        data: rows.map((row) => row.next_day.avg),
        itemStyle: { color: chartColors.trend },
        barMaxWidth: 28,
      },
      {
        name: "持有至今均%",
        type: "line",
        data: rows.map((row) => row.to_date.avg),
        itemStyle: { color: chartColors.priceLine },
        smooth: true,
      },
    ],
  };
  const ref = useChart(rows.length ? option : null);
  if (!rows.length) return null;
  return <div ref={ref} className="h-52 w-full" />;
}

/** 单票入场后浮盈路径 */
export function HoldPathChart({ pick }: { pick: StrategyReviewPick }) {
  const path = pick.path ?? [];
  const option: echarts.EChartsCoreOption = {
    grid: { left: 44, right: 16, top: 16, bottom: 28 },
    tooltip: { trigger: "axis" },
    xAxis: {
      type: "category",
      data: path.map((p) => `T+${p.session}`),
      axisLabel: { color: chartColors.axisText },
      axisLine: { lineStyle: { color: chartColors.gridLine } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: chartColors.axisText, formatter: "{value}%" },
      splitLine: { lineStyle: { color: chartColors.gridLine } },
    },
    series: [
      {
        name: "收盘浮盈",
        type: "line",
        data: path.map((p) => p.close_ret),
        smooth: true,
        areaStyle: { opacity: 0.08 },
        itemStyle: { color: chartColors.priceLine },
        markLine: {
          silent: true,
          data: [{ yAxis: 0 }],
          lineStyle: { color: chartColors.gridLine, type: "dashed" },
          symbol: "none",
        },
      },
      {
        name: "当日最高",
        type: "line",
        data: path.map((p) => p.high_ret),
        showSymbol: false,
        lineStyle: { type: "dotted", width: 1, color: chartColors.bull },
        itemStyle: { color: chartColors.bull },
      },
      {
        name: "当日最低",
        type: "line",
        data: path.map((p) => p.low_ret),
        showSymbol: false,
        lineStyle: { type: "dotted", width: 1, color: chartColors.bear },
        itemStyle: { color: chartColors.bear },
      },
    ],
  };
  const ref = useChart(path.length ? option : null);
  if (!path.length) {
    return <p className="text-sm text-ink-muted">尚无入场后路径</p>;
  }
  return <div ref={ref} className="h-56 w-full" />;
}
