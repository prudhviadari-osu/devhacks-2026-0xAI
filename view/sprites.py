"""
Sprite + spritesheet loading for the animated renderer.

Kenney packs ship a packed PNG (a grid of equal-size tiles). This slices that
grid into individual frames you can index. Works whether a "character" is one
frame (just move it) or several (animate a walk cycle).

Graceful by design: if an asset file is missing, loaders return None and the
renderer falls back to drawing shapes — so the game runs while you're still
collecting assets.

Config: edit ASSET_CONFIG (or drop a sprites.json) to say which tile indices in
the sheet are which champion / terrain. Defaults assume a Kenney-style packed
sheet; adjust the indices to match the pack you downloaded.
"""
from __future__ import annotations

import json
import os

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")

# Default mapping. Override by placing assets/sprites.json with the same shape.
# `tile` = index into the packed sheet (row-major). `frames` = list of indices
# for a walk animation (optional; falls back to [tile] if absent).
DEFAULT_CONFIG = {
    "sheet": "tilemap_packed.png",   # Kenney packed spritesheet filename
    "tile_size": 16,                 # px per tile in the sheet (Kenney often 16)
    "scale": 3,                      # draw scale (16*3 = 48px characters)
    "champions": {
        # champion_name: {"frames": [idx, ...]}  (indices into the sheet grid)
        "Sona":  {"frames": [84]},
        "Lulu":  {"frames": [85]},
        "Ryze":  {"frames": [86]},
        "Jax":   {"frames": [87]},
        "Zac":   {"frames": [88]},
        "_default": {"frames": [84]},
    },
}


def load_config() -> dict:
    path = os.path.join(ASSETS_DIR, "sprites.json")
    if os.path.exists(path):
        with open(path) as f:
            user = json.load(f)
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(user)
        return cfg
    return DEFAULT_CONFIG


class SpriteSheet:
    """Slices a packed PNG into a list of per-tile surfaces."""

    def __init__(self, pygame, path: str, tile_size: int, scale: int):
        self.pygame = pygame
        self.tiles: list = []
        self.scale = scale
        if not os.path.exists(path):
            return  # missing -> empty; renderer falls back to shapes
        sheet = pygame.image.load(path).convert_alpha()
        sw, sh = sheet.get_size()
        cols, rows = sw // tile_size, sh // tile_size
        for r in range(rows):
            for c in range(cols):
                rect = pygame.Rect(c * tile_size, r * tile_size,
                                   tile_size, tile_size)
                tile = sheet.subsurface(rect).copy()
                if scale != 1:
                    tile = pygame.transform.scale(
                        tile, (tile_size * scale, tile_size * scale))
                self.tiles.append(tile)

    def ok(self) -> bool:
        return len(self.tiles) > 0

    def frame(self, index: int):
        if not self.tiles:
            return None
        return self.tiles[index % len(self.tiles)]


class ChampionSprite:
    """Holds a champion's animation frames and advances the walk cycle."""

    def __init__(self, sheet: SpriteSheet, frame_indices: list[int],
                 fps: float = 6.0):
        self.frames = [sheet.frame(i) for i in frame_indices]
        self.frames = [f for f in self.frames if f is not None]
        self.fps = fps
        self.t = 0.0

    def ok(self) -> bool:
        return len(self.frames) > 0

    def current(self, moving: bool, dt: float):
        if not self.frames:
            return None
        if moving and len(self.frames) > 1:
            self.t += dt * self.fps
        else:
            self.t = 0.0  # standing -> first frame
        return self.frames[int(self.t) % len(self.frames)]


def build_champion_sprites(pygame) -> tuple[dict, dict]:
    """Returns (sprites_by_name, config). sprites empty if assets missing."""
    cfg = load_config()
    sheet_path = os.path.join(ASSETS_DIR, cfg["sheet"])
    sheet = SpriteSheet(pygame, sheet_path, cfg["tile_size"], cfg["scale"])
    sprites: dict[str, ChampionSprite] = {}
    if sheet.ok():
        for name, spec in cfg["champions"].items():
            sprites[name] = ChampionSprite(sheet, spec.get("frames", [0]))
    return sprites, cfg
