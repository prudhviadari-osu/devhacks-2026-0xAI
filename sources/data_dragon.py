"""
Data Dragon loader — builds *realistic* simulated characters from Riot's static data.

Data Dragon is STATIC: champion base stats, ability info, items, icons. No live
game state. We use it to seed the sim's characters with real numbers (real base
HP, real ranges, real ability cooldowns) so "simulated Leona" behaves like Leona,
not a made-up blob.

No API key needed. Fetch once (ideally cache to disk). These endpoints are stable;
run this from your Mac (the hackathon sandbox blocks outbound HTTP).

Usage:
    python3 -m sources.data_dragon            # prints Leona's loaded stats
"""
from __future__ import annotations

import json
import os
import urllib.request

DDRAGON = "https://ddragon.leagueoflegends.com"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".ddragon_cache")


def _get_json(url: str, cache_key: str | None = None) -> dict:
    """Fetch JSON, with a simple on-disk cache so you only download once."""
    if cache_key:
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = os.path.join(CACHE_DIR, cache_key)
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read().decode())
    if cache_key:
        with open(os.path.join(CACHE_DIR, cache_key), "w") as f:
            json.dump(data, f)
    return data


def latest_version() -> str:
    versions = _get_json(f"{DDRAGON}/api/versions.json", "versions.json")
    return versions[0]


def champion_stats(name: str, version: str | None = None) -> dict:
    """Return the real base stats + spell cooldowns for one champion.

    Shape:
        {
          "name": "Leona",
          "base": {"hp": 646.0, "mp": 302.2, "movespeed": 335, "range": 125, ...},
          "spells": {"Q": {"name": "...", "cooldown": [6,6,6,6,6]}, ...},
        }
    """
    version = version or latest_version()
    detail = _get_json(
        f"{DDRAGON}/cdn/{version}/data/en_US/champion/{name}.json",
        f"champion_{name}_{version}.json",
    )
    champ = detail["data"][name]
    slots = ["Q", "W", "E", "R"]
    spells = {}
    for slot, spell in zip(slots, champ.get("spells", [])):
        spells[slot] = {
            "name": spell.get("name"),
            "cooldown": spell.get("cooldown", [0]),  # per-rank list
        }
    return {
        "name": name,
        "base": champ.get("stats", {}),
        "spells": spells,
    }


def initial_cooldowns(stats: dict, rank: int = 1) -> dict[str, float]:
    """Max cooldown per ability at a given rank -> seeds Champion.cooldowns.

    We store the ability's base cooldown so the sim's cooldown timers are real
    (e.g. Leona Q = 6s), not invented.
    """
    out: dict[str, float] = {}
    for slot, spell in stats["spells"].items():
        cds = spell["cooldown"]
        idx = min(rank - 1, len(cds) - 1)
        out[slot] = 0.0  # starts ready; the sim decrements from max after a cast
    return out


def ability_base_cooldown(stats: dict, slot: str, rank: int = 1) -> float:
    cds = stats["spells"].get(slot, {}).get("cooldown", [0])
    return float(cds[min(rank - 1, len(cds) - 1)])


if __name__ == "__main__":
    s = champion_stats("Leona")
    print(f"Loaded {s['name']}")
    print(f"  base HP:        {s['base'].get('hp')}")
    print(f"  attack range:   {s['base'].get('attackrange')}")
    print(f"  move speed:     {s['base'].get('movespeed')}")
    for slot, sp in s["spells"].items():
        print(f"  {slot}: {sp['name']:<24} cd={sp['cooldown']}")
