# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""PredictionMarket - a YES/NO prediction market resolved by GenLayer consensus.

Anyone can create a market on a verifiable real-world event (with a deadline
and an evidence URL). Participants stake GEN on YES or NO. After the deadline,
anyone can call resolve_market: validators fetch the evidence URL and use an
LLM to decide the outcome, with a custom comparative validator function that
re-runs the same task and requires exact agreement on the outcome field.
Winners claim pro-rata payouts; if the evidence does not settle the question
(outcome VOID) or nobody staked on the winning side, everyone is refunded.

Equivalence strategy: custom leader/validator pair (run_nondet_unsafe) for the
LLM + web resolution. All money is atto-scale u256. No floats for money.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from genlayer import *

# ---------------------------------------------------------------------------
# Error classification (validators compare these prefixes, see _handle_leader_error)
# ---------------------------------------------------------------------------
ERROR_EXPECTED = "[EXPECTED]"  # Business logic (deterministic) - exact match required
ERROR_EXTERNAL = "[EXTERNAL]"  # External API 4xx (deterministic) - exact match required
ERROR_TRANSIENT = "[TRANSIENT]"  # Network/5xx (non-deterministic) - agree if both transient
ERROR_LLM = "[LLM_ERROR]"  # LLM misbehavior - always disagree, force rotation

MAX_QUESTION_LEN = 500
MAX_URL_LEN = 500
MAX_STAKE = u256(1000) * u256(10**18)  # 1000 GEN max per stake
EVIDENCE_CHARS = 6000


@allow_storage
@dataclass
class Market:
    id: str
    question: str
    evidence_url: str
    deadline_ts: u256
    status: str  # "open" | "resolved" | "void"
    outcome: str  # "" | "YES" | "NO" | "VOID"
    total_yes: u256
    total_no: u256
    creator: Address
    created_ts: u256
    evidence_summary: str


@allow_storage
@dataclass
class Stake:
    bettor: Address
    side: str  # "YES" | "NO"
    amount: u256
    claimed: bool


@gl.evm.contract_interface
class _EoaRecipient:
    class View:
        pass

    class Write:
        pass


