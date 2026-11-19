"""Integration tests for PredictionMarket against GLSim (localnet).

Full consensus: leader + validators run the resolution with mocked web/LLM
responses (via transaction_context), so no real LLM API key is needed.
Accounts are funded through GLSim's sim_fundAccount RPC.

Requires a running simulator: glsim --port 4000 --validators 5
Run: gltest tests/integration/ -v -s --network localnet
"""

import json
import urllib.request

from gltest import create_accounts, get_contract_factory, get_default_account
from gltest.assertions import tx_execution_failed, tx_execution_succeeded

ONE_GEN = 10**18
FUTURE_DEADLINE = 1893456000  # 2030-01-01T00:00:00Z
EVIDENCE_URL = "https://example.com/events/final-1"
GLSIM_URL = "http://127.0.0.1:4000/api"


def _rpc(method, params):
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()
    req = urllib.request.Request(
        GLSIM_URL, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    if "error" in payload:
        raise RuntimeError(f"GLSim RPC {method} failed: {payload['error']}")
    return payload["result"]


def _fund(address, amount):
    _rpc("sim_fundAccount", {"account_address": address, "amount": amount})


def _resolution_context(outcome, with_time=True):
    """Mocks for resolve_market: evidence page + LLM verdict, time past deadline."""
    ctx = {
        "validators": [
            {
                "plugin_config": {
                    "mock_web_response": {
                        "nondet_web_request": {
                            EVIDENCE_URL: {
                                "status": 200,
                                "body": "Team A won the final 2-1.",
                            }
                        }
                    },
                    "mock_response": {
                        "response": {
                            ".*resolving a YES/NO prediction market.*": json.dumps(
                                {
                                    "outcome": outcome,
                                    "evidence": "Decisive fact from the page.",
                                    "confidence": 95,
                                }
                            )
                        }
                    },
                }
            }
        ],
    }
    if with_time:
        ctx["genvm_datetime"] = "2030-01-02T00:00:00Z"
    return ctx


def _deploy_and_fund():
    factory = get_contract_factory("PredictionMarket")
    contract = factory.deploy(args=[])
    owner = get_default_account()
    alice, bob = create_accounts(2)
    _fund(owner.address, 10 * ONE_GEN)
    _fund(alice.address, 10 * ONE_GEN)
    _fund(bob.address, 10 * ONE_GEN)
    return contract, owner, alice, bob


def _create_market(contract):
    receipt = contract.create_market(
        args=["Will Team A win the final?", EVIDENCE_URL, FUTURE_DEADLINE]
    ).transact()
    assert tx_execution_succeeded(receipt)
    return "mkt_0"


def test_full_flow_stake_resolve_claim():
    contract, owner, alice, bob = _deploy_and_fund()
    market_id = _create_market(contract)

    # Alice stakes 1 GEN on YES, Bob stakes 2 GEN on NO
    receipt = contract.connect(alice).stake(args=[market_id, "YES"]).transact(
        value=ONE_GEN
    )
    assert tx_execution_succeeded(receipt)
    receipt = contract.connect(bob).stake(args=[market_id, "NO"]).transact(
        value=2 * ONE_GEN
    )
    assert tx_execution_succeeded(receipt)

    market = contract.get_market(args=[market_id]).call()
    assert market["total_yes"] == ONE_GEN
    assert market["total_no"] == 2 * ONE_GEN
    assert market["status"] == "open"

    # Resolve after the deadline (mocked evidence + LLM say YES)
    receipt = contract.resolve_market(args=[market_id]).transact(
        transaction_context=_resolution_context("YES")
    )
    assert tx_execution_succeeded(receipt)
    market = contract.get_market(args=[market_id]).call()
    assert market["status"] == "resolved"
    assert market["outcome"] == "YES"

    # Winner claims the whole 3 GEN pot; loser claims 0 but is recorded
    receipt = contract.connect(alice).claim(args=[market_id]).transact()
    assert tx_execution_succeeded(receipt)
    stake = contract.get_stake(args=[market_id, alice.address]).call()
    assert stake["claimed"] is True

    receipt = contract.connect(bob).claim(args=[market_id]).transact()
    assert tx_execution_succeeded(receipt)
    stake = contract.get_stake(args=[market_id, bob.address]).call()
    assert stake["claimed"] is True


def test_void_market_refunds():
    contract, owner, alice, bob = _deploy_and_fund()
    market_id = _create_market(contract)

    receipt = contract.connect(alice).stake(args=[market_id, "YES"]).transact(
        value=ONE_GEN
    )
    assert tx_execution_succeeded(receipt)

    receipt = contract.resolve_market(args=[market_id]).transact(
        transaction_context=_resolution_context("VOID")
    )
    assert tx_execution_succeeded(receipt)
    market = contract.get_market(args=[market_id]).call()
    assert market["status"] == "void"
    assert market["outcome"] == "VOID"

    receipt = contract.connect(alice).claim(args=[market_id]).transact()
    assert tx_execution_succeeded(receipt)
    stake = contract.get_stake(args=[market_id, alice.address]).call()
    assert stake["claimed"] is True


def test_resolve_before_deadline_fails():
    contract, owner, alice, bob = _deploy_and_fund()
    market_id = _create_market(contract)

    # No genvm_datetime override: sim time is 2026 (reset by the fixture),
    # before the 2030 deadline — mocks are still installed so the leader
    # does not call a real LLM.
    receipt = contract.resolve_market(args=[market_id]).transact(
        transaction_context=_resolution_context("YES", with_time=False)
    )
    assert tx_execution_failed(receipt)
    market = contract.get_market(args=[market_id]).call()
    assert market["status"] == "open"
