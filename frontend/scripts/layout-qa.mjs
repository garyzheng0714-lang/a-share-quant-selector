import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve("qa-shots");
fs.mkdirSync(OUT, { recursive: true });

const recommend = {
  available: true,
  trade_date: "2026-08-07",
  core_factor: {
    key: "cloud_stair",
    name: "云阶",
    plain: "双周期验证主策略",
    why: "结构确认",
  },
  honest_note: "研究工具，不构成投资建议。",
  today_buy: [
    {
      rank: 1,
      code: "603956",
      name: "威派格",
      close: 12.48,
      pct_change: 2.13,
      industry: "仪器仪表",
      cap_yi: 86,
      reason: "云阶双周期共振，板块热度靠前。",
      sector: { score: 78, rank: 12, total: 86, delta3: 6, stage: "升温" },
    },
    {
      rank: 2,
      code: "688711",
      name: "宏微科技",
      close: 41.2,
      pct_change: -0.84,
      industry: "半导体",
      cap_yi: 142,
      reason: "突破确认后回踩观察，板块仍处高位。",
      sector: { score: 81, rank: 8, total: 86, delta3: -2, stage: "高位" },
    },
  ],
};

const candidates = Array.from({ length: 8 }, (_, i) => ({
  code: String(100000 + i).padStart(6, "0"),
  name: ["兴蓉环境", "中原传媒", "威派格", "宏微科技", "中国核电", "长江电力", "招商银行", "宁德时代"][i],
  action: i < 2 ? "observe" : i === 7 ? "avoid" : "observe",
  industry: ["水务", "传媒", "仪器仪表", "半导体", "电力", "电力", "银行", "电池"][i],
  baseline: {
    close: 7.12 + i,
    J: 12.3 + i,
    signal_labels: ["B1"],
    weekly: {
      rising_count: i % 5,
      aligned: i % 5 === 4,
      gate_mode: "shadow",
      directions: { MA5: true, MA10: true, MA20: i > 2, MA60: i > 3 },
    },
    cap_yi: 100 + i * 10,
  },
  sector: { score: 40 + i * 3, rank: i + 1, total: 86, delta3: i - 2, stage: "观察" },
}));

const decision = {
  available: true,
  is_stale: false,
  trade_date: "2026-08-07",
  strategy_version: "demo",
  model_version: "demo",
  run_id: "demo-run",
  source_refs: ["a", "b"],
  freshness: { local_date: "2026-08-07", expected_date: "2026-08-07" },
  market: {
    decision_for_date: "2026-08-08",
    layer_modes: { weekly_four_ma: "shadow", market: "off", sector: "off" },
  },
  models: [
    { model_key: "market", mode: "off", status: "off" },
    { model_key: "sector", mode: "off", status: "off" },
  ],
  candidates,
};

const evolution = {
  available: true,
  data: {
    coverage_ratio: 1,
    promotion_status: "held",
    reason_codes: [],
    covered_count: 5100,
    universe_count: 5100,
    dataset_rows: 120000,
  },
};

const systemStatus = {
  available: true,
  market_data: { fresh: true, local_date: "2026-08-07", expected_date: "2026-08-07" },
};

const browser = await puppeteer.launch({
  channel: "chrome",
  headless: true,
  defaultViewport: { width: 1440, height: 1100, deviceScaleFactor: 2 },
});

const page = await browser.newPage();
await page.setRequestInterception(true);
page.on("request", (req) => {
  const url = req.url();
  if (url.includes("/api/recommend")) return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(recommend) });
  if (url.includes("/api/decision/latest")) return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(decision) });
  if (url.includes("/api/decision/evolution")) return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(evolution) });
  if (url.includes("/api/decision/system-status")) return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify(systemStatus) });
  if (url.includes("/api/")) return req.respond({ status: 200, contentType: "application/json", body: JSON.stringify({ available: false }) });
  return req.continue();
});

await page.goto("http://localhost:3001/stocks", { waitUntil: "networkidle0", timeout: 60000 });
await page.waitForSelector('[data-testid="today-recommend"]', { timeout: 20000 });
await page.waitForSelector('[data-testid="hierarchical-decision"]', { timeout: 20000 });
await new Promise((r) => setTimeout(r, 800));

const recommendBox = await page.$('[data-testid="today-recommend"]');
const decisionBox = await page.$('[data-testid="hierarchical-decision"]');
await page.screenshot({ path: path.join(OUT, "stocks-full.png"), fullPage: true });
if (recommendBox) await recommendBox.screenshot({ path: path.join(OUT, "today-recommend.png") });
if (decisionBox) await decisionBox.screenshot({ path: path.join(OUT, "decision.png") });

const overlap = await page.evaluate(() => {
  const items = [...document.querySelectorAll('[data-testid="today-recommend"] li, [data-testid="today-recommend"] [role="listitem"], [data-testid="today-recommend"] .astryx-list-item')];
  const rects = items.map((el) => el.getBoundingClientRect()).filter((r) => r.height > 0);
  let overlaps = 0;
  for (let i = 0; i < rects.length; i++) {
    for (let j = i + 1; j < rects.length; j++) {
      const a = rects[i];
      const b = rects[j];
      const yOverlap = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (yOverlap > 4) overlaps += 1;
    }
  }
  return {
    itemCount: rects.length,
    heights: rects.map((r) => Math.round(r.height)),
    overlaps,
  };
});

console.log(JSON.stringify({ out: OUT, overlap }, null, 2));
await browser.close();
