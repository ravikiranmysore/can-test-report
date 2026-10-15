from pathlib import Path

import pytest

from cantestreport.checker import RuleError, load_rules, run_checks
from cantestreport.simulator import simulate

ROOT = Path(__file__).resolve().parents[1]
DBC = ROOT / "dbc" / "vehicle.dbc"
RULES = ROOT / "rules" / "requirements.yaml"


def run(tmp_path, faults=()):
    log = tmp_path / "test.asc"
    simulate(DBC, log, duration=10.0, faults=faults)
    results, _ = run_checks(log, DBC, RULES)
    return {r.rule_id: r.status for r in results}


def test_clean_log_passes_everything(tmp_path):
    statuses = run(tmp_path)
    assert set(statuses.values()) == {"PASS"}


def test_overspeed_fails_only_the_range_rule(tmp_path):
    statuses = run(tmp_path, ["overspeed"])
    assert statuses["REQ-ENG-001"] == "FAIL"
    assert statuses["REQ-COM-001"] == "PASS"


def test_dropout_fails_the_cycle_time_rule(tmp_path):
    statuses = run(tmp_path, ["dropout"])
    assert statuses["REQ-COM-002"] == "FAIL"
    assert statuses["REQ-ENG-001"] == "PASS"


def test_slow_brake_light_fails_the_response_rule(tmp_path):
    statuses = run(tmp_path, ["slow_brake_light"])
    assert statuses["REQ-BRK-001"] == "FAIL"


def test_unknown_requirement_type_is_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("requirements:\n  - id: X-1\n    type: magic\n")
    with pytest.raises(RuleError):
        load_rules(bad)


def test_missing_key_is_reported(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("requirements:\n  - id: X-1\n    type: range\n    signal: EngineSpeed\n")
    with pytest.raises(RuleError, match="min"):
        load_rules(bad)
