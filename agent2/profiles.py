"""
Champion archetype profiles over the consolidated behavior set.

Weights multiply each behavior's utility. Keys must match behavior names in
agent2/behaviors.py. >1 prefer, <1 avoid, 0 effectively never. This is what makes
each class play distinctly over the SAME ~25 behaviors.

Behavior names:
  last_hit push_wave poke auto_trade cc_diver shield_ally body_block self_peel
  dive_carry pick_isolated collapse all_in focus_target protect_carry reposition
  secure_objective contest_objective trade_objective ward flee disengage recall
  group roam hold
"""
from __future__ import annotations

ENCHANTER = {   # Sona, Lulu: protect/peel/shield, stay back, don't dive/farm
    "shield_ally": 1.9,
    "cc_diver": 1.6,
    "body_block": 1.4,
    "ward": 1.1,
    "protect_carry": 1.3,
    "poke": 0.6,
    "group": 1.2,
    "self_peel": 1.0,
    "last_hit": 0.15, "push_wave": 0.2,
    "dive_carry": 0.2, "pick_isolated": 0.2, "all_in": 0.3,
    "focus_target": 0.5,
    "roam": 0.8,
    "flee": 1.3, "disengage": 1.2, "recall": 1.0, "hold": 1.0,
    "secure_objective": 0.7, "contest_objective": 0.5, "trade_objective": 0.6,
}

MAGE = {        # Ryze: poke/burst from range, farm to scale, don't dive
    "poke": 1.6,
    "focus_target": 1.4,
    "last_hit": 1.3, "push_wave": 0.9,
    "auto_trade": 0.9,
    "pick_isolated": 0.9,
    "reposition": 1.1,
    "self_peel": 1.0,
    "cc_diver": 0.6, "shield_ally": 0.0, "body_block": 0.2,
    "dive_carry": 0.5, "collapse": 0.8, "all_in": 0.7,
    "ward": 0.3, "group": 1.0, "roam": 0.9,
    "flee": 1.6, "disengage": 1.3, "recall": 1.0, "hold": 0.5,
    "secure_objective": 0.8, "contest_objective": 0.6,
}

MARKSMAN = {    # ADC: farm hard, kite-auto, focus in fights; never initiate
    "last_hit": 1.7, "push_wave": 1.0,
    "auto_trade": 1.4,
    "focus_target": 1.6,
    "self_peel": 1.2, "reposition": 1.2,
    "poke": 0.6,
    "cc_diver": 0.2, "shield_ally": 0.0, "body_block": 0.0,
    "dive_carry": 0.2, "pick_isolated": 0.3, "collapse": 0.6, "all_in": 0.5,
    "ward": 0.0, "group": 1.1, "roam": 0.4,
    "flee": 1.7, "disengage": 1.3, "recall": 1.0, "hold": 0.4,
    "secure_objective": 0.8, "contest_objective": 0.7,
}

BRUISER = {     # Jax: dive the carry, catch picks, commit; durable
    "dive_carry": 1.6,
    "pick_isolated": 1.4,
    "all_in": 1.4,
    "collapse": 1.2,
    "focus_target": 1.2,
    "auto_trade": 1.1, "push_wave": 0.9, "last_hit": 0.8,
    "self_peel": 0.6,
    "cc_diver": 0.4, "shield_ally": 0.0, "body_block": 0.2,
    "protect_carry": 0.2, "reposition": 0.2,
    "ward": 0.3, "group": 0.6, "roam": 0.7,
    "flee": 0.9, "disengage": 0.6, "recall": 0.8, "hold": 0.3,
    "secure_objective": 0.8, "contest_objective": 0.9,
}

TANK = {        # Zac: engage with the body, peel allies with CC, frontline
    "cc_diver": 1.5,
    "body_block": 1.4,
    "collapse": 1.3,
    "contest_objective": 1.2,
    "group": 1.3,
    "dive_carry": 1.2,
    "protect_carry": 1.0,
    "focus_target": 0.7,
    "self_peel": 0.6,
    "last_hit": 0.4, "push_wave": 0.6, "poke": 0.5, "auto_trade": 0.6,
    "shield_ally": 0.0,
    "ward": 0.6, "roam": 0.7,
    "flee": 0.5, "disengage": 0.5, "recall": 0.7, "hold": 0.5,
    "secure_objective": 1.0, "trade_objective": 0.6,
}

ARCHETYPES = {
    "ENCHANTER": ENCHANTER, "MAGE": MAGE, "MARKSMAN": MARKSMAN,
    "BRUISER": BRUISER, "TANK": TANK,
}

CHAMPION_ARCHETYPE = {
    "Sona": "ENCHANTER", "Lulu": "ENCHANTER", "Ryze": "MAGE",
    "Jax": "BRUISER", "Zac": "TANK",
}


def _base_key(name: str) -> str:
    return name.rstrip("0123456789")   # 'Jax2' -> 'Jax' (mirror matchups)


def profile_for_champion(name: str) -> dict[str, float]:
    arch = CHAMPION_ARCHETYPE.get(_base_key(name))
    return dict(ARCHETYPES.get(arch, {})) if arch else {}


def archetype_of(name: str) -> str:
    return CHAMPION_ARCHETYPE.get(_base_key(name), "UNKNOWN")
