"""SKL-Template-Engine.

Das Besondere am SKL-Format ist, dass es *spaltenbewusst* ist: Ein Tag belegt
nicht nur seine eigenen Zeichen, sondern auch die Leerzeichen daneben. Diese
Spanne ist das Feld. Werte werden auf Feldbreite gekuerzt und aufgefuellt,
damit nachfolgende ASCII-Rahmen in ihrer Spalte stehen bleiben.

Drei Ausrichtungen:

* ``LEFT``   - Feld = Tag + folgende Leerzeichen, Wert linksbuendig
* ``CENTER`` - wie LEFT, Wert zentriert
* ``RIGHT``  - Feld = *vorangehende* Leerzeichen + Tag, Wert rechtsbuendig
               (Schreibweise ``Size#`` statt ``#Size``)

Zusaetzlich replizieren sich Zeilen mit Track-, Notes- oder Gnews-Tags. Steht
in der Folgezeile derselbe Tag ohne die uebrigen Tags der Hauptzeile, dient sie
als Fortsetzungszeile fuer Umbrueche und CD-Trenner.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .model import Release
from .tags import (
    Align,
    Context,
    compose_track_title,
    LITERAL_ORDER,
    LITERALS,
    Scope,
    Settings,
    TagDef,
    apply_charcase,
)
from .text import read_template, to_ascii, wrap_value


# =============================================================== Zeilen-Parsing


@dataclass
class Field:
    """Eine Tag-Fundstelle samt der Spalten, die sie beanspruchen darf."""

    tag: TagDef
    lit_start: int
    lit_end: int
    start: int
    end: int

    @property
    def width(self) -> int:
        return self.end - self.start


@dataclass
class ParsedLine:
    raw: str
    fields: list[Field] = dc_field(default_factory=list)

    def tag_names(self) -> set[str]:
        return {f.tag.name for f in self.fields}

    def scopes(self) -> set[Scope]:
        return {f.tag.scope for f in self.fields}

    def field_for(self, name: str) -> Optional[Field]:
        for f in self.fields:
            if f.tag.name == name:
                return f
        return None

    def has_scope(self, scope: Scope) -> bool:
        return any(f.tag.scope is scope for f in self.fields)


def _find_literals(line: str) -> list[tuple[int, int, TagDef]]:
    """Longest-Match-Scan von links nach rechts."""
    found: list[tuple[int, int, TagDef]] = []
    i = 0
    n = len(line)
    while i < n:
        for lit in LITERAL_ORDER:
            if line.startswith(lit, i):
                found.append((i, i + len(lit), LITERALS[lit]))
                i += len(lit)
                break
        else:
            i += 1
    return found


def parse_line(line: str) -> ParsedLine:
    occurrences = _find_literals(line)
    if not occurrences:
        return ParsedLine(line)

    starts: list[int] = []
    ends: list[int] = []

    # Durchgang 1: rechtsbuendige Tags reklamieren ihre Leerzeichen nach links.
    for idx, (lit_start, lit_end, tag) in enumerate(occurrences):
        if tag.align is Align.RIGHT:
            floor = occurrences[idx - 1][1] if idx else 0
            j = lit_start
            while j > floor and line[j - 1] == " ":
                j -= 1
            starts.append(j)
        else:
            starts.append(lit_start)

    # Durchgang 2: links-/zentrierte Tags fuellen nach rechts auf, aber nur bis
    # zum Feldanfang des naechsten Tags.
    for idx, (lit_start, lit_end, tag) in enumerate(occurrences):
        if tag.align is Align.RIGHT:
            ends.append(lit_end)
            continue
        ceiling = starts[idx + 1] if idx + 1 < len(occurrences) else len(line)
        k = lit_end
        while k < ceiling and line[k] == " ":
            k += 1
        ends.append(k)

    fields = [
        Field(tag, lit_start, lit_end, starts[i], ends[i])
        for i, (lit_start, lit_end, tag) in enumerate(occurrences)
    ]
    return ParsedLine(line, fields)


def _place(buf: list[str], f: Field, value: str) -> None:
    w = f.width
    value = value[:w]
    if f.tag.align is Align.RIGHT:
        value = value.rjust(w)
    elif f.tag.align is Align.CENTER:
        value = value.center(w)
    else:
        value = value.ljust(w)
    buf[f.start:f.end] = list(value)


#: Steuerzeichen, die aus einem defekten Tag stammen koennen. Im NFO haetten
#: sie nichts verloren - sie zerstoeren die Spaltenausrichtung und ueberleben
#: manche Uebertragungswege nicht.
_CONTROL = {chr(c) for c in range(32)} | {chr(127)}


def strip_control(value: str) -> str:
    return "".join(c for c in value if c not in _CONTROL)


def render_line(pl: ParsedLine, ctx: Context) -> str:
    if not pl.fields:
        return pl.raw
    buf = list(pl.raw)
    # von rechts nach links, damit frueher gesetzte Indizes gueltig bleiben
    for f in sorted(pl.fields, key=lambda x: x.start, reverse=True):
        value = strip_control(f.tag.resolve(ctx) or "")
        value = apply_charcase(f.tag.name, value, ctx.settings)
        if ctx.settings.ascii_conversion:
            value = to_ascii(value)
        _place(buf, f, value)
    return "".join(buf)


# ======================================================================= Bloecke


class Block:
    def render(self, ctx: Context) -> list[str]:  # pragma: no cover - Interface
        raise NotImplementedError


@dataclass
class StaticBlock(Block):
    line: ParsedLine

    def render(self, ctx: Context) -> list[str]:
        return [render_line(self.line, ctx)]


@dataclass
class TrackBlock(Block):
    """Hauptzeile pro Track, optionale Fortsetzungszeile."""

    main: ParsedLine
    cont: Optional[ParsedLine] = None

    def _width(self, pl: ParsedLine) -> int:
        f = pl.field_for("Trk")
        return f.width if f else 0

    def render(self, ctx: Context) -> list[str]:
        out: list[str] = []
        release = ctx.release
        main_w = self._width(self.main)
        cont_w = self._width(self.cont) if self.cont else 0

        for disc in release.discs:
            if release.multi_disc and self.cont is not None:
                out.append(render_line(self.cont, _with(ctx, track_text=_disc_header(disc, release))))
                out.append(render_line(self.cont, _with(ctx, track_text="")))
            for track in disc.tracks:
                title = compose_track_title(track, ctx.settings)
                if (ctx.settings.wrap_tracklist and self.cont is not None
                        and main_w and cont_w > 0):
                    # Erste Zeile so breit wie das Hauptfeld, der Rest so
                    # breit wie das Fortsetzungsfeld - sonst wird dort
                    # abgeschnitten, was umbrochen werden sollte.
                    parts = wrap_value(title, cont_w, first_width=main_w)
                else:
                    parts = [title]
                out.append(render_line(self.main, _with(ctx, track=track, disc=disc,
                                                        track_text=parts[0])))
                for extra in parts[1:]:
                    if self.cont is None or cont_w <= 0:
                        break
                    out.append(render_line(self.cont, _with(ctx, track=track, disc=disc,
                                                            track_text=extra)))
        return out


@dataclass
class TextBlock(Block):
    """Gemeinsame Logik fuer #Rnotes und #Gnews."""

    main: ParsedLine
    cont: Optional[ParsedLine]
    scope: Scope

    def _lines(self, ctx: Context) -> list[str]:
        src = ctx.release.notes if self.scope is Scope.NOTES else ctx.release.group_news
        return list(src) or [""]

    def _width(self, pl: ParsedLine) -> int:
        name = "Rnotes" if self.scope is Scope.NOTES else "Gnews"
        f = pl.field_for(name)
        return f.width if f else 0

    def render(self, ctx: Context) -> list[str]:
        raw_lines = self._lines(ctx)
        main_w = self._width(self.main)
        cont_w = self._width(self.cont) if self.cont else main_w

        # Nur die allererste Ausgabezeile steht in der Hauptzeile - auch die
        # Umbruchreste der ersten Notiz landen schon in der Fortsetzungszeile
        # und muessen deshalb deren Breite haben.
        wrapped: list[str] = []
        for line in raw_lines:
            if self.cont is None:
                width, first = main_w, None
            else:
                width, first = cont_w, (main_w if not wrapped else None)
            wrapped.extend(wrap_value(line, width, first_width=first)
                           if width else [line])

        out: list[str] = []
        for i, line in enumerate(wrapped):
            ctx2 = _with(ctx, **{"notes_line" if self.scope is Scope.NOTES
                                 else "gnews_line": line})
            if i == 0 or self.cont is None:
                out.append(render_line(self.main, ctx2))
            else:
                out.append(render_line(self.cont, ctx2))
        return out


