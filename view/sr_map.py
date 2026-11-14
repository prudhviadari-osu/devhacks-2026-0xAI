"""
Summoner's Rift-style map background.

Draws a readable top-down Rift behind the champions: jungle base, three lanes
(top / mid / bottom), the diagonal river, both team bases, and lane borders.
Pure geometry in normalized 0..1 map space, scaled to the window — no art
assets. The point is orientation and "this reads as League," not pixel fidelity.

Coordinates follow the world's convention: (0,0) = bottom-left (blue base side),
(1,1) = top-right (red base side), y-up. The renderer flips y for the screen.
"""
from __future__ import annotations

# palette tuned to look like the Rift without being garish
JUNGLE = (28, 44, 34)          # base ground (dark green)
JUNGLE_HI = (36, 54, 42)
LANE = (58, 62, 48)            # dirt lanes
LANE_EDGE = (78, 84, 66)
RIVER = (40, 70, 96)           # blue river
BLUE_BASE = (40, 70, 120)
RED_BASE = (120, 50, 55)
NEXUS_BLUE = (90, 150, 230)
NEXUS_RED = (235, 110, 110)
GRID = (255, 255, 255)
WALL = (18, 28, 22)

LANE_W = 0.11                  # lane width in normalized units


def draw_map(pg, screen, win_w, win_h):
    """Render the full map background. Call before drawing champions."""
    def sx(x):   # normalized x -> screen x
        return int(x * win_w)

    def sy(y):   # normalized y -> screen y (flip so up = north)
        return int(win_h - y * win_h)

    def rect(x0, y0, x1, y1, color):
        left, top = sx(min(x0, x1)), sy(max(y0, y1))
        w = abs(sx(x1) - sx(x0))
        h = abs(sy(y1) - sy(y0))
        pg.draw.rect(screen, color, (left, top, w, h))

    def line(x0, y0, x1, y1, color, width):
        pg.draw.line(screen, color, (sx(x0), sy(y0)), (sx(x1), sy(y1)), width)

    def poly(points, color):
        pg.draw.polygon(screen, color, [(sx(x), sy(y)) for x, y in points])

    # 1) jungle base fills the whole map
    screen.fill(JUNGLE)
    # subtle jungle quadrant highlights (top-left and bottom-right jungles)
    poly([(0, 0.5), (0.5, 0), (0.6, 0.1), (0.1, 0.6)], JUNGLE_HI)
    poly([(0.4, 1.0), (1.0, 0.4), (0.9, 0.3), (0.3, 0.9)], JUNGLE_HI)

    # 2) the three lanes (bottom-left base to top-right base)
    #    BOTTOM lane: along the bottom then up the right
    rect(0.04, 0.04, 0.96, 0.04 + LANE_W, LANE)          # bottom horizontal
    rect(0.96 - LANE_W, 0.04, 0.96, 0.96, LANE)          # right vertical
    #    TOP lane: up the left then along the top
    rect(0.04, 0.04, 0.04 + LANE_W, 0.96, LANE)          # left vertical
    rect(0.04, 0.96 - LANE_W, 0.96, 0.96, LANE)          # top horizontal
    #    MID lane: diagonal corridor
    mid_pts = [(0.10, 0.04), (0.04, 0.10), (0.90, 0.96),
               (0.96, 0.90)]
    poly(mid_pts, LANE)

    # 3) the river: a diagonal band perpendicular to mid (top-left to bot-right)
    river_pts = [(0.0, 0.42), (0.42, 0.0), (0.58, 0.0), (0.0, 0.58)]
    poly(river_pts, RIVER)
    river_pts2 = [(1.0, 0.58), (0.58, 1.0), (0.42, 1.0), (1.0, 0.42)]
    poly(river_pts2, RIVER)

    # 4) bases in the two corners
    poly([(0.0, 0.0), (0.22, 0.0), (0.0, 0.22)], BLUE_BASE)   # blue (bottom-left)
    poly([(1.0, 1.0), (0.78, 1.0), (1.0, 0.78)], RED_BASE)    # red (top-right)
    #    nexuses
    pg.draw.circle(screen, NEXUS_BLUE, (sx(0.06), sy(0.06)), 9)
    pg.draw.circle(screen, NEXUS_RED, (sx(0.94), sy(0.94)), 9)

    # 5) lane edge lines for definition
    for seg in [((0.04, 0.04 + LANE_W), (0.96, 0.04 + LANE_W)),  # bottom top-edge
                ((0.04 + LANE_W, 0.04), (0.04 + LANE_W, 0.96)),  # left right-edge
                ((0.04, 0.96 - LANE_W), (0.96, 0.96 - LANE_W)),  # top bottom-edge
                ((0.96 - LANE_W, 0.04), (0.96 - LANE_W, 0.96))]: # right left-edge
        (ax, ay), (bx, by) = seg
        line(ax, ay, bx, by, LANE_EDGE, 1)

    return sx, sy  # handy if caller wants the same mapping
