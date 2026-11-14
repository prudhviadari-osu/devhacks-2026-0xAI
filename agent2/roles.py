"""
Role weight presets for the utility agent.

The same capability repertoire, weighted differently, produces different play.
Weights multiply each capability's utility score. >1 = prefer, <1 = avoid.

This is what makes bots behave by role (and makes a fight actually happen):
divers engage, carries trade/kite, supports peel/ward. Tune freely.
"""
from __future__ import annotations

SUPPORT = {
    "peel_carry": 1.6,
    "ward_objective": 1.2,
    "engage_cc": 0.7,
    "trade": 0.5,
    "kite": 0.6,
    "follow_carry": 1.0,
    "recall": 1.0,
    "disengage": 1.1,
}

CARRY = {          # ADC / mid: deal damage, kite, trade; don't dive
    "kite": 1.5,
    "trade": 1.3,
    "engage_cc": 0.6,
    "peel_carry": 0.3,
    "ward_objective": 0.6,
    "follow_carry": 0.4,
    "recall": 1.0,
    "disengage": 1.2,
}

DIVER = {          # assassin / bruiser: hunt the carry, engage hard
    "engage_cc": 1.8,
    "kite": 1.2,
    "trade": 1.1,
    "peel_carry": 0.2,
    "ward_objective": 0.4,
    "follow_carry": 0.2,
    "recall": 0.8,
    "disengage": 0.7,   # commits more; backs off less
}

BY_ROLE = {
    "SUPPORT": SUPPORT,
    "ADC": CARRY,
    "MID": CARRY,
    "JUNGLE": DIVER,
    "TOP": DIVER,
}


def weights_for(role: str) -> dict[str, float]:
    return BY_ROLE.get(role, {})
