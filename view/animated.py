"""
AnimatedRenderer — real moving characters on a textured map.

Upgrades the View with three things pygame-primitives couldn't give you:
  1. a textured TILEMAP background (Tiled .tmx via pytmx) if present, else the
     shape map (view/sr_map) as fallback,
  2. CHARACTER SPRITES with walk animation (Kenney/LPC sheets) if present, else
     colored circles,
  3. SMOOTH MOVEMENT: champions interpolate between the model's tick positions
     so they glide instead of teleporting.

Everything degrades gracefully: with no assets it still runs (shapes + circles),
so you can develop while collecting assets. The Model/bots are untouched.

Setup on your Mac:
    pip install pygame pytmx
    # drop a Kenney packed sheet into assets/ (see view/sprites.py config)
    # optional: a Tiled map at assets/rift.tmx
    HUMAN=0 python3 game.py
"""
from __future__ import annotations

import os

from model.world import MAP_SIZE, World

WIN_W, WIN_H = 900, 900
WHITE = (235, 235, 235)
ALLY = (80, 170, 255)
ENEMY = (235, 90, 90)
HUMAN = (120, 230, 140)
HP_BG = (50, 50, 58)
HP_FG = (90, 210, 120)
MP_FG = (90, 140, 230)
CC_COL = (240, 220, 90)
DRAGON = (200, 150, 60)
GREY = (120, 120, 130)


