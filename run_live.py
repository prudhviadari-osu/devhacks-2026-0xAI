"""
Demo 2: the SAME agent, reasoning over a REAL League game (read-only).

Be in a game first (Practice Tool is ideal for a controlled demo). This polls the
sanctioned Live Client Data API at 127.0.0.1:2999 and runs the identical agent —
proving the bot is decoupled from its environment. It observes and talks; it does
NOT drive the client.

    pip install -r requirements.txt
    python3 run_live.py
"""
from __future__ import annotations

import os
import time

from core.agent import SupportAgent
from core.comms import Comms
from core.controller import Controller
from core.health import HealthMonitor
from core.planner import Planner
from llm.provider import make_provider
from sources.live_client import LiveClientSource


def build_agent() -> SupportAgent:
    llm = make_provider(os.environ.get("LLM", "offline"))
    offline = isinstance(llm, type(make_provider("offline")))
    return SupportAgent(
        planner=Planner(None if offline else llm),
        controller=Controller(),
        comms=Comms(None if offline else llm),
        health=HealthMonitor(),
    )


def main() -> None:
    # set SELF_CHAMP to the support you're playing in the game
    source = LiveClientSource(self_name=os.environ.get("SELF_CHAMP", "Leona"))
    agent = build_agent()

    print("=== SUPPORT BOT — LIVE LEAGUE (read-only) ===")
    print("Polling 127.0.0.1:2999 ... (Ctrl-C to stop)\n")
    while True:
        try:
            gs = source.state()
        except Exception as e:  # not in a game / client closed
            print(f"  waiting for a live game... ({type(e).__name__})")
            time.sleep(2.0)
            continue
        out = agent.act(gs)
        print(f"[t={gs.time:6.0f}s] {out.priority.value:>15} -> "
              f"{out.action:<14} | {out.comms}")
        time.sleep(1.0)


if __name__ == "__main__":
    main()
