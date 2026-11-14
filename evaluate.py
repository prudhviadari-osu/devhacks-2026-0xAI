"""
Evidence harness — "compare against a simpler bot" (rubric: credible evidence).

Runs TWO scenarios, each three ways, and reports success:
  scenarios:
    - dive       : enemy assassin dives a reckless carry. Right play = PEEL.
    - objective  : carry is safe, dragon is up & uncontested. Right play = SETUP.
  variants:
    1. NO SUPPORT   — bot does nothing (HOLD). Baseline.
    2. DUMB SUPPORT — always PEEL, never reads the board.
    3. OUR AGENT    — planner + controller + health.

The point: the DUMB bot wins only the scenario it happens to fit (dive) and
fails the other (objective). OUR AGENT reads the board and wins BOTH. That's the
"value is the role, not win rate" argument, shown with numbers.
"""
from __future__ import annotations

import os

from core.agent import SupportAgent
from core.comms import Comms
from core.controller import Controller
from core.health import HealthMonitor
from core.planner import Planner
from llm.provider import make_provider
from sources.sim import SupportSim

SCENARIOS = ["dive", "objective"]


def run_scripted(scenario: str, action_fn) -> bool:
    sim = SupportSim(scenario=scenario)
    while not sim.done():
        gs = sim.state()
        action, target = action_fn(gs)
        sim.step(action, target)
    return sim.success()


def run_agent(scenario: str) -> bool:
    llm = make_provider(os.environ.get("LLM", "offline"))
    offline = isinstance(llm, type(make_provider("offline")))
    agent = SupportAgent(
        planner=Planner(None if offline else llm),
        controller=Controller(),
        comms=Comms(None if offline else llm),
        health=HealthMonitor(),
    )
    sim = SupportSim(scenario=scenario)
    while not sim.done():
        gs = sim.state()
        out = agent.act(gs)
        sim.step(out.action, out.target)
    return sim.success()


def _dumb(gs):
    carry = gs.ally_carry()
    return "PEEL", carry.name if carry else None


def main() -> None:
    variants = {
        "NO SUPPORT (baseline)": lambda s: run_scripted(s, lambda gs: ("HOLD", None)),
        "DUMB SUPPORT (always peel)": lambda s: run_scripted(s, _dumb),
        "OUR AGENT": run_agent,
    }

    header = f"{'variant':<28}" + "".join(f"{s:<14}" for s in SCENARIOS) + "wins"
    print(header)
    print("-" * len(header))
    for name, fn in variants.items():
        row_results = [fn(s) for s in SCENARIOS]
        cells = "".join(f"{('PASS' if r else 'FAIL'):<14}" for r in row_results)
        print(f"{name:<28}{cells}{sum(row_results)}/{len(SCENARIOS)}")


if __name__ == "__main__":
    main()
