"""
Reactive controller — the FAST layer (behavior tree) with the survival gate.

Given the planner's Decision (priority + target + the triage reads), pick the
concrete support action. Then run the SURVIVAL GATE — the user's "contribute but
don't throw / don't sell" rule:

    before committing to a RISKY play (diving in to CC, body-blocking into a
    pack), check whether I'd survive AND whether it actually helps. If not,
    DOWNGRADE to the best safe contribution (zone from range, ward, reposition)
    instead of either throwing my life away OR going passive.

So "don't throw" never means "do nothing" — it means swap the suicidal action
for the best helpful-but-safe one.

SWAP SEAM: replace `_choose_action` with a learned policy later; the gate and the
interface stay the same.
"""
from __future__ import annotations

import math

from core.measurements import AllyRead
from core.planner import Decision
from core.schema import BotOutput, GameState, Priority

# if committing would leave me below this HP with enemies on me, it's a throw
SURVIVE_MIN_HP = 0.25
# how close an enemy has to be to me to count as "on me"
ENEMY_ON_ME = 0.14


def _dist(ax, ay, bx, by) -> float:
    return math.hypot(ax - bx, ay - by)


class Controller:
    def choose(self, gs: GameState, decision: Decision) -> BotOutput:
        trace: list[str] = [f"priority={decision.priority.value}",
                            f"target={decision.target}",
                            f"top_score={decision.top_score:.2f}"]

        action, target = self._choose_action(gs, decision, trace)

        # ---- SURVIVAL GATE: don't throw, but still contribute ----
        if self._is_risky(action):
            if not self._would_survive(gs, trace):
                safe_action, safe_target = self._safe_downgrade(gs, decision, trace)
                action, target = safe_action, safe_target

        return BotOutput(decision.priority, action, target, trace=trace)

    # ---- behavior-tree action selection (pre-gate) ----
    def _choose_action(self, gs: GameState, d: Decision,
                       trace: list[str]) -> tuple[str, str | None]:
        me = gs.me()

        if d.priority == Priority.PEEL_CARRY and d.target:
            ally_read = self._read_for(d, d.target)
            threat = self._threat_near(gs, d.target)
            if threat:
                dc = _dist(threat.x, threat.y,
                           self._ally(gs, d.target).x, self._ally(gs, d.target).y)
                trace.append(f"threat={threat.name} d_to_ally={dc:.2f}")
                if dc < 0.10 and me.ability_ready("Q"):
                    trace.append("CC in range + ready -> ENGAGE_CC")
                    return "ENGAGE_CC", threat.name
            trace.append("body-block the ally -> PEEL")
            return "PEEL", d.target

        if d.priority == Priority.SETUP_OBJECTIVE:
            trace.append(f"ward+zone {d.target}")
            return "WARD_OBJECTIVE", d.target

        if d.priority == Priority.ENGAGE and me.ability_ready("Q"):
            threat = self._threat_near(gs, d.target) if d.target else None
            if threat:
                trace.append(f"engage onto {threat.name}")
                return "ENGAGE_CC", threat.name

        if d.priority == Priority.PLAY_SAFE:
            trace.append("no reachable danger -> HOLD position, stay present")
            return "HOLD", None

        trace.append("no trigger -> HOLD")
        return "HOLD", None

    # ---- survival gate helpers ----
    def _is_risky(self, action: str) -> bool:
        return action in ("ENGAGE_CC", "PEEL")

    def _would_survive(self, gs: GameState, trace: list[str]) -> bool:
        me = gs.me()
        enemies_on_me = sum(
            1 for e in gs.enemies() if _dist(e.x, e.y, me.x, me.y) < ENEMY_ON_ME
        )
        # throw if I'm already low AND there are enemies on me
        if me.hp_frac < SURVIVE_MIN_HP and enemies_on_me >= 1:
            trace.append(f"SURVIVAL GATE: my_hp={me.hp_frac:.2f}, "
                         f"{enemies_on_me} enemies on me -> would throw")
            return False
        return True

    def _safe_downgrade(self, gs: GameState, d: Decision,
                        trace: list[str]) -> tuple[str, str | None]:
        """Still contribute, from safety: zone an objective, else reposition."""
        if gs.objectives:
            trace.append("downgrade -> WARD_OBJECTIVE (contribute safely)")
            return "WARD_OBJECTIVE", gs.objectives[0].name
        trace.append("downgrade -> RETREAT (reposition, stay in the fight)")
        return "RETREAT", None

    # ---- small lookups ----
    def _ally(self, gs: GameState, name: str):
        return next(c for c in gs.allies() if c.name == name)

    def _threat_near(self, gs: GameState, ally_name: str | None):
        if not ally_name:
            return None
        ally = self._ally(gs, ally_name)
        enemies = gs.enemies()
        if not enemies:
            return None
        return min(enemies, key=lambda e: _dist(e.x, e.y, ally.x, ally.y))

    def _read_for(self, d: Decision, name: str) -> AllyRead | None:
        return next((r for r in d.ally_reads if r.ally.name == name), None)
