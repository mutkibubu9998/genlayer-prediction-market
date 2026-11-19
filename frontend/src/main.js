// PredictionMarket frontend — talks to the deployed StudioNet contract
// directly through genlayer-js. No backend, no fake data.
import { createClient, createAccount, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const CONTRACT = "0x0170f655B02435d3fA95fd883d43e57F7beAfe71";
const RPC_URL = "https://studio.genlayer.com/api";
const CHAIN_ID = 61999;
const WEI = 10n ** 18n;
const DEMO_KEY = "pm-demo-private-key";

const $ = (id) => document.getElementById(id);
const marketsEl = $("markets");
const activityEl = $("activity");

let wallet = null; // { kind: "metamask"|"demo", address, account? }
let markets = [];

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

function parseGenToWei(s) {
  const m = String(s).trim().match(/^(\d+)(?:\.(\d{1,18}))?$/);
  if (!m) throw new Error("Enter a GEN amount like 1 or 2.5");
  return BigInt(m[1]) * WEI + BigInt((m[2] || "").padEnd(18, "0") || "0");
}

function fmtGen(wei) {
  const w = BigInt(wei);
  const whole = w / WEI;
  const frac = w % WEI;
  if (frac === 0n) return `${whole} GEN`;
  return `${whole}.${frac.toString().padStart(18, "0").replace(/0+$/, "").slice(0, 4)} GEN`;
}

function fmtTs(ts) {
  return new Date(Number(ts) * 1000).toLocaleString(undefined, { timeZoneName: "short" });
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function readClient() {
  return createClient({ chain: studionet });
}

function writeClient() {
  if (!wallet) throw new Error("Connect a wallet first (MetaMask or demo account).");
  if (wallet.kind === "demo") return createClient({ chain: studionet, account: wallet.account });
  // MetaMask: the SDK signs through window.ethereum when given an address.
  return createClient({ chain: studionet, account: wallet.address });
}

function logActivity(text, hash) {
  const first = activityEl.querySelector(".muted");
  if (first) first.remove();
  const li = document.createElement("li");
  li.innerHTML = `${esc(new Date().toLocaleTimeString())} — ${esc(text)}` +
    (hash ? ` · tx <code>${esc(hash)}</code>` : "");
  activityEl.prepend(li);
}

async function loadMarkets() {
  const client = readClient();
  const [res, pool] = await Promise.all([
    client.readContract({ address: CONTRACT, functionName: "list_markets", args: [] }),
    client.readContract({ address: CONTRACT, functionName: "get_pool_balance", args: [] }),
  ]);
  markets = toPlain(res).markets || [];
  markets.sort((a, b) => Number(b.created_ts) - Number(a.created_ts));
  $("pool-balance").textContent = fmtGen(pool);
  $("market-count").textContent = `(${markets.length})`;
  renderMarkets();
}

async function myStake(marketId) {
  if (!wallet) return null;
  try {
    const s = await readClient().readContract({
      address: CONTRACT, functionName: "get_stake", args: [marketId, wallet.address],
    });
    return toPlain(s);
  } catch {
    return null;
  }
}

function marketOpen(m) {
  return m.status === "open" && Date.now() / 1000 < Number(m.deadline_ts);
}

function renderMarkets() {
  if (!markets.length) {
    marketsEl.innerHTML = `<p class="muted">No markets yet — create the first one above.</p>`;
    return;
  }
  marketsEl.innerHTML = "";
  for (const m of markets) {
    const yes = BigInt(m.total_yes), no = BigInt(m.total_no);
    const pot = yes + no;
    const yesPct = pot > 0n ? Number((yes * 100n) / pot) : 50;
    const open = marketOpen(m);
    const card = document.createElement("article");
    card.className = "market card";
    card.innerHTML = `
      <div class="row between">
        <h3>${esc(m.question)}</h3>
        <span class="badge ${m.status}">${esc(m.status.toUpperCase())}${m.outcome ? ` · ${esc(m.outcome)}` : ""}</span>
      </div>
      <p class="muted small">ID <code>${esc(m.id)}</code> · created ${fmtTs(m.created_ts)} · deadline ${fmtTs(m.deadline_ts)} ${open ? "· <b>open for staking</b>" : ""}</p>
      <p>Evidence: <a href="${esc(m.evidence_url)}" target="_blank" rel="noopener">${esc(m.evidence_url)}</a></p>
      ${m.evidence_summary ? `<p class="evidence">Verdict evidence: ${esc(m.evidence_summary)}</p>` : ""}
      <div class="potbar"><div class="yes" style="width:${yesPct}%"></div><div class="no" style="width:${100 - yesPct}%"></div></div>
      <div class="row between small">
        <span>YES <b>${fmtGen(yes)}</b></span>
        <span>Pot <b>${fmtGen(pot)}</b></span>
        <span>NO <b>${fmtGen(no)}</b></span>
      </div>
      <div class="actions" data-id="${esc(m.id)}">
        <input class="amt" type="text" inputmode="decimal" value="1" aria-label="Stake amount in GEN" ${open ? "" : "disabled"} />
        <span class="muted small">GEN</span>
        <button class="btn small yes" data-act="stake-yes" ${open ? "" : "disabled"}>Stake YES</button>
        <button class="btn small no" data-act="stake-no" ${open ? "" : "disabled"}>Stake NO</button>
        <button class="btn small" data-act="resolve" ${m.status === "open" && !open ? "" : "disabled"}>Resolve</button>
        <button class="btn small" data-act="claim" ${m.status !== "open" ? "" : "disabled"}>Claim</button>
        <span class="stake-info muted small"></span>
      </div>`;
    marketsEl.appendChild(card);
    refreshStakeInfo(card, m);
  }
}

async function refreshStakeInfo(card, m) {
  const info = card.querySelector(".stake-info");
  if (!wallet) { info.textContent = ""; return; }
  const s = await myStake(m.id);
  info.textContent = s
    ? `Your stake: ${fmtGen(s.amount)} on ${s.side}${s.claimed ? " · claimed" : ""}`
    : "You have no stake here.";
}

marketsEl.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const card = e.target.closest(".actions");
  const id = card.dataset.id;
  const act = btn.dataset.act;
  const amtInput = card.querySelector(".amt");
  btn.disabled = true;
  try {
    if (act === "stake-yes" || act === "stake-no") {
      const side = act === "stake-yes" ? "YES" : "NO";
      const value = parseGenToWei(amtInput.value);
      if (value <= 0n || value > 1000n * WEI) throw new Error("Stake must be between 0 and 1000 GEN.");
      const hash = await writeClient().writeContract({
        address: CONTRACT, functionName: "stake", args: [id, side], value,
      });
      logActivity(`Staked ${fmtGen(value)} on ${side} (${id}) — waiting for consensus…`, hash);
      await writeClient().waitForTransactionReceipt({ hash, status: "ACCEPTED", retries: 40, interval: 5000 });
      logActivity(`Stake on ${id} accepted`, hash);
    } else if (act === "resolve") {
      btn.textContent = "Resolving… (LLM + evidence, ~1 min)";
      const hash = await writeClient().writeContract({
        address: CONTRACT, functionName: "resolve_market", args: [id], value: 0n,
      });
      logActivity(`Resolve ${id} submitted — validators are fetching the evidence…`, hash);
      await writeClient().waitForTransactionReceipt({ hash, status: "ACCEPTED", retries: 60, interval: 5000 });
      const m = toPlain(await readClient().readContract({ address: CONTRACT, functionName: "get_market", args: [id] }));
      logActivity(`Market ${id} resolved: ${m.outcome}`, hash);
    } else if (act === "claim") {
      const hash = await writeClient().writeContract({
        address: CONTRACT, functionName: "claim", args: [id], value: 0n,
      });
      logActivity(`Claim on ${id} submitted…`, hash);
      await writeClient().waitForTransactionReceipt({ hash, status: "ACCEPTED", retries: 40, interval: 5000 });
      logActivity(`Claim on ${id} accepted`, hash);
    }
    await loadMarkets();
  } catch (err) {
    alert(`Failed: ${err?.shortMessage || err?.message || err}`);
  } finally {
    btn.disabled = false;
    if (act === "resolve") btn.textContent = "Resolve";
  }
});

