// Smoke test for the PredictionMarket frontend's exact client path:
// genlayer-js reads + a real create_market write on StudioNet.
// Usage: node scripts/smoke-test.mjs [--create]
import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const CONTRACT = "0x0170f655B02435d3fA95fd883d43e57F7beAfe71";
const DO_CREATE = process.argv.includes("--create");

function toPlain(v) {
  if (v instanceof Map) {
    const o = {};
    for (const [k, val] of v.entries()) o[k] = toPlain(val);
    return o;
  }
  if (Array.isArray(v)) return v.map(toPlain);
  if (typeof v === "bigint") return v.toString();
  return v;
}

const client = createClient({ chain: studionet });

console.log("== reads (no wallet) ==");
const count = await client.readContract({ address: CONTRACT, functionName: "get_market_count", args: [] });
console.log("get_market_count ->", toPlain(count), typeof count);
const pool = await client.readContract({ address: CONTRACT, functionName: "get_pool_balance", args: [] });
console.log("get_pool_balance ->", toPlain(pool));
const markets = await client.readContract({ address: CONTRACT, functionName: "list_markets", args: [] });
console.log("list_markets raw type:", markets?.constructor?.name, "->", JSON.stringify(toPlain(markets)));

if (!DO_CREATE) {
  console.log("reads OK. Re-run with --create to test the write path.");
  process.exit(0);
}

console.log("== write: create_market (generated demo account) ==");
const account = createAccount();
console.log("demo account:", account.address);
const writer = createClient({ chain: studionet, account });
const deadline = Math.floor(Date.UTC(2026, 10, 26, 0, 0, 0) / 1000);
console.log("deadline_ts:", deadline);
const hash = await writer.writeContract({
  address: CONTRACT,
  functionName: "create_market",
  args: [
    "Will the genlayer-prediction-market repo still be public on GitHub on 2026-11-26?",
    "https://github.com/mutkibubu9998/genlayer-prediction-market",
    deadline,
  ],
  value: 0n,
});
console.log("tx hash:", hash);
const receipt = await writer.waitForTransactionReceipt({ hash, status: "ACCEPTED", retries: 40, interval: 5000 });
console.log("receipt status:", receipt?.status, "| tx:", receipt?.transactionHash ?? hash);
const count2 = await client.readContract({ address: CONTRACT, functionName: "get_market_count", args: [] });
console.log("get_market_count after ->", toPlain(count2));
const markets2 = await client.readContract({ address: CONTRACT, functionName: "list_markets", args: [] });
console.log("list_markets after ->", JSON.stringify(toPlain(markets2), null, 2));
