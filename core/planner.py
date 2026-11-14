"""
Strategic planner — the SLOW layer, now driven by triage.

Each replan it scores every ally and objective (core/measurements.py) on one
scale and picks the highest. That choice becomes:
  - a Priority (PEEL_CARRY / SETUP_OBJECTIVE / PLAY_SAFE / ...), and
  - a target (which ally to protect, or which objective to take).

The LLM path is optional and only *overrides* the priority keyword; the triage
target and its numbers always come from the measurements so the decision stays
grounded and explainable in the trace.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.measurements import AllyRead, ObjectiveRead, Triage
from core.schema import GameState, Priority
from llm.provider import LLMProvider

# an ally is "in danger" (worth peeling for) once its score clears this
DANGER_SCORE = 0.15


@dataclass
class Decision:
    priority: Priority
    target: str | None            # champion name or objective name
    source: str                   # "triage" | "llm" | "cached"
    ally_reads: list[AllyRead]
    obj_reads: list[ObjectiveRead]
    top_score: float


class Planner:
    def __init__(self, llm: LLMProvider | None = None, replan_every: float = 1.0,
                 move_speed: float = 0.12):
        self.llm = llm
        self.replan_every = replan_every
        self.triage = Triage(move_speed=move_speed)
        self._last_plan_t = -999.0
        self._prev_hp: dict[str, float] = {}
        self._last_t = 0.0
        self._cached: Decision | None = None

    def decide(self, gs: GameState) -> Decision:
        dt = max(1e-6, gs.time - self._last_t)
        self._last_t = gs.time

        # reuse on the slow clock, but ALWAYS refresh HP history for dmg rate
        if self._cached and gs.time - self._last_plan_t < self.replan_every:
            self._record_hp(gs)
            return self._as_source(self._cached, "cached")
        self._last_plan_t = gs.time

        ally_reads = self.triage.read_allies(gs, self._prev_hp, dt)
        any_danger = any(r.score >= DANGER_SCORE for r in ally_reads)
        obj_reads = self.triage.read_objectives(gs, any_ally_in_danger=any_danger)
        self._record_hp(gs)

        decision = self._pick(gs, ally_reads, obj_reads)

        # optional: let the LLM override ONLY the priority keyword
        if self.llm is not None:
            decision.priority = self._llm_priority(gs, decision)
            decision.source = "llm"

        self._cached = decision
        return decision

    # ---- turn the top-scored read into a priority + target ----
    def _pick(self, gs: GameState, ally_reads: list[AllyRead],
              obj_reads: list[ObjectiveRead]) -> Decision:
        best_ally = max(ally_reads, key=lambda r: r.score, default=None)
        best_obj = max(obj_reads, key=lambda r: r.score, default=None)

        ally_score = best_ally.score if best_ally else 0.0
        obj_score = best_obj.score if best_obj else 0.0

        # an endangered, reachable ally outranks everything (lean-support rule)
        if best_ally and ally_score >= DANGER_SCORE and ally_score >= obj_score:
            return Decision(Priority.PEEL_CARRY, best_ally.ally.name, "triage",
                            ally_reads, obj_reads, ally_score)

        # else take a reachable objective if it scores
        if best_obj and obj_score > 0.0:
            return Decision(Priority.SETUP_OBJECTIVE, best_obj.objective.name,
                            "triage", ally_reads, obj_reads, obj_score)

        # nobody reachable in danger, no objective -> stay safe but present
        return Decision(Priority.PLAY_SAFE, None, "triage",
                        ally_reads, obj_reads, max(ally_score, obj_score))

    def _record_hp(self, gs: GameState) -> None:
        for c in gs.allies():
            self._prev_hp[c.name] = c.hp_frac

    def _as_source(self, d: Decision, src: str) -> Decision:
        return Decision(d.priority, d.target, src, d.ally_reads,
                        d.obj_reads, d.top_score)

    # ---- optional LLM override of the priority keyword only ----
    def _llm_priority(self, gs: GameState, d: Decision) -> Priority:
        allowed = [p.value for p in Priority]
        best = max(d.ally_reads, key=lambda r: r.score, default=None)
        lines = [
            "You are the strategic planner for a League SUPPORT bot.",
            "Pick ONE team priority. Reply with ONLY the keyword.",
            f"Allowed: {', '.join(allowed)}",
            f"Triage suggests: {d.priority.value} (target={d.target}, "
            f"score={d.top_score:.2f})",
        ]
        if best:
            lines.append(
                f"Top ally {best.ally.name}: hp={best.hp_frac:.2f} "
                f"enemies_near={best.enemies_near} ttd={best.time_to_die:.1f}s "
                f"reachable={best.reachable}")
        lines.append("Keyword:")
        raw = (self.llm.complete("\n".join(lines), temperature=0.2) or "").upper()
        for p in Priority:
            if p.value in raw:
                return p
        return d.priority  # garbage -> keep triage's grounded choice
