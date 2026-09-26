"""Gemeinsames Interface des Audio-Layers.

Jeder Format-Reader liefert ein ``AudioInfo``. Der Scanner setzt daraus die
``Release``-Struktur zusammen. Formatspezifische Eigenheiten - etwa dass rohe
EC-3-Streams ueberhaupt keine Tags tragen koennen - werden hier sichtbar
gemacht statt versteckt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


class AudioError(Exception):
    """Datei konnte nicht gelesen oder nicht erkannt werden."""


@dataclass
class AudioInfo:
    path: Path
    codec: str = ""                      # MP3 | FLAC | EAC3
    size_bytes: int = 0

    # --- technische Werte --------------------------------------------------
    duration: float = 0.0                # Sekunden
    bitrate: Optional[int] = None        # kbps
    samplerate: Optional[int] = None     # Hz
    channels: Optional[int] = None
    channel_mode: str = ""               # "Joint-Stereo", "3/2 (5.1)" ...
    bits_per_sample: Optional[int] = None
    vbr: bool = False
    encoder: str = ""
    compression_ratio: Optional[float] = None   # nur FLAC

    # --- Tags --------------------------------------------------------------
    artist: str = ""
    album_artist: str = ""
    title: str = ""
    album: str = ""
    genre: str = ""
    comment: str = ""
    year: Optional[int] = None
    track_no: Optional[int] = None
    total_tracks: Optional[int] = None
    disc_no: Optional[int] = None
    total_discs: Optional[int] = None

    # --- Objektbasiertes Audio --------------------------------------------
    #: True/False wenn sicher bestimmbar, None wenn der Container es nicht sagt
    atmos: Optional[bool] = None
    object_count: Optional[int] = None

    #: True, wenn das Format gar keine Tags tragen kann (roher EC-3-Stream)
    tagless: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def has_tags(self) -> bool:
        return bool(self.artist or self.title or self.album)


#: Endung -> Reader. Wird von den Format-Modulen befuellt.
READERS: dict[str, Callable[[Path], AudioInfo]] = {}

AUDIO_EXTENSIONS: tuple[str, ...] = (
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".mpc", ".mp+",
    ".ec3", ".eac3", ".m4a", ".mp4", ".m4b",
)


def register(*extensions: str):
    def deco(fn: Callable[[Path], AudioInfo]):
        for ext in extensions:
            READERS[ext.lower()] = fn
        return fn
    return deco


def read_file(path: str | Path) -> AudioInfo:
    p = Path(path)
    if not p.is_file():
        raise AudioError(f"keine Datei: {p}")
    reader = READERS.get(p.suffix.lower())
    if reader is None:
        raise AudioError(f"nicht unterstuetzte Endung: {p.suffix}")
    return reader(p)


# Channel-Mode-Bezeichnungen des AC-3/E-AC-3-acmod-Feldes.
ACMOD_NAMES = {
    0: ("1+1", 2),
    1: ("1/0", 1),
    2: ("2/0", 2),
    3: ("3/0", 3),
    4: ("2/1", 3),
    5: ("3/1", 4),
    6: ("2/2", 4),
    7: ("3/2", 5),
}


def _as_int(value: str) -> Optional[int]:
    head = value.partition("/")[0].strip()
    return int(head) if head.isdigit() else None


def _as_total(value: str) -> Optional[int]:
    tail = value.partition("/")[2].strip()
    return int(tail) if tail.isdigit() else None


def apply_vorbis_tags(tags, info: AudioInfo) -> None:
    """Vorbis-Comments auf AudioInfo abbilden.

    Gemeinsam genutzt von FLAC, Ogg Vorbis und Opus - alle drei tragen
    dieselbe Kommentarstruktur.
    """
    def first(key: str) -> str:
        values = tags.get(key) if tags else None
        return str(values[0]).strip() if values else ""

    info.title = first("title")
    info.artist = first("artist")
    info.album_artist = first("albumartist")
    info.album = first("album")
    info.genre = first("genre")
    info.comment = first("comment") or first("description")
    info.encoder = first("encoder") or first("encoded_by")

    date = first("date") or first("year")
    if date[:4].isdigit():
        info.year = int(date[:4])

    info.track_no = _as_int(first("tracknumber"))
    info.total_tracks = (_as_int(first("tracktotal") or first("totaltracks"))
                         or _as_total(first("tracknumber")))
    info.disc_no = _as_int(first("discnumber"))
    info.total_discs = (_as_int(first("disctotal") or first("totaldiscs"))
                        or _as_total(first("discnumber")))


def apply_ape_tags(tags, info: AudioInfo) -> None:
    """APEv2-Tags auf AudioInfo abbilden (Musepack, WavPack)."""
    def first(key: str) -> str:
        if not tags:
            return ""
        for candidate in (key, key.lower(), key.upper(), key.title()):
            if candidate in tags:
                return str(tags[candidate]).strip()
        return ""

    info.title = first("Title")
    info.artist = first("Artist")
    info.album_artist = first("Album Artist")
    info.album = first("Album")
    info.genre = first("Genre")
    info.comment = first("Comment")
    info.encoder = first("Encoder")

    date = first("Year") or first("Date")
    if date[:4].isdigit():
        info.year = int(date[:4])

    info.track_no = _as_int(first("Track"))
    info.total_tracks = _as_int(first("Tracktotal")) or _as_total(first("Track"))
    info.disc_no = _as_int(first("Disc"))
    info.total_discs = _as_int(first("Disctotal")) or _as_total(first("Disc"))
