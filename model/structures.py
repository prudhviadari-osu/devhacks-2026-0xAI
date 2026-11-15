"""
Towers + nexus — real League map structure and win condition.

Each team has towers guarding its three lanes and a nexus at base. Towers shoot
the nearest enemy (champion or minion) in range and must be destroyed in lane
order before the nexus is vulnerable. Destroying the enemy nexus wins.

Kept readable: one outer + one inhibitor-ish tower per lane + the nexus. Towers
hit hard (so diving under tower is punished — real League texture the bots can
learn to respect via the reward/spacing).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

TOWER_RANGE = 1300.0
TOWER_DAMAGE = 140.0          # per shot; ramps on champions in real LoL (simplified)
TOWER_ATTACK_CD = 1.0
# HP tuned so sieges resolve within a sim session (real LoL towers are tankier;
# scaled down so you can watch a full game end on a nexus kill).
TOWER_HP = 1050.0
NEXUS_HP = 1700.0


@dataclass
class Structure:
    team: str                  # "ALLY" | "ENEMY"
    kind: str                  # "tower" | "nexus"
    lane: str                  # "TOP"|"MID"|"BOT"|"BASE"
    tier: int                  # 1 = outer, 2 = inner; nexus = 0
    x: float
    y: float
    hp: float
    max_hp: float
    attack_cd: float = 0.0

    @property
    def alive(self) -> bool:
        return self.hp > 0.0

    @property
    def hp_frac(self) -> float:
        return self.hp / self.max_hp if self.max_hp else 0.0


# tower positions per team along each lane (ally = blue, enemy = red)
def _tower_layout():
    towers = []
    # ally (blue, bottom-left side): outer towers pushed toward mid, inner closer home
    ally = {
        "TOP": [(1400, 9500), (1400, 5500)],
        "MID": [(5500, 5500), (3500, 3500)],
        "BOT": [(9500, 1400), (5500, 1400)],
    }
    enemy = {
        "TOP": [(5500, 13600), (9500, 13600)],
        "MID": [(9500, 9500), (11500, 11500)],
        "BOT": [(13600, 5500), (13600, 9500)],
    }
    for lane, pts in ally.items():
        for tier, (x, y) in enumerate(pts, start=1):
            towers.append(Structure("ALLY", "tower", lane, tier, x, y,
                                    TOWER_HP, TOWER_HP))
    for lane, pts in enemy.items():
        for tier, (x, y) in enumerate(pts, start=1):
            towers.append(Structure("ENEMY", "tower", lane, tier, x, y,
                                    TOWER_HP, TOWER_HP))
    return towers


class StructureManager:
    def __init__(self):
        self.structures: list[Structure] = _tower_layout()
        self.structures.append(Structure("ALLY", "nexus", "BASE", 0,
                                          1000, 1000, NEXUS_HP, NEXUS_HP))
        self.structures.append(Structure("ENEMY", "nexus", "BASE", 0,
                                          14000, 14000, NEXUS_HP, NEXUS_HP))
        self.winner: str | None = None

    def towers(self, team: str) -> list[Structure]:
        return [s for s in self.structures if s.team == team
                and s.kind == "tower" and s.alive]

    def nexus(self, team: str) -> Structure | None:
        return next((s for s in self.structures if s.team == team
                     and s.kind == "nexus"), None)

    def update(self, world, dt: float) -> None:
        for s in self.structures:
            if not s.alive:
                continue
            s.attack_cd = max(0.0, s.attack_cd - dt)
            if s.kind == "tower" and s.attack_cd <= 0.0:
                self._tower_shoot(world, s)
        self._check_win()

    def _tower_shoot(self, world, tower: Structure) -> None:
        # nearest enemy champion or minion in range; prefer minions (LoL aggro)
        best, bd = None, TOWER_RANGE
        mm = getattr(world, "minions", None)
        if mm:
            for m in mm.minions:
                if m.team != tower.team and m.alive:
                    d = math.hypot(m.x - tower.x, m.y - tower.y)
                    if d < bd:
                        best, bd = m, d
        if best is None:  # no minion -> hit a champion
            for c in world.champions:
                if c.team != tower.team and c.alive:
                    d = math.hypot(c.x - tower.x, c.y - tower.y)
                    if d < bd:
                        best, bd = c, d
        if best is None:
            return
        tower.attack_cd = TOWER_ATTACK_CD
        if hasattr(best, "take_damage"):      # champion
            best.take_damage(TOWER_DAMAGE, "true", source=None, now=world.time)
            world.log.append(f"{tower.team} {tower.lane} tower hits {best.name}")
        else:                                  # minion
            best.hp = max(0.0, best.hp - TOWER_DAMAGE)

    def damage_structure(self, s: Structure, amount: float, world) -> None:
        """A champion/minion attacks a structure (only if it's attackable)."""
        if not self.attackable(s):
            return
        s.hp = max(0.0, s.hp - amount)
        if not s.alive:
            world.log.append(f"{s.team} {s.lane} "
                             f"{'nexus' if s.kind=='nexus' else 'tower T'+str(s.tier)} destroyed")

    def attackable(self, s: Structure) -> bool:
        """A tower is attackable only if the earlier-tier tower in its lane is
        down; a nexus only if all that team's towers are down (simplified)."""
        if not s.alive:
            return False
        if s.kind == "nexus":
            # nexus is exposed once a LANE is fully broken (both its towers down),
            # not only when every tower on the map is gone — matches how a real
            # push opens the base, and lets games actually end.
            for lane in ("TOP", "MID", "BOT"):
                lane_towers = [t for t in self.structures if t.team == s.team
                               and t.kind == "tower" and t.lane == lane]
                if lane_towers and all(not t.alive for t in lane_towers):
                    return True
            return len(self.towers(s.team)) == 0
        if s.tier == 1:
            return True
        # tier 2 requires tier 1 in the same lane destroyed
        t1 = next((t for t in self.structures if t.team == s.team
                   and t.lane == s.lane and t.tier == 1), None)
        return t1 is None or not t1.alive

    def _check_win(self) -> None:
        for team in ("ALLY", "ENEMY"):
            nx = self.nexus(team)
            if nx and not nx.alive:
                self.winner = "ENEMY" if team == "ALLY" else "ALLY"

    def nearest_attackable_enemy_structure(self, champ):
        # if the enemy nexus is exposed, prioritize it (close out the game)
        enemy_team = "ENEMY" if champ.team == "ALLY" else "ALLY"
        nx = self.nexus(enemy_team)
        if nx is not None and nx.alive and self.attackable(nx):
            return nx
        best, bd = None, float("inf")
        for s in self.structures:
            if s.team != champ.team and self.attackable(s):
                d = math.hypot(s.x - champ.x, s.y - champ.y)
                if d < bd:
                    best, bd = s, d
        return best
