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
             "attackspeedperlevel": 3.4, "movespeed": 350, "attackrange": 125},
    "Lulu": {"hp": 595, "hpperlevel": 92, "mp": 350, "mpperlevel": 55,
             "attackdamage": 47, "attackdamageperlevel": 2.6,
             "armor": 29, "armorperlevel": 4.2, "spellblock": 30,
             "spellblockperlevel": 1.3, "attackspeed": 0.625,
             "attackspeedperlevel": 2.0, "movespeed": 330, "attackrange": 550},
    "Ryze": {"hp": 635, "hpperlevel": 110, "mp": 470, "mpperlevel": 65,
             "attackdamage": 55, "attackdamageperlevel": 3.0,
             "armor": 25, "armorperlevel": 4.7, "spellblock": 30,
             "spellblockperlevel": 1.3, "attackspeed": 0.658,
             "attackspeedperlevel": 2.11, "movespeed": 340, "attackrange": 550},
    "Sona": {"hp": 550, "hpperlevel": 82, "mp": 340, "mpperlevel": 45,
             "attackdamage": 49, "attackdamageperlevel": 3.0,
             "armor": 26, "armorperlevel": 4.2, "spellblock": 30,
             "spellblockperlevel": 1.3, "attackspeed": 0.644,
             "attackspeedperlevel": 2.3, "movespeed": 325, "attackrange": 550},
    "Zac":  {"hp": 685, "hpperlevel": 109, "mp": 0, "mpperlevel": 0,
             "attackdamage": 60, "attackdamageperlevel": 3.4,
             "armor": 33, "armorperlevel": 4.0, "spellblock": 32,
             "spellblockperlevel": 2.05, "attackspeed": 0.638,
             "attackspeedperlevel": 1.6, "movespeed": 340, "attackrange": 175},
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

    def __post_init__(self) -> None:
        base = base_stats_for(self.name)
        self.stats = ChampionStats.resolve(base, self.level)
        self.abilities = abilities_for(self.name)
        self.hp = self.stats.max_hp
        self.mp = self.stats.max_mp
        self.cooldowns = {"Q": 0.0, "W": 0.0, "E": 0.0, "R": 0.0}
        # respawn: remember where this champ started (its base) and death timer
        self.spawn_x = self.x
        self.spawn_y = self.y
        self.respawn_timer = 0.0        # seconds until revive (0 = alive)
        # economy
        self.gold = 500                 # starting gold (League-ish)
        self.cs = 0                     # creep score (minions last-hit)
        self.items: list = []           # inventory (filled by the shop)

    # ---- queries ----
    @property
    def alive(self) -> bool:
        return self.hp > 0.0

    @property
    def dead(self) -> bool:
        return self.hp <= 0.0

    def respawn(self) -> None:
        """Revive at base, full HP/mana, cooldowns reset."""
        self.hp = self.stats.max_hp
        self.mp = self.stats.max_mp
        self.x, self.y = self.spawn_x, self.spawn_y
        self.cc_remaining = 0.0
        self.attack_cd = 0.0
        self.respawn_timer = 0.0
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
    def take_damage(self, raw: float, damage_type: str) -> float:
        """Apply raw damage through the right resistance; return actual dealt."""
        from model.stats import post_mitigation
        if damage_type == "true":
            dealt = raw
        elif damage_type == "physical":
            dealt = post_mitigation(raw, self.stats.armor)
        else:  # magic
            dealt = post_mitigation(raw, self.stats.mr)
        self.hp = max(0.0, self.hp - dealt)
        return dealt

    def heal(self, amount: float) -> None:
        self.hp = min(self.stats.max_hp, self.hp + amount)

    def tick(self, dt: float) -> None:
        for k in self.cooldowns:
            self.cooldowns[k] = max(0.0, self.cooldowns[k] - dt)
        self.cc_remaining = max(0.0, self.cc_remaining - dt)
        self.attack_cd = max(0.0, self.attack_cd - dt)
