"""
Game-phase / context detection — the backbone for many distinct behaviors.

The same capability family means different things in different phases, so phases
are what let a manageable set of behaviors express as ~50 distinct PATTERNS
without 50 thrashing rules. Each tick we classify the situation into a Phase;
capabilities declare which phases they're relevant in, so only ~8-12 compete at
once (the rest are gated out -> no thrash).

Phases:
    LANING     — early, near minions, few champs clashing: farm/trade/poke
    SKIRMISH   — a small fight (2-3 a side) is happening or imminent
    TEAMFIGHT  — most champions clustered and fighting
    OBJECTIVE  — dragon/objective is up and contested-ish
    RESET      — low hp / out of resources -> recall/heal
    RETREAT    — losing the current engagement, disengage
"""
from __future__ import annotations

from enum import Enum


class Phase(str, Enum):
    LANING = "LANING"
    SKIRMISH = "SKIRMISH"
    TEAMFIGHT = "TEAMFIGHT"
    OBJECTIVE = "OBJECTIVE"
    RESET = "RESET"
    RETREAT = "RETREAT"


def _dist(a, b) -> float:
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def detect_phase(p) -> Phase:
    """Classify the current situation for the acting champion `p.me`."""
    me = p.me
    allies = p.allies()
    enemies = p.enemies()
    world = p.world

    # RESET: critically low and not actively dying this instant
    if me.hp_frac < 0.25:
        near_enemy = any(_dist(me, e) < 1500 for e in enemies)
        return Phase.RETREAT if near_enemy else Phase.RESET

    if not enemies:
        return Phase.LANING

    # count how many champions are clustered near the acting champ
    cluster_radius = 2500.0
    nearby_allies = sum(1 for a in allies if _dist(me, a) < cluster_radius)
    nearby_enemies = sum(1 for e in enemies if _dist(me, e) < cluster_radius)
    combatants = nearby_allies + nearby_enemies + 1

    # OBJECTIVE: dragon up and the acting champ (or a cluster) is near the pit
    obj = world.objective
    if world.objective_up() and _dist(me, obj) < 3500 and nearby_enemies >= 1:
        return Phase.OBJECTIVE

    # TEAMFIGHT: a big cluster is fighting
    if combatants >= 5 and nearby_enemies >= 2:
        return Phase.TEAMFIGHT

    # SKIRMISH: a small fight / an enemy close enough to trade with
    nearest_enemy_d = min((_dist(me, e) for e in enemies), default=9999)
    if nearest_enemy_d < 1800:
        return Phase.SKIRMISH

    # default early/neutral state
    return Phase.LANING
