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
        # per-champion AI decision info for the overlay panel (set by game loop)
        self.ai_info: dict[str, dict] = {}

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

        # attack / cast / heal effect lines (from this tick's world.fx)
        self._draw_effects(pg, world)

        # minions (small dots in team colors with a thin hp bar)
        self._draw_minions(pg, world)

        for c in world.champions:
            self._draw_champion(pg, c, dt)

        # --- UI overlay ---
        self._draw_ai_panel(pg, world)          # right: what each AI is doing
        self._draw_combat_feed(pg, world)       # bottom: recent events
        if priority:
            self._text(f"YOU/BOT: {priority}", 12, 12, WHITE, big=True)
        if callout:
            self._text(f"\u201c{callout}\u201d", 12, 34, HUMAN, big=True)
        self._text(f"t={world.time:.1f}s", WIN_W - 150, 12, GREY)
        pg.display.flip()
        self.clock.tick(60)

    # ---- minions: small team-colored squares with a tiny hp bar ----
    def _draw_minions(self, pg, world) -> None:
        mm = getattr(world, "minions", None)
        if mm is None:
            return
        for m in mm.minions:
            if not m.alive:
                continue
            mx, my = self.to_screen(m.x, m.y)
            col = (70, 130, 200) if m.team == "ALLY" else (200, 80, 80)
            # siege minions a touch bigger/brighter
            size = 5 if m.kind == "siege" else 3
            pg.draw.rect(self.screen, col, (mx - size, my - size,
                                            size * 2, size * 2))
            # tiny hp bar when damaged (so last-hit windows are visible)
            if m.hp_frac < 1.0:
                w = 10
                pg.draw.rect(self.screen, (40, 40, 40),
                             (mx - w // 2, my - size - 4, w, 2))
                pg.draw.rect(self.screen, (90, 210, 120),
                             (mx - w // 2, my - size - 4, int(w * m.hp_frac), 2))

    # ---- visible attacks/casts: draw a line from src to dst, colored by kind ----
    def _draw_effects(self, pg, world) -> None:
        for fx in getattr(world, "fx", []):
            src = world.by_name.get(fx["src"])
            if not src:
                continue
            dst_name = fx["dst"]
            # target may be a champion OR a minion ("minion:<uid>")
            if isinstance(dst_name, str) and dst_name.startswith("minion:"):
                uid = int(dst_name.split(":", 1)[1])
                mm = getattr(world, "minions", None)
                dst = next((m for m in mm.minions if m.uid == uid), None) if mm else None
            else:
                dst = world.by_name.get(dst_name)
            if not dst:
                continue
            a = self._draw_pos.get(src.name) or self.to_screen(src.x, src.y)
            b = self.to_screen(dst.x, dst.y)
            if fx["kind"] == "auto":
                pg.draw.line(self.screen, (230, 230, 180), a, b, 2)
            elif fx["kind"] == "heal":
                pg.draw.line(self.screen, (120, 240, 160), a, b, 3)
                pg.draw.circle(self.screen, (120, 240, 160), b, 16, 2)
            else:  # ability cast
                col = (240, 220, 90) if fx["cc"] else (200, 120, 240)
                pg.draw.line(self.screen, col, a, b, 3)
                pg.draw.circle(self.screen, col, b, 14, 2)
                if fx["slot"]:
                    self._text(fx["slot"], b[0] - 4, b[1] - 24, col)

    # ---- right-side panel: every champion's current AI decision ----
    def _draw_ai_panel(self, pg, world) -> None:
        panel_w = 230
        x0 = WIN_W - panel_w
        s = pg.Surface((panel_w, WIN_H), pg.SRCALPHA)
        s.fill((10, 12, 18, 200))
        self.screen.blit(s, (x0, 0))
        y = 40
        self._text("AI DECISIONS", x0 + 12, 14, WHITE, big=True)
        for name, info in self.ai_info.items():
            ch = world.by_name.get(name)
            if not ch:
                continue
            team_col = ALLY if ch.team == "ALLY" else ENEMY
            status = "" if ch.alive else f"  dead {ch.respawn_timer:.0f}s"
            self._text(f"{name}{status}", x0 + 12, y, team_col)
            self._text(f"\u2192 {info.get('priority','')}", x0 + 20, y + 15,
                       WHITE)
            # top considered options with scores (the "why")
            yy = y + 30
            for cap, sc in info.get("considered", [])[:3]:
                self._text(f"   {cap} {sc}", x0 + 20, yy, GREY)
                yy += 13
            y = yy + 8

    # ---- bottom strip: last few combat events ----
    def _draw_combat_feed(self, pg, world) -> None:
        feed_h = 90
        s = pg.Surface((WIN_W - 240, feed_h), pg.SRCALPHA)
        s.fill((10, 12, 18, 190))
        self.screen.blit(s, (0, WIN_H - feed_h))
        self._text("COMBAT", 10, WIN_H - feed_h + 4, WHITE)
        recent = [l for l in world.log
                  if any(k in l for k in ("hits", "autos", "stuns", "died",
                                          "respawned", "heals"))][-5:]
        for i, line in enumerate(recent):
            self._text(line, 10, WIN_H - feed_h + 20 + i * 14, (210, 210, 220))

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
