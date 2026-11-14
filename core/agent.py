"""
The agent: wires planner -> controller -> comms, guarded by the health monitor.

This is the whole loop, and it is the ONLY thing a new source has to talk to.
`act(GameState) -> BotOutput`. Sim or live League, identical call.
"""
from __future__ import annotations

from core.comms import Comms
from core.controller import Controller
from core.health import HealthMonitor
from core.planner import Planner
from core.schema import BotOutput, GameState, Priority


class SupportAgent:
    def __init__(self, planner: Planner, controller: Controller,
                 comms: Comms, health: HealthMonitor):
        self.planner = planner
        self.controller = controller
        self.comms = comms
        self.health = health

    def act(self, gs: GameState) -> BotOutput:
        decision = self.planner.decide(gs)
        out = self.controller.choose(gs, decision)
        out.trace.insert(0, f"plan_src={decision.source}")

        # circuit breaker: trip only if the policy collapsed AND the outcome
        # (carry survival) is worsening. Holding one correct action is healthy.
        carry = gs.ally_carry()
        outcome = carry.hp_frac if carry else 1.0
        self.health.record(out.action, outcome)
        out.health_ok = self.health.check()
        if not out.health_ok:
            out.trace.append(
                f"CIRCUIT BREAKER tripped (entropy={self.health.entropy():.2f}) "
                "-> safe policy")
            out = BotOutput(Priority.PLAY_SAFE, "RETREAT", None,
                            trace=out.trace, health_ok=False)

        out.comms = self.comms.say(gs, out)
        return out
