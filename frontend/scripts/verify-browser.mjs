// Browser end-to-end check of the built static app:
// loads the page, reads live StudioNet state, then does a real in-browser
// stake with a demo account and verifies the on-chain total changes.
// Usage: NODE_PATH=/home/hatch/workspace/shot/node_modules node scripts/verify-browser.mjs
import { chromium } from "/home/hatch/workspace/shot/node_modules/playwright-core/index.mjs";

const URL = "http://127.0.0.1:4173/genlayer-prediction-market/";
const browser = await chromium.launch({
  executablePath: "/home/hatch/.cache/ms-playwright/chromium-1255/chrome-linux64/chrome",
  args: ["--no-sandbox", "--disable-gpu", "--proxy-bypass-list=localhost,127.0.0.1"],
  proxy: { server: "http://127.0.0.1:18080" },
});
const page = await browser.newPage({ viewport: { width: 1100, height: 900 }, ignoreHTTPSErrors: true });
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });

await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60000 });
// Wait for live data: market card + pool balance rendered from StudioNet.
await page.getByText("Will the genlayer-prediction-market repo still be public").waitFor({ timeout: 90000 });
await page.waitForTimeout(1500);
const poolBefore = await page.locator("#pool-balance").innerText();
console.log("pool balance before stake:", poolBefore);
const yesBefore = await page.locator(".market").first().innerText();
console.log("market card before stake:\n" + yesBefore.split("\n").slice(0, 12).join("\n"));

// Demo account + stake 1 GEN on YES in the browser.
await page.getByRole("button", { name: "Use demo account" }).click();
await page.waitForTimeout(1000);
console.log("wallet status:", await page.locator("#wallet-status").innerText());
await page.locator(".market").first().getByRole("button", { name: "Stake YES" }).click();
// Wait until the YES total updates to 2 GEN (consensus can take a while).
await page.getByText("YES 2 GEN").waitFor({ timeout: 240000 });
await page.waitForTimeout(1500);
const poolAfter = await page.locator("#pool-balance").innerText();
console.log("pool balance after stake:", poolAfter);
console.log("market card after stake:\n" + (await page.locator(".market").first().innerText()).split("\n").slice(0, 14).join("\n"));
console.log("activity:\n" + (await page.locator("#activity").innerText()).split("\n").slice(0, 6).join("\n"));
await page.screenshot({ path: "/home/hatch/workspace/genlayer/prediction-market/frontend/scripts/browser-verify.png", fullPage: true });
console.log("console/page errors:", errors.length ? errors : "none");
await browser.close();
console.log("BROWSER VERIFY OK");
