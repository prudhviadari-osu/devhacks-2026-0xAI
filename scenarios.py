"""
Demo scenarios — curated setups that each showcase a different behavior family.

Pick one with the SCENARIO env var:
    SCENARIO=dive     python3 game.py
    SCENARIO=farm     python3 game.py
    SCENARIO=teamfight HUMAN=0 python3 game.py
    ...

Each scenario returns (champions, dragon_spawn, description, who_is_human).
The point is to make the 25 behaviors visible: a given scenario forces a phase
and a situation so the relevant behaviors actually fire and you can watch them.

Scenarios:
    dive       — enemy bruiser+tank dive the ally carry -> peel family
    farm       — ally carry alone with a wave -> farming/last-hit
    teamfight  — 3v3 clustered at mid -> teamfight family (focus/protect/reposition)
    objective  — dragon up, both squads nearby -> objective family
    skirmish   — 2v2 even fight -> trading/engage family
    retreat    — outnumbered allies low on hp -> survival family (flee/disengage/recall)
    poke       — ranged mage vs a target at distance -> poke/kite
"""
from __future__ import annotations

from model.champion import Champion


def _c(name, team, role, x, y, level=9, hp_frac=1.0):
    ch = Champion(name, team, role, level=level, x=x, y=y)
    ch.hp = ch.stats.max_hp * hp_frac
    return ch


# team base corners (match the nexus positions in model/structures.py)
BASE = {"ALLY": (1000, 1000), "ENEMY": (14000, 14000)}


import random as _random
_match_rng = _random.Random()   # reseeded per match for variety


def _at_base(name, team, role, level=9):
    """Create a champion AT its team's base corner (how a real match starts)."""
    bx, by = BASE[team]
    # random spread each match so games play out differently (not deterministic)
    ox, oy = _match_rng.randint(-600, 600), _match_rng.randint(-600, 600)
    return _c(name, team, role, bx + ox, by + oy, level=level)


def dive():
    champs = [
        _c("Lulu", "ALLY", "ADC", 5500, 5500),
        _c("Sona", "ALLY", "SUPPORT", 5300, 5700),
        _c("Zac",  "ENEMY", "JUNGLE", 6800, 6800),
        _c("Jax",  "ENEMY", "TOP", 7000, 6600),
    ]
    return champs, 999, "Enemy bruiser + tank dive the ADC — watch the peel family", "Sona"


def farm():
    # ADC sits at mid-middle where the two mid waves collide (~7500,7500), with
    # one lone enemy far away so Farm outscores everything and you see CS tick up.
    champs = [
        _c("Lulu", "ALLY", "ADC", 7500, 7500),
        _c("Ryze", "ENEMY", "MID", 13000, 13000),   # enemy exists but far off
    ]
    return champs, 999, "ADC at mid with the wave — last-hitting / farming (watch CS)", None


def teamfight():
    champs = [
        _c("Lulu", "ALLY", "ADC", 7200, 7200),
        _c("Sona", "ALLY", "SUPPORT", 7000, 7400),
        _c("Ryze", "ALLY", "MID", 7400, 7000),
        _c("Zac",  "ENEMY", "JUNGLE", 7800, 7800),
        _c("Jax",  "ENEMY", "TOP", 8000, 7600),
    ]
    return champs, 999, "3v2 clustered at mid — full teamfight (focus/protect/reposition)", None


def objective():
    # both squads start near the dragon pit (~9866,4414), dragon up now
    champs = [
        _c("Lulu", "ALLY", "ADC", 8800, 5200),
        _c("Sona", "ALLY", "SUPPORT", 8600, 5400),
        _c("Zac",  "ENEMY", "JUNGLE", 10800, 3600),
        _c("Jax",  "ENEMY", "TOP", 11000, 3400),
    ]
    return champs, 0, "Dragon up, both squads near the pit — objective family", None


def skirmish():
    champs = [
        _c("Ryze", "ALLY", "MID", 6500, 6500),
        _c("Sona", "ALLY", "SUPPORT", 6300, 6700),
        _c("Jax",  "ENEMY", "TOP", 7400, 7400),
        _c("Zac",  "ENEMY", "JUNGLE", 7600, 7200),
    ]
    return champs, 999, "2v2 even fight — trading / engage family", None


def retreat():
    # allies are LOW and outnumbered -> survival behaviors (flee/disengage/recall)
    champs = [
        _c("Lulu", "ALLY", "ADC", 6500, 6500, hp_frac=0.18),
        _c("Sona", "ALLY", "SUPPORT", 6300, 6700, hp_frac=0.22),
        _c("Zac",  "ENEMY", "JUNGLE", 7200, 7200),
        _c("Jax",  "ENEMY", "TOP", 7000, 7400),
        _c("Ryze", "ENEMY", "MID", 7400, 7000),
    ]
    return champs, 999, "Allies low & outnumbered — survival family (flee/disengage/recall)", None


def poke():
    champs = [
        _c("Ryze", "ALLY", "MID", 6000, 6000),       # mage pokes
        _c("Jax",  "ENEMY", "TOP", 7200, 7200),      # target at range
    ]
    return champs, 999, "Mage vs a target at range — poke / kite", "Ryze"


def balanced_5v5():
    """A full 5v5 with TEN DISTINCT champions SPREAD ACROSS THE THREE LANES — so
    play isn't a mid-blob. Bot and top laners start in their lanes; mid in mid;
    jungle roams. Each side archetype-balanced. Champions default to their lane
    and only group/rotate when it's worth it (via the behaviors), so the map
    stays spread like a real game."""
    # Both squads meet near mid, close enough that they actually clash (the
    # lane-spread version left bot/top champs stranded far from any fight, so
    # they'd wander around their lane and never engage). Here everyone is within
    # skirmish range, so you get a real teamfight you can watch.
    # champions START at their base corners (real League) and walk out to fight.
    # Respawns also return to base. So it opens with both teams marching from
    # opposite corners toward mid, then clashing.
    blue = [("Ashe", "ADC"), ("Sona", "SUPPORT"), ("Ryze", "MID"),
            ("Darius", "TOP"), ("Zac", "JUNGLE")]
    red = [("Ahri", "ADC"), ("Lulu", "SUPPORT"), ("Lux", "MID"),
           ("Jax", "TOP"), ("Leona", "JUNGLE")]
    _match_rng.seed()   # fresh randomness each match -> varied games
    champs = [_at_base(n, "ALLY", r) for n, r in blue] + \
             [_at_base(n, "ENEMY", r) for n, r in red]
    return champs, 20, "Full 5v5 — spawn at base corners, march out, fight", None


_jit_i = [0]
def _jit():
    # small deterministic offset so lane-mates aren't perfectly stacked
    _jit_i[0] += 1
    return ((_jit_i[0] * 137) % 400) - 200


SCENARIOS = {
    "dive": dive,
    "farm": farm,
    "teamfight": teamfight,
    "objective": objective,
    "skirmish": skirmish,
    "retreat": retreat,
    "poke": poke,
    "balanced": balanced_5v5,
}


def get(name: str):
    fn = SCENARIOS.get(name)
    if fn is None:
        raise KeyError(f"unknown scenario '{name}'. "
                       f"Options: {', '.join(SCENARIOS)}")
    return fn()
