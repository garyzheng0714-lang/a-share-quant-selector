import { describe, expect, it } from "vitest";
import { aggregateByStock } from "@/lib/review-stock";
import type { StrategyReviewPick } from "@/lib/api";

function pick(partial: Partial<StrategyReviewPick> & { code: string; pick_date: string }): StrategyReviewPick {
  return {
    name: partial.name ?? partial.code,
    industry: "",
    entry_date: null,
    entry_price: null,
    next_day_chg: null,
    ret_to_date: null,
    holding_sessions_to_date: null,
    ret_1: null,
    ret_5: null,
    ret_10: null,
    ret_20: null,
    status: "open",
    ...partial,
  };
}

describe("aggregateByStock", () => {
  it("keeps one row per stock code and uses first pick metrics", () => {
    const rows = aggregateByStock([
      pick({ code: "003013", name: "地铁设计", pick_date: "2026-08-05", ret_to_date: null }),
      pick({ code: "003013", name: "地铁设计", pick_date: "2026-08-04", ret_to_date: 1.0 }),
      pick({ code: "000676", name: "智度股份", pick_date: "2026-08-04", ret_to_date: 3.0 }),
    ]);
    expect(rows).toHaveLength(2);
    const metro = rows.find((row) => row.code === "003013");
    expect(metro?.pick_count).toBe(2);
    expect(metro?.first_pick_date).toBe("2026-08-04");
    expect(metro?.last_pick_date).toBe("2026-08-05");
    expect(metro?.ret_to_date).toBe(1.0);
    expect(metro?.history).toHaveLength(2);
  });
});
