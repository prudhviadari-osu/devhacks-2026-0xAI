"""
Live League source — the integratability proof.

Reads Riot's Live Client Data API (local, read-only, sanctioned) from a running
game (Practice Tool is perfect for a demo). Normalizes the JSON into the SAME
GameState the sim emits, so the agent runs unchanged on real League.

NOTE: the endpoint uses a self-signed cert on localhost, so we disable TLS verify
for 127.0.0.1 only. This is read-only observation — it does NOT drive the client
(input injection + memory reads are blocked by Vanguard / closed by Riot in 2026).
"""
from __future__ import annotations

import urllib3

from core.schema import Champion, GameState, Objective, Role, Team

urllib3.disable_warnings()  # silence the self-signed localhost cert warning

BASE = "https://127.0.0.1:2999/liveclientdata"

# Map Riot's position strings to our Role enum (best-effort).
_ROLE = {
    "TOP": Role.TOP, "JUNGLE": Role.JUNGLE, "MIDDLE": Role.MID,
    "BOTTOM": Role.ADC, "UTILITY": Role.SUPPORT,
}


class LiveClientSource:
    def __init__(self, self_name: str):
        self.self_name = self_name

    def state(self) -> GameState:
        import requests
        data = requests.get(f"{BASE}/allgamedata", verify=False, timeout=2).json()
        game_time = data.get("gameData", {}).get("gameTime", 0.0)

        active_team = None
        champs: list[Champion] = []
        for p in data.get("allPlayers", []):
            name = p.get("championName", p.get("summonerName", "Unknown"))
            team_str = p.get("team", "ORDER")
            if p.get("summonerName") == data.get("activePlayer", {}).get("summonerName"):
                active_team = team_str
            role = _ROLE.get(p.get("position", ""), Role.SUPPORT)
            # Live Client Data does NOT expose x/y for all players (fog of war,
            # by design). We fill what we can; positions are 0 where unknown.
            champs.append(Champion(
                name=name,
                team=Team.ALLY if team_str == active_team else Team.ENEMY,
                role=role,
                x=0.0, y=0.0,
                hp_frac=self._hp_frac(p),
                mana_frac=1.0,
                cooldowns={},
            ))

        objectives = self._objectives_from_events(data, game_time)
        return GameState(time=game_time, champions=champs,
                         objectives=objectives, self_name=self.self_name)

    def _hp_frac(self, p: dict) -> float:
        scores = p.get("scores", {})
        # allgamedata doesn't always give raw hp; default healthy if absent
        hp = p.get("health")
        maxhp = p.get("maxHealth")
        if hp and maxhp:
            return max(0.0, min(1.0, hp / maxhp))
        return 1.0

    def _objectives_from_events(self, data, t) -> list[Objective]:
        # Dragon spawns ~5:00; refine with the eventdata feed for your demo.
        spawns_in = max(0.0, 300.0 - t)
        return [Objective("DRAGON", x=0.55, y=0.20, spawns_in=spawns_in)]