def _disc_header(disc, release: Release) -> str:
    label = f"CD{disc.number}"
    if disc.title:
        label += f" - {disc.title}"
    if disc.year and disc.year != release.year:
        label += f" ({disc.year})"
    return label


def _with(ctx: Context, **changes) -> Context:
    return Context(
        release=ctx.release,
        settings=ctx.settings,
        track=changes.get("track", ctx.track),
        disc=changes.get("disc", ctx.disc),
        notes_line=changes.get("notes_line", ctx.notes_line),
        gnews_line=changes.get("gnews_line", ctx.gnews_line),
        track_text=changes.get("track_text", ctx.track_text),
    )


# ====================================================================== Template


@dataclass
class Template:
    blocks: list[Block]
    lines: list[ParsedLine]

    # ------------------------------------------------------------- Konstruktion

    @classmethod
    def parse(cls, text: str) -> "Template":
        lines = [parse_line(l) for l in text.replace("\r\n", "\n").split("\n")]
        blocks: list[Block] = []
        i = 0
        while i < len(lines):
            pl = lines[i]
            if _is_track_main(pl):
                cont = lines[i + 1] if i + 1 < len(lines) else None
                if cont is not None and _is_track_cont(cont):
                    blocks.append(TrackBlock(pl, cont))
                    i += 2
                else:
                    blocks.append(TrackBlock(pl, None))
                    i += 1
                continue
            for scope, name in ((Scope.NOTES, "Rnotes"), (Scope.GNEWS, "Gnews")):
                if name in pl.tag_names():
                    cont = lines[i + 1] if i + 1 < len(lines) else None
                    if cont is not None and name in cont.tag_names():
                        blocks.append(TextBlock(pl, cont, scope))
                        i += 2
                    else:
                        blocks.append(TextBlock(pl, None, scope))
                        i += 1
                    break
            else:
                blocks.append(StaticBlock(pl))
                i += 1
        return cls(blocks, lines)

    @classmethod
    def from_file(cls, path: str | Path, codepage: str = "cp437") -> "Template":
        return cls.parse(read_template(path, codepage))

    # ------------------------------------------------------------------ Rendern

    def render(
        self,
        release: Release,
        settings: Optional[Settings] = None,
        trim_trailing: bool = True,
        dedent: bool = False,
    ) -> str:
        ctx = Context(release=release, settings=settings or Settings())
        out: list[str] = []
        for block in self.blocks:
            out.extend(block.render(ctx))
        if trim_trailing:
            out = [l.rstrip() for l in out]
        if dedent:
            out = _dedent(out)
        return "\n".join(out)

    # ------------------------------------------------- Introspektion fuer die GUI

    def track_layout(self) -> tuple[int, bool]:
        """(Breite des Trackfelds, ob eine Fortsetzungszeile existiert).

        Ohne Fortsetzungszeile wird ein zu langer Titel abgeschnitten statt
        umgebrochen - das laesst sich nur hier feststellen, nicht am Feld.
        """
        for block in self.blocks:
            if isinstance(block, TrackBlock):
                field = block.main.field_for("Trk")
                return (field.width if field else 0, block.cont is not None)
        return 0, False

    def tag_names(self) -> set[str]:
        return {f.tag.name for pl in self.lines for f in pl.fields}

    def field_widths(self) -> dict[str, int]:
        """Maximale Feldbreite je Tag - das Original dimensioniert damit die
        Eingabefelder und deaktiviert Felder ohne Entsprechung im Template."""
        widths: dict[str, int] = {}
        for pl in self.lines:
            for f in pl.fields:
                widths[f.tag.name] = max(widths.get(f.tag.name, 0), f.width)
        return widths

    def unused_tags(self, available: Iterable[str]) -> set[str]:
        return set(available) - self.tag_names()


def _is_track_main(pl: ParsedLine) -> bool:
    names = pl.tag_names()
    if not pl.has_scope(Scope.TRACK):
        return False
    return bool(names & {"N", "Ptit", "hhLPtit", "hhhPtit"}) or "Trk" in names


def _is_track_cont(pl: ParsedLine) -> bool:
    names = pl.tag_names()
    return "Trk" in names and not (names & {"N", "Ptit", "hhLPtit", "hhhPtit"})


def _dedent(lines: Sequence[str]) -> list[str]:
    indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip()]
    cut = min(indents) if indents else 0
    return [l[cut:] if l.strip() else l for l in lines]
