import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve("qa-shots-lists");
fs.mkdirSync(OUT, { recursive: true });

const NAMES = ["威派格", "宏微科技", "兴蓉环境", "中原传媒", "中国核电", "长江电力", "招商银行", "宁德时代", "隆基绿能", "比亚迪"];
const INDUSTRIES = ["仪器仪表", "半导体", "水务", "传媒", "电力", "电力", "银行", "电池", "光伏设备", "汽车整车"];

function mkStock(i, extra = {}) {
  return {
    code: String(600000 + i * 37).padStart(6, "0"),
    name: NAMES[i % NAMES.length],
    industry: INDUSTRIES[i % INDUSTRIES.length],
    close: 12 + i * 3.37,
    J: 20 + i * 4,
    market_cap: 80 + i * 23,
    ...extra,
  };
}

const ranking = {
  success: true,
  data: Array.from({ length: 12 }, (_, i) => ({
    ...mkStock(i),
    category: ["bowl_center", "near_duokong", "near_short_trend"][i % 3],
    similarity_score: 55 + i * 3.2,
    volume_ratio: 1.2,
    matched_case: null,
    match_breakdown: null,
    views: [],
    run_date: "2026-08-07",
  })),
  total: 12,
  run_date: "2026-08-07",
};

const superB1 = {
  available: true,
  trade_date: "2026-08-07",
  cap_missing: 0,
  hits: Array.from({ length: 8 }, (_, i) => ({
    ...mkStock(i),
    market_cap_yi: 80 + i * 23,
    date: "2026-08-07",
    RSI: 55 + i,
    signals: ["b1"],
    signal_labels: i % 2 === 0 ? ["B1 主升"] : ["B1", "放量"],
  })),
};

const factors = {
  trade_date: "2026-08-07",
  recent_dates: ["2026-08-07", "2026-08-06"],
  groups: ["形态类", "量能类"],
  factors: Array.from({ length: 6 }, (_, i) => ({
    key: `factor_${i}`,
    name: `示例策略 ${i + 1} · 长名称测试用于验证不会撑高定高按钮导致重叠`,
    group: i % 2 === 0 ? "形态类" : "量能类",
    desc: "策略说明文本，用于验证策略库行的两行内容不会被固定高度的按钮裁切或重叠。",
    plain: "大白话说明：这是一句偏长的策略概览文案，测试截断与对齐。",
    today_hits: i * 3,
    track: { grade: ["short_robust", "short_ok", "long_only", "unstable", "negative"][i % 5], dd: null, periods: {} },
  })),
};

function factorScan(strategy) {
  return {
    available: true,
    strategy,
    trade_date: "2026-08-07",
    total_scanned: 5000,
    hits: Array.from({ length: 6 }, (_, i) => ({
      ...mkStock(i),
      pct_change: i % 2 === 0 ? 1.23 : -0.87,
      RSI: 50 + i,
      cap_yi: 80 + i * 23,
      sector: { score: 70 + i, delta3: i - 3, rank: i + 1, total: 90, stage: "观察" },
    })),
  };
}

const performanceSummary = {
  total_records: 320,
  overall: {
    ret_1: { count: 320, win_rate: 54, avg: 0.8 },
    ret_5: { count: 300, win_rate: 58, avg: 1.6 },
    ret_10: { count: 280, win_rate: 52, avg: 1.1 },
    ret_20: { count: 260, win_rate: 49, avg: -0.3 },
    drawdown: { avg: -4.2, median: -3.1, count: 260 },
  },
  by_category: {
    bowl_center: { ret_1: { count: 100, win_rate: 55, avg: 0.9 }, ret_5: { count: 95, win_rate: 60, avg: 1.8 }, ret_10: { count: 90, win_rate: 50, avg: 1.0 }, ret_20: { count: 85, win_rate: 48, avg: -0.2 } },
  },
  by_similarity: {
    ">=80": { ret_1: { count: 60, win_rate: 62, avg: 1.4 }, ret_5: { count: 58, win_rate: 65, avg: 2.3 }, ret_10: { count: 55, win_rate: 55, avg: 1.6 }, ret_20: { count: 50, win_rate: 51, avg: 0.4 } },
  },
  benchmark: { ret_1: 0.3, ret_5: 0.9, ret_10: 0.7, ret_20: 0.2 },
};

