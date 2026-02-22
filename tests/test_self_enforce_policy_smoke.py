import json
from pathlib import Path


def test_self_enforce_policy_smoke():
    policy_path = Path("team/mcp-skills/policies/role_policy_coder_a.json")
    assert policy_path.exists(), f"Missing policy file: {policy_path}"

    with policy_path.open("r", encoding="utf-8") as f:
        policy = json.load(f)

    for key in ("default", "allow", "deny", "self_enforcement"):
        assert key in policy, f"Missing key in policy JSON: {key}"

    assert policy["default"] == "deny", "Policy default must be 'deny'"
