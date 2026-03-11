import { useKline } from "@/lib/hooks";
import { chartColors } from "@/lib/tokens";

interface MiniSparklineProps {
  code: string;
  className?: string;
}

function buildPolyline(
  values: (number | null)[],
  width: number,
  height: number,
  minVal: number,
  maxVal: number,
): string {
  const range = maxVal - minVal || 1;
  const points: string[] = [];
  const step = width / Math.max(values.length - 1, 1);

  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v == null) continue;
    const x = i * step;
    const y = height - ((v - minVal) / range) * height;
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return points.join(" ");
}

export function MiniSparkline({ code, className = "" }: MiniSparklineProps) {
  const { data: klineData } = useKline(code, "daily");

  if (!klineData?.data?.length) {
    return <div className={`bg-elevated rounded-lg ${className}`} />;
  }

  const raw = klineData.data;
  const days = 60;
  const slice = raw.slice(-days);

  const closes = slice.map((d) => d[2] as number);
  const trends = slice.map((d) =>
    d[9] != null ? (d[9] as number) : null,
  );
  const dks = slice.map((d) =>
    d[10] != null ? (d[10] as number) : null,
  );

  const allValues = [
    ...closes,
    ...trends.filter((v): v is number => v != null),
    ...dks.filter((v): v is number => v != null),
  ];
  const minVal = Math.min(...allValues);
  const maxVal = Math.max(...allValues);

  const W = 200;
  const H = 48;
  const pad = 1;
  const innerW = W - pad * 2;
  const innerH = H - pad * 2;

  const closePoints = buildPolyline(closes, innerW, innerH, minVal, maxVal);
  const trendPoints = buildPolyline(trends, innerW, innerH, minVal, maxVal);
  const dkPoints = buildPolyline(dks, innerW, innerH, minVal, maxVal);

  const lastClose = closes[closes.length - 1];
  const firstClose = closes[0];
  const isBull = lastClose >= firstClose;

  const areaPoints = closePoints
    ? `${pad},${H - pad} ${closePoints
        .split(" ")
        .map((p) => {
          const [x, y] = p.split(",");
          return `${(parseFloat(x) + pad).toFixed(1)},${(parseFloat(y) + pad).toFixed(1)}`;
        })
        .join(" ")} ${innerW + pad},${H - pad}`
    : "";

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={`${className}`}
      preserveAspectRatio="none"
    >
      {areaPoints && (
        <polygon
          points={areaPoints}
          fill={isBull ? "rgba(239,68,68,0.08)" : "rgba(34,197,94,0.08)"}
        />
      )}
      {closePoints && (
        <polyline
          points={closePoints.split(" ").map((p) => {
            const [x, y] = p.split(",");
            return `${(parseFloat(x) + pad).toFixed(1)},${(parseFloat(y) + pad).toFixed(1)}`;
          }).join(" ")}
          fill="none"
          stroke={isBull ? chartColors.bull : chartColors.bear}
          strokeWidth="1"
          opacity="0.4"
        />
      )}
      {trendPoints && (
        <polyline
          points={trendPoints.split(" ").map((p) => {
            const [x, y] = p.split(",");
            return `${(parseFloat(x) + pad).toFixed(1)},${(parseFloat(y) + pad).toFixed(1)}`;
          }).join(" ")}
          fill="none"
          stroke={chartColors.trend}
          strokeWidth="1.5"
        />
      )}
      {dkPoints && (
        <polyline
          points={dkPoints.split(" ").map((p) => {
            const [x, y] = p.split(",");
            return `${(parseFloat(x) + pad).toFixed(1)},${(parseFloat(y) + pad).toFixed(1)}`;
          }).join(" ")}
          fill="none"
          stroke="#f59e0b"
          strokeWidth="1.5"
        />
      )}
    </svg>
  );
}
