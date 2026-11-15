"""
Minions + lanes — the substance a laning bot reasons about.

Waves spawn periodically from each base, march along a lane toward the enemy
base, and auto-attack the nearest enemy (minion or champion) in range. When a
minion dies, whoever landed the killing blow gets GOLD (last-hitting) — the core
early-game skill that gives the bot constant meaningful micro-decisions.

Kept deliberately simple and readable (not a full creep-equilibrium sim): three
minion types with real-ish relative stats, one lane path each. Enough texture for
"farm vs. trade vs. help" to be a real choice, without modeling all of League.

Real League touchpoints: caster/melee/siege split, ~30g per minion-ish, waves
every ~30s. Numbers are approximate and labeled.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

MINION_TICK_RANGE = 900.0      # minion attack range (melee short, caster long)
WAVE_INTERVAL = 30.0           # seconds between waves (SR is ~30s)


@dataclass
class Minion:
    team: str                  # "ALLY" | "ENEMY"
    kind: str                  # "melee" | "caster" | "siege"
    lane: str                  # "TOP" | "MID" | "BOT"
    x: float
    y: float
    hp: float
    max_hp: float
    ad: float
    attack_range: float
    speed: float
    gold: int                  # bounty on last-hit
    attack_cd: float = 0.0
    uid: int = 0

    @property
    def alive(self) -> bool:
        return self.hp > 0.0

    @property
    def hp_frac(self) -> float:
        return self.hp / self.max_hp if self.max_hp else 0.0


# real-ish relative stats (not exact; labeled approximate)
_TYPES = {
    "melee":  dict(hp=480, ad=12, rng=120, speed=325, gold=21),
    "caster": dict(hp=300, ad=23, rng=550, speed=325, gold=14),
    "siege":  dict(hp=900, ad=40, rng=300, speed=325, gold=60),
}

# lane waypoint paths in game units (bottom-left base -> top-right base).
# ALLY walks start->end; ENEMY walks end->start.
LANE_PATHS = {
    "TOP": [(600, 2000), (600, 13000), (13000, 14400)],
    "MID": [(1500, 1500), (7500, 7500), (13500, 13500)],
    "BOT": [(2000, 600), (13000, 600), (14400, 13000)],
}


class MinionManager:
    """Owns all minions: spawning waves, moving, fighting, death + gold."""

    def __init__(self):
        self.minions: list[Minion] = []
        self._next_wave = 10.0     # first wave a little after game start
        self._uid = 0

    def update(self, world, dt: float) -> None:
        # spawn waves
        if world.time >= self._next_wave:
            self._spawn_wave("ALLY")
            self._spawn_wave("ENEMY")
            self._next_wave += WAVE_INTERVAL

        for m in self.minions:
            m.attack_cd = max(0.0, m.attack_cd - dt)

        self._act(world, dt)
        self._siege_structures(world)
        # clear dead (gold already awarded on the killing blow)
        self.minions = [m for m in self.minions if m.alive]

    def _siege_structures(self, world) -> None:
        """Minions chip the nearest attackable enemy structure they're next to —
        this is what actually pushes lanes toward the nexus."""
        sm = getattr(world, "structures", None)
        if sm is None:
            return
        for m in self.minions:
            if not m.alive:
                continue
            s = sm.nearest_attackable_enemy_structure(m)
            if s and math.hypot(s.x - m.x, s.y - m.y) <= m.attack_range:
                sm.damage_structure(s, m.ad * 0.5, world)

    def _spawn_wave(self, team: str) -> None:
        for lane, path in LANE_PATHS.items():
            start = path[0] if team == "ALLY" else path[-1]
            composition = ["melee", "melee", "melee", "caster", "caster", "caster"]
            for i, kind in enumerate(composition):
                t = _TYPES[kind]
                self._uid += 1
                # stagger along the lane start so they're not stacked
                ox = (-1) ** i * (i * 40)
                self.minions.append(Minion(
                    team=team, kind=kind, lane=lane,
                    x=start[0] + ox, y=start[1] + ox,
                    hp=t["hp"], max_hp=t["hp"], ad=t["ad"],
                    attack_range=t["rng"], speed=t["speed"], gold=t["gold"],
                    uid=self._uid))

    def _act(self, world, dt: float) -> None:
        for m in self.minions:
            if not m.alive:
                continue
            target = self._nearest_enemy(world, m)
            if target and self._dist(m, target) <= m.attack_range:
                if m.attack_cd <= 0.0:
                    self._minion_attack(world, m, target)
                    m.attack_cd = 1.0           # ~1 attack/sec
            else:
                self._march(m, dt)

    def _march(self, m: Minion, dt: float) -> None:
        path = LANE_PATHS[m.lane]
        goal = path[-1] if m.team == "ALLY" else path[0]
        dx, dy = goal[0] - m.x, goal[1] - m.y
        d = math.hypot(dx, dy)
        if d < 1e-6:
            return
        step = min(m.speed * dt, d)
        m.x += dx / d * step
        m.y += dy / d * step

    def _minion_attack(self, world, m: Minion, target) -> None:
        # target is a Minion or a Champion; both have take_damage-ish behavior
        if hasattr(target, "take_damage"):          # champion
            target.take_damage(m.ad, "physical")
        else:                                        # minion
            target.hp = max(0.0, target.hp - m.ad)
            if not target.alive:
                world.log.append(f"minion killed enemy {target.kind}")

    def _nearest_enemy(self, world, m: Minion):
        best, bd = None, float("inf")
        # enemy minions
        for other in self.minions:
            if other.team != m.team and other.alive:
                d = self._dist(m, other)
                if d < bd:
                    best, bd = other, d
        # enemy champions
        for c in world.champions:
            if c.team != m.team and c.alive:
                d = self._dist(m, c)
                if d < bd:
                    best, bd = c, d
        # only return a target if it's actually within THIS minion's attack range;
        # otherwise None so the minion marches toward the enemy base
        return best if (best is not None and bd <= m.attack_range) else None

    # champion deals damage to a minion; award gold on last-hit
    def champion_hit_minion(self, world, champ, minion: Minion, raw: float,
                            dtype: str) -> bool:
        """Returns True if this hit was the killing blow (last-hit -> gold)."""
        minion.hp = max(0.0, minion.hp - raw)   # minions have ~0 resist
        if not minion.alive:
            champ.gold = getattr(champ, "gold", 0) + minion.gold
            champ.cs = getattr(champ, "cs", 0) + 1
            world.log.append(
                f"{champ.name} last-hit {minion.kind} (+{minion.gold}g, "
                f"cs {champ.cs})")
            return True
        return False

    def nearest_killable(self, champ, team: str):
        """Lowest-hp enemy minion near the champ — a last-hit candidate."""
        cands = [m for m in self.minions
                 if m.team != team and m.alive
                 and self._dist(champ, m) < 1200]
        return min(cands, key=lambda m: m.hp, default=None)

    def _dist(self, a, b) -> float:
        return math.hypot(a.x - b.x, a.y - b.y)