class PredictionMarket(gl.Contract):
    owner: Address
    market_count: u256
    markets: TreeMap[str, Market]
    market_ids: DynArray[str]
    stakes: TreeMap[str, TreeMap[Address, Stake]]

    def __init__(self):
        self.owner = gl.message.sender_address
        self.market_count = u256(0)

    # ------------------------------------------------------------------
    # Helpers (deterministic)
    # ------------------------------------------------------------------
    def _now(self) -> u256:
        return u256(int(datetime.now(timezone.utc).timestamp()))

    def _get_market(self, market_id: str) -> Market:
        if market_id not in self.markets:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Market not found: {market_id}")
        return self.markets[market_id]

    def _market_to_dict(self, m: Market) -> dict:
        return {
            "id": m.id,
            "question": m.question,
            "evidence_url": m.evidence_url,
            "deadline_ts": int(m.deadline_ts),
            "status": m.status,
            "outcome": m.outcome,
            "total_yes": int(m.total_yes),
            "total_no": int(m.total_no),
            "creator": m.creator.as_hex,
            "created_ts": int(m.created_ts),
            "evidence_summary": m.evidence_summary,
        }

    def _parse_outcome(self, raw) -> dict:
        """Defensively parse the LLM resolution JSON (dict or raw string)."""
        if isinstance(raw, dict):
            data = raw
        elif isinstance(raw, str):
            text = raw
            first = text.find("{")
            last = text.rfind("}")
            if first < 0 or last < 0:
                raise gl.vm.UserError(f"{ERROR_LLM} LLM returned no JSON object")
            text = text[first : last + 1]
            text = re.sub(r",(?!\s*?[\{\[\"\'\w])", "", text)
            try:
                data = json.loads(text)
            except Exception:
                raise gl.vm.UserError(f"{ERROR_LLM} LLM JSON unparsable")
        else:
            raise gl.vm.UserError(f"{ERROR_LLM} LLM returned non-dict: {type(raw)}")

        if not isinstance(data, dict):
            raise gl.vm.UserError(f"{ERROR_LLM} LLM JSON is not an object")

        outcome = data.get("outcome")
        if outcome is None:
            for alt in ("result", "decision", "winner"):
                if alt in data:
                    outcome = data[alt]
                    break
        if outcome is None:
            raise gl.vm.UserError(f"{ERROR_LLM} Missing 'outcome'. Keys: {list(data.keys())}")

        outcome = str(outcome).strip().upper()
        if outcome not in ("YES", "NO", "VOID"):
            raise gl.vm.UserError(f"{ERROR_LLM} Invalid outcome: {outcome}")

        evidence = data.get("evidence", "")
        if not isinstance(evidence, str):
            evidence = str(evidence)
        return {"outcome": outcome, "evidence": evidence[:500]}

    def _handle_leader_error(self, leaders_res, leader_fn) -> bool:
        """Canonical error comparison for validators (see write-contract skill)."""
        leader_msg = leaders_res.message if hasattr(leaders_res, "message") else ""
        try:
            leader_fn()
            return False  # Leader errored, validator succeeded - disagree
        except gl.vm.UserError as e:
            validator_msg = e.message if hasattr(e, "message") else str(e)
            if validator_msg.startswith(ERROR_EXPECTED) or validator_msg.startswith(
                ERROR_EXTERNAL
            ):
                return validator_msg == leader_msg
            if validator_msg.startswith(ERROR_TRANSIENT) and leader_msg.startswith(
                ERROR_TRANSIENT
            ):
                return True
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Create a market
    # ------------------------------------------------------------------
    @gl.public.write
    def create_market(
        self, question: str, evidence_url: str, deadline_ts: u256
    ) -> str:
        question = question.strip()
        if len(question) == 0:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Question is empty")
        if len(question) > MAX_QUESTION_LEN:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Question too long")
        if not (
            evidence_url.startswith("http://")
            or evidence_url.startswith("https://")
        ):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} evidence_url must be http(s)")
        if len(evidence_url) > MAX_URL_LEN:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} evidence_url too long")

        now = self._now()
        if deadline_ts <= now:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Deadline must be in the future")

        market_id = f"mkt_{int(self.market_count)}"
        market = Market(
            id=market_id,
            question=question,
            evidence_url=evidence_url,
            deadline_ts=deadline_ts,
            status="open",
            outcome="",
            total_yes=u256(0),
            total_no=u256(0),
            creator=gl.message.sender_address,
            created_ts=now,
            evidence_summary="",
        )
        self.markets[market_id] = market
        self.market_ids.append(market_id)
        self.market_count = self.market_count + u256(1)
        return market_id

    # ------------------------------------------------------------------
    # Stake GEN on YES or NO (one stake per bettor per market)
    # ------------------------------------------------------------------
    @gl.public.write.payable
    def stake(self, market_id: str, side: str) -> None:
        market = self._get_market(market_id)
        if market.status != "open":
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Market is not open")
        if self._now() >= market.deadline_ts:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Staking deadline has passed")
        if side not in ("YES", "NO"):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} side must be YES or NO")

        amount = gl.message.value
        if amount == u256(0):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Stake amount must be > 0")
        if amount > MAX_STAKE:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Stake exceeds 1000 GEN max")

        sender = gl.message.sender_address
        book = self.stakes.get_or_insert_default(market_id)
        if sender in book:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Already staked on this market")

        book[sender] = Stake(bettor=sender, side=side, amount=amount, claimed=False)
        if side == "YES":
            market.total_yes = market.total_yes + amount
        else:
            market.total_no = market.total_no + amount
        self.markets[market_id] = market

    # ------------------------------------------------------------------
    # Resolve a market after its deadline (LLM + live web evidence)
    # ------------------------------------------------------------------
    @gl.public.write
    def resolve_market(self, market_id: str) -> str:
        market = self._get_market(market_id)
        if market.status != "open":
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Market already resolved")
        if self._now() < market.deadline_ts:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Market deadline has not passed")

        question = market.question
        url = market.evidence_url

        def leader_fn() -> dict:
            res = gl.nondet.web.get(url)
            if res.status == 200:
                pass
            elif 400 <= res.status < 500:
                raise gl.vm.UserError(f"{ERROR_EXTERNAL} Evidence URL returned {res.status}")
            else:
                raise gl.vm.UserError(f"{ERROR_TRANSIENT} Evidence URL returned {res.status}")
            try:
                page = res.body.decode("utf-8", errors="ignore")[:EVIDENCE_CHARS]
            except Exception:
                raise gl.vm.UserError(f"{ERROR_TRANSIENT} Evidence page undecodable")

            prompt = f"""You are resolving a YES/NO prediction market.
Question: {question}
Evidence (fetched from {url}):
{page}

Decide the outcome based ONLY on the evidence above.
Respond with JSON only, nothing else:
{{"outcome": "YES" | "NO" | "VOID", "evidence": "<one sentence quoting the decisive fact>", "confidence": <0-100>}}
Use "VOID" only if the evidence does not settle the question (event not concluded, ambiguous, or page unreadable)."""
            raw = gl.nondet.exec_prompt(prompt, response_format="json")
            return self._parse_outcome(raw)

        def validator_fn(leaders_res: gl.vm.Result) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return self._handle_leader_error(leaders_res, leader_fn)
            try:
                mine = leader_fn()
            except gl.vm.UserError:
                return False
            except Exception:
                return False
            leader_data = leaders_res.calldata
            if not isinstance(leader_data, dict):
                return False
            # Exact agreement on the decision field; free-text evidence may differ.
            return leader_data.get("outcome") == mine.get("outcome")

        result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        outcome = result["outcome"]
        evidence = result.get("evidence", "")

        # If nobody staked on the winning side, the pot cannot be paid out:
        # void the market so everyone is refunded.
        winning_total = market.total_yes if outcome == "YES" else market.total_no
        if outcome == "VOID" or winning_total == u256(0):
            market.status = "void"
            market.outcome = "VOID"
        else:
            market.status = "resolved"
            market.outcome = outcome
        market.evidence_summary = evidence
        self.markets[market_id] = market
        return market.outcome

    # ------------------------------------------------------------------
    # Claim winnings (or a refund when void)
    # ------------------------------------------------------------------
    @gl.public.write
    def claim(self, market_id: str) -> None:
        market = self._get_market(market_id)
        if market.status == "open":
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Market not resolved yet")

        sender = gl.message.sender_address
        book = self.stakes.get_or_insert_default(market_id)
        if sender not in book:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} No stake on this market")
        stake = book[sender]
        if stake.claimed:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} Already claimed")

        payout = u256(0)
        if market.status == "void":
            payout = stake.amount
        elif stake.side == market.outcome:
            total_pot = market.total_yes + market.total_no
            winning_total = (
                market.total_yes if market.outcome == "YES" else market.total_no
            )
            if winning_total > u256(0):
                payout = stake.amount * total_pot // winning_total

        stake.claimed = True
        book[sender] = stake

        if payout > u256(0):
            _EoaRecipient(sender).emit_transfer(value=payout)

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    @gl.public.view
    def get_market(self, market_id: str) -> dict:
        return self._market_to_dict(self._get_market(market_id))

    @gl.public.view
    def list_markets(self) -> dict:
        return {
            "markets": [self._market_to_dict(self.markets[mid]) for mid in self.market_ids]
        }

    @gl.public.view
    def get_stake(self, market_id: str, bettor: str) -> dict:
        self._get_market(market_id)
        book = self.stakes.get_or_insert_default(market_id)
        addr = Address(bettor)
        if addr not in book:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} No stake for this bettor")
        s = book[addr]
        return {
            "bettor": s.bettor.as_hex,
            "side": s.side,
            "amount": int(s.amount),
            "claimed": s.claimed,
        }

    @gl.public.view
    def get_market_count(self) -> u256:
        return self.market_count

    @gl.public.view
    def get_pool_balance(self) -> u256:
        return self.balance
