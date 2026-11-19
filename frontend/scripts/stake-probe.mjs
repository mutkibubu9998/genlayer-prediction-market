// Stake-path probe: does a 0-GEN account fail on stake (expected), and what
// does the receipt look like? No state changes on a failed execution.
// Usage: node scripts/stake-probe.mjs
import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const CONTRACT = "0x0170f655B02435d3fA95fd883d43e57F7beAfe71";
const account = createAccount();
console.log("probe account:", account.address);
const writer = createClient({ chain: studionet, account });
try {
  const hash = await writer.writeContract({
    address: CONTRACT,
    functionName: "stake",
    args: ["mkt_0", "YES"],
    value: 10n ** 18n, // 1 GEN
  });
  console.log("tx hash:", hash);
  const receipt = await writer.waitForTransactionReceipt({ hash, status: "ACCEPTED", retries: 40, interval: 5000 });
  console.log("receipt:", JSON.stringify(receipt, (k, v) => typeof v === "bigint" ? v.toString() : v, 2).slice(0, 2000));
} catch (e) {
  console.log("stake failed as expected (or unexpectedly):", e?.shortMessage ?? e?.message ?? e);
}
const reader = createClient({ chain: studionet });
const m = await reader.readContract({ address: CONTRACT, functionName: "get_market", args: ["mkt_0"] });
console.log("mkt_0 after probe:", JSON.stringify(m, (k, v) => typeof v === "bigint" ? v.toString() : v));
