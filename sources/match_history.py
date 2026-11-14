"""
Match-V5 history source — REAL past games, for the PLANNER's macro grounding.

This is Riot's official web API (needs a dev key). Unlike the Live Client Data
API it needs NO running game and NO history on your own account — you query any
public player's finished matches. Great for seeding the planner with how real
(ideally high-elo) players handle objectives, gold leads, and rotations.

HARD LIMIT (by design): timeline PARTICIPANT POSITIONS are sampled only every
~60 seconds. That's fine for MACRO context (gold, objective timing, lane drift)
but far too coarse for the reactive peel/dive logic — that stays in the sim.

Key handling:
  - read from env var RIOT_API_KEY. NEVER hardcode it.
  - dev keys expire every 24h; regenerate at developer.riotgames.com.

Regions:
  - account lookup (Riot ID -> puuid) uses a ROUTING region: americas | asia | europe
  - match endpoints also use the routing region
  Example: a KR player is routed through "asia"; NA through "americas".

Usage (on your Mac, after `export RIOT_API_KEY=...`):
    python3 -m sources.match_history "Faker#KR1" asia
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from core.schema import Champion, GameState, Objective, Role, Team

# Map Match-V5 teamPosition -> our Role
_ROLE = {
    "TOP": Role.TOP, "JUNGLE": Role.JUNGLE, "MIDDLE": Role.MID,
    "BOTTOM": Role.ADC, "UTILITY": Role.SUPPORT,
}

# Summoner's Rift is ~15000 x 15000 game units; normalize to 0..1 for our schema
MAP_MAX = 15000.0


class RiotAuthError(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("RIOT_API_KEY")
    if not k:
        raise RiotAuthError(
            "RIOT_API_KEY not set. Run: export RIOT_API_KEY='your-dev-key' "
            "(regenerate at developer.riotgames.com; keys expire every 24h)."
        )
    return k


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"X-Riot-Token": _key()})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                import json
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limited -> back off and retry
                wait = int(e.headers.get("Retry-After", "2"))
                time.sleep(wait)
                continue
            if e.code in (401, 403):
                raise RiotAuthError(
                    f"HTTP {e.code}: key rejected. It may be expired (dev keys "
                    "last 24h) or wrong. Regenerate at developer.riotgames.com."
                ) from e
            raise
    raise RuntimeError("rate-limited after retries; try again shortly")


class MatchHistorySource:
    def __init__(self, riot_id: str, routing: str = "americas"):
        """riot_id: 'GameName#TAG'. routing: americas | asia | europe."""
        if "#" not in riot_id:
            raise ValueError("riot_id must look like 'GameName#TAG'")
        self.game_name, self.tag = riot_id.split("#", 1)
        self.routing = routing
        self.base = f"https://{routing}.api.riotgames.com"
        self.puuid = self._resolve_puuid()

    def _resolve_puuid(self) -> str:
        name = urllib.parse.quote(self.game_name)
        tag = urllib.parse.quote(self.tag)
        data = _get(f"{self.base}/riot/account/v1/accounts/by-riot-id/{name}/{tag}")
        return data["puuid"]

    def recent_match_ids(self, count: int = 5, queue: int | None = 420) -> list[str]:
        """queue 420 = ranked solo/duo. Set queue=None for any."""
        q = f"&queue={queue}" if queue is not None else ""
        return _get(f"{self.base}/lol/match/v5/matches/by-puuid/"
                    f"{self.puuid}/ids?start=0&count={count}{q}")

    def timeline(self, match_id: str) -> dict:
        return _get(f"{self.base}/lol/match/v5/matches/{match_id}/timeline")

    def match(self, match_id: str) -> dict:
        return _get(f"{self.base}/lol/match/v5/matches/{match_id}")

    # ---- normalize ONE 60s timeline frame into our GameState ----
    def frames_as_states(self, match_id: str) -> list[GameState]:
        """Yield one GameState per ~60s frame. Positions are coarse (that's the
        API limit); use these for the planner's macro view, not the controller."""
        tl = self.timeline(match_id)
        info = tl["info"]
        parts = info["participants"]  # participantId -> puuid mapping
        # participantId (1..10) -> (team, role) from the match detail
        meta = self._participant_meta(match_id)

        states: list[GameState] = []
        for frame in info["frames"]:
            t = frame["timestamp"] / 1000.0  # ms -> s
            champs: list[Champion] = []
            for pid_str, pf in frame["participantFrames"].items():
                pid = int(pid_str)
                pos = pf.get("position", {"x": 0, "y": 0})
                team, role, champ_name = meta.get(pid, (Team.ALLY, Role.MID, f"P{pid}"))
                total_gold = pf.get("totalGold", 0)
                champs.append(Champion(
                    name=champ_name,
                    team=team,
                    role=role,
                    x=pos["x"] / MAP_MAX,
                    y=pos["y"] / MAP_MAX,
                    hp_frac=1.0,  # timeline frames don't carry live HP
                    mana_frac=1.0,
                    cooldowns={},
                ))
            states.append(GameState(time=t, champions=champs,
                                    objectives=self._objectives(frame),
                                    self_name=self._pick_support(meta)))
        return states

    def _participant_meta(self, match_id: str) -> dict[int, tuple[Team, Role, str]]:
        detail = self.match(match_id)
        out: dict[int, tuple[Team, Role, str]] = {}
        for i, p in enumerate(detail["info"]["participants"], start=1):
            team = Team.ALLY if p.get("teamId") == 100 else Team.ENEMY
            role = _ROLE.get(p.get("teamPosition", ""), Role.MID)
            out[i] = (team, role, p.get("championName", f"P{i}"))
        return out

    def _pick_support(self, meta: dict[int, tuple[Team, Role, str]]) -> str:
        for _, (team, role, name) in meta.items():
            if team == Team.ALLY and role == Role.SUPPORT:
                return name
        return next(iter(meta.values()))[2] if meta else ""

    def _objectives(self, frame: dict) -> list[Objective]:
        # the eventsframe carries ELITE_MONSTER_KILL etc.; for macro grounding
        # we expose a simple dragon marker. Refine from frame["events"] as needed.
        return [Objective("DRAGON", x=0.37, y=0.13, spawns_in=0.0)]


if __name__ == "__main__":
    riot_id = sys.argv[1] if len(sys.argv) > 1 else "Faker#KR1"
    routing = sys.argv[2] if len(sys.argv) > 2 else "asia"
    src = MatchHistorySource(riot_id, routing)
    print(f"Resolved {riot_id} -> puuid {src.puuid[:12]}...")
    ids = src.recent_match_ids(count=3)
    print(f"Recent ranked matches: {ids}")
    if ids:
        states = src.frames_as_states(ids[0])
        print(f"Match {ids[0]}: {len(states)} timeline frames "
              f"(~{len(states)} minutes, positions sampled every ~60s)")
        if states:
            s = states[min(5, len(states) - 1)]
            print(f"  frame @ {s.time:.0f}s has {len(s.champions)} champions")
            for c in s.champions[:3]:
                print(f"    {c.name:<12} {c.team.value:<5} {c.role.value:<8} "
                      f"pos=({c.x:.2f},{c.y:.2f})")
