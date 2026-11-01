import type { ComposeHit, ComposeJoin, FactorComposeResponse, FactorHit } from "./api";

/** hits.json：每个扫描日每个因子命中的代码（新→旧） */
export interface HitIndex {
  dates: string[];
  hits: Record<string, Record<string, string[]>>;
}

/** scan/{date}.json：当日每个因子的命中明细 + 命中股近 20 日收盘 */
export interface ScanDay {
  factors: Record<string, { hits: FactorHit[]; total_scanned: number }>;
  spark: Record<string, number[]>;
}

function composeCodes(sets: Set<string>[], join: ComposeJoin): Set<string> {
  if (!sets.length) return new Set();
  let out = new Set(sets[0]);
  for (const s of sets.slice(1)) {
    out = join === "and" ? new Set([...out].filter((c) => s.has(c))) : new Set([...out, ...s]);
  }
  return out;
}

/** 多因子组合：任一因子没有当日结果就整体不可用；连命中天数逐个往前看扫描日，断档即停 */
export function composeFactors(
  keys: string[],
  join: ComposeJoin,
  tradeDate: string,
  index: HitIndex,
  day: ScanDay | null,
): FactorComposeResponse {
  const cache = day?.factors ?? {};
  const missing = keys.filter((k) => !(k in cache));
  if (missing.length) {
    return {
      available: false,
      reason: `${tradeDate || "当日"} 没有 ${missing.join(", ")} 的扫描结果`,
      trade_date: tradeDate,
    };
  }

  const perKey = Object.fromEntries(keys.map((k) => [k, new Map(cache[k].hits.map((h) => [h.code, h]))]));
  const codes = composeCodes(keys.map((k) => new Set(perKey[k].keys())), join);

  const history: Set<string>[] = [];
  for (const prev of index.dates.filter((d) => d < tradeDate)) {
    const prevHits = index.hits[prev] ?? {};
    if (keys.some((k) => !(k in prevHits))) break;
    history.push(composeCodes(keys.map((k) => new Set(prevHits[k])), join));
  }
  const streak = (code: string) => {
    let n = 1;
    for (const prev of history) {
      if (!prev.has(code)) break;
      n += 1;
    }
    return n;
  };

  const hits: ComposeHit[] = [...codes].map((code) => {
    const matched = keys.filter((k) => perKey[k].has(code));
    return {
      ...perKey[matched[0]].get(code)!,
      matched,
      streak: streak(code),
      streak_depth: history.length + 1,
      spark: day?.spark[code] ?? [],
    };
  });
  hits.sort(
    (a, b) =>
      b.matched.length - a.matched.length ||
      b.streak - a.streak ||
      (a.J ?? 999) - (b.J ?? 999) ||
      (a.code < b.code ? -1 : a.code > b.code ? 1 : 0),
  );

  return {
    available: true,
    keys,
    join,
    trade_date: tradeDate,
    hits,
    per_key_counts: Object.fromEntries(keys.map((k) => [k, perKey[k].size])),
    total_scanned: Math.max(0, ...keys.map((k) => cache[k].total_scanned ?? 0)),
  };
}
