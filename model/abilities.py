"""
Tier-2 ability data (hand-entered) for the v1 roster.

Data Dragon gives base stats + ability cooldowns, but NOT clean machine-readable
ability damage/ratios/CC. Those are public (wiki/tooltips) but must be entered by
hand for faithful numbers. This file is that curated data for:

    Jax, Lulu, Ryze, Sona, Zac

Values are per-rank lists (index 0 = rank 1). Damage is base; `ap_ratio`/`ad_ratio`
scale with the caster's AP/AD. CC durations in seconds. These are the CORE
interactions modeled faithfully for v1; genuinely complex/aura mechanics
(Ryze rune-stacking combos, Sona's passive aura cycling) are simplified and
flagged with `SIMPLIFIED` so the tradeoff is explicit (mentor deck: know it).

Patch note: tune these to the live patch before the demo — numbers drift.
Treat this as a small, reviewable data table, not engine logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ability:
    slot: str                        # "Q" | "W" | "E" | "R"
    name: str
    cooldown: list[float]            # per rank, seconds
    base_damage: list[float] = field(default_factory=lambda: [0.0])
    ap_ratio: float = 0.0            # bonus = ap_ratio * caster_AP
    ad_ratio: float = 0.0            # bonus = ad_ratio * caster_AD (total AD)
    damage_type: str = "magic"       # "magic" | "physical" | "true"
    cc_type: str | None = None       # "stun" | "root" | "slow" | "knockup" | None
    cc_duration: list[float] = field(default_factory=lambda: [0.0])
    heal: list[float] = field(default_factory=lambda: [0.0])
    shield: list[float] = field(default_factory=lambda: [0.0])
    range: float = 600.0             # cast range in game units
    notes: str = ""

    def dmg(self, rank: int, ap: float = 0.0, ad: float = 0.0) -> float:
        i = min(rank - 1, len(self.base_damage) - 1)
        return self.base_damage[i] + self.ap_ratio * ap + self.ad_ratio * ad

    def cc(self, rank: int) -> float:
        i = min(rank - 1, len(self.cc_duration) - 1)
        return self.cc_duration[i]

    def cd(self, rank: int) -> float:
        return self.cooldown[min(rank - 1, len(self.cooldown) - 1)]


# ---- roster ability tables ----
ABILITIES: dict[str, dict[str, Ability]] = {

    "Jax": {  # AD bruiser; E stun on the counterstrike
        "Q": Ability("Q", "Leap Strike", cooldown=[7, 6.25, 5.5, 4.75, 4],
                     base_damage=[65, 110, 155, 200, 245], ad_ratio=1.0,
                     damage_type="physical", range=700),
        "W": Ability("W", "Empower", cooldown=[6, 5.5, 5, 4.5, 4],
                     base_damage=[55, 80, 105, 130, 155], ap_ratio=0.6,
                     damage_type="magic", range=150),
        "E": Ability("E", "Counter Strike", cooldown=[14, 12.5, 11, 9.5, 8],
                     base_damage=[55, 80, 105, 130, 155], ap_ratio=0.5,
                     damage_type="magic", cc_type="stun",
                     cc_duration=[1, 1, 1, 1, 1], range=300,
                     notes="stun after channel / when struck"),
        "R": Ability("R", "Grandmaster's Might", cooldown=[0, 0, 0],
                     base_damage=[0], notes="SIMPLIFIED: passive on-hit, not a cast"),
    },

    "Lulu": {  # enchanter: shields/heals/peel, R knockup
        "Q": Ability("Q", "Glitterlance", cooldown=[7, 6.5, 6, 5.5, 5],
                     base_damage=[70, 105, 140, 175, 210], ap_ratio=0.5,
                     damage_type="magic", cc_type="slow",
                     cc_duration=[0.8]*5, range=950),
        "W": Ability("W", "Whimsy", cooldown=[17, 16, 15, 14, 13],
                     cc_type="polymorph", cc_duration=[1.25, 1.5, 1.75, 2, 2.25],
                     range=650, notes="polymorph enemy OR haste ally"),
        "E": Ability("E", "Help, Pix!", cooldown=[10, 9, 8, 7, 6],
                     base_damage=[80, 120, 160, 200, 240], ap_ratio=0.4,
                     shield=[70, 105, 140, 175, 210], range=650,
                     notes="shield ally OR damage enemy"),
        "R": Ability("R", "Wild Growth", cooldown=[110, 95, 80],
                     shield=[300, 450, 600], cc_type="knockup",
                     cc_duration=[1, 1, 1], range=900,
                     notes="ally grows: big HP + knockup nearby enemies"),
    },

    "Ryze": {  # AP combo mage; E root-spreads (SIMPLIFIED to a direct root)
        "Q": Ability("Q", "Overload", cooldown=[3.2, 3.05, 2.9, 2.75, 2.6],
                     base_damage=[80, 95, 110, 125, 140], ap_ratio=0.55,
                     damage_type="magic", range=1000),
        "W": Ability("W", "Rune Prison", cooldown=[13, 12, 11, 10, 9],
                     base_damage=[80, 110, 140, 170, 200], ap_ratio=0.6,
                     damage_type="magic", cc_type="root",
                     cc_duration=[0.8, 0.9, 1.0, 1.1, 1.2], range=600),
        "E": Ability("E", "Spell Flux", cooldown=[3.2, 3.05, 2.9, 2.75, 2.6],
                     base_damage=[60, 85, 110, 135, 160], ap_ratio=0.4,
                     damage_type="magic", range=600,
                     notes="SIMPLIFIED: single-target, no spread/flux chaining"),
        "R": Ability("R", "Realm Warp", cooldown=[210, 180, 150],
                     notes="SIMPLIFIED: utility teleport, no combat effect in v1"),
    },

    "Sona": {  # enchanter: heal/shield/dmg auras, R AoE stun
        "Q": Ability("Q", "Hymn of Valor", cooldown=[7, 6.5, 6, 5.5, 5],
                     base_damage=[40, 70, 100, 130, 160], ap_ratio=0.4,
                     damage_type="magic", range=850,
                     notes="SIMPLIFIED: direct dmg, aura ADbuff omitted"),
        "W": Ability("W", "Aria of Perseverance", cooldown=[7, 6.5, 6, 5.5, 5],
                     heal=[35, 55, 75, 95, 115], ap_ratio=0.25,
                     shield=[50, 65, 80, 95, 110], range=850,
                     notes="SIMPLIFIED: heal+shield, aura MR buff omitted"),
        "E": Ability("E", "Song of Celerity", cooldown=[7, 6.5, 6, 5.5, 5],
                     cc_type="haste", cc_duration=[1.5]*5, range=1000,
                     notes="movement-speed buff to allies"),
        "R": Ability("R", "Crescendo", cooldown=[140, 120, 100],
                     base_damage=[150, 250, 350], ap_ratio=0.5,
                     damage_type="magic", cc_type="stun",
                     cc_duration=[1.5, 1.5, 1.5], range=1000,
                     notes="AoE stun — Sona's signature teamfight peel/engage"),
    },

    "Zac": {  # tanky engage/diver; E long-range knockup engage
        "Q": Ability("Q", "Stretching Strike", cooldown=[6, 5.5, 5, 4.5, 4],
                     base_damage=[30, 45, 60, 75, 90], ap_ratio=0.3,
                     damage_type="magic", cc_type="knockup",
                     cc_duration=[0.5]*5, range=550),
        "W": Ability("W", "Unstable Matter", cooldown=[4, 4, 4, 4, 4],
                     base_damage=[40, 55, 70, 85, 100], ap_ratio=0.5,
                     damage_type="magic", range=300),
        "E": Ability("E", "Elastic Slingshot", cooldown=[16, 14.5, 13, 11.5, 10],
                     base_damage=[80, 120, 160, 200, 240], ap_ratio=0.7,
                     damage_type="magic", cc_type="knockup",
                     cc_duration=[1, 1, 1, 1, 1], range=1800,
                     notes="long-range engage — the dive threat the support peels"),
        "R": Ability("R", "Let's Bounce!", cooldown=[95, 75, 55],
                     base_damage=[140, 210, 280], ap_ratio=0.4,
                     damage_type="magic", cc_type="knockup",
                     cc_duration=[1, 1, 1], range=1000,
                     notes="AoE knockup bounces — teamfight engage"),
    },

    "Ashe": {  # marksman: slow-heavy, long-range stun ult
        "Q": Ability("Q", "Ranger's Focus", cooldown=[0, 0, 0, 0, 0],
                     base_damage=[0], ad_ratio=1.05, damage_type="physical",
                     range=600, notes="SIMPLIFIED: attack-speed burst"),
        "W": Ability("W", "Volley", cooldown=[16, 13, 10, 7, 4],
                     base_damage=[20, 35, 50, 65, 80], ad_ratio=1.0,
                     damage_type="physical", cc_type="slow",
                     cc_duration=[1.5]*5, range=1200),
        "E": Ability("E", "Hawkshot", cooldown=[0, 0, 0, 0, 0],
                     notes="SIMPLIFIED: vision scout, no combat effect"),
        "R": Ability("R", "Enchanted Crystal Arrow", cooldown=[100, 90, 80],
                     base_damage=[200, 400, 600], ap_ratio=1.0,
                     damage_type="magic", cc_type="stun",
                     cc_duration=[1.5, 2.25, 3.0], range=1600,
                     notes="global stun arrow — long-range engage/peel"),
    },

    "Darius": {  # bruiser/juggernaut: bleed, pull, execute R
        "Q": Ability("Q", "Decimate", cooldown=[9, 8, 7, 6, 5],
                     base_damage=[50, 80, 110, 140, 170], ad_ratio=1.0,
                     damage_type="physical", range=425),
        "W": Ability("W", "Crippling Strike", cooldown=[9, 8, 7, 6, 5],
                     base_damage=[0], ad_ratio=1.4, damage_type="physical",
                     cc_type="slow", cc_duration=[0.9]*5, range=175),
        "E": Ability("E", "Apprehend", cooldown=[24, 21, 18, 15, 12],
                     cc_type="pull", cc_duration=[0.5]*5, range=535,
                     notes="pull enemy toward you (engage/catch)"),
        "R": Ability("R", "Noxian Guillotine", cooldown=[100, 90, 80],
                     base_damage=[100, 200, 300], ad_ratio=0.75,
                     damage_type="true", range=460,
                     notes="true-damage execute — resets on kill"),
    },

    "Lux": {  # mage: long-range binding root + huge poke ult
        "Q": Ability("Q", "Light Binding", cooldown=[11, 10.5, 10, 9.5, 9],
                     base_damage=[80, 120, 160, 200, 240], ap_ratio=0.6,
                     damage_type="magic", cc_type="root",
                     cc_duration=[1.8, 1.9, 2.0, 2.1, 2.2], range=1175),
        "W": Ability("W", "Prismatic Barrier", cooldown=[14, 13, 12, 11, 10],
                     shield=[50, 65, 80, 95, 110], ap_ratio=0.2, range=1075,
                     notes="shields allies it passes through"),
        "E": Ability("E", "Lucent Singularity", cooldown=[10, 9.5, 9, 8.5, 8],
                     base_damage=[65, 115, 165, 215, 265], ap_ratio=0.8,
                     damage_type="magic", cc_type="slow",
                     cc_duration=[1.0]*5, range=1100),
        "R": Ability("R", "Final Spark", cooldown=[80, 60, 40],
                     base_damage=[300, 400, 500], ap_ratio=1.2,
                     damage_type="magic", range=3400,
                     notes="long-range AoE laser — signature poke/burst"),
    },

    "Leona": {  # tank engage support: stun, root, AoE ult
        "Q": Ability("Q", "Shield of Daybreak", cooldown=[6, 5.5, 5, 4.5, 4],
                     base_damage=[60, 100, 140, 180, 220], ap_ratio=0.3,
                     damage_type="magic", cc_type="stun",
                     cc_duration=[1.0]*5, range=125),
        "W": Ability("W", "Eclipse", cooldown=[14, 13, 12, 11, 10],
                     base_damage=[0], range=0,
                     notes="SIMPLIFIED: resist buff, no target"),
        "E": Ability("E", "Zenith Blade", cooldown=[10, 9.25, 8.5, 7.75, 7],
                     base_damage=[60, 100, 140, 180, 220], ap_ratio=0.4,
                     damage_type="magic", cc_type="root",
                     cc_duration=[0.5]*5, range=875,
                     notes="dash to target + root — engage"),
        "R": Ability("R", "Solar Flare", cooldown=[90, 75, 60],
                     base_damage=[100, 175, 250], ap_ratio=0.8,
                     damage_type="magic", cc_type="stun",
                     cc_duration=[0.5, 0.5, 0.5], range=1200,
                     notes="AoE stun (center) — teamfight engage"),
    },

    "Ahri": {  # assassin-mage: charm, mobility ult
        "Q": Ability("Q", "Orb of Deception", cooldown=[7, 6.5, 6, 5.5, 5],
                     base_damage=[60, 90, 120, 150, 180], ap_ratio=0.55,
                     damage_type="magic", range=880),
        "W": Ability("W", "Fox-Fire", cooldown=[9, 8, 7, 6, 5],
                     base_damage=[50, 70, 90, 110, 130], ap_ratio=0.4,
                     damage_type="magic", range=700),
        "E": Ability("E", "Charm", cooldown=[12, 11, 10, 9, 8],
                     base_damage=[80, 110, 140, 170, 200], ap_ratio=0.6,
                     damage_type="magic", cc_type="stun",
                     cc_duration=[1.4, 1.55, 1.7, 1.85, 2.0], range=1000,
                     notes="charm (treated as stun) — pick/setup"),
        "R": Ability("R", "Spirit Rush", cooldown=[130, 105, 80],
                     base_damage=[60, 90, 120], ap_ratio=0.35,
                     damage_type="magic", range=450,
                     notes="3 dashes — assassinate/escape mobility"),
    },
}


def abilities_for(champion: str) -> dict[str, Ability]:
    if champion not in ABILITIES:
        raise KeyError(f"no ability data for {champion}; add it to ABILITIES")
    return ABILITIES[champion]
