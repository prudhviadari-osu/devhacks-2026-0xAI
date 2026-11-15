"""
A live champion instance (the MODEL's core unit).

Combines: resolved stats @ level (model/stats.py) + ability data
(model/abilities.py) + mutable live state (position, current HP/mana, cooldown
timers, cc). This is what the world ticks and what controllers read/act on.

v1 = scope (a): movement + auto-attacks + ONE ability each + armor/MR + growth.
The ability table already holds all four slots, so scope (b) just unlocks more
casts — no structural change here.

Base stats come from Data Dragon (model/stats.BaseStats.from_ddragon). For
offline/dev use we also ship a small hardcoded fallback table of REAL values for
the v1 roster so the sim runs with no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from model.abilities import Ability, abilities_for
from model.stats import BaseStats, ChampionStats

# Real Data Dragon base-stat values for the v1 roster (fallback when offline).
# Field names mirror Data Dragon's champion `stats` dict exactly.
_ROSTER_BASE: dict[str, dict] = {
    "Jax":  {"hp": 685, "hpperlevel": 103, "mp": 339, "mpperlevel": 52,
             "attackdamage": 68, "attackdamageperlevel": 3.4,
             "armor": 36, "armorperlevel": 4.5, "spellblock": 32,
             "spellblockperlevel": 2.05, "attackspeed": 0.638,
             "attackspeedperlevel": 3.4, "movespeed": 365, "attackrange": 125},
    "Lulu": {"hp": 595, "hpperlevel": 92, "mp": 350, "mpperlevel": 55,
             "attackdamage": 47, "attackdamageperlevel": 2.6,
             "armor": 29, "armorperlevel": 4.2, "spellblock": 30,
             "spellblockperlevel": 1.3, "attackspeed": 0.625,
             "attackspeedperlevel": 2.0, "movespeed": 320, "attackrange": 550},
    "Ryze": {"hp": 635, "hpperlevel": 110, "mp": 470, "mpperlevel": 65,
             "attackdamage": 55, "attackdamageperlevel": 3.0,
             "armor": 25, "armorperlevel": 4.7, "spellblock": 30,
             "spellblockperlevel": 1.3, "attackspeed": 0.658,
             "attackspeedperlevel": 2.11, "movespeed": 345, "attackrange": 550},
    "Sona": {"hp": 550, "hpperlevel": 82, "mp": 340, "mpperlevel": 45,
             "attackdamage": 49, "attackdamageperlevel": 3.0,
             "armor": 26, "armorperlevel": 4.2, "spellblock": 30,
             "spellblockperlevel": 1.3, "attackspeed": 0.644,
             "attackspeedperlevel": 2.3, "movespeed": 315, "attackrange": 550},
    "Zac":  {"hp": 685, "hpperlevel": 109, "mp": 0, "mpperlevel": 0,
             "attackdamage": 60, "attackdamageperlevel": 3.4,
             "armor": 33, "armorperlevel": 4.0, "spellblock": 32,
             "spellblockperlevel": 2.05, "attackspeed": 0.638,
             "attackspeedperlevel": 1.6, "movespeed": 345, "attackrange": 175},
    "Ashe": {"hp": 640, "hpperlevel": 101, "mp": 280, "mpperlevel": 35,
             "attackdamage": 59, "attackdamageperlevel": 2.95,
             "armor": 26, "armorperlevel": 4.6, "spellblock": 30,
             "spellblockperlevel": 1.3, "attackspeed": 0.658,
             "attackspeedperlevel": 3.33, "movespeed": 330, "attackrange": 600},
    "Darius": {"hp": 652, "hpperlevel": 114, "mp": 263, "mpperlevel": 37.5,
               "attackdamage": 64, "attackdamageperlevel": 5.0,
               "armor": 39, "armorperlevel": 4.0, "spellblock": 32,
               "spellblockperlevel": 2.05, "attackspeed": 0.625,
               "attackspeedperlevel": 1.0, "movespeed": 350, "attackrange": 175},
    "Lux":  {"hp": 580, "hpperlevel": 99, "mp": 480, "mpperlevel": 23.5,
             "attackdamage": 54, "attackdamageperlevel": 3.3,
             "armor": 21, "armorperlevel": 4.7, "spellblock": 30,
             "spellblockperlevel": 1.3, "attackspeed": 0.669,
             "attackspeedperlevel": 2.0, "movespeed": 340, "attackrange": 550},
    "Leona": {"hp": 646, "hpperlevel": 104, "mp": 302, "mpperlevel": 40,
              "attackdamage": 60, "attackdamageperlevel": 3.0,
              "armor": 47, "armorperlevel": 4.8, "spellblock": 32,
              "spellblockperlevel": 2.05, "attackspeed": 0.625,
              "attackspeedperlevel": 2.9, "movespeed": 335, "attackrange": 125},
    "Ahri": {"hp": 590, "hpperlevel": 104, "mp": 418, "mpperlevel": 25,
             "attackdamage": 53, "attackdamageperlevel": 3.0,
             "armor": 21, "armorperlevel": 4.7, "spellblock": 30,
             "spellblockperlevel": 1.3, "attackspeed": 0.668,
             "attackspeedperlevel": 2.0, "movespeed": 345, "attackrange": 550},
}


def base_stats_for(champion: str) -> BaseStats:
    if champion not in _ROSTER_BASE:
        raise KeyError(f"no base stats for {champion}")
    return BaseStats.from_ddragon(_ROSTER_BASE[champion])


@dataclass
class Champion:
    """A champion in the world. Positions are in GAME UNITS (SR is ~15000)."""
    name: str
    team: str                       # "ALLY" | "ENEMY"
    role: str                       # "SUPPORT" | "ADC" | ...
    level: int = 1
    x: float = 0.0
    y: float = 0.0

    # resolved + mutable state (filled in __post_init__)
    stats: ChampionStats = field(init=False)
    abilities: dict[str, Ability] = field(init=False)
    hp: float = field(init=False)
    mp: float = field(init=False)
    cooldowns: dict[str, float] = field(init=False)   # seconds remaining per slot
    cc_remaining: float = 0.0
    attack_cd: float = 0.0          # seconds until next auto is ready
    ability_ranks: dict[str, int] = field(default_factory=lambda: {
        "Q": 1, "W": 1, "E": 1, "R": 1})

    def champion_key(self) -> str:
        """Base champion identity for stats/abilities/profile lookup. Lets a
        mirror matchup use display names like 'Jax2' that resolve to 'Jax'."""
        return self.name.rstrip("0123456789")

    def __post_init__(self) -> None:
        key = self.champion_key()
        base = base_stats_for(key)
        self.stats = ChampionStats.resolve(base, self.level)
        self.abilities = abilities_for(key)
        self.hp = self.stats.max_hp
        self.mp = self.stats.max_mp
        self.cooldowns = {"Q": 0.0, "W": 0.0, "E": 0.0, "R": 0.0}
        # base = the team's fountain/nexus corner (set by the World on spawn).
        # respawn ALWAYS returns here (real League), not to where you died or
        # where you started the scenario. Defaults to team corner; World overrides.
        self.base_x = 1000.0 if self.team == "ALLY" else 14000.0
        self.base_y = 1000.0 if self.team == "ALLY" else 14000.0
        # spawn_x/y kept for the scoreboard "dead marker" location = base
        self.spawn_x = self.base_x
        self.spawn_y = self.base_y
        self.respawn_timer = 0.0        # seconds until revive (0 = alive)
        # economy
        self.gold = 500                 # starting gold (League-ish)
        self.cs = 0                     # creep score (minions last-hit)
        self.items: list = []           # inventory (filled by the shop)
        # combat record (for reward + scoreboard)
        self.kills = 0
        self.deaths = 0
        self.assists = 0
        self.killstreak = 0             # current streak (resets on death)
        self.time_alive = 0.0           # seconds alive this life (resets on death)
        self.total_time_alive = 0.0     # cumulative across lives
        # recent attackers: name -> game-time of last damage (for assist credit)
        self.recent_damagers: dict[str, float] = {}

    # ---- queries ----
    @property
    def alive(self) -> bool:
        return self.hp > 0.0

    @property
    def dead(self) -> bool:
        return self.hp <= 0.0

    def respawn(self) -> None:
        """Revive at the team BASE (fountain), full HP/mana, cooldowns reset —
        real League: you always come back at base, then walk out."""
        self.hp = self.stats.max_hp
        self.mp = self.stats.max_mp
        self.x, self.y = self.base_x, self.base_y
        self.cc_remaining = 0.0
        self.attack_cd = 0.0
        self.respawn_timer = 0.0
        self.killstreak = 0           # streak resets on death
        self.time_alive = 0.0         # this-life timer resets
        self.recent_damagers = {}
        for k in self.cooldowns:
            self.cooldowns[k] = 0.0

    @property
    def hp_frac(self) -> float:
        return self.hp / self.stats.max_hp if self.stats.max_hp else 0.0

    def ability_ready(self, slot: str) -> bool:
        return self.cooldowns.get(slot, 0.0) <= 0.0 and self.cc_remaining <= 0.0

    def can_auto(self) -> bool:
        return self.attack_cd <= 0.0 and self.cc_remaining <= 0.0

    # ---- mutations the world applies ----
    def take_damage(self, raw: float, damage_type: str,
                    source: str | None = None, now: float = 0.0) -> float:
        """Apply raw damage through the right resistance; return actual dealt.
        `source` (attacker name) + `now` (game time) record assist credit."""
        from model.stats import post_mitigation
        if damage_type == "true":
            dealt = raw
        elif damage_type == "physical":
            dealt = post_mitigation(raw, self.stats.armor)
        else:  # magic
            dealt = post_mitigation(raw, self.stats.mr)
        self.hp = max(0.0, self.hp - dealt)
        if source:
            self.recent_damagers[source] = now
        return dealt

    def heal(self, amount: float) -> None:
        self.hp = min(self.stats.max_hp, self.hp + amount)

    def tick(self, dt: float) -> None:
        for k in self.cooldowns:
            self.cooldowns[k] = max(0.0, self.cooldowns[k] - dt)
        self.cc_remaining = max(0.0, self.cc_remaining - dt)
        self.attack_cd = max(0.0, self.attack_cd - dt)
