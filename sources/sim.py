"""
The environment.

A tiny, deterministic, tick-based 2D sim built around *support decisions*, not
mechanics twitch. It is League-grounded: a carry to keep alive, an enemy assassin
that dives, and a dragon that spawns — the three situations that force a support
to choose between PEEL / ENGAGE / SETUP_OBJECTIVE / PLAY_SAFE.

Why a sim and not live League: Riot blocked memory access (Oct 2026) and there is
no server-side bot hook outside Riot. The hackathon prompt literally asks for
"the bot, plus a small environment where its decisions can be observed." This is
that environment. It emits the SAME GameState the live feed does, so the agent
cannot tell the difference — that is the integratability proof.
"""
from __future__ import annotations

import math
import random

from core.schema import (
    Champion,
    GameState,
    Objective,
    Role,
    Team,
)

TICK = 0.5  # seconds of game time per step


def _dist(a: Champion, b: Champion) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


class SupportSim:
    """A scripted-ish scenario the support bot has to survive and play well.

    The ally ADC farms toward the enemy and is reckless (models a real player who
    overextends). An enemy assassin periodically dives the ADC. A dragon spawns
    mid-game. The bot controls the SUPPORT ("Leona" by default).
    """

    def __init__(self, seed: int = 7, self_name: str = "Leona",
                 scenario: str = "dive"):
        self.rng = random.Random(seed)
        self.self_name = self_name
        self.scenario = scenario  # "dive" | "objective"
        self.t = 0.0
        self._build()

    def _build(self) -> None:
        self.champs = [
            # our support — the bot
            Champion(self.self_name, Team.ALLY, Role.SUPPORT, x=0.30, y=0.30,
                     hp_frac=1.0, mana_frac=1.0,
                     cooldowns={"Q": 0.0, "E": 0.0, "R": 0.0}),
            # our carry — reckless, walks forward
            Champion("Jinx", Team.ALLY, Role.ADC, x=0.34, y=0.28,
                     hp_frac=1.0, mana_frac=1.0, cooldowns={}),
            # enemy assassin — dives the carry
            Champion("Zed", Team.ENEMY, Role.MID, x=0.70, y=0.70,
                     hp_frac=1.0, mana_frac=1.0,
                     cooldowns={"R": 0.0}),
            # enemy support — contests objectives
            Champion("Thresh", Team.ENEMY, Role.SUPPORT, x=0.66, y=0.66,
                     hp_frac=1.0, mana_frac=1.0, cooldowns={}),
        ]
        if self.scenario == "objective":
            # carry is SAFE (enemies far, not diving); dragon is up NOW and
            # uncontested. The RIGHT support play is to set it up, not hug the
            # ADC. A "dumb always-peel" bot never contests it and the team
            # loses the objective. This is where reading the board pays off.
            self._get("Zed").x, self._get("Zed").y = 0.90, 0.90
            self._get("Thresh").x, self._get("Thresh").y = 0.88, 0.88
            self.objectives = [Objective("DRAGON", x=0.55, y=0.20, spawns_in=0.0)]
            self._dive_cooldown = 999.0  # no dive in this scenario
            self._diving = False
        else:
            self.objectives = [Objective("DRAGON", x=0.55, y=0.20, spawns_in=20.0)]
            self._dive_cooldown = 8.0  # assassin dives roughly every N seconds
            self._diving = False
        self._objective_secured_ticks = 0

    # ---- the source interface: hand the agent a normalized snapshot ----
    def state(self) -> GameState:
        return GameState(
            time=self.t,
            champions=[self._copy(c) for c in self.champs],
            objectives=[self._copy_obj(o) for o in self.objectives],
            self_name=self.self_name,
        )

    def _copy(self, c: Champion) -> Champion:
        return Champion(c.name, c.team, c.role, c.x, c.y, c.hp_frac,
                        c.mana_frac, dict(c.cooldowns), c.cc_remaining)

    def _copy_obj(self, o: Objective) -> Objective:
        return Objective(o.name, o.x, o.y, o.spawns_in, o.contested)

    # ---- advance the world one tick, applying the bot's chosen action ----
    def step(self, action: str, target: str | None) -> None:
        self.t += TICK
        me = self._get(self.self_name)
        adc = self._get("Jinx")
        zed = self._get("Zed")

        # tick cooldowns / cc / objective timer
        for c in self.champs:
            for k in list(c.cooldowns):
                c.cooldowns[k] = max(0.0, c.cooldowns[k] - TICK)
            c.cc_remaining = max(0.0, c.cc_remaining - TICK)
        for o in self.objectives:
            o.spawns_in = max(0.0, o.spawns_in - TICK)

        # reckless ADC drifts toward the enemy
        adc.x = min(0.62, adc.x + 0.01)

        # enemy assassin dives the ADC: once it decides to go, it commits and
        # closes distance every tick until it's on top of the carry.
        self._dive_cooldown -= TICK
        if self._dive_cooldown <= 0.0:
            self._diving = True
        if getattr(self, "_diving", False) and zed.cc_remaining <= 0.0:
            # move a fixed step toward the carry (not a fraction, so it arrives)
            dx, dy = adc.x - zed.x, adc.y - zed.y
            d = max(1e-6, math.hypot(dx, dy))
            step = min(0.08, d)
            zed.x += dx / d * step
            zed.y += dy / d * step

        # apply the bot's support action (may CC the assassin / body-block)
        self._apply_action(me, action, target, adc, zed)

        # resolve assassin damage: if it's on the carry and NOT crowd-controlled,
        # it bursts. A body-block (support between zed and adc) also soaks it.
        blocked = _dist(me, adc) < 0.06 and _dist(me, zed) < 0.14
        if _dist(zed, adc) < 0.10 and zed.cc_remaining <= 0.0 and not blocked:
            adc.hp_frac = max(0.0, adc.hp_frac - 0.30)
            self._diving = False
            self._dive_cooldown = 8.0  # reset for the next dive attempt

    def _apply_action(self, me, action, target, adc, zed) -> None:
        if action == "ENGAGE_CC" and target == "Zed" and me.ability_ready("Q"):
            # land CC on the assassin: stops its damage this tick
            zed.cc_remaining = 1.5
            me.cooldowns["Q"] = 6.0
            me.x, me.y = zed.x, zed.y  # moved in to CC
        elif action == "PEEL":
            # body-block: position BETWEEN the diver and the carry so the
            # blocked-check (support between zed and adc) soaks the burst.
            dx, dy = zed.x - adc.x, zed.y - adc.y
            d = max(1e-6, math.hypot(dx, dy))
            me.x = adc.x + dx / d * 0.04
            me.y = adc.y + dy / d * 0.04
            # if the diver is adjacent and CC is up, lock it down too
            if _dist(me, zed) < 0.12 and me.ability_ready("Q"):
                zed.cc_remaining = 1.0
                me.cooldowns["Q"] = 6.0
        elif action == "WARD_OBJECTIVE":
            obj = self.objectives[0]
            me.x, me.y = obj.x - 0.05, obj.y + 0.05
            obj.contested = True
            if obj.spawns_in <= 0.0:
                self._objective_secured_ticks += 1
        elif action == "RETREAT":
            me.x = max(0.20, me.x - 0.03)
            me.y = max(0.20, me.y - 0.03)
        # "HOLD" / anything else: do nothing this tick

    def _get(self, name: str) -> Champion:
        return next(c for c in self.champs if c.name == name)

    def adc_alive(self) -> bool:
        return self._get("Jinx").hp_frac > 0.0

    def objective_secured(self) -> bool:
        """Dragon is 'secured' if the support warded/zoned it for enough ticks."""
        return self._objective_secured_ticks >= 6  # ~3s of presence

    def success(self) -> bool:
        """Scenario-aware win condition for the evidence harness."""
        if self.scenario == "objective":
            return self.objective_secured()
        return self.adc_alive()

    def done(self) -> bool:
        if self.scenario == "objective":
            return self.t >= 20.0 or self.objective_secured()
        return self.t >= 40.0 or not self.adc_alive()
