"""
Items + shop — real League-style item stats that champions buy with gold.

Each item is a bag of stat bonuses with a gold cost. Champions earn gold (CS,
kills, assists, time) and the shop spends it on the best affordable item for the
champion's archetype. Item stats sum into the champion's resolved stats via the
bonus_* hooks already in model/stats.py, so buying an item actually makes a
champion stronger (more AD/AP/HP/armor/MR → more damage dealt / taken reduced).

Stats are real-ish League values (approximate, labeled). AP is added here since
the base stat engine didn't model it.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Item:
    name: str
    cost: int
    ad: float = 0.0
    ap: float = 0.0
    hp: float = 0.0
    armor: float = 0.0
    mr: float = 0.0
    attack_speed: float = 0.0   # flat added to base AS
    # which archetypes want this item (shop picks from these)
    for_roles: tuple = ()


# a compact but real item pool spanning the damage/defense spectrum
ITEMS = [
    # --- AD / marksman / bruiser ---
    Item("Long Sword", 350, ad=10, for_roles=("MARKSMAN", "BRUISER")),
    Item("Pickaxe", 875, ad=25, for_roles=("MARKSMAN", "BRUISER")),
    Item("B.F. Sword", 1300, ad=40, for_roles=("MARKSMAN", "BRUISER")),
    Item("Infinity Edge", 3400, ad=70, for_roles=("MARKSMAN",)),
    Item("Kraken Slayer", 3100, ad=65, attack_speed=0.25, for_roles=("MARKSMAN",)),
    Item("Trinity Force", 3333, ad=45, hp=300, attack_speed=0.33,
         for_roles=("BRUISER",)),
    # --- AP / mage ---
    Item("Amp Tome", 435, ap=20, for_roles=("MAGE", "ENCHANTER")),
    Item("Blasting Wand", 850, ap=40, for_roles=("MAGE",)),
    Item("Needlessly Large Rod", 1250, ap=60, for_roles=("MAGE",)),
    Item("Rabadon's Deathcap", 3600, ap=120, for_roles=("MAGE",)),
    Item("Luden's Tempest", 3200, ap=90, for_roles=("MAGE",)),
    # --- tank / defense ---
    Item("Cloth Armor", 300, armor=15, for_roles=("TANK", "BRUISER")),
    Item("Null-Magic Mantle", 450, mr=25, for_roles=("TANK", "ENCHANTER")),
    Item("Ruby Crystal", 400, hp=150, for_roles=("TANK", "BRUISER")),
    Item("Sunfire Aegis", 2900, hp=450, armor=30, for_roles=("TANK",)),
    Item("Thornmail", 2700, hp=350, armor=50, for_roles=("TANK",)),
    Item("Spirit Visage", 2900, hp=450, mr=40, for_roles=("TANK", "BRUISER")),
    # --- enchanter / support utility ---
    Item("Ardent Censer", 2600, ap=45, mr=20, for_roles=("ENCHANTER",)),
    Item("Redemption", 2300, ap=40, hp=200, for_roles=("ENCHANTER",)),
    Item("Locket", 2500, hp=200, armor=25, for_roles=("ENCHANTER", "TANK")),
]


def item_stats_total(items: list[Item]) -> dict:
    """Sum all owned items' bonuses into the bonus_* kwargs resolve() expects."""
    tot = {"bonus_ad": 0.0, "bonus_ap": 0.0, "bonus_hp": 0.0,
           "bonus_armor": 0.0, "bonus_mr": 0.0, "bonus_as": 0.0}
    for it in items:
        tot["bonus_ad"] += it.ad
        tot["bonus_ap"] += it.ap
        tot["bonus_hp"] += it.hp
        tot["bonus_armor"] += it.armor
        tot["bonus_mr"] += it.mr
        tot["bonus_as"] += it.attack_speed
    return tot


def best_affordable(gold: int, owned: list[Item], archetype: str) -> Item | None:
    """Pick the best item this champion can afford and doesn't already own —
    prefer the most expensive relevant one (biggest power spike it can buy)."""
    owned_names = {it.name for it in owned}
    affordable = [it for it in ITEMS
                  if it.cost <= gold and it.name not in owned_names
                  and (not it.for_roles or archetype in it.for_roles)]
    if not affordable:
        return None
    return max(affordable, key=lambda it: it.cost)