$("create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("btn-create");
  const status = $("create-status");
  const question = $("q-question").value.trim();
  const url = $("q-url").value.trim();
  const deadline = Math.floor(new Date($("q-deadline").value).getTime() / 1000);
  if (!deadline || deadline <= Date.now() / 1000) { status.textContent = "Deadline must be in the future."; return; }
  btn.disabled = true;
  status.textContent = "Submitting…";
  try {
    const hash = await writeClient().writeContract({
      address: CONTRACT, functionName: "create_market", args: [question, url, deadline], value: 0n,
    });
    logActivity(`Created market "${question}" — waiting for consensus…`, hash);
    const receipt = await writeClient().waitForTransactionReceipt({ hash, status: "ACCEPTED", retries: 40, interval: 5000 });
    logActivity(`Market created`, hash);
    status.textContent = `Created! Tx ${hash.slice(0, 18)}…`;
    e.target.reset();
    await loadMarkets();
  } catch (err) {
    status.textContent = `Failed: ${err?.shortMessage || err?.message || err}`;
  } finally {
    btn.disabled = false;
  }
});

$("btn-refresh").addEventListener("click", () => loadMarkets().catch((e) => alert(e.message)));

function setWallet(w) {
  wallet = w;
  const label = w ? `${w.kind === "demo" ? "Demo account" : "MetaMask"} · ${w.address.slice(0, 6)}…${w.address.slice(-4)}` : "";
  $("wallet-status").textContent = w
    ? `Connected: ${label} — you can create, stake, resolve and claim.`
    : "Not connected — reads work without a wallet. Writes need MetaMask or a demo account.";
  $("btn-disconnect").classList.toggle("hidden", !w);
  $("btn-metamask").disabled = !!w;
  $("btn-demo").disabled = !!w;
  if (markets.length) renderMarkets();
}

