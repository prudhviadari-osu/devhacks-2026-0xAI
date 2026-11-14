"""
Strategic planner — the SLOW layer.

Runs every few ticks (not every tick), reads the whole board, and outputs one
`Priority`. This is where the LLM belongs (mentor deck: LLM = slow planning +
talk/remember/explain; fast control stays out of the LLM).

Ships with a deterministic heuristic fallback so the demo runs with no API key
and so you have a *baseline* to compare the LLM against for your evidence slide.
"""
from __future__ import annotations

import math

from core.schema import GameState, Priority
from llm.provider import LLMProvider


def _dist(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)


class Planner:
    def __init__(self, llm: LLMProvider | None = None, replan_every: float = 3.0):
        self.llm = llm
        self.replan_every = replan_every
        self._last_plan_t = -999.0
        self._cached = Priority.PLAY_SAFE

    def decide(self, gs: GameState) -> tuple[Priority, str]:
        # only replan on the slow clock; reuse the cached priority otherwise
        if gs.time - self._last_plan_t < self.replan_every:
            return self._cached, "cached"
        self._last_plan_t = gs.time

        if self.llm is not None:
            prio = self._llm_decide(gs)
            self._cached = prio
            return prio, "llm"

        prio = self.heuristic(gs)
        self._cached = prio
        return prio, "heuristic"

    # ---- baseline: a readable rule set (also your comparison target) ----
    def heuristic(self, gs: GameState) -> Priority:
        me = gs.me()
        carry = gs.ally_carry()
        enemies = gs.enemies()

        # is an enemy threatening our carry right now?
        threat = None
        if carry:
            threat = min(
                enemies,
                key=lambda e: _dist(e.x, e.y, carry.x, carry.y),
                default=None,
            )
            # react EARLY: start peeling while the diver is still approaching,
            # not after it's already on top of the carry (too late to body-block).
            if threat and _dist(threat.x, threat.y, carry.x, carry.y) < 0.30:
                # only bail if WE are too low to help at all
                if me.hp_frac < 0.20:
                    return Priority.PLAY_SAFE
                return Priority.PEEL_CARRY

        # objective coming up soon and we're healthy -> set it up
        obj = gs.next_objective()
        if obj and obj.spawns_in < 6.0 and me.hp_frac > 0.5:
            return Priority.SETUP_OBJECTIVE

        if me.hp_frac < 0.25:
            return Priority.PLAY_SAFE
        return Priority.PLAY_SAFE

    # ---- LLM path: ask for a priority, hard-validate the answer ----
    def _llm_decide(self, gs: GameState) -> Priority:
        allowed = [p.value for p in Priority]
        prompt = self._build_prompt(gs, allowed)
        raw = (self.llm.complete(prompt, temperature=0.2) or "").strip().upper()
        for p in Priority:
            if p.value in raw:
                return p
        # LLM gave garbage -> fall back to the safe heuristic, never crash
        return self.heuristic(gs)

    def _build_prompt(self, gs: GameState, allowed: list[str]) -> str:
        carry = gs.ally_carry()
        obj = gs.next_objective()
        lines = [
            "You are the strategic planner for a League of Legends SUPPORT bot.",
            "Pick ONE team priority. Reply with ONLY the keyword.",
            f"Allowed: {', '.join(allowed)}",
            f"Time: {gs.time:.0f}s",
            f"Me (support) hp={gs.me().hp_frac:.2f}",
        ]
        if carry:
            lines.append(f"Carry {carry.name} hp={carry.hp_frac:.2f} "
                         f"pos=({carry.x:.2f},{carry.y:.2f})")
        for e in gs.enemies():
            lines.append(f"Enemy {e.name} pos=({e.x:.2f},{e.y:.2f})")
        if obj:
            lines.append(f"Next objective {obj.name} up_in={obj.spawns_in:.0f}s")
        lines.append("Keyword:")
        return "\n".join(lines)
