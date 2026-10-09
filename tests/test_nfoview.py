"""Tests für die Rasterdarstellung der .nfo (Block- und Rahmenzeichen)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.nfoview import (  # noqa: E402
    BOX,
    SHADES,
    cell_rects,
    is_drawn,
    line_metrics,
    shapes_for,
)

SIZES = [(8, 16), (8, 17), (9, 18), (7, 15), (10, 21)]


def covered(rects, width, height):
    """Die Pixel, die eine Zelle deckt (Deckkraft voll)."""
    pixels = set()
    for x, y, w, h, alpha in rects:
        assert 0 <= x and 0 <= y and x + w <= width and y + h <= height, \
            "Rechteck ragt aus der Zelle"
        if alpha == 1.0:
            pixels |= {(px, py) for px in range(x, x + w)
                       for py in range(y, y + h)}
    return pixels


# ------------------------------------------------------------------ Blöcke


@pytest.mark.parametrize("width, height", SIZES)
def test_full_block_fills_the_cell_to_the_edge(width, height):
    """Ohne Fuge zur Nachbarzelle - in einem Textfeld blieb sie."""
    pixels = covered(cell_rects("█", width, height), width, height)
    assert len(pixels) == width * height


@pytest.mark.parametrize("width, height", SIZES)
def test_half_blocks_split_the_cell_without_gap_or_overlap(width, height):
    upper = covered(cell_rects("▀", width, height), width, height)
    lower = covered(cell_rects("▄", width, height), width, height)
    assert not upper & lower
    assert len(upper | lower) == width * height
    left = covered(cell_rects("▌", width, height), width, height)
    right = covered(cell_rects("▐", width, height), width, height)
    assert not left & right
    assert len(left | right) == width * height


def test_quadrants_tile_the_cell():
    width, height = 9, 17
    singles = [covered(cell_rects(char, width, height), width, height)
               for char in "▘▝▖▗"]
    assert sum(map(len, singles)) == width * height
    assert len(set().union(*singles)) == width * height
    # ▙ = oben links + unten links + unten rechts
    assert covered(cell_rects("▙", width, height), width, height) == \
        singles[0] | singles[2] | singles[3]


@pytest.mark.parametrize("char, alpha", sorted(SHADES.items()))
def test_shades_cover_the_cell_with_their_density(char, alpha):
    (rect,) = cell_rects(char, 8, 16)
    assert rect == (0, 0, 8, 16, alpha)


def test_eighth_blocks_grow_from_the_bottom_and_the_left():
    heights = [cell_rects(chr(code), 8, 16)[0][3] for code in range(0x2581, 0x2589)]
    assert heights == [2, 4, 6, 8, 10, 12, 14, 16]
    widths = [cell_rects(chr(code), 8, 16)[0][2] for code in range(0x2589, 0x2590)]
    assert widths == [7, 6, 5, 4, 3, 2, 1]


# ---------------------------------------------------------- Rahmenzeichen


def _touches(pixels, edge, width, height):
    """Positionen, an denen die Zeichnung den Zellrand berührt."""
    if edge == "up":
        return sorted(x for x, y in pixels if y == 0)
    if edge == "down":
        return sorted(x for x, y in pixels if y == height - 1)
    if edge == "left":
        return sorted(y for x, y in pixels if x == 0)
    return sorted(y for x, y in pixels if x == width - 1)


@pytest.mark.parametrize("width, height", SIZES)
def test_box_lines_reach_the_edges_where_their_arms_point(width, height):
    """Damit Linien über die Zellgrenze hinweg anschließen: Jeder Arm
    berührt seinen Rand genau auf der Linienposition - einfach in der
    Mitte, doppelt im festen Abstand davon. Ohne Arm bleibt der Rand frei.
    Geprüft für alle 40 Rahmenzeichen der Codepage 437."""
    thickness, gap = line_metrics(width, height)
    cx, cy = width // 2, height // 2
    for char in sorted(BOX):
        pixels = covered(cell_rects(char, width, height), width, height)
        for edge, weight in zip(("up", "right", "down", "left"), BOX[char]):
            center = cx if edge in ("up", "down") else cy
            positions = {0: [], 1: [center],
                         2: [center - gap, center + gap]}[weight]
            expected = sorted(p - thickness // 2 + i for p in positions
                              for i in range(thickness))
            assert _touches(pixels, edge, width, height) == expected, \
                (char, edge)


def test_double_corner_bends_outside_and_stops_inside():
    """╔: die äußere Linie biegt um, die innere hält an der inneren an."""
    width, height = 8, 16
    _t, gap = line_metrics(width, height)
    cx, cy = width // 2, height // 2
    pixels = covered(cell_rects("╔", width, height), width, height)
    assert (cx - gap, cy - gap) in pixels                 # äußere Ecke
    assert (cx + gap, cy + gap) in pixels                 # innere Ecke
    assert (cx - gap, cy + gap - 1) in pixels             # außen durchgehend
    assert (cx + gap, cy) not in pixels                   # innen nicht


def test_crossings_keep_the_double_lines_open():
    """╬ hat in der Mitte ein freies Feld, ╫ eine durchgehende Querlinie."""
    width, height = 8, 16
    cx, cy = width // 2, height // 2
    assert (cx, cy) not in covered(cell_rects("╬", width, height), width, height)
    across = covered(cell_rects("╫", width, height), width, height)
    assert all((x, cy) in across for x in range(width))


def test_every_cp437_graphics_character_is_drawn_as_a_surface():
    """0xB0-0xDF sind in Codepage 437 Schattierungen, Rahmen und Blöcke -
    genau die Zeichen, die einer Schrift am ehesten fehlen."""
    graphics = bytes(range(0xB0, 0xE0)).decode("cp437")
    assert all(is_drawn(char) for char in graphics), \
        [char for char in graphics if not is_drawn(char)]
    assert is_drawn("■") is False                         # aus der Schrift
    assert cell_rects("A", 8, 16) is None
    assert not is_drawn("") and not is_drawn("ab")


def test_shapes_for_lists_only_the_drawn_characters_of_a_text():
    shapes = shapes_for("║ Titel ▓\n╚═╝", 8, 16)
    assert set(shapes) == {"║", "▓", "╚", "═", "╝"}
    assert shapes["▓"] == [[0, 0, 8, 16, 0.75]]
