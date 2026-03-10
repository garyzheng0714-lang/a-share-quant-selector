import { useEffect, useRef, useCallback } from "react";
import { chartColors } from "@/lib/tokens";
import * as echarts from "echarts/core";
import { CandlestickChart, BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  DatasetComponent,
  MarkLineComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  CandlestickChart,
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
  DatasetComponent,
  MarkLineComponent,
  CanvasRenderer,
]);

export interface KlineOverlay {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change: number;
  kdjK?: number;
  kdjD?: number;
  kdjJ?: number;
  trendLine?: number;
  dkLine?: number;
  ma5?: number;
  ma10?: number;
  ma20?: number;
  ma60?: number;
}

interface KlineChartProps {
  data: (string | number)[][];
  period: "daily" | "weekly";
  weeklyLineMode?: "trend" | "ma";
  onCrosshairMove?: (data: KlineOverlay | null) => void;
  className?: string;
}

type EChartsOption = echarts.ComposeOption<
  | import("echarts/charts").CandlestickSeriesOption
  | import("echarts/charts").BarSeriesOption
  | import("echarts/charts").LineSeriesOption
  | import("echarts/components").GridComponentOption
  | import("echarts/components").TooltipComponentOption
  | import("echarts/components").DataZoomComponentOption
  | import("echarts/components").DatasetComponentOption
  | import("echarts/components").MarkLineComponentOption
>;

const {
  bull: BULL_COLOR,
  bear: BEAR_COLOR,
  gridLine: GRID_LINE,
  axisText: AXIS_TEXT,
  tooltipBg: TOOLTIP_BG,
  priceLine: PRICE_LINE_COLOR,
  trend: TREND_COLOR,
  dk: DK_COLOR,
  kdjK: KDJ_K_COLOR,
  kdjD: KDJ_D_COLOR,
  kdjJ: KDJ_J_COLOR,
  ma5: MA5_COLOR,
  ma10: MA10_COLOR,
  ma20: MA20_COLOR,
  ma60: MA60_COLOR,
  datazoomFill: DATAZOOM_FILL,
  datazoomHandle: DATAZOOM_HANDLE,
  markLineBg: MARKLINE_BG,
  datazoomBg: DATAZOOM_BG,
  dataBackgroundLine: DATA_BG_LINE,
  dataBackgroundArea: DATA_BG_AREA,
} = chartColors;
const BG_COLOR = "transparent";
const LINE_WIDTH = 1.5;

function formatVolumeAxis(v: number): string {
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(1) + "\u4ebf";
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(0) + "\u4e07";
  return v.toFixed(0);
}

interface LineSeriesOpt {
  type: "line";
  name: string;
  xAxisIndex: number;
  yAxisIndex: number;
  showSymbol: boolean;
  smooth: boolean;
  lineStyle: { width: number; color: string };
  itemStyle: { color: string };
  encode: { x: number; y: number };
  z: number;
}

function lineSeries(
  name: string,
  dataIndex: number,
  color: string,
  xIdx: number,
  yIdx: number,
): LineSeriesOpt {
  return {
    type: "line",
    name,
    xAxisIndex: xIdx,
    yAxisIndex: yIdx,
    showSymbol: false,
    smooth: true,
    lineStyle: { width: LINE_WIDTH, color },
    itemStyle: { color },
    encode: { x: 0, y: dataIndex },
    z: 2,
  };
}

