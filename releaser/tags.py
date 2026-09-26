"""Tag-Registry.

Jeder SKL-Tag ist hier genau einmal definiert: Name, Geltungsbereich, Default-
Ausrichtung und die Funktion, die den Wert liefert. Der Renderer kennt
ausschliesslich diese Tabelle - neue Tags brauchen keine Aenderung am Parser.

Quelle der Tagnamen: mp3r_tags.nfo und skl_making_guide.nfo des Originals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from .model import Disc, Release, Track
from .text import CharCase, format_size_mb, format_time


class Align(Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class Scope(Enum):
    RELEASE = "release"      # einmal pro NFO
    TRACK = "track"          # wiederholt sich pro Track
    NOTES = "notes"          # wiederholt sich pro Notizzeile
    GNEWS = "gnews"          # wiederholt sich pro News-Zeile
    MARKER = "marker"        # reiner Positionsmarker, rendert leer


@dataclass
class Settings:
    """Optionen, die das Original ueber die Settings-Tabs anbot."""

    nfo_charcase: CharCase = CharCase.UNCHANGED
    ascii_conversion: bool = False
    strip_leading_zeros_time: bool = False
    decimal_comma: bool = False
    space_before_kbps: bool = False
    wrap_tracklist: bool = True
    vbr_string: str = "VBR"
    track_no_digits: int = 2
    #: Trennstring zwischen Artist und Titel in der Trackliste
    track_separator: str = " - "
    #: Tags, deren Schreibweise die Charcase-Regel nicht anfassen darf
    charcase_exempt: frozenset[str] = frozenset({"Url", "CntUrl", "2ndUrl", "Cnt2ndUrl"})


@dataclass
class Context:
    """Auswertungskontext einer einzelnen Zeile."""

    release: Release
    settings: Settings = field(default_factory=Settings)
    track: Optional[Track] = None
    disc: Optional[Disc] = None
    notes_line: str = ""
    gnews_line: str = ""
    #: erlaubt es, den #Trk-Slot mit beliebigem Text zu belegen - gebraucht
    #: fuer umgebrochene Titel und fuer CD-Kopfzeilen bei Multi-CD-Releases
    track_text: Optional[str] = None


@dataclass(frozen=True)
class TagDef:
    name: str
    scope: Scope
    align: Align
    resolve: Callable[[Context], str]
    description: str = ""


# ------------------------------------------------------------------ Hilfsfunktionen


def _time(ctx: Context, seconds: float) -> str:
    return format_time(seconds, ctx.settings.strip_leading_zeros_time)


def _bitrate(ctx: Context) -> str:
    """``320kbps`` oder - mit ``space_before_kbps`` - ``320 kbps``.

    Das Leerzeichen gehoert zwischen Zahl und Einheit. Frueher stand es vor
    dem ganzen Wert (`` 320kbps``) und verschob das Feld um eine Spalte.
    """
    r = ctx.release
    if r.vbr:
        return r.vbr_string or ctx.settings.vbr_string
    if r.bitrate:
        unit = " kbps" if ctx.settings.space_before_kbps else "kbps"
        return f"{r.bitrate}{unit}"
    return ""


def _per_disc(ctx: Context, fn: Callable[[Disc], str]) -> str:
    """Baut die 'CD1: x CD2: y'-Form fuer Multi-CD-Releases."""
    r = ctx.release
    if not r.multi_disc:
        return fn(r.discs[0]) if r.discs else ""
    return "  ".join(f"CD{d.number}: {fn(d)}" for d in r.discs)


def _album_with_addition(ctx: Context) -> str:
    r = ctx.release
    return f"{r.album} {r.album_addition}".strip() if r.album_addition else r.album


def compose_track_title(track: Optional[Track], settings: Settings) -> str:
    """Anzeigetitel eines Tracks - bei Samplern mit vorangestelltem Artist.

    Das Modell haelt Titel und Artist getrennt; zusammengesetzt wird erst zur
    Anzeige. So landet beim Tag-Schreiben der Artist im Artist-Feld und nicht
    im Titelfeld.

    Der Renderer braucht diese Funktion getrennt vom Tag-Resolver, weil er den
    Text vor dem Zeilenumbruch kennen muss.
    """
    if track is None:
        return ""
    if track.artist:
        return f"{track.artist}{settings.track_separator}{track.title}"
    return track.title


def _track_title(ctx: Context) -> str:
    if ctx.track_text is not None:
        return ctx.track_text
    return compose_track_title(ctx.track, ctx.settings)


# ------------------------------------------------------------------- Registry

_DEFS: list[TagDef] = [
    # --- Kopfdaten ---------------------------------------------------------
    TagDef("Release", Scope.RELEASE, Align.CENTER,
           lambda c: c.release.release_name, "Artist - Album, zentriert"),
    TagDef("Releasenc", Scope.RELEASE, Align.LEFT,
           lambda c: c.release.release_name, "Artist - Album, linksbuendig"),
    TagDef("RName", Scope.RELEASE, Align.LEFT,
           lambda c: c.release.full_name, "kompletter Releasename"),
    TagDef("RNameCnt", Scope.RELEASE, Align.CENTER,
           lambda c: c.release.full_name, "kompletter Releasename, zentriert"),
    TagDef("Fullrelease", Scope.RELEASE, Align.LEFT,
           lambda c: c.release.full_name, "kompletter Releasename"),
    TagDef("Artist", Scope.RELEASE, Align.LEFT, lambda c: c.release.artist),
    TagDef("Albwthadd", Scope.RELEASE, Align.LEFT, _album_with_addition),
    TagDef("Album", Scope.RELEASE, Align.LEFT, lambda c: c.release.album),

    # --- Beteiligte / Herkunft --------------------------------------------
    TagDef("Rip", Scope.RELEASE, Align.LEFT, lambda c: c.release.ripper),
    TagDef("Sup", Scope.RELEASE, Align.LEFT, lambda c: c.release.supplier),
    TagDef("Grab", Scope.RELEASE, Align.LEFT, lambda c: c.release.grabber),
    TagDef("Enc", Scope.RELEASE, Align.LEFT, lambda c: c.release.encoder),
    TagDef("Company", Scope.RELEASE, Align.LEFT, lambda c: c.release.company),
    TagDef("Catnr", Scope.RELEASE, Align.LEFT, lambda c: c.release.catalog_no),
    TagDef("Country", Scope.RELEASE, Align.LEFT, lambda c: c.release.country),
    TagDef("Language", Scope.RELEASE, Align.LEFT, lambda c: c.release.language),
    TagDef("Source", Scope.RELEASE, Align.LEFT, lambda c: c.release.source),
    TagDef("Format", Scope.RELEASE, Align.LEFT, lambda c: c.release.audio_format),
    TagDef("Typ", Scope.RELEASE, Align.LEFT, lambda c: c.release.release_type),
    TagDef("Subgenre", Scope.RELEASE, Align.LEFT, lambda c: c.release.subgenre),
    TagDef("Genre", Scope.RELEASE, Align.LEFT, lambda c: c.release.genre),
    TagDef("Style", Scope.RELEASE, Align.LEFT, lambda c: c.release.style),
    TagDef("RelWith", Scope.RELEASE, Align.LEFT, lambda c: c.release.released_with),
    TagDef("Rc", Scope.RELEASE, Align.LEFT, lambda c: c.release.release_counter),

    # --- Daten -------------------------------------------------------------
    TagDef("Rdate", Scope.RELEASE, Align.LEFT, lambda c: c.release.release_date),
    TagDef("Sdate", Scope.RELEASE, Align.LEFT, lambda c: c.release.store_date),
    TagDef("Ldate", Scope.RELEASE, Align.LEFT, lambda c: c.release.liveset_date),
    TagDef("Year", Scope.RELEASE, Align.LEFT,
           lambda c: str(c.release.year or "")),
    TagDef("Y", Scope.RELEASE, Align.LEFT, lambda c: str(c.release.year or "")),

    # --- URLs (von der Charcase-Regel ausgenommen) -------------------------
    TagDef("CntUrl", Scope.RELEASE, Align.CENTER, lambda c: c.release.url),
    TagDef("Cnt2ndUrl", Scope.RELEASE, Align.CENTER, lambda c: c.release.url2),
    TagDef("2ndUrl", Scope.RELEASE, Align.LEFT, lambda c: c.release.url2),
    TagDef("Url", Scope.RELEASE, Align.LEFT, lambda c: c.release.url),

    # --- Technik -----------------------------------------------------------
    TagDef("Br", Scope.RELEASE, Align.LEFT, _bitrate),
    TagDef("Bm", Scope.RELEASE, Align.LEFT, lambda c: "", "unbenutzt im Original"),
    TagDef("Bps", Scope.RELEASE, Align.LEFT,
           lambda c: str(c.release.bits_per_sample or "")),
    TagDef("10Hz", Scope.RELEASE, Align.LEFT,
           lambda c: str(c.release.samplerate or "")),
    TagDef("Hz", Scope.RELEASE, Align.LEFT,
           lambda c: f"{c.release.samplerate / 1000:g}" if c.release.samplerate else ""),
    TagDef("Mode", Scope.RELEASE, Align.LEFT, lambda c: c.release.channel_mode),
    TagDef("FlacC", Scope.RELEASE, Align.LEFT,
           lambda c: f"{c.release.flac_compression:.1%}"
           if c.release.flac_compression else ""),

    # --- Mengen und Laengen ------------------------------------------------
    TagDef("Tn", Scope.RELEASE, Align.LEFT, lambda c: str(c.release.total_tracks)),
    TagDef("Sn", Scope.RELEASE, Align.LEFT,
           lambda c: _per_disc(c, lambda d: str(len(d.tracks))),
           "Tracks pro CD"),
    TagDef("hhhCpti", Scope.RELEASE, Align.RIGHT,
           lambda c: _per_disc(c, lambda d: _time(c, d.seconds))),
    TagDef("hhLCpti", Scope.RELEASE, Align.LEFT,
           lambda c: _per_disc(c, lambda d: _time(c, d.seconds))),
    TagDef("Cpti", Scope.RELEASE, Align.LEFT,
           lambda c: _per_disc(c, lambda d: _time(c, d.seconds))),
    TagDef("TptCTT#", Scope.RELEASE, Align.RIGHT,
           lambda c: _time(c, c.release.seconds), "Gesamtlaenge aller CDs"),
    TagDef("hhhTpti", Scope.RELEASE, Align.RIGHT,
           lambda c: _time(c, c.release.seconds)),
    TagDef("hhLTpti", Scope.RELEASE, Align.LEFT,
           lambda c: _time(c, c.release.seconds)),
    TagDef("Tpti#", Scope.RELEASE, Align.RIGHT,
           lambda c: _time(c, c.release.seconds)),
    TagDef("Tpti", Scope.RELEASE, Align.LEFT,
           lambda c: _time(c, c.release.seconds)),
    TagDef("Size#", Scope.RELEASE, Align.RIGHT,
           lambda c: format_size_mb(c.release.size_bytes, c.settings.decimal_comma)),
    TagDef("Size", Scope.RELEASE, Align.LEFT,
           lambda c: format_size_mb(c.release.size_bytes, c.settings.decimal_comma)),

    # --- Trackliste --------------------------------------------------------
    TagDef("N", Scope.TRACK, Align.LEFT,
           lambda c: str(c.track.no).zfill(c.settings.track_no_digits)
           if c.track else ""),
    TagDef("Trk", Scope.TRACK, Align.LEFT, _track_title),
    TagDef("hhhPtit", Scope.TRACK, Align.RIGHT,
           lambda c: _time(c, c.track.seconds) if c.track else ""),
    TagDef("hhLPtit", Scope.TRACK, Align.LEFT,
           lambda c: _time(c, c.track.seconds) if c.track else ""),
    TagDef("Ptit", Scope.TRACK, Align.LEFT,
           lambda c: _time(c, c.track.seconds) if c.track else ""),

    # --- Freitextbloecke ---------------------------------------------------
    TagDef("Rnotes", Scope.NOTES, Align.LEFT, lambda c: c.notes_line),
    TagDef("Gnews", Scope.GNEWS, Align.LEFT, lambda c: c.gnews_line),
    TagDef("Notesmarkend", Scope.MARKER, Align.LEFT, lambda c: ""),
    TagDef("Notesmark", Scope.MARKER, Align.LEFT, lambda c: ""),
]

REGISTRY: dict[str, TagDef] = {d.name: d for d in _DEFS}

#: Tags, die im Template *ohne* fuehrendes '#' stehen und stattdessen mit '#'
#: enden. Das Original nutzt diese Schreibweise als Marker fuer rechtsbuendig.
SUFFIX_ONLY: frozenset[str] = frozenset({"Size#", "Tpti#"})


def literal_of(name: str) -> str:
    """Exakte Zeichenkette, die fuer diesen Tag im Template steht."""
    if name in SUFFIX_ONLY:
        return name
    return "#" + name


#: literal -> TagDef, sortiert nach Laenge absteigend. Die Sortierung ist
#: zwingend: ohne sie wuerde "#Releasenc" als "#Release" + "nc" gelesen,
#: "#Albwthadd" als "#Alb..." und "#10Hz" als Text + "#Hz".
LITERALS: dict[str, TagDef] = {literal_of(n): d for n, d in REGISTRY.items()}
LITERAL_ORDER: list[str] = sorted(LITERALS, key=len, reverse=True)

#: Tags, die eine Zeile pro Track wiederholen.
TRACK_TAGS: frozenset[str] = frozenset(
    n for n, d in REGISTRY.items() if d.scope is Scope.TRACK
)


def apply_charcase(name: str, value: str, settings: Settings) -> str:
    if name in settings.charcase_exempt:
        return value
    return settings.nfo_charcase.apply(value)
