# can-test-report

Turn a CAN log into a requirement-based test report. Fast, repeatable, no manual log reading.

Runs fully on simulated data. No CAN hardware. No CANoe. Only free Python tools.

## The problem

After a test run, someone opens a trace, checks signals by eye and writes up the results by hand. It is slow. It is easy to miss a gap or a late reaction. This tool does that check in seconds.

## What it does

- Reads a CAN log in ASC format (the format CANoe also writes) and decodes it with a DBC file.
- Checks requirements from a YAML file.
- Writes an HTML report with evidence and a signal plot, plus a JUnit XML file for CI.
- Exits with code 1 if any requirement fails, so a pipeline can stop on it.

## Requirement types

| Type | Question it answers | Example |
|---|---|---|
| `range` | Did a signal stay inside its limits? | Engine speed between 0 and 8000 rpm |
| `cycle_time` | Was a message sent on time? | EngineData every 10 ms, plus or minus 10 percent |
| `response` | Did B react to A fast enough? | Brake light on within 100 ms of brake pedal pressed |

If `nominal_ms` is missing in a cycle time rule, the value is read from the DBC (`GenMsgCycleTime`).

## Quick start

```bash
pip install -e ".[dev]"

# 1. Create a clean log and a log with three injected faults
cantestreport simulate --dbc dbc/vehicle.dbc --out logs/clean.asc
cantestreport simulate --dbc dbc/vehicle.dbc --out logs/faulty.asc \
    --fault overspeed --fault dropout --fault slow_brake_light

# 2. Check them
cantestreport run --log logs/clean.asc  --dbc dbc/vehicle.dbc --rules rules/requirements.yaml --html reports/clean.html
cantestreport run --log logs/faulty.asc --dbc dbc/vehicle.dbc --rules rules/requirements.yaml --html reports/faulty.html
```

Open `reports/faulty.html` in a browser. Three requirements fail, each with a timestamp.

## Injected faults

| Fault | What happens | Rule that catches it |
|---|---|---|
| `overspeed` | Engine speed spikes to 8600 rpm near 6.0 s | REQ-ENG-001 |
| `dropout` | VehicleSpeed frames missing for 200 ms | REQ-COM-002 |
| `slow_brake_light` | Brake light reacts 250 ms late | REQ-BRK-001 |

## Project layout

```
dbc/vehicle.dbc            signal and message definitions, with cycle times
rules/requirements.yaml    the requirements to check
src/cantestreport/
  simulator.py             makes ASC logs from the DBC, with optional faults
  checker.py               decodes the log and runs the rules
  report.py                HTML and JUnit output
  cli.py                   command line
tests/                     pytest checks for the tool itself
.github/workflows/ci.yml   runs tests and both reports on every push
```

## Use it on real logs

Export a trace from CANoe (or another tool) as ASC. Point `--log` at it, use your own DBC and edit the YAML. Nothing else changes.

## Add your own requirement type

Write one function in `checker.py` that takes a rule, the decoded log and the DBC, and returns a `Result`. Register it in `CHECKS` and list its keys in `REQUIRED`.

## Ideas for next steps

- Read BLF files (python-can supports them).
- Link requirement IDs to a DOORS or Polarion export.
- Add a rule type for signal rate of change.