$("btn-demo").addEventListener("click", () => {
  let pk = localStorage.getItem(DEMO_KEY);
  if (!pk) { pk = generatePrivateKey(); localStorage.setItem(DEMO_KEY, pk); }
  const account = createAccount(pk);
  setWallet({ kind: "demo", address: account.address, account });
  logActivity(`Demo account ready: ${account.address}`);
});

$("btn-disconnect").addEventListener("click", () => setWallet(null));

$("btn-metamask").addEventListener("click", async () => {
  try {
    if (!window.ethereum) { alert("MetaMask is not installed in this browser."); return; }
    const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
    if (!accounts?.length) throw new Error("No account selected.");
    try {
      await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: `0x${CHAIN_ID.toString(16)}` }] });
    } catch (err) {
      if (err.code === 4902) {
        await window.ethereum.request({
          method: "wallet_addEthereumChain",
          params: [{
            chainId: `0x${CHAIN_ID.toString(16)}`, chainName: "GenLayer Studio",
            nativeCurrency: { name: "GEN", symbol: "GEN", decimals: 18 },
            rpcUrls: [RPC_URL], blockExplorerUrls: [],
          }],
        });
      } else throw err;
    }
    setWallet({ kind: "metamask", address: accounts[0] });
    logActivity(`MetaMask connected: ${accounts[0]}`);
  } catch (err) {
    alert(`MetaMask connect failed: ${err?.message || err}`);
  }
});

if (window.ethereum) {
  window.ethereum.on?.("accountsChanged", (accs) => {
    if (wallet?.kind === "metamask") setWallet(accs.length ? { kind: "metamask", address: accs[0] } : null);
  });
}

// Restore a previous demo account (same identity across reloads).
try {
  const pk = localStorage.getItem(DEMO_KEY);
  if (pk) setWallet({ kind: "demo", address: createAccount(pk).address, account: createAccount(pk) });
} catch { /* fresh demo account on next click */ }

loadMarkets().catch((e) => {
  marketsEl.innerHTML = `<p class="muted">Could not load markets from StudioNet: ${esc(e?.message || e)}. Check your connection and press Refresh.</p>`;
});