function buildOption(
  raw: (string | number)[][],
  period: "daily" | "weekly",
  weeklyLineMode: "trend" | "ma",
): EChartsOption {
  const isDaily = period === "daily";
  const dates = raw.map((d) => d[0] as string);
  const dataLen = dates.length;
  const defaultVisible = isDaily ? 120 : 60;
  const startPercent = Math.max(
    0,
    ((dataLen - defaultVisible) / dataLen) * 100,
  );

  const isMobile = typeof window !== "undefined" && window.innerWidth < 640;
  const gridLeft = isMobile ? 40 : 60;
  const gridRight = isMobile ? 10 : 60;
  const labelFontSize = isMobile ? 10 : 11;

  const commonAxisLabel = {
    color: AXIS_TEXT,
    fontSize: labelFontSize,
  } as const;

  const commonSplitLine = {
    show: true as const,
    lineStyle: { color: GRID_LINE },
  };

  const grids = isDaily
    ? [
        { left: gridLeft, right: gridRight, top: 30, height: "50%" },
        { left: gridLeft, right: gridRight, top: "58%", height: "12%" },
        { left: gridLeft, right: gridRight, top: "73%", height: "18%" },
      ]
    : [
        { left: gridLeft, right: gridRight, top: 30, height: "65%" },
        { left: gridLeft, right: gridRight, top: "73%", height: "16%" },
      ];

  const xAxes = isDaily
    ? [
        {
          type: "category" as const,
          data: dates,
          gridIndex: 0,
          axisLabel: { show: false },
          axisTick: { show: false },
          axisLine: { show: false },
          splitLine: commonSplitLine,
          axisPointer: { label: { show: false } },
        },
        {
          type: "category" as const,
          data: dates,
          gridIndex: 1,
          axisLabel: { show: false },
          axisTick: { show: false },
          axisLine: { show: false },
          splitLine: commonSplitLine,
          axisPointer: { label: { show: false } },
        },
        {
          type: "category" as const,
          data: dates,
          gridIndex: 2,
          axisLabel: commonAxisLabel,
          axisTick: { show: false },
          axisLine: { lineStyle: { color: GRID_LINE } },
          splitLine: commonSplitLine,
          axisPointer: { label: { show: true } },
        },
      ]
    : [
        {
          type: "category" as const,
          data: dates,
          gridIndex: 0,
          axisLabel: { show: false },
          axisTick: { show: false },
          axisLine: { show: false },
          splitLine: commonSplitLine,
          axisPointer: { label: { show: false } },
        },
        {
          type: "category" as const,
          data: dates,
          gridIndex: 1,
          axisLabel: commonAxisLabel,
          axisTick: { show: false },
          axisLine: { lineStyle: { color: GRID_LINE } },
          splitLine: commonSplitLine,
          axisPointer: { label: { show: true } },
        },
      ];

  const yAxes = isDaily
    ? [
        {
          type: "value" as const,
          gridIndex: 0,
          scale: true,
          splitLine: commonSplitLine,
          axisLabel: commonAxisLabel,
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          type: "value" as const,
          gridIndex: 1,
          scale: true,
          splitLine: { show: false },
          axisLabel: {
            ...commonAxisLabel,
            formatter: formatVolumeAxis,
          },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          type: "value" as const,
          gridIndex: 2,
          scale: true,
          splitLine: { show: false },
          axisLabel: commonAxisLabel,
          axisLine: { show: false },
          axisTick: { show: false },
        },
      ]
    : [
        {
          type: "value" as const,
          gridIndex: 0,
          scale: true,
          splitLine: commonSplitLine,
          axisLabel: commonAxisLabel,
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          type: "value" as const,
          gridIndex: 1,
          scale: true,
          splitLine: { show: false },
          axisLabel: {
            ...commonAxisLabel,
            formatter: formatVolumeAxis,
          },
          axisLine: { show: false },
          axisTick: { show: false },
        },
      ];

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const series: any[] = [];

  const lastRow = raw[raw.length - 1];
  const latestClose = lastRow ? (lastRow[2] as number) : 0;
  const prevClose =
    raw.length > 1 ? (raw[raw.length - 2][2] as number) : latestClose;
  const isBullish = latestClose >= prevClose;

  series.push({
    type: "candlestick",
    name: "K\u7ebf",
    xAxisIndex: 0,
    yAxisIndex: 0,
    encode: { x: 0, y: [1, 2, 3, 4] },
    itemStyle: {
      color: BULL_COLOR,
      color0: BEAR_COLOR,
      borderColor: BULL_COLOR,
      borderColor0: BEAR_COLOR,
    },
    z: 1,
    markLine: {
      silent: true,
      symbol: "none",
      label: {
        show: true,
        position: "end",
        formatter: latestClose.toFixed(2),
        color: isBullish ? BULL_COLOR : BEAR_COLOR,
        backgroundColor: MARKLINE_BG,
        borderColor: isBullish ? BULL_COLOR : BEAR_COLOR,
        borderWidth: 1,
        borderRadius: 3,
        padding: [3, 6],
        fontSize: 10,
        fontFamily: "SF Mono, Menlo, Consolas, monospace",
      },
      lineStyle: {
        color: PRICE_LINE_COLOR,
        type: "dashed",
        width: 1,
      },
      data: [{ yAxis: latestClose }],
      animation: false,
    },
  });

  series.push({
    type: "bar",
    name: "\u6210\u4ea4\u91cf",
    xAxisIndex: isDaily ? 1 : 1,
    yAxisIndex: isDaily ? 1 : 1,
    encode: { x: 0, y: 5 },
    barMaxWidth: 8,
    itemStyle: {
      color: (params: { dataIndex: number }) => {
        const d = raw[params.dataIndex];
        return (d[2] as number) >= (d[1] as number) ? BULL_COLOR : BEAR_COLOR;
      },
    },
    z: 1,
  });

  if (isDaily) {
    series.push(lineSeries("\u8d8b\u52bf\u7ebf", 9, TREND_COLOR, 0, 0));
    series.push(lineSeries("DK\u7ebf", 10, DK_COLOR, 0, 0));

    series.push(lineSeries("K", 6, KDJ_K_COLOR, 2, 2));
    series.push(lineSeries("D", 7, KDJ_D_COLOR, 2, 2));
    series.push(lineSeries("J", 8, KDJ_J_COLOR, 2, 2));
  } else {
    if (weeklyLineMode === "trend") {
      series.push(lineSeries("\u8d8b\u52bf\u7ebf", 10, TREND_COLOR, 0, 0));
      series.push(lineSeries("DK\u7ebf", 11, DK_COLOR, 0, 0));
    } else {
      series.push(lineSeries("MA5", 6, MA5_COLOR, 0, 0));
      series.push(lineSeries("MA10", 7, MA10_COLOR, 0, 0));
      series.push(lineSeries("MA20", 8, MA20_COLOR, 0, 0));
      series.push(lineSeries("MA60", 9, MA60_COLOR, 0, 0));
    }
  }

  const option: EChartsOption = {
    backgroundColor: BG_COLOR,
    animation: false,
    dataset: { source: raw },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      showContent: false,
      backgroundColor: TOOLTIP_BG,
    },
    axisPointer: {
      link: [{ xAxisIndex: "all" }],
      lineStyle: { color: AXIS_TEXT, type: "dashed" },
      label: {
        backgroundColor: TOOLTIP_BG,
        color: AXIS_TEXT,
      },
    },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    series: series as EChartsOption["series"],
    dataZoom: [
      {
        type: "slider",
        xAxisIndex: isDaily ? [0, 1, 2] : [0, 1],
        bottom: 8,
        height: 24,
        start: startPercent,
        end: 100,
        borderColor: "transparent",
        backgroundColor: DATAZOOM_BG,
        fillerColor: DATAZOOM_FILL,
        handleStyle: {
          color: DATAZOOM_HANDLE,
          borderColor: DATAZOOM_HANDLE,
        },
        moveHandleStyle: { color: DATAZOOM_HANDLE },
        textStyle: { color: AXIS_TEXT, fontSize: 10 },
        dataBackground: {
          lineStyle: { color: DATA_BG_LINE },
          areaStyle: { color: DATA_BG_AREA },
        },
        selectedDataBackground: {
          lineStyle: { color: DATAZOOM_HANDLE },
          areaStyle: { color: DATAZOOM_FILL },
        },
      },
      {
        type: "inside",
        xAxisIndex: isDaily ? [0, 1, 2] : [0, 1],
        start: startPercent,
        end: 100,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
      },
    ],
  };

  return option;
}

