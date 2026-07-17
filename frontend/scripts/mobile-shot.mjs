// 手机视口截图工具（iPhone 12 模拟：390×844 @3x 触摸）
// 用法: node scripts/mobile-shot.mjs <baseURL> <输出目录> [路径列表,逗号分隔]
// 例:   node scripts/mobile-shot.mjs http://127.0.0.1:5000 /tmp/shots /sectors,/stocks,/review
import puppeteer from "puppeteer-core";
import { mkdir } from "node:fs/promises";

const [base, outDir, pathsArg] = process.argv.slice(2);
if (!base || !outDir) {
  console.error("用法: node mobile-shot.mjs <baseURL> <outDir> [paths]");
  process.exit(1);
}
const paths = (pathsArg || "/").split(",");
await mkdir(outDir, { recursive: true });

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new" });
const page = await browser.newPage();
await page.emulate({
  viewport: { width: 390, height: 844, deviceScaleFactor: 3, isMobile: true, hasTouch: true },
  userAgent:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
});

for (const p of paths) {
  const url = base.replace(/\/$/, "") + (p.startsWith("/") ? p : "/" + p);
  const name = p === "/" ? "home" : p.replace(/\W+/g, "-").replace(/^-|-$/g, "");
  await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });
  await new Promise((r) => setTimeout(r, 1500)); // 等动画
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  await page.screenshot({ path: `${outDir}/mob-${name}.png`, fullPage: true });
  console.log(`✓ ${p} -> mob-${name}.png  横向溢出: ${overflow}px${overflow > 0 ? " ⚠️" : ""}`);
}
await browser.close();
