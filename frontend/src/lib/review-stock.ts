import type { StrategyReviewPick } from "@/lib/api";

/** 一票一行：同代码多次命中合并，收益口径取首次选出。 */
export type StockReviewRow = StrategyReviewPick & {
  id: string;
  first_pick_date: string;
  last_pick_date: string;
  pick_count: number;
  history: StrategyReviewPick[];
};

export function aggregateByStock(picks: StrategyReviewPick[]): StockReviewRow[] {
  const groups = new Map<string, StrategyReviewPick[]>();
  for (const pick of picks) {
    const list = groups.get(pick.code) ?? [];
    list.push(pick);
    groups.set(pick.code, list);
  }

  const rows: StockReviewRow[] = [];
  for (const [code, list] of groups) {
    const history = [...list].sort((a, b) => a.pick_date.localeCompare(b.pick_date));
    const first = history[0];
    const last = history[history.length - 1];
    rows.push({
      ...first,
      id: code,
      first_pick_date: first.pick_date,
      last_pick_date: last.pick_date,
      pick_count: history.length,
      history,
      pick_date: first.pick_date,
    });
  }

  rows.sort((a, b) => {
    const byDate = b.first_pick_date.localeCompare(a.first_pick_date);
    return byDate !== 0 ? byDate : a.code.localeCompare(b.code);
  });
  return rows;
}