const performanceRecords = {
  total: 40,
  records: Array.from({ length: 40 }, (_, i) => ({
    id: i,
    view_id: 1,
    run_date: "2026-08-0" + (1 + (i % 7)),
    code: String(600000 + i * 37).padStart(6, "0"),
    name: NAMES[i % NAMES.length] + (i > 9 ? "长名称压力测试股份有限公司" : ""),
    category: ["bowl_center", "near_duokong", "near_short_trend"][i % 3],
    similarity_score: 50 + i,
    sel_close: 12.3,
    buy_price: 12.4,
    ret_1: (i % 5) - 2,
    ret_5: (i % 7) - 3,
    ret_10: (i % 9) - 4,
    ret_20: (i % 11) - 5,
    max_gain: 3,
    max_drawdown: -3,
  })),
};

const sectors = {
  available: true,
  trade_date: "2026-08-07",
  series_dates: Array.from({ length: 20 }, (_, i) => `08-${(i + 1).toString().padStart(2, "0")}`),
  industries: 90,
  stocks: 5000,
  relay: [{ name: "半导体设备与材料长名称压力测试用行业分类", score: 80, heat: 80, reasons: [] }],
  ranking: Array.from({ length: 20 }, (_, i) => ({
    name: (i === 0 ? "半导体设备与材料长名称压力测试用行业分类名称超长" : INDUSTRIES[i % INDUSTRIES.length] + "板块") + (i + 1),
    score: 90 - i * 2,
    delta3: (i % 7) - 3,
    stage: ["主线", "接力", "升温", "观察"][i % 4],
    trend: "up",
    breadth_ma10: 40 + i,
    turn_ratio: 1.2,
    rank: i + 1,
    total: 20,
  })),
};

const sectorDetail = {
  available: true,
  trade_date: "2026-08-07",
  sector: { score: 80, delta3: 3, stage: "主线", rank: 1, total: 20, name: "半导体板块1" },
  stocks: Array.from({ length: 8 }, (_, i) => ({
    rank: i + 1,
    ...mkStock(i),
    ret1: 1.2,
    ret5: 3.4,
    b1: i % 2 === 0,
    b1_signals: ["B1"],
    confirmation_count: 2,
    confirmations: [],
    action: ["buy", "observe", "avoid"][i % 3],
    reason_codes: [],
    data_status: "complete",
    risk_status: "passed",
    weekly: { passed: true },
    decision_run_id: "run-1",
  })),
  total: 8,
};

const systemStatus = {
  available: true,
  as_of: "2026-08-07",
  market_data: { fresh: true, local_date: "2026-08-07", expected_date: "2026-08-07" },
  decision: { available: true, run_id: "r1", trade_date: "2026-08-07", status: "ok", model_version: "demo", candidate_counts: { buy: 3, observe: 5, avoid: 2 } },
  policy: { state: "off" },
  paper: { established: false },
  ai: { status: "not_called" },
  evolution: { status: "not_run" },
};

const stocksPage = {
  success: true,
  data: Array.from({ length: 30 }, (_, i) => mkStock(i, { latest_price: 12 + i, latest_date: "2026-08-07", data_count: 1200 })),
  total: 30,
  page: 1,
  total_pages: 1,
};

const kline = {
  success: true,
  code: "600001",
  name: "威派格",
  period: "daily",
  as_of: "2026-08-07",
  change_label: "今日涨跌",
  data: Array.from({ length: 60 }, (_, i) => [
    `2026-06-${(1 + (i % 28)).toString().padStart(2, "0")}`,
    10 + i * 0.1, 10 + i * 0.12, 9.8 + i * 0.1, 10.1 + i * 0.1, 100000,
    50 + i, 48 + i, 52 + i, 40 + i, 5, 4,
  ]),
  signals: [],
};

const stockProfile = { success: true, data: { code: "600001", name: "威派格", industry: "仪器仪表", board: "主板", business: "供水设备", listing_date: "2020-01-01", total_shares: "1亿", circ_shares: "1亿" } };

const recommend = {
  available: true,
  trade_date: "2026-08-07",
  core_factor: { key: "cloud_stair", name: "云阶", plain: "双周期验证主策略", why: "结构确认" },
  honest_note: "研究工具，不构成投资建议。",
  today_buy: Array.from({ length: 3 }, (_, i) => ({ ...mkStock(i), rank: i + 1, pct_change: 1.2, reason: "云阶双周期共振" })),
};

const routes = [
  ["/api/recommend", recommend],
  ["/api/ranking", ranking],
  ["/api/super-b1", superB1],
  ["/api/factors", factors],
  ["/api/performance/summary", performanceSummary],
  ["/api/performance/records", performanceRecords],
  ["/api/sectors/", sectorDetail],
  ["/api/sectors", sectors],
  ["/api/decision/system-status", systemStatus],
  ["/api/stocks", stocksPage],
  ["/api/stock/", kline],
  ["/api/data/coverage", { success: true, data: { covered_count: 5000, universe_count: 5100, trainable_count: 4000, trainable_eligible_count: 4200, short_history_count: 100, running: false, remaining_count: 0 } }],
];

