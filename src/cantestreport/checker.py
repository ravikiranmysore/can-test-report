"""Read a CAN log, decode it with a DBC and check requirements from a YAML file."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import can
import cantools
import yaml
from cantools.database.errors import DecodeError

MAX_FAILURES_SHOWN = 8


class RuleError(ValueError):
    """The requirements file is wrong."""


@dataclass
class LogData:
    signals: dict = field(default_factory=lambda: defaultdict(list))  # name -> [(t, value)]
    frames: dict = field(default_factory=lambda: defaultdict(list))   # message -> [t]
    total_frames: int = 0
    unknown_frames: int = 0
    undecodable_frames: int = 0
    duration: float = 0.0


@dataclass
class Result:
    rule_id: str
    description: str
    rtype: str
    status: str            # PASS or FAIL
    summary: str
    failures: list = field(default_factory=list)
    plot: dict | None = None


def load_log(log_path, db) -> LogData:
    data = LogData()
    first = None
    with can.LogReader(str(log_path)) as reader:
        for frame in reader:
            if first is None:
                first = frame.timestamp
            t = frame.timestamp - first
            data.total_frames += 1
            data.duration = max(data.duration, t)
            try:
                msg = db.get_message_by_frame_id(frame.arbitration_id)
            except KeyError:
                data.unknown_frames += 1
                continue
            try:
                decoded = msg.decode(bytes(frame.data), decode_choices=False)
            except (DecodeError, ValueError):
                data.undecodable_frames += 1
                continue
            data.frames[msg.name].append(t)
            for name, value in decoded.items():
                data.signals[name].append((t, float(value)))
    return data


REQUIRED = {
    "range": ["signal", "min", "max"],
    "cycle_time": ["message", "tolerance_pct"],
    "response": ["trigger_signal", "trigger_value", "expect_signal", "expect_value", "within_ms"],
}


def load_rules(path) -> list[dict]:
    raw = yaml.safe_load(Path(path).read_text())
    rules = (raw or {}).get("requirements")
    if not rules:
        raise RuleError("No 'requirements' list found in the rules file.")
    seen = set()
    for rule in rules:
        for key in ("id", "type"):
            if key not in rule:
                raise RuleError(f"A requirement is missing '{key}': {rule}")
        if rule["id"] in seen:
            raise RuleError(f"Duplicate requirement id {rule['id']}")
        seen.add(rule["id"])
        if rule["type"] not in REQUIRED:
            raise RuleError(f"{rule['id']}: unknown type '{rule['type']}'. Use one of {sorted(REQUIRED)}.")
        for key in REQUIRED[rule["type"]]:
            if key not in rule:
                raise RuleError(f"{rule['id']}: missing '{key}' for type '{rule['type']}'")
    return rules


def _no_data(rule, what) -> Result:
    return Result(rule["id"], rule.get("description", ""), rule["type"], "FAIL",
                  f"No data: {what} never appeared in the log.")


def check_range(rule, log: LogData, db) -> Result:
    samples = log.signals.get(rule["signal"])
    if not samples:
        return _no_data(rule, f"signal {rule['signal']}")
    lo, hi = rule["min"], rule["max"]
    bad = [(t, v) for t, v in samples if v < lo or v > hi]
    values = [v for _, v in samples]
    summary = (f"{len(samples)} samples, min {min(values):g}, max {max(values):g}, "
               f"allowed {lo:g} to {hi:g}. {len(bad)} out of range.")
    failures = [f"t = {t:.3f} s: {rule['signal']} = {v:g}" for t, v in bad[:MAX_FAILURES_SHOWN]]
    if len(bad) > MAX_FAILURES_SHOWN:
        failures.append(f"... and {len(bad) - MAX_FAILURES_SHOWN} more")
    plot = {"samples": samples, "lo": lo, "hi": hi, "bad": [t for t, _ in bad]}
    return Result(rule["id"], rule.get("description", ""), "range",
                  "FAIL" if bad else "PASS", summary, failures, plot)


def check_cycle_time(rule, log: LogData, db) -> Result:
    name = rule["message"]
    times = log.frames.get(name, [])
    if len(times) < 2:
        return _no_data(rule, f"message {name}")
    nominal = rule.get("nominal_ms")
    if nominal is None:
        nominal = db.get_message_by_name(name).cycle_time
    if not nominal:
        raise RuleError(f"{rule['id']}: no nominal_ms given and no cycle time in the DBC for {name}")
    tol = rule["tolerance_pct"] / 100.0
    lo, hi = nominal * (1 - tol), nominal * (1 + tol)
    gaps = [((b - a) * 1000.0, b) for a, b in zip(times, times[1:])]
    bad = [(g, t) for g, t in gaps if g < lo or g > hi]
    values = [g for g, _ in gaps]
    summary = (f"{len(times)} frames, nominal {nominal:g} ms, allowed {lo:.1f} to {hi:.1f} ms, "
               f"seen min {min(values):.1f} ms, max {max(values):.1f} ms. {len(bad)} gaps out of range.")
    failures = [f"t = {t:.3f} s: gap of {g:.1f} ms" for g, t in bad[:MAX_FAILURES_SHOWN]]
    if len(bad) > MAX_FAILURES_SHOWN:
        failures.append(f"... and {len(bad) - MAX_FAILURES_SHOWN} more")
    return Result(rule["id"], rule.get("description", ""), "cycle_time",
                  "FAIL" if bad else "PASS", summary, failures)


def check_response(rule, log: LogData, db) -> Result:
    trig = log.signals.get(rule["trigger_signal"])
    exp = log.signals.get(rule["expect_signal"])
    if not trig:
        return _no_data(rule, f"signal {rule['trigger_signal']}")
    if not exp:
        return _no_data(rule, f"signal {rule['expect_signal']}")
    limit = rule["within_ms"] / 1000.0
    events, failures, delays = 0, [], []
    for (_, prev), (t, value) in zip(trig, trig[1:]):
        if value != rule["trigger_value"] or prev == value:
            continue
        events += 1
        hit = next((te for te, ve in exp if te >= t and ve == rule["expect_value"]), None)
        if hit is None:
            failures.append(f"t = {t:.3f} s: {rule['expect_signal']} never reached {rule['expect_value']:g}")
        elif hit - t > limit:
            failures.append(f"t = {t:.3f} s: reaction after {(hit - t) * 1000:.0f} ms (limit {rule['within_ms']:g} ms)")
            delays.append(hit - t)
        else:
            delays.append(hit - t)
    if events == 0:
        return Result(rule["id"], rule.get("description", ""), "response", "FAIL",
                      "The trigger never happened, so the requirement was not exercised.")
    worst = f"{max(delays) * 1000:.0f} ms" if delays else "n/a"
    summary = f"{events} trigger event(s), slowest reaction {worst}, limit {rule['within_ms']:g} ms."
    return Result(rule["id"], rule.get("description", ""), "response",
                  "FAIL" if failures else "PASS", summary, failures)


CHECKS = {"range": check_range, "cycle_time": check_cycle_time, "response": check_response}


def run_checks(log_path, dbc_path, rules_path):
    db = cantools.database.load_file(str(dbc_path))
    rules = load_rules(rules_path)
    log = load_log(log_path, db)
    results = [CHECKS[r["type"]](r, log, db) for r in rules]
    return results, log