class AnimatedRenderer:
    def __init__(self, human_name: str | None = None):
        try:
            import pygame
        except ImportError as e:
            raise ImportError("pip install pygame pytmx") from e
        self.pygame = pygame
        pygame.init()
        self.screen = pygame.display.set_mode((WIN_W, WIN_H))
        pygame.display.set_caption("League-accurate sim")
        self.font = pygame.font.SysFont("menlo", 13)
        self.big = pygame.font.SysFont("menlo", 18, bold=True)
        self.human_name = human_name
        self.clock = pygame.time.Clock()

        # sprites (graceful if missing)
        from view.sprites import build_champion_sprites
        self.sprites, self.sprite_cfg = build_champion_sprites(pygame)

        # tiled map (graceful if missing)
        self.tmx = self._load_tmx()

        # smooth movement: remember last drawn screen pos per champ
        self._draw_pos: dict[str, tuple[float, float]] = {}

    def _load_tmx(self):
        path = os.path.join(os.path.dirname(__file__), "..", "assets", "rift.tmx")
        if not os.path.exists(path):
            return None
        try:
            import pytmx
            return pytmx.load_pygame(path)
        except Exception:
            return None   # bad/missing map -> shape fallback

    # ---- coordinate mapping ----
    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return int(x / MAP_SIZE * WIN_W), int(WIN_H - y / MAP_SIZE * WIN_H)

    def scale_units(self, u: float) -> int:
        return max(1, int(u / MAP_SIZE * WIN_W))

    # ---- main draw ----
    def draw(self, world: World, callout: str = "", priority: str = "") -> None:
        pg = self.pygame
        dt = self.clock.get_time() / 1000.0 or (1 / 30)

        self._draw_background(pg)

        # objective
        ox, oy = self.to_screen(world.objective.x, world.objective.y)
        up = world.objective_up()
        pg.draw.circle(self.screen, DRAGON if up else GREY, (ox, oy), 12)
        self._text("DRAGON" + (" UP" if up else f" {world.objective.spawns_in:.0f}s"),
                   ox - 24, oy + 14, DRAGON if up else GREY)

        for c in world.champions:
            self._draw_champion(pg, c, dt)

        if priority:
            self._text(f"priority: {priority}", 12, 12, WHITE, big=True)
        if callout:
            self._text(f"\u201c{callout}\u201d", 12, 36, HUMAN, big=True)
        self._text(f"t={world.time:.1f}s", WIN_W - 90, 12, GREY)
        pg.display.flip()
        self.clock.tick(60)

    def _draw_background(self, pg) -> None:
        if self.tmx is not None:
            self._draw_tmx(pg)
        else:
            from view.sr_map import draw_map   # shape fallback
            draw_map(pg, self.screen, WIN_W, WIN_H)

    def _draw_tmx(self, pg) -> None:
        tmx = self.tmx
        tw, th = tmx.tilewidth, tmx.tileheight
        # scale the whole map to fill the window
        sx = WIN_W / (tmx.width * tw)
        sy = WIN_H / (tmx.height * th)
        self.screen.fill((20, 22, 28))
        for layer in tmx.visible_layers:
            if not hasattr(layer, "tiles"):
                continue
            for x, y, image in layer.tiles():
                if image is None:
                    continue
                img = pg.transform.scale(image, (int(tw * sx) + 1, int(th * sy) + 1))
                self.screen.blit(img, (int(x * tw * sx), int(y * th * sy)))

    def _draw_champion(self, pg, c, dt) -> None:
        if not c.alive:
            # show a respawn countdown marker at base instead of a corpse
            bx, by = self.to_screen(c.spawn_x, c.spawn_y)
            self._text(f"{c.name} \u2620 {c.respawn_timer:.0f}s", bx - 24, by,
                       GREY)
            self._draw_pos.pop(c.name, None)
            return

        tx, ty = self.to_screen(c.x, c.y)
        # smooth movement: lerp drawn position toward the true position
        px, py = self._draw_pos.get(c.name, (tx, ty))
        nx, ny = px + (tx - px) * 0.35, py + (ty - py) * 0.35
        self._draw_pos[c.name] = (nx, ny)
        moving = (abs(tx - px) + abs(ty - py)) > 1.5
        cx, cy = int(nx), int(ny)

        color = HUMAN if c.name == self.human_name else (
            ALLY if c.team == "ALLY" else ENEMY)

        # attack range ring
        r = self.scale_units(c.stats.attack_range)
        if r > 3:
            pg.draw.circle(self.screen, tuple(int(v * 0.35) for v in color),
                           (cx, cy), r, 1)

        # sprite if available, else circle
        sprite = self.sprites.get(c.name) or self.sprites.get("_default")
        frame = sprite.current(moving, dt) if sprite and sprite.ok() else None
        if frame is not None:
            rect = frame.get_rect(center=(cx, cy))
            # team tint ring behind sprite so you can tell sides apart
            pg.draw.circle(self.screen, color, (cx, cy),
                           frame.get_width() // 2 + 3, 2)
            self.screen.blit(frame, rect)
        else:
            pg.draw.circle(self.screen, color, (cx, cy), 11)
            pg.draw.circle(self.screen, WHITE, (cx, cy), 11, 1)

        if c.cc_remaining > 0:
            pg.draw.circle(self.screen, CC_COL, (cx, cy), 18, 3)

        self._text(f"{c.name} L{c.level}", cx - 26, cy - 34, WHITE)
        self._bar(cx - 24, cy + 20, 48, 6, c.hp_frac, HP_FG)
        if c.stats.max_mp > 0:
            self._bar(cx - 24, cy + 28, 48, 3, c.mp / c.stats.max_mp, MP_FG)

    def _bar(self, x, y, w, h, frac, color) -> None:
        pg = self.pygame
        frac = max(0.0, min(1.0, frac))
        pg.draw.rect(self.screen, HP_BG, (x, y, w, h))
        pg.draw.rect(self.screen, color, (x, y, int(w * frac), h))

    def _text(self, s, x, y, color, big=False) -> None:
        font = self.big if big else self.font
        self.screen.blit(font.render(s, True, color), (x, y))

    def poll_quit(self) -> bool:
        for _ in self.pygame.event.get(self.pygame.QUIT):
            return True
        return False

    def close(self) -> None:
        self.pygame.quit()
