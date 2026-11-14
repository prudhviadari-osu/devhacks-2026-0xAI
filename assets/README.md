# Assets — drop your free sprite/map files here

The animated renderer (`view/animated.py`) looks for assets in this folder and
**degrades gracefully** if they're missing (falls back to shapes + circles), so
the game always runs.

## What to add (free, from kenney.nl — CC0, no login/attribution)

1. Download a top-down pack from https://kenney.nl/assets (filter: 2D).
   Good picks: **"Roguelike/RPG pack"** (has walk frames) or **"Tiny Dungeon"**.
2. Unzip it, find the packed spritesheet PNG (often `tilemap_packed.png` in a
   `Tilesheet/` folder).
3. Copy that PNG into this `assets/` folder as **`tilemap_packed.png`**
   (or edit the filename in `assets/sprites.json`).

## Point sprites at the right tiles

Each champion needs the tile index (or indices, for a walk animation) in the
packed sheet. Create `assets/sprites.json` to override defaults, e.g.:

```json
{
  "sheet": "tilemap_packed.png",
  "tile_size": 16,
  "scale": 3,
  "champions": {
    "Sona":  {"frames": [84, 85]},
    "Lulu":  {"frames": [96, 97]},
    "Ryze":  {"frames": [100]},
    "Jax":   {"frames": [101]},
    "Zac":   {"frames": [102]},
    "_default": {"frames": [84]}
  }
}
```
Count tiles left-to-right, top-to-bottom starting at 0. Two+ frames = animated
walk cycle; one frame = a static sprite that still moves smoothly.

## Optional: a textured Tiled map

Make a map in the free **Tiled** editor (https://www.mapeditor.org), export as
`assets/rift.tmx` (keep the tileset PNG alongside). The renderer draws it as the
background automatically. No map = the built-in shape Rift is used instead.
