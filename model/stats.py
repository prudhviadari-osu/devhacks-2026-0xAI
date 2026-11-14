"""
League-accurate stat engine.

Two exact, public League formulas drive everything so the sim is statistically
close to real League where the numbers are knowable:

1) Per-level growth (non-linear). Source: LoL Wiki growth template.
       stat(L) = base + growth * (L-1) * (0.7025 + 0.0175 * (L-1))

2) Armor / magic-resist mitigation. Source: LoL Wiki (Armor).
       taken = raw * 100 / (100 + R)          for R >= 0
       taken = raw * (2 - 100 / (100 - R))     for R < 0   (amplified)

`base` and `growth` per stat come straight from Data Dragon
(sources/data_dragon.py), so adding a champion = loading its real numbers.
Ability damage/ratios are Tier-2 (hand-entered per champion) and live in
model/abilities.py, not here.
"""
from __future__ import annotations

from dataclasses import dataclass


# ---- formula 1: non-linear per-level growth ----
def growth_multiplier(level: int) -> float:
    """The (L-1)*(0.7025 + 0.0175*(L-1)) factor applied to a stat's growth."""
    n = level - 1
    return n * (0.7025 + 0.0175 * n)


def stat_at_level(base: float, growth: float, level: int) -> float:
    return base + growth * growth_multiplier(level)


# ---- formula 2: resistance mitigation ----
def mitigation_multiplier(resistance: float) -> float:
    """Fraction of raw damage that gets through after armor/MR."""
    if resistance >= 0:
        return 100.0 / (100.0 + resistance)
    # negative resistance amplifies damage (shred below 0)
    return 2.0 - 100.0 / (100.0 - resistance)


def post_mitigation(raw: float, resistance: float) -> float:
    return raw * mitigation_multiplier(resistance)


@dataclass
class BaseStats:
    """Level-1 base + per-level growth, as published by Data Dragon."""
    hp: float
    hp_per_level: float
    mp: float
    mp_per_level: float
    ad: float
    ad_per_level: float
    armor: float
    armor_per_level: float
    mr: float
    mr_per_level: float
    attack_speed: float            # base AS (e.g. 0.625)
    attack_speed_per_level: float  # % growth (Data Dragon gives this as a number)
    move_speed: float
    attack_range: float

    @classmethod
    def from_ddragon(cls, base: dict) -> "BaseStats":
        """Build from Data Dragon's champion `stats` dict (real field names)."""
        return cls(
            hp=base["hp"], hp_per_level=base["hpperlevel"],
            mp=base.get("mp", 0.0), mp_per_level=base.get("mpperlevel", 0.0),
            ad=base["attackdamage"], ad_per_level=base["attackdamageperlevel"],
            armor=base["armor"], armor_per_level=base["armorperlevel"],
            mr=base["spellblock"], mr_per_level=base["spellblockperlevel"],
            attack_speed=base["attackspeed"],
            attack_speed_per_level=base["attackspeedperlevel"],
            move_speed=base["movespeed"],
            attack_range=base["attackrange"],
        )


@dataclass
class ChampionStats:
    """Fully resolved stats at a given level (+ later: item bonuses)."""
    level: int
    max_hp: float
    max_mp: float
    ad: float
    armor: float
    mr: float
    attack_speed: float
    move_speed: float
    attack_range: float

    @classmethod
    def resolve(cls, base: BaseStats, level: int,
                bonus_armor: float = 0.0, bonus_mr: float = 0.0,
                bonus_hp: float = 0.0, bonus_ad: float = 0.0) -> "ChampionStats":
        return cls(
            level=level,
            max_hp=stat_at_level(base.hp, base.hp_per_level, level) + bonus_hp,
            max_mp=stat_at_level(base.mp, base.mp_per_level, level),
            ad=stat_at_level(base.ad, base.ad_per_level, level) + bonus_ad,
            armor=stat_at_level(base.armor, base.armor_per_level, level) + bonus_armor,
            mr=stat_at_level(base.mr, base.mr_per_level, level) + bonus_mr,
            # attack speed grows by a PERCENT of base per level (League rule)
            attack_speed=base.attack_speed * (
                1 + (base.attack_speed_per_level / 100.0) * growth_multiplier(level)
            ),
            move_speed=base.move_speed,
            attack_range=base.attack_range,
        )

    def effective_hp_vs_physical(self) -> float:
        """EHP: every point of armor adds ~1% effective HP vs physical."""
        return self.max_hp * (1 + self.armor / 100.0)

    def effective_hp_vs_magic(self) -> float:
        return self.max_hp * (1 + self.mr / 100.0)
