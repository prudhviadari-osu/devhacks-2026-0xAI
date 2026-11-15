"""
Headless state server — runs the sim and serves world state as JSON over HTTP.

This makes the Python AI RENDERER-AGNOSTIC: Unity (or a web page, or Godot) just
polls GET /state each frame and draws what it reads. Zero game logic leaves
Python; the renderer is a dumb display. Same decoupling as the Overwolf path.

Endpoints:
    GET /state   -> current world snapshot (JSON) and advances the sim one tick
    GET /health  -> {"ok": true}

Run (no extra installs; stdlib only):
    python3 state_server.py                 # default scenario 'balanced'
    SCENARIO=teamfight python3 state_server.py
    PORT=8765 python3 state_server.py

Then point a renderer at http://127.0.0.1:8765/state.

The JSON shape (stable contract for the Unity client):
{
  "time": 12.3,
  "map_size": 15000,
  "objective": {"name":"DRAGON","x":..,"y":..,"up":true,"spawns_in":0.0},
  "champions": [
    {"name","team","role","x","y","hp","max_hp","hp_frac","mp_frac",
     "alive","cc","level","behavior","dead_timer"}
  ],
  "minions": [{"team","kind","x","y","hp_frac"}],
  "fx": [{"kind","src_x","src_y","dst_x","dst_y","slot","cc"}]
}
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import scenarios
from agent2.profiles import profile_for_champion
from controllers.utility_bot import UtilityBotController
from model.world import World

MAP_SIZE = 15000.0


class SimRunner:
    """Owns the sim + controllers and advances one tick per /state request."""

    def __init__(self, scenario_name: str):
        champs, dragon_spawn, desc, _ = scenarios.get(scenario_name)
        self.world = World(champs, dragon_spawn=dragon_spawn)
        self.controllers = {
            ch.name: UtilityBotController(profile_for_champion(ch.name))
            for ch in champs
        }
        self.desc = desc

    def tick(self) -> None:
        actions = {name: ctrl.decide(self.world, name)
                   for name, ctrl in self.controllers.items()}
        self.world.step(actions)

    def snapshot(self) -> dict:
        w = self.world
        champs = []
        for c in w.champions:
            ctrl = self.controllers.get(c.name)
            behavior = getattr(ctrl, "last_priority", "") if ctrl else ""
            champs.append({
                "name": c.name, "team": c.team, "role": c.role,
                "x": c.x, "y": c.y,
                "hp": round(c.hp, 1), "max_hp": round(c.stats.max_hp, 1),
                "hp_frac": round(c.hp_frac, 3),
                "mp_frac": round(c.mp / c.stats.max_mp, 3) if c.stats.max_mp else 0,
                "alive": c.alive, "cc": round(c.cc_remaining, 2),
                "level": c.level, "behavior": behavior,
                "dead_timer": round(c.respawn_timer, 1),
                "spawn_x": c.spawn_x, "spawn_y": c.spawn_y,
            })
        minions = [{"team": m.team, "kind": m.kind, "x": m.x, "y": m.y,
                    "hp_frac": round(m.hp_frac, 2)}
                   for m in w.minions.minions if m.alive]
        # resolve fx endpoints to coordinates for the renderer
        fx = []
        for e in getattr(w, "fx", []):
            src = w.by_name.get(e["src"])
            if not src:
                continue
            dst_name = e["dst"]
            if isinstance(dst_name, str) and dst_name.startswith("minion:"):
                uid = int(dst_name.split(":", 1)[1])
                dst = next((m for m in w.minions.minions if m.uid == uid), None)
            else:
                dst = w.by_name.get(dst_name)
            if not dst:
                continue
            fx.append({"kind": e["kind"], "src_x": src.x, "src_y": src.y,
                       "dst_x": dst.x, "dst_y": dst.y,
                       "slot": e.get("slot"), "cc": e.get("cc", False)})
        o = w.objective
        return {
            "time": round(w.time, 1), "map_size": MAP_SIZE, "desc": self.desc,
            "objective": {"name": o.name, "x": o.x, "y": o.y,
                          "up": w.objective_up(), "spawns_in": round(o.spawns_in, 1)},
            "champions": champs, "minions": minions, "fx": fx,
        }


class Handler(BaseHTTPRequestHandler):
    runner: SimRunner = None  # set at startup

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")  # allow web renderers
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"ok": True})
        elif self.path.startswith("/state"):
            Handler.runner.tick()
            self._send(200, Handler.runner.snapshot())
        else:
            self._send(404, {"error": "use /state or /health"})

    def log_message(self, *args):
        pass  # quiet


def main() -> None:
    scenario = os.environ.get("SCENARIO", "balanced")
    port = int(os.environ.get("PORT", "8765"))
    Handler.runner = SimRunner(scenario)
    print(f"[state_server] scenario='{scenario}' -> http://127.0.0.1:{port}/state")
    print(f"[state_server] {Handler.runner.desc}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
