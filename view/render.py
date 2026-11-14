"""
View — pygame renderer. Fidelity over art: shapes, bars, ranges, text.

Draws the World each frame: champions as colored circles (ally/enemy), HP and
mana bars, attack-range rings, CC indicators, the dragon objective, and the
bot's current callout + priority. No sprites — the point is readable, accurate
state, not graphics.

Runs on your Mac: `pip install pygame`. This module imports pygame lazily so the
rest of the project (and headless tests) never require it.

Coordinate mapping: World is ~15000 game units; we scale to the window.
"""
from __future__ import annotations

from model.world import MAP_SIZE, World

WIN_W, WIN_H = 900, 900
BG = (24, 26, 32)
ALLY = (80, 170, 255)
ENEMY = (235, 90, 90)
HUMAN = (120, 230, 140)
DRAGON = (200, 150, 60)
WHITE = (235, 235, 235)
GREY = (120, 120, 130)
HP_BG = (60, 60, 68)
HP_FG = (90, 210, 120)
MP_FG = (90, 140, 230)
CC_COL = (240, 220, 90)


class Renderer:
    def __init__(self, human_name: str | None = None):
        import pygame
        self.pygame = pygame
        pygame.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("Support Bot — League-accurate sim")
        self.font = pygame.font.SysFont("menlo", 14)
        self.big = pygame.font.SysFont("menlo", 18, bold=True)
        self.human_name = human_name

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        sx = int(x / MAP_SIZE * WIN_W)
        sy = int(WIN_H - y / MAP_SIZE * WIN_H)   # flip y so up = north
        return sx, sy

    def scale(self, units: float) -> int:
        return max(1, int(units / MAP_SIZE * WIN_W))

    def draw(self, world: World, callout: str = "", priority: str = "") -> None:
        pg = self.pygame
        self.screen.fill(BG)

        # objective
        ox, oy = self.to_screen(world.objective.x, world.objective.y)
        up = world.objective_up()
        pg.draw.circle(self.screen, DRAGON if up else GREY, (ox, oy), 12)
        label = "DRAGON UP" if up else f"dragon {world.objective.spawns_in:.0f}s"
        self._text(label, ox - 28, oy + 14, DRAGON if up else GREY)

        # champions
        for c in world.champions:
            if not c.alive:
                continue
            cx, cy = self.to_screen(c.x, c.y)
            color = HUMAN if c.name == self.human_name else (
                ALLY if c.team == "ALLY" else ENEMY)
            # attack-range ring
            pg.draw.circle(self.screen, (*color, 40),
                           (cx, cy), self.scale(c.stats.attack_range), 1)
            # body
            pg.draw.circle(self.screen, color, (cx, cy), 10)
            if c.cc_remaining > 0:
                pg.draw.circle(self.screen, CC_COL, (cx, cy), 13, 2)
            # name + level
            self._text(f"{c.name} L{c.level}", cx - 24, cy - 30, WHITE)
            # hp / mana bars
            self._bar(cx - 22, cy + 14, 44, 5, c.hp_frac, HP_FG)
            if c.stats.max_mp > 0:
                self._bar(cx - 22, cy + 21, 44, 3, c.mp / c.stats.max_mp, MP_FG)

        # bot callout HUD
        if priority:
            self._text(f"priority: {priority}", 12, 12, WHITE, big=True)
        if callout:
            self._text(f"\u201c{callout}\u201d", 12, 36, HUMAN, big=True)
        self._text(f"t={world.time:.1f}s", WIN_W - 90, 12, GREY)

        pg.display.flip()

    def _bar(self, x, y, w, h, frac, color) -> None:
        pg = self.pygame
        frac = max(0.0, min(1.0, frac))
        pg.draw.rect(self.screen, HP_BG, (x, y, w, h))
        pg.draw.rect(self.screen, color, (x, y, int(w * frac), h))

    def _text(self, s, x, y, color, big=False) -> None:
        font = self.big if big else self.font
        self.screen.blit(font.render(s, True, color), (x, y))

    def poll_quit(self) -> bool:
        for e in self.pygame.event.get(self.pygame.QUIT):
            return True
        return False

    def close(self) -> None:
        self.pygame.quit()
