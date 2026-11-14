"""
Measurements + triage — the heart of the teammate bot.

Each tick we turn raw GameState into per-ally numbers the bot reasons over, then
score every ally (and each objective) on ONE scale so the situation picks the
target, not a hand-written priority ranking.

Model (confirmed with the user):
    time_to_die   = ally_hp / incoming_damage_rate      # secs until they die
    time_to_reach = distance_to_ally / my_move_speed     # secs for me to arrive
    reachable     = time_to_reach < time_to_die          # "can I get there in time?"
    threat        = low_hp x nearby_enemies x urgency
    reachability  = reachable? 1/(1+distance) : ~0        # distance nudge + cutoff
    help_score    = threat x reachability

An ally dying across the map => reachable is False => reachability ~0 => low score,
so the bot helps someone nearby or takes the objective instead. That is the
user's "don't run across the map and lose everyone" rule, as math.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from core.schema import Champion, GameState, Objective

# how close an enemy must be to count as "around / threatening" an ally
ENEMY_NEAR_RADIUS = 0.18
# a support watches divers APPROACH, not just arrive — anticipate within this band
ENEMY_APPROACH_RADIUS = 0.32
# tiny floor so reachability is never exactly 0 (keeps scores comparable)
UNREACHABLE_FLOOR = 0.001


@dataclass
class AllyRead:
    ally: Champion
    distance: float            # from me to this ally
    hp_frac: float
    incoming_dps: float        # HP fraction lost per second, estimated
    enemies_near: int
    time_to_die: float         # seconds (inf if not taking damage)
    time_to_reach: float       # seconds for me to arrive
    reachable: bool
    threat: float
    reachability: float
    score: float


@dataclass
class ObjectiveRead:
    objective: Objective
    distance: float
    up_now: bool
    score: float


def _dist(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)


class Triage:
    """Scores allies and objectives so the controller can pick the top one.

    `move_speed` is in the SAME normalized units/second the sim moves in. We
    default to a sim value; pass the Data-Dragon-derived speed to make
    time_to_reach realistic.
    """

    def __init__(self, move_speed: float = 0.12,
                 reach_horizon: float = 6.0):
        self.move_speed = move_speed
        # if an ally can't be reached within this many seconds, treat as too far
        self.reach_horizon = reach_horizon

    def read_allies(self, gs: GameState, prev_hp: dict[str, float],
                    dt: float) -> list[AllyRead]:
        me = gs.me()
        enemies = gs.enemies()
        reads: list[AllyRead] = []

        for ally in gs.allies():
            if ally.name == me.name:
                continue  # don't triage myself as someone to run to

            distance = _dist(me.x, me.y, ally.x, ally.y)

            # incoming damage: HP fraction lost since last tick, as a rate
            last = prev_hp.get(ally.name, ally.hp_frac)
            lost = max(0.0, last - ally.hp_frac)
            incoming_dps = (lost / dt) if dt > 0 else 0.0

            enemies_near = sum(
                1 for e in enemies
                if _dist(e.x, e.y, ally.x, ally.y) < ENEMY_NEAR_RADIUS
            )

            # ---- proximity danger: react to the THREAT of damage, not only to
            # damage already dealt. A support that waits for HP to drop reacts
            # too late to ever reach the ally. The nearest enemy's closeness
            # (and whether it's approaching) drives an anticipated-damage term. ----
            nearest_enemy_d = min(
                (_dist(e.x, e.y, ally.x, ally.y) for e in enemies),
                default=math.inf,
            )
            # 1.0 when an enemy is on the ally, decaying to 0 at the APPROACH
            # radius — this gives the support lead time to rotate before the dive
            proximity_danger = max(0.0, 1.0 - nearest_enemy_d / ENEMY_APPROACH_RADIUS)

            # effective damage rate = what's already happening, OR what a diver
            # on top of this ally would do (so time_to_die is predictive)
            anticipated_dps = proximity_danger * 0.6  # ~burst rate of a diver
            effective_dps = max(incoming_dps, anticipated_dps)

            if effective_dps > 1e-6:
                time_to_die = ally.hp_frac / effective_dps
            else:
                time_to_die = math.inf

            time_to_reach = distance / self.move_speed if self.move_speed else math.inf
            reachable = (time_to_reach < time_to_die
                         and time_to_reach <= self.reach_horizon)

            # threat: scales with LOW hp, surrounding/approaching enemies, urgency
            low_hp = 1.0 - ally.hp_frac                   # 0 (full) .. 1 (dead)
            surround = enemies_near + proximity_danger     # count + closeness
            urgency = 1.0 / (1.0 + time_to_die)            # ->1 as death nears
            # (0.3 floor on low_hp so a FULL-hp ally under a dive still scores)
            threat = (0.3 + low_hp) * (0.5 + surround) * (0.5 + urgency)

            if reachable:
                reachability = 1.0 / (1.0 + distance)      # distance nudge
            else:
                reachability = UNREACHABLE_FLOOR           # effectively ignore

            reads.append(AllyRead(
                ally=ally, distance=distance, hp_frac=ally.hp_frac,
                incoming_dps=incoming_dps, enemies_near=enemies_near,
                time_to_die=time_to_die, time_to_reach=time_to_reach,
                reachable=reachable, threat=threat,
                reachability=reachability, score=threat * reachability,
            ))
        return reads

    def read_objectives(self, gs: GameState,
                        any_ally_in_danger: bool) -> list[ObjectiveRead]:
        me = gs.me()
        reads: list[ObjectiveRead] = []
        for obj in gs.objectives:
            distance = _dist(me.x, me.y, obj.x, obj.y)
            up_now = obj.spawns_in <= 0.0
            # objectives only win the triage when nobody reachable is in danger
            base = 0.6 if up_now else 0.0
            score = base * (0.0 if any_ally_in_danger else 1.0) / (1.0 + distance)
            reads.append(ObjectiveRead(obj, distance, up_now, score))
        return reads
