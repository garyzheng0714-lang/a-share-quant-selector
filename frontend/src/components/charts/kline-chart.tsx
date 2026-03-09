import { useEffect, useRef, useCallback } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
  CrosshairMode,
  LineStyle,
  type MouseEventParams,
} from "lightweight-charts";

interface KlineOverlay {
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
}

interface KlineChartProps {
  data: (string | number)[][];
  period: "daily" | "weekly";
  onCrosshairMove?: (data: KlineOverlay | null) => void;
  className?: string;
}

const BULL_COLOR = "#c0392b";
const BEAR_COLOR = "#27896e";
const CANVAS_BG = "#faf6f0";
const GRID_COLOR = "rgba(45,43,40,0.04)";
const TEXT_COLOR = "#9c9590";
const ACCENT_COLOR = "#c0785a";

function parseKlineData(raw: (string | number)[][], period: string) {
  const candles: CandlestickData<Time>[] = [];
  const volumes: HistogramData<Time>[] = [];
  const kLines: LineData<Time>[] = [];
  const dLines: LineData<Time>[] = [];
  const jLines: LineData<Time>[] = [];
  const trendLines: LineData<Time>[] = [];
  const dkLines: LineData<Time>[] = [];
  const ma5Lines: LineData<Time>[] = [];
  const ma10Lines: LineData<Time>[] = [];
  const ma20Lines: LineData<Time>[] = [];
  const ma60Lines: LineData<Time>[] = [];

  for (const d of raw) {
    const time = (d[0] as string) as Time;
    const open = d[1] as number;
    const close = d[2] as number;
    const low = d[3] as number;
    const high = d[4] as number;
    const volume = d[5] as number;
    const isUp = close >= open;

    candles.push({
      time,
      open,
      high,
      low,
      close,
    });

    volumes.push({
      time,
      value: volume,
      color: isUp ? `${BULL_COLOR}80` : `${BEAR_COLOR}80`,
    });

    if (period === "daily") {
      if (d[6] != null) kLines.push({ time, value: d[6] as number });
      if (d[7] != null) dLines.push({ time, value: d[7] as number });
      if (d[8] != null) jLines.push({ time, value: d[8] as number });
      if (d[9] != null) trendLines.push({ time, value: d[9] as number });
      if (d[10] != null) dkLines.push({ time, value: d[10] as number });
    } else {
      if (d[6] != null) ma5Lines.push({ time, value: d[6] as number });
      if (d[7] != null) ma10Lines.push({ time, value: d[7] as number });
      if (d[8] != null) ma20Lines.push({ time, value: d[8] as number });
      if (d[9] != null) ma60Lines.push({ time, value: d[9] as number });
      if (d[10] != null) trendLines.push({ time, value: d[10] as number });
      if (d[11] != null) dkLines.push({ time, value: d[11] as number });
    }
  }

  return {
    candles,
    volumes,
    kLines,
    dLines,
    jLines,
    trendLines,
    dkLines,
    ma5Lines,
    ma10Lines,
    ma20Lines,
    ma60Lines,
  };
}

export function KlineChart({ data, period, onCrosshairMove, className = "" }: KlineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  const handleCrosshair = useCallback(
    (param: MouseEventParams<Time>) => {
      if (!onCrosshairMove || !candleSeriesRef.current) return;

      if (!param.time || !param.seriesData) {
        onCrosshairMove(null);
        return;
      }

      const candleData = param.seriesData.get(candleSeriesRef.current) as
        | CandlestickData<Time>
        | undefined;
      if (!candleData) {
        onCrosshairMove(null);
        return;
      }

      const idx = data.findIndex((d) => d[0] === param.time);
      if (idx === -1) {
        onCrosshairMove(null);
        return;
      }

      const d = data[idx];
      const prevClose = idx > 0 ? (data[idx - 1][2] as number) : (d[1] as number);
      const change = prevClose ? (((d[2] as number) - prevClose) / prevClose) * 100 : 0;

      const overlay: KlineOverlay = {
        date: d[0] as string,
        open: d[1] as number,
        high: d[4] as number,
        low: d[3] as number,
        close: d[2] as number,
        volume: d[5] as number,
        change,
      };

      if (period === "daily") {
        overlay.kdjK = d[6] as number | undefined;
        overlay.kdjD = d[7] as number | undefined;
        overlay.kdjJ = d[8] as number | undefined;
        overlay.trendLine = d[9] as number | undefined;
        overlay.dkLine = d[10] as number | undefined;
      }

      onCrosshairMove(overlay);
    },
    [data, period, onCrosshairMove],
  );

  useEffect(() => {
    if (!containerRef.current || !data.length) return;

    const container = containerRef.current;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { color: CANVAS_BG },
        textColor: TEXT_COLOR,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif',
      },
      grid: {
        vertLines: { color: GRID_COLOR },
        horzLines: { color: GRID_COLOR },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: `${ACCENT_COLOR}40`, style: LineStyle.Dashed, width: 1 },
        horzLine: { color: `${ACCENT_COLOR}40`, style: LineStyle.Dashed, width: 1 },
      },
      rightPriceScale: {
        borderColor: GRID_COLOR,
      },
      timeScale: {
        borderColor: GRID_COLOR,
        timeVisible: false,
      },
    });

    chartRef.current = chart;

    const parsed = parseKlineData(data, period);

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: BULL_COLOR,
      downColor: BEAR_COLOR,
      borderUpColor: BULL_COLOR,
      borderDownColor: BEAR_COLOR,
      wickUpColor: BULL_COLOR,
      wickDownColor: BEAR_COLOR,
    });
    candleSeries.setData(parsed.candles);
    candleSeriesRef.current = candleSeries;

    // Trend line
    if (parsed.trendLines.length > 0) {
      const trendSeries = chart.addLineSeries({
        color: "#3b82f6",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      trendSeries.setData(parsed.trendLines);
    }

    // DK line
    if (parsed.dkLines.length > 0) {
      const dkSeries = chart.addLineSeries({
        color: "#f59e0b",
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      dkSeries.setData(parsed.dkLines);
    }

    // Weekly MAs
    if (period === "weekly") {
      const maConfigs = [
        { data: parsed.ma5Lines, color: "#3b82f6" },
        { data: parsed.ma10Lines, color: "#f59e0b" },
        { data: parsed.ma20Lines, color: "#c0785a" },
        { data: parsed.ma60Lines, color: "#9c9590" },
      ];
      for (const ma of maConfigs) {
        if (ma.data.length > 0) {
          const s = chart.addLineSeries({
            color: ma.color,
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          s.setData(ma.data);
        }
      }
    }

    // Subscribe to crosshair
    chart.subscribeCrosshairMove(handleCrosshair);

    // Fit content
    chart.timeScale().fitContent();

    // Resize observer
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        chart.applyOptions({ width, height });
      }
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.unsubscribeCrosshairMove(handleCrosshair);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, [data, period, handleCrosshair]);

  return <div ref={containerRef} className={`w-full ${className}`} />;
}
