"""
Demo 1: the bot plays support in the sim, printing a behavior trace each tick.
This is the prompt's literal ask: bot -> scenario -> behavior trace.

Usage:
    python run_sim.py                 # offline (heuristic planner + templates)
    LLM=ollama python run_sim.py      # LLM planner + comms, local on your Mac
    LLM=openai python run_sim.py      # LLM via OpenAI (needs OPENAI_API_KEY)
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


def build_agent() -> SupportAgent:
    llm = make_provider(os.environ.get("LLM", "offline"))
    use_llm = not isinstance(llm, type(make_provider("offline")))
    return SupportAgent(
        planner=Planner(llm if use_llm else None),
        controller=Controller(),
        comms=Comms(llm if use_llm else None),
        health=HealthMonitor(),
    )


def main() -> None:
    sim = SupportSim()
    agent = build_agent()

    print("=== SUPPORT BOT — SIM DEMO ===")
    while not sim.done():
        gs = sim.state()
        out = agent.act(gs)
        carry = gs.ally_carry()
        print(
            f"[t={gs.time:5.1f}] carry_hp={carry.hp_frac:4.2f} "
            f"{out.priority.value:>15} -> {out.action:<13} "
            f"| {out.comms}"
        )
        for line in out.trace:
            print(f"            · {line}")
        sim.step(out.action, out.target)

    final_adc = sim._get("Jinx").hp_frac
    print("=== RESULT ===")
    print(f"ADC survived: {sim.adc_alive()}  final hp={final_adc:.2f}  "
          f"time={sim.t:.1f}s")


if __name__ == "__main__":
    main()
