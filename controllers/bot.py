"""
BotController — the support brain, playing in the real-units World.

Reuses the decoupled brain unchanged (core/planner, measurements, controller,
health, comms). The brain speaks normalized 0..1 GameState; the World speaks
game units (~15000). This controller is the ONLY place that converts between
them, so the brain stays pure and the Overwolf transition stays easy.

Pipeline each tick:
    World  --adapt-->  GameState (0..1)
    GameState  -->  Planner (triage: who to help) + Controller (what to do)
    bot decision (priority/action/target)  --translate-->  World Action
"""
from __future__ import annotations

from controllers.base import CharacterController
from core.agent import SupportAgent
from core.comms import Comms
from core.controller import Controller as BrainController
from core.health import HealthMonitor
from core.planner import Planner
from core.schema import Champion as GChampion
from core.schema import GameState, Role, Team
from model.world import Action, Auto, Cast, Idle, Move, World, MAP_SIZE

_ROLE = {"TOP": Role.TOP, "JUNGLE": Role.JUNGLE, "MID": Role.MID,
         "ADC": Role.ADC, "SUPPORT": Role.SUPPORT}


class BotController(CharacterController):
    def __init__(self, llm=None, move_speed_norm: float = 0.12):
        self.agent = SupportAgent(
            planner=Planner(llm, move_speed=move_speed_norm),
            controller=BrainController(),
            comms=Comms(llm),
            health=HealthMonitor(),
        )
        self.last_comms = ""
        self.last_priority = ""

    def decide(self, world: World, me_name: str) -> Action:
        gs = self._world_to_gamestate(world, me_name)
        out = self.agent.act(gs)
        self.last_comms = out.comms
        self.last_priority = out.priority.value
        return self._translate(world, me_name, out)

    # ---- World (game units) -> brain GameState (normalized 0..1) ----
    def _world_to_gamestate(self, world: World, me_name: str) -> GameState:
        me = world.get(me_name)
        champs: list[GChampion] = []
        for c in world.champions:
            if not c.alive:
                continue
            champs.append(GChampion(
                name=c.name,
                team=Team.ALLY if c.team == me.team else Team.ENEMY,
                role=_ROLE.get(c.role, Role.MID),
                x=c.x / MAP_SIZE, y=c.y / MAP_SIZE,
                hp_frac=c.hp_frac, mana_frac=1.0,
                cooldowns=dict(c.cooldowns), cc_remaining=c.cc_remaining,
            ))
        from core.schema import Objective as GObjective
        obj = world.objective
        objectives = [GObjective(obj.name, obj.x / MAP_SIZE, obj.y / MAP_SIZE,
                                 obj.spawns_in)]
        return GameState(time=world.time, champions=champs,
                         objectives=objectives, self_name=me_name)

    # ---- brain decision -> concrete World Action ----
    def _translate(self, world: World, me_name: str, out) -> Action:
        me = world.get(me_name)
        action = out.action
        target = out.target

        if action == "ENGAGE_CC" and target:
            tgt = world.by_name.get(target)
            cc_slot = self._best_cc_slot(me)
            if tgt and cc_slot and me.ability_ready(cc_slot) and \
                    self._in_range(me, tgt, cc_slot):
                return Cast(cc_slot, target=target)   # champ's real CC ability
            if tgt:
                return Move(tgt.x, tgt.y)             # not ready/in range -> close

        if action == "PEEL" and target:
            ally = world.by_name.get(target)
            threat = self._nearest_enemy_to(world, me, ally)
            cc_slot = self._best_cc_slot(me)
            if threat and cc_slot and me.ability_ready(cc_slot) and \
                    self._in_range(me, threat, cc_slot):
                return Cast(cc_slot, target=threat.name)   # stun/root the diver
            if ally:
                # body-block: step between the diver and the ally
                if threat:
                    bx = ally.x + (threat.x - ally.x) * 0.15
                    by = ally.y + (threat.y - ally.y) * 0.15
                    return Move(bx, by)
                return Move(ally.x, ally.y)

        if action == "WARD_OBJECTIVE":
            o = world.objective
            return Move(o.x, o.y)

        if action == "RETREAT":
            # fall back toward own side (toward 0,0 for ALLY base, roughly)
            return Move(max(0.0, me.x - 800), max(0.0, me.y - 800))

        if action == "HOLD":
            # a support holds near its most-valuable ally
            ally = self._best_ally(world, me)
            if ally:
                return Move(ally.x - 150, ally.y - 150)

        return Idle()

    # ---- helpers ----
    def _nearest_enemy_to(self, world: World, me, ally):
        if not ally:
            return None
        enemies = world.enemies_of(me.team)
        if not enemies:
            return None
        return min(enemies, key=lambda e: (e.x - ally.x) ** 2 + (e.y - ally.y) ** 2)

    def _best_ally(self, world: World, me):
        allies = [c for c in world.allies_of(me.team) if c.name != me.name]
        carries = [c for c in allies if c.role in ("ADC", "MID")]
        pool = carries or allies
        return min(pool, key=lambda c: c.hp_frac, default=None)

    def _in_range(self, me, target, slot: str) -> bool:
        ab = me.abilities.get(slot)
        if not ab:
            return False
        return ((me.x - target.x) ** 2 + (me.y - target.y) ** 2) ** 0.5 <= ab.range

    # hard-CC slots per champion (stun/root/knockup/polymorph), best for peel
    _HARD_CC = ("stun", "root", "knockup", "polymorph")

    def _best_cc_slot(self, me) -> str | None:
        """The champion's strongest available CC ability for peeling a diver.

        Prefers longest CC duration among ready hard-CC abilities, so Sona peels
        with R (stun), Lulu with R/W, Jax with E, Ryze with W, Zac with E — not
        a blanket 'Q'.
        """
        best_slot, best_dur = None, 0.0
        for slot, ab in me.abilities.items():
            if ab.cc_type in self._HARD_CC and me.ability_ready(slot):
                rank = me.ability_ranks.get(slot, 1)
                dur = ab.cc(rank)
                if dur > best_dur:
                    best_slot, best_dur = slot, dur
        return best_slot
