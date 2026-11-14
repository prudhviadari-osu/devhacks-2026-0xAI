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
        try:
            import pygame
        except ImportError as e:
            raise ImportError(
                "pygame is required to render the game. Install it with:\n"
                "    pip install pygame\n"
                "(the sim logic runs without it; only the View needs it.)"
            ) from e
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
            # attack-range ring (dimmed version of the champ color; no alpha
            # tuple — pygame.draw.circle takes RGB only, RGBA crashes)
            ring = tuple(int(ch * 0.35) for ch in color)
            r_px = self.scale(c.stats.attack_range)
            if r_px > 3:
                pg.draw.circle(self.screen, ring, (cx, cy), r_px, 1)
            # body
            pg.draw.circle(self.screen, color, (cx, cy), 11)
            pg.draw.circle(self.screen, WHITE, (cx, cy), 11, 1)  # outline
            if c.cc_remaining > 0:
                pg.draw.circle(self.screen, CC_COL, (cx, cy), 15, 3)
            # name + level
            self._text(f"{c.name} L{c.level}", cx - 26, cy - 32, WHITE)
            # hp / mana bars
            self._bar(cx - 24, cy + 15, 48, 6, c.hp_frac, HP_FG)
            if c.stats.max_mp > 0:
                self._bar(cx - 24, cy + 23, 48, 3, c.mp / c.stats.max_mp, MP_FG)

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


def selftest() -> None:
    """Render a few frames to an OFF-SCREEN surface (no window) to prove the
    draw path doesn't crash. Run: `python3 -m view.render` """
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # headless
    from model.champion import Champion
    from model.world import World, Idle
    champs = [
        Champion("Sona", "ALLY", "SUPPORT", level=6, x=5000, y=5000),
        Champion("Lulu", "ALLY", "ADC", level=6, x=5200, y=4900),
        Champion("Zac", "ENEMY", "JUNGLE", level=6, x=9000, y=9000),
    ]
    w = World(champs, dragon_spawn=5)
    r = Renderer(human_name="Sona")
    for _ in range(10):
        w.step({c.name: Idle() for c in champs})
        r.draw(w, callout="Peeling for you — Lulu, hold!", priority="peel_carry")
    r.close()
    print("render self-test OK: 10 frames drawn headless, no crash")


if __name__ == "__main__":
    selftest()
