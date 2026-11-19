"""Direct-mode tests for PredictionMarket.

Fast, in-memory (~30ms). Leader function only — validator logic is NOT
exercised here (see tests/integration for full consensus). All web/LLM
calls are mocked.
"""

import json

import pytest

ONE_GEN = 10**18
FUTURE_DEADLINE = 1893456000  # 2030-01-01T00:00:00Z
PAST_DEADLINE = 1000000000  # 2001-09-09T01:46:40Z
EVIDENCE_URL = "https://example.com/events/final-1"


def _hex(addr) -> str:
    """Raw 20-byte test address -> 0x-prefixed hex (contract returns checksummed)."""
    return "0x" + bytes(addr).hex()


def _deal(direct_vm, *accounts):
    for acc in accounts:
        direct_vm.deal(acc, 100 * ONE_GEN)


def _create_market(contract, direct_vm, alice, question="Will Team A win the final?"):
    direct_vm.sender = alice
    return contract.create_market(question, EVIDENCE_URL, FUTURE_DEADLINE)


def _mock_resolution(direct_vm, outcome, page_text="Team A won the final 2-1."):
    direct_vm.mock_web(
        r".*example\.com/events/final-1.*",
        {"status": 200, "body": page_text},
    )
    direct_vm.mock_llm(
        r".*resolving a YES/NO prediction market.*",
        json.dumps(
            {"outcome": outcome, "evidence": "Decisive fact from the page.", "confidence": 95}
        ),
    )


