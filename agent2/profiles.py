"""
Champion archetype profiles — personalized play, not everyone-is-a-support.

Each ARCHETYPE defines weights over the capability repertoire so a champion plays
like its class: an enchanter shields/peels, a mage pokes/zones, a bruiser dives
and sticks, a tank engages with its body and peels with CC, a marksman farms and
kites. Weight > 1 = prefer, < 1 = avoid, 0 = effectively never.

Mapping champions -> archetype is in CHAMPION_ARCHETYPE. Add a champion = map it
to an archetype (or give it a bespoke profile).

This replaces the thin role weights in roles.py with class identity, so the bots
stop all feeling support-flavored.
"""
from __future__ import annotations

# capability names (keep in sync with agent2/capabilities.py)
#   peel_carry engage_cc kite trade farm ward_objective recall disengage follow_carry

ENCHANTER = {   # Sona, Lulu: protect/peel/shield, stay back, don't dive or farm
    "peel_carry": 1.8,
    "protect_low_ally": 1.9,   # shielding/healing is their signature
    "ward_objective": 1.1,
    "trade": 0.7,            # light poke
    "kite": 0.5,
    "engage_cc": 0.5,        # only as peel, not initiation
    "focus_fire": 0.6,
    "chase": 0.3,
    "group": 1.2,            # enchanters hate being alone
    "farm": 0.15,
    "follow_carry": 1.1,     # glued to the carry
    "flee_low": 1.6,
    "recall": 1.0,
    "disengage": 1.2,
}

MAGE = {        # Ryze: poke/burst from range, zone, farm to scale, don't dive
    "trade": 1.5,           # poke is the mage's bread and butter
    "focus_fire": 1.3,      # bursts the low target in fights
    "farm": 1.3,
    "kite": 1.1,
    "engage_cc": 0.7,       # root to peel/catch, not to dive
    "chase": 0.6,
    "group": 1.0,
    "peel_carry": 0.5,
    "protect_low_ally": 0.2,
    "ward_objective": 0.6,
    "follow_carry": 0.4,
    "flee_low": 1.7,
    "recall": 1.0,
    "disengage": 1.3,       # squishy -> values escape
}

MARKSMAN = {    # (if an ADC joins): farm hard, kite, trade; never initiate
    "farm": 1.6,
    "kite": 1.5,
    "focus_fire": 1.4,
    "trade": 1.1,
    "chase": 0.7,
    "group": 1.1,
    "engage_cc": 0.3,
    "peel_carry": 0.3,
    "protect_low_ally": 0.0,
    "ward_objective": 0.5,
    "follow_carry": 0.3,
    "flee_low": 1.8,
    "recall": 1.0,
    "disengage": 1.3,
}

BRUISER = {     # Jax: dive the carry, stick to it, chase; moderately durable
    "engage_cc": 1.6,
    "chase": 1.5,           # bruisers run you down
    "trade": 1.4,
    "focus_fire": 1.2,
    "kite": 1.2,            # sticky, attack-move onto target
    "farm": 0.9,
    "group": 0.6,
    "peel_carry": 0.3,
    "protect_low_ally": 0.0,
    "ward_objective": 0.5,
    "follow_carry": 0.2,
    "flee_low": 1.0,        # durable -> flees less eagerly
    "recall": 0.8,
    "disengage": 0.6,       # commits to fights
}

TANK = {        # Zac: engage with the body, peel allies with CC, soak; low farm
    "engage_cc": 1.7,       # initiation is the tank's job
    "peel_carry": 1.3,      # also peels (body-block + CC)
    "group": 1.3,           # frontlines WITH the team
    "focus_fire": 0.7,
    "chase": 0.8,
    "ward_objective": 0.8,
    "trade": 0.6,
    "kite": 0.5,
    "protect_low_ally": 0.0,
    "farm": 0.5,
    "follow_carry": 0.5,
    "flee_low": 0.5,        # soaks damage, rarely flees
    "recall": 0.7,
    "disengage": 0.5,       # frontline: stays in, doesn't flee early
}

ARCHETYPES = {
    "ENCHANTER": ENCHANTER,
    "MAGE": MAGE,
    "MARKSMAN": MARKSMAN,
    "BRUISER": BRUISER,
    "TANK": TANK,
}

# which archetype each roster champion plays as
CHAMPION_ARCHETYPE = {
    "Sona": "ENCHANTER",
    "Lulu": "ENCHANTER",
    "Ryze": "MAGE",
    "Jax":  "BRUISER",
    "Zac":  "TANK",
}


def profile_for_champion(name: str) -> dict[str, float]:
    arch = CHAMPION_ARCHETYPE.get(name)
    return dict(ARCHETYPES.get(arch, {})) if arch else {}


def archetype_of(name: str) -> str:
    return CHAMPION_ARCHETYPE.get(name, "UNKNOWN")
