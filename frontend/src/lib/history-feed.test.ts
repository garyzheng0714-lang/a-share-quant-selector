import { describe, expect, it } from "vitest";

import type { CloudStairHistoryRow } from "./api";
import {
  HISTORY_ROW_HEIGHT,
  groupHistoryRows,
  shouldPrefetchMore,
  visibleWindow,
} from "./history-feed";

function row(id: string, date: string): CloudStairHistoryRow {
  return {
    signal_id: id,
    code: id.slice(-6),
    name: "测试",
    exchange: "SZSE",
    board: "main",
    signal_date: date,
    close: 1,
    t1_settled: true,
    t1_win: true,
    t1_net_return_pct: 1,
    t5_settled: false,
    t5_net_return_pct: null,
    t20_settled: false,
    t20_net_return_pct: null,
  };
}

describe("groupHistoryRows", () => {
  it("inserts one group header per consecutive date", () => {
    const items = groupHistoryRows([
      row("a", "2026-08-14"),
      row("b", "2026-08-14"),
      row("c", "2026-08-13"),
    ]);
    expect(items.map((item) => item.kind)).toEqual(["group", "row", "row", "group", "row"]);
    expect(items[0]).toMatchObject({ kind: "group", date: "2026-08-14", count: 2 });
    expect(items[3]).toMatchObject({ kind: "group", date: "2026-08-13", count: 1 });
  });
});

describe("shouldPrefetchMore", () => {
  it("loads the next 50 when the remaining list is within 50 rows", () => {
    expect(
      shouldPrefetchMore({
        loadedCount: 50,
        total: 33342,
        remainingPx: 50 * HISTORY_ROW_HEIGHT,
      }),
    ).toBe(true);
    expect(
      shouldPrefetchMore({
        loadedCount: 100,
        total: 33342,
        remainingPx: 51 * HISTORY_ROW_HEIGHT,
      }),
    ).toBe(false);
    expect(shouldPrefetchMore({ loadedCount: 33342, total: 33342, remainingPx: 0 })).toBe(false);
  });
});

describe("visibleWindow", () => {
  it("only keeps a window of items plus buffer", () => {
    const items = groupHistoryRows(
      Array.from({ length: 80 }, (_, index) =>
        row(String(index).padStart(6, "0"), index < 22 ? "2026-08-14" : "2026-08-13"),
      ),
    );
    const window = visibleWindow(items, 0, 200, 80);
    expect(window.start).toBe(0);
    expect(window.end).toBeGreaterThan(0);
    expect(window.end).toBeLessThan(items.length);
    expect(window.padTop).toBe(0);
    expect(window.padBottom).toBeGreaterThan(0);
  });
});