def test_create_market(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/prediction_market.py")
    _deal(direct_vm, direct_alice, direct_bob)

    market_id = _create_market(contract, direct_vm, direct_alice)
    assert market_id == "mkt_0"
    assert contract.get_market_count() == 1

    m = contract.get_market(market_id)
    assert m["question"] == "Will Team A win the final?"
    assert m["evidence_url"] == EVIDENCE_URL
    assert m["status"] == "open"
    assert m["outcome"] == ""
    assert m["total_yes"] == 0
    assert m["total_no"] == 0
    assert m["deadline_ts"] == FUTURE_DEADLINE
    assert m["creator"].lower() == _hex(direct_alice).lower()

    listed = contract.list_markets()
    assert len(listed["markets"]) == 1
    assert listed["markets"][0]["id"] == "mkt_0"


def test_create_market_validation(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy("contracts/prediction_market.py")
    _deal(direct_vm, direct_alice)
    direct_vm.sender = direct_alice

    with direct_vm.expect_revert("[EXPECTED] Question is empty"):
        contract.create_market("   ", EVIDENCE_URL, FUTURE_DEADLINE)
    with direct_vm.expect_revert("[EXPECTED] evidence_url must be http(s)"):
        contract.create_market("Q?", "ftp://example.com/x", FUTURE_DEADLINE)
    with direct_vm.expect_revert("[EXPECTED] Deadline must be in the future"):
        contract.create_market("Q?", EVIDENCE_URL, PAST_DEADLINE)
    with direct_vm.expect_revert("[EXPECTED] Market not found: mkt_99"):
        contract.get_market("mkt_99")


def test_stake_yes_and_no(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/prediction_market.py")
    _deal(direct_vm, direct_alice, direct_bob)
    market_id = _create_market(contract, direct_vm, direct_alice)

    direct_vm.sender = direct_alice
    direct_vm.value = ONE_GEN
    contract.stake(market_id, "YES")

    direct_vm.sender = direct_bob
    direct_vm.value = 2 * ONE_GEN
    contract.stake(market_id, "NO")

    m = contract.get_market(market_id)
    assert m["total_yes"] == ONE_GEN
    assert m["total_no"] == 2 * ONE_GEN

    s = contract.get_stake(market_id, _hex(direct_alice))
    assert s["side"] == "YES"
    assert s["amount"] == ONE_GEN
    assert s["claimed"] is False


def test_stake_reverts(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/prediction_market.py")
    _deal(direct_vm, direct_alice, direct_bob)
    market_id = _create_market(contract, direct_vm, direct_alice)

    direct_vm.sender = direct_alice
    direct_vm.value = 0
    with direct_vm.expect_revert("[EXPECTED] Stake amount must be > 0"):
        contract.stake(market_id, "YES")

    direct_vm.value = ONE_GEN
    with direct_vm.expect_revert("[EXPECTED] side must be YES or NO"):
        contract.stake(market_id, "MAYBE")

    contract.stake(market_id, "YES")
    with direct_vm.expect_revert("[EXPECTED] Already staked on this market"):
        contract.stake(market_id, "NO")

    # Staking after the deadline reverts
    direct_vm.warp("2030-01-02T00:00:00Z")
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("[EXPECTED] Staking deadline has passed"):
        contract.stake(market_id, "NO")


def test_resolve_yes(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/prediction_market.py")
    _deal(direct_vm, direct_alice, direct_bob)
    market_id = _create_market(contract, direct_vm, direct_alice)

    direct_vm.sender = direct_alice
    direct_vm.value = ONE_GEN
    contract.stake(market_id, "YES")
    direct_vm.sender = direct_bob
    direct_vm.value = 2 * ONE_GEN
    contract.stake(market_id, "NO")

    # Cannot resolve before the deadline
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("[EXPECTED] Market deadline has not passed"):
        contract.resolve_market(market_id)

    direct_vm.warp("2030-01-02T00:00:00Z")
    _mock_resolution(direct_vm, "YES")

    outcome = contract.resolve_market(market_id)
    assert outcome == "YES"
    m = contract.get_market(market_id)
    assert m["status"] == "resolved"
    assert m["outcome"] == "YES"
    assert m["evidence_summary"] == "Decisive fact from the page."

    # Resolving twice reverts
    with direct_vm.expect_revert("[EXPECTED] Market already resolved"):
        contract.resolve_market(market_id)


def test_resolve_void_refunds(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/prediction_market.py")
    _deal(direct_vm, direct_alice, direct_bob)
    market_id = _create_market(contract, direct_vm, direct_alice)

    direct_vm.sender = direct_alice
    direct_vm.value = ONE_GEN
    contract.stake(market_id, "YES")

    direct_vm.warp("2030-01-02T00:00:00Z")
    _mock_resolution(direct_vm, "VOID", page_text="The final was postponed, no result yet.")
    outcome = contract.resolve_market(market_id)
    assert outcome == "VOID"
    assert contract.get_market(market_id)["status"] == "void"

    direct_vm.sender = direct_alice
    contract.claim(market_id)
    assert contract.get_stake(market_id, _hex(direct_alice))["claimed"] is True


def test_void_when_no_winning_stakes(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Everyone bet NO, outcome is YES -> market voids so all are refunded."""
    contract = direct_deploy("contracts/prediction_market.py")
    _deal(direct_vm, direct_alice, direct_bob)
    market_id = _create_market(contract, direct_vm, direct_alice)

    direct_vm.sender = direct_bob
    direct_vm.value = 2 * ONE_GEN
    contract.stake(market_id, "NO")

    direct_vm.warp("2030-01-02T00:00:00Z")
    _mock_resolution(direct_vm, "YES")
    outcome = contract.resolve_market(market_id)
    assert outcome == "VOID"
    assert contract.get_market(market_id)["status"] == "void"

    direct_vm.sender = direct_bob
    contract.claim(market_id)
    assert contract.get_stake(market_id, _hex(direct_bob))["claimed"] is True


def test_claim_winner_and_loser(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = direct_deploy("contracts/prediction_market.py")
    _deal(direct_vm, direct_alice, direct_bob)
    market_id = _create_market(contract, direct_vm, direct_alice)

    direct_vm.sender = direct_alice
    direct_vm.value = ONE_GEN
    contract.stake(market_id, "YES")
    direct_vm.sender = direct_bob
    direct_vm.value = 2 * ONE_GEN
    contract.stake(market_id, "NO")

    direct_vm.warp("2030-01-02T00:00:00Z")
    _mock_resolution(direct_vm, "YES")
    contract.resolve_market(market_id)

    # Winner claims (pro-rata: 1 GEN stake wins the whole 3 GEN pot)
    direct_vm.sender = direct_alice
    contract.claim(market_id)
    assert contract.get_stake(market_id, _hex(direct_alice))["claimed"] is True

    # Loser claims nothing but the claim is still recorded
    direct_vm.sender = direct_bob
    contract.claim(market_id)
    assert contract.get_stake(market_id, _hex(direct_bob))["claimed"] is True

    # Double claim reverts
    with direct_vm.expect_revert("[EXPECTED] Already claimed"):
        contract.claim(market_id)


def test_claim_reverts(direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie):
    contract = direct_deploy("contracts/prediction_market.py")
    _deal(direct_vm, direct_alice, direct_bob, direct_charlie)
    market_id = _create_market(contract, direct_vm, direct_alice)

    direct_vm.sender = direct_alice
    direct_vm.value = ONE_GEN
    contract.stake(market_id, "YES")

    # Unresolved market
    with direct_vm.expect_revert("[EXPECTED] Market not resolved yet"):
        contract.claim(market_id)

    # No stake
    direct_vm.sender = direct_charlie
    direct_vm.warp("2030-01-02T00:00:00Z")
    _mock_resolution(direct_vm, "YES")
    contract.resolve_market(market_id)
    with direct_vm.expect_revert("[EXPECTED] No stake on this market"):
        contract.claim(market_id)