const browser = await puppeteer.launch({
  channel: "chrome",
  headless: true,
  defaultViewport: { width: 1440, height: 1200, deviceScaleFactor: 2 },
});

const page = await browser.newPage();
page.on("pageerror", (e) => console.log("PAGEERROR:", e.message));
await page.setRequestInterception(true);
page.on("request", (req) => {
  const url = req.url();
  if (url.includes("/api/factor-scan")) {
    const m = /strategy=([^&]+)/.exec(url);
    return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(factorScan(decodeURIComponent(m?.[1] ?? "factor_0"))) });
  }
  if (url.includes("/api/stock/") && url.includes("/profile")) {
    return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(stockProfile) });
  }
  if (url.includes("/api/stock/") && url.includes("/kline")) {
    return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(kline) });
  }
  for (const [prefix, body] of routes) {
    if (url.includes(prefix)) {
      return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    }
  }
  if (url.includes("/api/")) return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify({ available: false, success: true, data: [] }) });
  return req.continue();
});

function overlapCheck(rects) {
  let overlaps = 0;
  for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i];
      const b = rects[j];
      const yOverlap = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (yOverlap > 4) overlaps += 1;
    }
  }
  return overlaps;
}

async function shootListItems(name, selector) {
  const overlap = await page.evaluate((sel) => {
    const items = [...document.querySelectorAll(sel)];
    return items.map((el) => el.getBoundingClientRect()).filter((r) => r.height > 0);
  }, selector);
  const overlaps = overlapCheck(overlap);
  console.log(JSON.stringify({ page: name, itemCount: overlap.length, overlaps }));
  return overlaps;
}

const results = {};

// 1. sectors
await page.goto("http://localhost:3001/sectors", { waitUntil: "networkidle0", timeout: 60000 });
await new Promise((r) => setTimeout(r, 900));
await page.screenshot({ path: path.join(OUT, "sectors.png"), fullPage: true });
results.sectors = await shootListItems("sectors", "li");

// 2. review (lists tab, default source=factors -> full-bleed factor workbench)
await page.goto("http://localhost:3001/review", { waitUntil: "networkidle0", timeout: 60000 });
await new Promise((r) => setTimeout(r, 900));
await page.screenshot({ path: path.join(OUT, "review-lists-factors.png"), fullPage: true });

function clickByText(text) {
  return page.evaluate((t) => {
    const btns = [...document.querySelectorAll("button")];
    const target = btns.find((b) => b.textContent?.trim().includes(t));
    target?.click();
    return !!target;
  }, text);
}

// switch source to superb1 via SegmentedControl
await clickByText("超级B1");
await new Promise((r) => setTimeout(r, 500));
await page.screenshot({ path: path.join(OUT, "review-lists-superb1.png"), fullPage: true });
results.superb1 = await shootListItems("review-superb1", "li");

await clickByText("碗口B1");
await new Promise((r) => setTimeout(r, 500));
await page.screenshot({ path: path.join(OUT, "review-lists-strategy.png"), fullPage: true });
results.strategy = await shootListItems("review-strategy", "li");

// performance tab
await clickByText("整体战绩");
await new Promise((r) => setTimeout(r, 700));
await page.screenshot({ path: path.join(OUT, "review-performance.png"), fullPage: true });
results.performance = await shootListItems("review-performance", "li");

// 3. stocks (decision + research)
await page.goto("http://localhost:3001/stocks", { waitUntil: "networkidle0", timeout: 60000 });
await new Promise((r) => setTimeout(r, 900));
await page.screenshot({ path: path.join(OUT, "stocks-decision.png"), fullPage: true });

await clickByText("其他策略");
await new Promise((r) => setTimeout(r, 900));
await page.screenshot({ path: path.join(OUT, "stocks-research.png"), fullPage: true });
results.research = await shootListItems("stocks-research", "li");

// 4. stock detail with candidate nav list populated via SuperB1 list click-through
await page.goto("http://localhost:3001/review", { waitUntil: "networkidle0", timeout: 60000 });
await new Promise((r) => setTimeout(r, 700));
await clickByText("超级B1");
await new Promise((r) => setTimeout(r, 500));
await page.evaluate(() => {
  const item = document.querySelector("li");
  item?.click();
});
await new Promise((r) => setTimeout(r, 900));
await page.screenshot({ path: path.join(OUT, "stock-detail.png"), fullPage: true });
results.stockDetailNav = await shootListItems("stock-detail-nav", "li");

console.log(JSON.stringify({ out: OUT, results }, null, 2));
await browser.close();
