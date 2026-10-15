"""Generate a synthetic CAN log (ASC format) from a DBC file.

No hardware and no CANoe needed. Frame timing comes from the cycle times
stored in the DBC. Faults can be injected to give the checker something to find.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import can
import cantools

FAULTS = {
    "overspeed": "Engine speed spikes above its limit around 6.0 s.",
    "dropout": "VehicleSpeed frames go missing between 4.0 s and 4.2 s.",
    "slow_brake_light": "Brake light command reacts 250 ms late.",
}

BRAKE_WINDOWS = [(3.0, 5.0), (7.0, 8.0)]


def _brake_pressed(t: float) -> int:
    return int(any(start <= t < end for start, end in BRAKE_WINDOWS))


def _signal_values(name: str, t: float, faults: set[str]) -> dict:
    if name == "EngineData":
        rpm = 900 + 2100 * (0.5 - 0.5 * math.cos(2 * math.pi * t / 10))
        if "overspeed" in faults and 6.0 <= t < 6.1:
            rpm = 8600
        return {"EngineSpeed": rpm, "CoolantTemp": min(90.0, 20 + 7 * t)}
    if name == "VehicleSpeed":
        return {"VehicleSpeed": 12 * t}
    if name == "BrakeStatus":
        return {"BrakePedal": _brake_pressed(t)}
    if name == "LightControl":
        delay = 0.25 if "slow_brake_light" in faults else 0.02
        return {"BrakeLightCmd": _brake_pressed(t - delay)}
    raise ValueError(f"No simulation model for message {name}")


def simulate(dbc_path, out_path, duration: float = 10.0, faults=(), seed: int = 1) -> int:
    """Write an ASC log. Returns the number of frames written."""
    unknown = set(faults) - set(FAULTS)
    if unknown:
        raise ValueError(f"Unknown fault(s): {', '.join(sorted(unknown))}")
    faults = set(faults)
    db = cantools.database.load_file(str(dbc_path))
    rng = random.Random(seed)

    events = []
    for msg in db.messages:
        if not msg.cycle_time:
            continue
        period = msg.cycle_time / 1000.0
        for k in range(int(duration / period)):
            t = (k + 1) * period + rng.uniform(-0.02, 0.02) * period
            if "dropout" in faults and msg.name == "VehicleSpeed" and 4.0 <= t < 4.2:
                continue
            data = msg.encode(_signal_values(msg.name, t, faults), strict=False)
            events.append((t, msg.frame_id, bytes(data)))
    events.sort()

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with can.ASCWriter(str(out_path), channel=1) as writer:
        for t, frame_id, data in events:
            writer.on_message_received(
                can.Message(timestamp=t, arbitration_id=frame_id, data=data,
                            is_extended_id=False, channel=1)
            )
    return len(events)
