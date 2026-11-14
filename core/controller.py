"""
Reactive controller — the FAST layer (behavior tree).

Runs every tick. Given the planner's Priority + the current state, it picks the
concrete support action. A behavior tree (not an LLM) because fast control must
be cheap and deterministic (mentor deck slide 6: fast decisions stay in a tree /
small policy, 7.8ms-per-frame budgets).

SWAP SEAM: `choose()` maps (priority, state) -> action string. To go RL later,
replace the body of `choose()` with `policy.act(encode(gs, priority))` and keep
the same signature. Nothing else in the codebase changes.
"""
from __future__ import annotations

import math

from core.schema import BotOutput, GameState, Priority


def _dist(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)


class Controller:
    def choose(self, gs: GameState, priority: Priority) -> BotOutput:
        trace: list[str] = [f"priority={priority.value}"]
        me = gs.me()
        carry = gs.ally_carry()
        enemies = gs.enemies()

        # nearest threat to the carry — the thing a support reacts to
        threat = None
        if carry and enemies:
            threat = min(enemies, key=lambda e: _dist(e.x, e.y, carry.x, carry.y))

        if priority == Priority.PEEL_CARRY and carry and threat:
            d = _dist(threat.x, threat.y, carry.x, carry.y)
            trace.append(f"threat={threat.name} d_to_carry={d:.2f}")
            if d < 0.10 and me.ability_ready("Q"):
                trace.append("CC in range + ready -> ENGAGE_CC")
                return BotOutput(priority, "ENGAGE_CC", target=threat.name, trace=trace)
            trace.append("body-block the carry -> PEEL")
            return BotOutput(priority, "PEEL", target=carry.name, trace=trace)

        if priority == Priority.SETUP_OBJECTIVE:
            obj = gs.next_objective()
            trace.append(f"ward+zone {obj.name if obj else 'objective'}")
            return BotOutput(priority, "WARD_OBJECTIVE",
                             target=obj.name if obj else None, trace=trace)

        if priority == Priority.ENGAGE and threat and me.ability_ready("Q"):
            trace.append(f"engage onto {threat.name}")
            return BotOutput(priority, "ENGAGE_CC", target=threat.name, trace=trace)

        if priority == Priority.PLAY_SAFE:
            trace.append("disengage / reset -> RETREAT")
            return BotOutput(priority, "RETREAT", target=None, trace=trace)

        trace.append("no trigger -> HOLD")
        return BotOutput(priority, "HOLD", target=None, trace=trace)
