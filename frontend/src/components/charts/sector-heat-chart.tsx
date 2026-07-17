import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { chartColors } from "@/lib/tokens";

echarts.use([LineChart, GridComponent, MarkLineComponent, TooltipComponent, CanvasRenderer]);

interface SectorHeatChartProps {
  name: string;
  dates: string[];
  values: number[];
}

export function SectorHeatChart({ name, dates, values }: SectorHeatChartProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current || !values.length) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chart.setOption({
      animationDuration: 240,
      grid: { left: 38, right: 16, top: 20, bottom: 28 },
      tooltip: {
        trigger: "axis",
        backgroundColor: chartColors.tooltipBg,
        borderColor: "rgba(255,255,255,.12)",
        textStyle: { color: "#f3f0e8", fontSize: 12 },
        formatter: (params: unknown) => {
          const rows = params as Array<{ axisValue: string; value: number }>;
          const row = rows[0];
          return row ? `${row.axisValue}<br/>${name} 热度 ${Number(row.value).toFixed(1)}` : "";
        },
      },
      xAxis: {
        type: "category",
        data: dates.map((date) => date.slice(5)),
        boundaryGap: false,
        axisLine: { lineStyle: { color: chartColors.gridLine } },
        axisTick: { show: false },
        axisLabel: { color: chartColors.axisText, fontSize: 10 },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 100,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: chartColors.axisText, fontSize: 10 },
        splitLine: { lineStyle: { color: chartColors.gridLine } },
      },
      series: [{
        type: "line",
        data: values,
        showSymbol: values.length <= 8,
        symbolSize: 5,
        smooth: false,
        lineStyle: { color: "#d7b56d", width: 2 },
        itemStyle: { color: "#d7b56d" },
        areaStyle: { color: "rgba(215,181,109,.08)" },
        markLine: {
          silent: true,
          symbol: "none",
          label: { formatter: "主线阈值", color: chartColors.axisText, fontSize: 10 },
          lineStyle: { color: "rgba(244,91,105,.35)", type: "dashed" },
          data: [{ yAxis: 80 }],
        },
      }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [dates, name, values]);

  if (!values.length) {
    return <div className="flex h-48 items-center justify-center text-xs text-ink-muted">热度历史正在积累</div>;
  }

  return (
    <div
      ref={ref}
      className="h-48 w-full"
      role="img"
      aria-label={`${name}近${values.length}个交易日热度，当前${values.at(-1)?.toFixed(1)}`}
    />
  );
}
