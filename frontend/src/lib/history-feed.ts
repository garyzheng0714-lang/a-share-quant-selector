import type { CloudStairHistoryRow } from "./api";

export const HISTORY_PAGE_SIZE = 50;
export const HISTORY_PREFETCH_ROWS = 50;
export const HISTORY_ROW_HEIGHT = 40;
export const HISTORY_GROUP_HEIGHT = 36;

export type HistoryListItem =
  | { kind: "group"; key: string; date: string; count: number; height: number }
  | { kind: "row"; key: string; row: CloudStairHistoryRow; height: number };

export function groupHistoryRows(rows: CloudStairHistoryRow[]): HistoryListItem[] {
  const items: HistoryListItem[] = [];
  let index = 0;
  while (index < rows.length) {
    const date = rows[index].signal_date;
    let end = index + 1;
    while (end < rows.length && rows[end].signal_date === date) end += 1;
    items.push({
      kind: "group",
      key: `g-${date}-${index}`,
      date,
      count: end - index,
      height: HISTORY_GROUP_HEIGHT,
    });
    for (let cursor = index; cursor < end; cursor += 1) {
      const row = rows[cursor];
      items.push({
        kind: "row",
        key: row.signal_id,
        row,
        height: HISTORY_ROW_HEIGHT,
      });
    }
    index = end;
  }
  return items;
}

export function historyContentHeight(items: HistoryListItem[]): number {
  return items.reduce((sum, item) => sum + item.height, 0);
}

export function shouldPrefetchMore(input: {
  loadedCount: number;
  total: number;
  remainingPx: number;
}): boolean {
  if (input.loadedCount <= 0) return false;
  if (input.loadedCount >= input.total && input.total > 0) return false;
  return input.remainingPx <= HISTORY_PREFETCH_ROWS * HISTORY_ROW_HEIGHT;
}

export function visibleWindow(
  items: HistoryListItem[],
  scrollTop: number,
  viewportHeight: number,
  bufferPx = HISTORY_PREFETCH_ROWS * HISTORY_ROW_HEIGHT,
): { start: number; end: number; padTop: number; padBottom: number } {
  const top = Math.max(0, scrollTop - bufferPx);
  const bottom = scrollTop + viewportHeight + bufferPx;
  let offset = 0;
  let start = 0;
  let padTop = 0;
  while (start < items.length && offset + items[start].height <= top) {
    offset += items[start].height;
    start += 1;
  }
  padTop = offset;
  let end = start;
  while (end < items.length && offset < bottom) {
    offset += items[end].height;
    end += 1;
  }
  const padBottom = Math.max(0, historyContentHeight(items) - offset);
  return { start, end, padTop, padBottom };
}
