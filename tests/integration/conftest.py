"""Shared fixtures for GLSim integration tests.

GLSim keeps one VM clock for the whole server process: a transaction that
warps time (genvm_datetime) leaks into later tests. Reset the clock to a
fixed date before every test so deadlines behave deterministically.
"""

import json
import urllib.request

import pytest

GLSIM_URL = "http://127.0.0.1:4000/api"
BASE_TIME = "2026-11-19T00:00:00Z"


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


@pytest.fixture(autouse=True)
def _reset_sim_time():
    _rpc("sim_setTime", {"datetime": BASE_TIME})
    yield
    _rpc("sim_setTime", {"datetime": BASE_TIME})