function buildOverlay(
  raw: (string | number)[][],
  dataIndex: number,
  period: "daily" | "weekly",
): KlineOverlay | null {
  if (dataIndex < 0 || dataIndex >= raw.length) return null;

  const d = raw[dataIndex];
  const prevClose =
    dataIndex > 0 ? (raw[dataIndex - 1][2] as number) : (d[1] as number);
  const close = d[2] as number;
  const change = prevClose ? ((close - prevClose) / prevClose) * 100 : 0;

  const overlay: KlineOverlay = {
    date: d[0] as string,
    open: d[1] as number,
    high: d[4] as number,
    low: d[3] as number,
    close,
    volume: d[5] as number,
    change,
  };

  if (period === "daily") {
    if (d[6] != null) overlay.kdjK = d[6] as number;
    if (d[7] != null) overlay.kdjD = d[7] as number;
    if (d[8] != null) overlay.kdjJ = d[8] as number;
    if (d[9] != null) overlay.trendLine = d[9] as number;
    if (d[10] != null) overlay.dkLine = d[10] as number;
  } else {
    if (d[6] != null) overlay.ma5 = d[6] as number;
    if (d[7] != null) overlay.ma10 = d[7] as number;
    if (d[8] != null) overlay.ma20 = d[8] as number;
    if (d[9] != null) overlay.ma60 = d[9] as number;
    if (d[10] != null) overlay.trendLine = d[10] as number;
    if (d[11] != null) overlay.dkLine = d[11] as number;
  }

  return overlay;
}

export function KlineChart({
  data,
  period,
  weeklyLineMode = "trend",
  onCrosshairMove,
  className = "",
}: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const dataRef = useRef(data);
  const periodRef = useRef(period);

  dataRef.current = data;
  periodRef.current = period;

  const handleAxisPointer = useCallback(
    (params: { axesInfo?: { value?: number }[] }) => {
      if (!onCrosshairMove) return;

      const axesInfo = params.axesInfo;
      if (!axesInfo?.length || axesInfo[0].value == null) {
        onCrosshairMove(null);
        return;
      }

      const dataIndex = axesInfo[0].value as number;
      const overlay = buildOverlay(
        dataRef.current,
        dataIndex,
        periodRef.current,
      );
      onCrosshairMove(overlay);
    },
    [onCrosshairMove],
  );

  useEffect(() => {
    if (!containerRef.current || !data.length) return;

    const container = containerRef.current;

    if (chartRef.current) {
      chartRef.current.dispose();
      chartRef.current = null;
    }

    const chart = echarts.init(container, undefined, {
      renderer: "canvas",
    });
    chartRef.current = chart;

    const option = buildOption(data, period, weeklyLineMode);
    chart.setOption(option);

    chart.on(
      "updateAxisPointer",
      handleAxisPointer as (...args: unknown[]) => void,
    );

    const observer = new ResizeObserver(() => {
      chart.resize();
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.off(
        "updateAxisPointer",
        handleAxisPointer as (...args: unknown[]) => void,
      );
      chart.dispose();
      chartRef.current = null;
    };
  }, [data, period, weeklyLineMode, handleAxisPointer]);

  return <div ref={containerRef} className={`w-full ${className}`} />;
}
