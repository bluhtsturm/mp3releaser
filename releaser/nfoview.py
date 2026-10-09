"""Zeichnet eine .nfo im Raster - wie ein NFO-Betrachter, nicht wie ein Editor.

Eine .nfo ist ein Bild aus Zeichen: 80 Spalten, jede Zeile gleich hoch, und
die Block- und Rahmenzeichen der Codepage 437 (``█ ▄ ▀ ▌ ▐ ░ ▒ ▓``,
``═ ║ ╔ ╗ …``) stoßen ohne Fuge aneinander. Ein Textfeld mit einer
Systemschrift kann das nicht garantieren:

* Fehlen einer Schrift die Blockzeichen, nimmt die Textdarstellung sie aus
  einer Ersatzschrift - mit anderer Breite. Jede Zeile mit solchen Zeichen
  verrutscht dann gegenüber den anderen; die Grafik sieht eingerückt aus.
* Der Zeilenabstand einer Textschrift ist größer als ihre Zeichen. Zwischen
  übereinanderliegenden Blöcken bleibt eine helle Fuge, senkrechte Linien
  werden gestrichelt.

Deshalb hier die Geometrie für ein festes Raster: Block- und Rahmenzeichen
werden als Rechtecke beschrieben, die ihre Zelle exakt bis zum Rand füllen.
Desktop (cairo) und Weboberfläche (canvas) zeichnen danach dieselben
Rechtecke; nur gewöhnliche Schriftzeichen kommen noch aus der Schrift, jedes
an seinem Rasterplatz.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

#: (x, y, breite, höhe, deckkraft) in Pixeln innerhalb einer Zelle
Rect = tuple[int, int, int, int, float]

#: Zellgröße der Weboberfläche in CSS-Pixeln - das Verhältnis 1:2 der
#: VGA-Textschrift, in der .nfo-Dateien gezeichnet werden
WEB_CELL = (8, 16)

#: Schattierungen - als Deckkraft statt als Punktmuster, das bei kleinen
#: Zellen flimmert
SHADES = {"░": 0.25, "▒": 0.5, "▓": 0.75}

#: Rahmenzeichen der Codepage 437 als Gewichte der vier Arme
#: (oben, rechts, unten, links): 0 = keiner, 1 = einfach, 2 = doppelt
BOX: dict[str, tuple[int, int, int, int]] = {
    "─": (0, 1, 0, 1), "│": (1, 0, 1, 0),
    "┌": (0, 1, 1, 0), "┐": (0, 0, 1, 1), "└": (1, 1, 0, 0), "┘": (1, 0, 0, 1),
    "├": (1, 1, 1, 0), "┤": (1, 0, 1, 1), "┬": (0, 1, 1, 1), "┴": (1, 1, 0, 1),
    "┼": (1, 1, 1, 1),
    "═": (0, 2, 0, 2), "║": (2, 0, 2, 0),
    "╔": (0, 2, 2, 0), "╗": (0, 0, 2, 2), "╚": (2, 2, 0, 0), "╝": (2, 0, 0, 2),
    "╠": (2, 2, 2, 0), "╣": (2, 0, 2, 2), "╦": (0, 2, 2, 2), "╩": (2, 2, 0, 2),
    "╬": (2, 2, 2, 2),
    "╒": (0, 2, 1, 0), "╓": (0, 1, 2, 0), "╕": (0, 0, 1, 2), "╖": (0, 0, 2, 1),
    "╘": (1, 2, 0, 0), "╙": (2, 1, 0, 0), "╛": (1, 0, 0, 2), "╜": (2, 0, 0, 1),
    "╞": (1, 2, 1, 0), "╟": (2, 1, 2, 0), "╡": (1, 0, 1, 2), "╢": (2, 0, 2, 1),
    "╤": (0, 2, 1, 2), "╥": (0, 1, 2, 1), "╧": (1, 2, 0, 2), "╨": (2, 1, 0, 1),
    "╪": (1, 2, 1, 2), "╫": (2, 1, 2, 1),
}


def is_drawn(char: str) -> bool:
    """Ob das Zeichen als Fläche gezeichnet wird statt aus der Schrift."""
    return len(char) == 1 and (char in BOX or 0x2580 <= ord(char) <= 0x259F)


@lru_cache(maxsize=4096)
def cell_rects(char: str, width: int, height: int) -> Optional[tuple[Rect, ...]]:
    """Die Rechtecke eines Block- oder Rahmenzeichens in einer Zelle.

    ``None`` für Zeichen, die aus der Schrift kommen. Alle Koordinaten sind
    ganze Pixel: Halbe Blöcke teilen die Zelle ohne Lücke und ohne
    Überlappung, Linien laufen bis an den Zellrand und schließen so an die
    Nachbarzelle an.
    """
    if char in SHADES:
        return ((0, 0, width, height, SHADES[char]),)
    if 0x2580 <= ord(char) <= 0x259F:
        return _block(char, width, height)
    if char in BOX:
        return _box(BOX[char], width, height)
    return None


def _block(char: str, w: int, h: int) -> tuple[Rect, ...]:
    code = ord(char)
    half_w, half_h = w // 2, h // 2

    def rows(top: int, bottom: int) -> Rect:
        return (0, top, w, bottom - top, 1.0)

    def cols(left: int, right: int) -> Rect:
        return (left, 0, right - left, h, 1.0)

    if code == 0x2580:                                   # ▀ obere Hälfte
        return (rows(0, half_h),)
    # Achtel mit derselben Abrundung wie die Hälften: ▄ beginnt genau dort,
    # wo ▀ endet - auch bei ungerader Zellhöhe ohne Fuge dazwischen
    if 0x2581 <= code <= 0x2588:                         # ▁ … █ von unten
        eighths = code - 0x2580
        return (rows(min(h - 1, h * (8 - eighths) // 8), h),)
    if 0x2589 <= code <= 0x258F:                         # ▉ … ▏ von links
        eighths = 0x2590 - code
        return (cols(0, max(1, w * eighths // 8)),)
    if code == 0x2590:                                   # ▐ rechte Hälfte
        return (cols(half_w, w),)
    if code == 0x2594:                                   # ▔ oberes Achtel
        return (rows(0, max(1, round(h / 8))),)
    if code == 0x2595:                                   # ▕ rechtes Achtel
        return (cols(w - max(1, round(w / 8)), w),)

    # Viertel ▖ ▗ ▘ ▙ ▚ ▛ ▜ ▝ ▞ ▟ - als Menge aus oben links, oben rechts,
    # unten links, unten rechts
    quadrants = {
        0x2596: "ul", 0x2597: "ur", 0x2598: "ol", 0x2599: "ol ul ur",
        0x259A: "ol ur", 0x259B: "ol or ul", 0x259C: "ol or ur",
        0x259D: "or", 0x259E: "or ul", 0x259F: "or ul ur",
    }[code].split()
    boxes = {
        "ol": (0, 0, half_w, half_h), "or": (half_w, 0, w - half_w, half_h),
        "ul": (0, half_h, half_w, h - half_h),
        "ur": (half_w, half_h, w - half_w, h - half_h),
    }
    return tuple((*boxes[name], 1.0) for name in quadrants)


def line_metrics(w: int, h: int) -> tuple[int, int]:
    """Linienstärke und Abstand der Doppellinie von der Mitte."""
    thickness = max(1, round(w / 8))
    gap = max(thickness + 1, round(w / 4))
    return thickness, gap


def _box(arms: tuple[int, int, int, int], w: int, h: int) -> tuple[Rect, ...]:
    """Linien eines Rahmenzeichens.

    Jeder Arm läuft vom Zellrand zur Mitte. Wo er dort endet, hängt von den
    querenden Armen ab: Eine Doppellinie biegt an der Ecke außen weiter und
    hält innen an der querenden Doppellinie an (``╔``, ``╬``); eine
    einfache Linie stößt an die nächste Doppellinie (``╟``) oder läuft
    durch, wenn auf der anderen Seite ihr Gegenstück weitergeht (``╫``).
    """
    up, right, down, left = arms
    t, g = line_metrics(w, h)
    cx, cy = w // 2, h // 2
    rects: list[Rect] = []

    def hline(y: int, x0: int, x1: int) -> None:
        lo, hi = min(x0, x1), max(x0, x1)
        rects.append((lo, y - t // 2, hi - lo, t, 1.0))

    def vline(x: int, y0: int, y1: int) -> None:
        lo, hi = min(y0, y1), max(y0, y1)
        rects.append((x - t // 2, lo, t, hi - lo, 1.0))

    def reach(end: int, toward_far: bool) -> int:
        """Endkoordinate so, dass eine Linie an dieser Stelle mitgedeckt
        wird - in Laufrichtung des Arms."""
        return end - t // 2 if toward_far else end - t // 2 + t

    vertical_double = 2 in (up, down)
    horizontal_double = 2 in (left, right)

    # waagerechte Arme
    for weight, sign, opposite in ((right, 1, left), (left, -1, right)):
        if not weight:
            continue
        edge = w if sign > 0 else 0
        near, far = cx + sign * g, cx - sign * g
        if weight == 1:
            ys = ((cy, None),)
        else:
            ys = ((cy - g, "up"), (cy + g, "down"))
        for y, side in ys:
            if weight == 1:
                end = near if vertical_double and not opposite else cx
            else:
                other = "down" if side == "up" else "up"
                arm = {"up": up, "down": down}
                if arm[side] == 2:
                    end = near
                elif arm[other] == 2:
                    end = far
                else:
                    end = cx
            hline(y, edge, reach(end, toward_far=sign > 0))

    # senkrechte Arme
    for weight, sign, opposite in ((down, 1, up), (up, -1, down)):
        if not weight:
            continue
        edge = h if sign > 0 else 0
        near, far = cy + sign * g, cy - sign * g
        if weight == 1:
            xs = ((cx, None),)
        else:
            xs = ((cx - g, "left"), (cx + g, "right"))
        for x, side in xs:
            if weight == 1:
                end = near if horizontal_double and not opposite else cy
            else:
                other = "right" if side == "left" else "left"
                arm = {"left": left, "right": right}
                if arm[side] == 2:
                    end = near
                elif arm[other] == 2:
                    end = far
                else:
                    end = cy
            vline(x, edge, reach(end, toward_far=sign > 0))

    return tuple(rects)


def shapes_for(text: str, width: int, height: int) -> dict[str, list[list]]:
    """Die Rechtecke aller gezeichneten Zeichen eines Textes - für die
    Weboberfläche, die damit dieselben Flächen malt wie der Desktop."""
    return {char: [list(rect) for rect in cell_rects(char, width, height)]
            for char in sorted(set(text)) if is_drawn(char)}
