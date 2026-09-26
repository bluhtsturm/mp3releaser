"""CUE-Sheets lesen.

Ein CUE beschreibt die Trackaufteilung einer Audiodatei, die als ein Stück
vorliegt - typisch bei Vinyl- oder DJ-Mix-Rips. Das Original verarbeitete sie
und meldete, wenn die Trackzahl im CUE nicht zur Tabelle passte.

Zeitangaben stehen als ``MM:SS:FF`` mit 75 Frames je Sekunde. Die Laufzeit
eines Tracks ergibt sich aus dem Abstand zum nächsten INDEX 01; der letzte
Track reicht bis zum Ende der Audiodatei, deren Länge das CUE nicht kennt.

**Folge für das Datenmodell:** alle Tracks eines CUE zeigen auf dieselbe
Datei. Umbenennen, SFV und M3U müssen das berücksichtigen, sonst wird die
Datei mehrfach angefasst oder mehrfach gelistet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

FRAMES_PER_SECOND = 75

_LINE = re.compile(r"^\s*(?P<command>[A-Z]+)\s*(?P<rest>.*)$")
_QUOTED = re.compile(r'"([^"]*)"')
_INDEX = re.compile(r"^(?P<number>\d+)\s+(?P<time>\d+:\d{2}:\d{2})")
_TRACK = re.compile(r"^(?P<number>\d+)\s+(?P<mode>\S+)")


class CueError(Exception):
    pass


def parse_time(value: str) -> float:
    """``MM:SS:FF`` in Sekunden. Minuten dürfen über 59 hinausgehen."""
    parts = value.split(":")
    if len(parts) != 3:
        raise CueError(f"ungültige Zeitangabe: {value!r}")
    try:
        minutes, seconds, frames = (int(p) for p in parts)
    except ValueError as exc:
        raise CueError(f"ungültige Zeitangabe: {value!r}") from exc
    if not 0 <= seconds < 60 or not 0 <= frames < FRAMES_PER_SECOND:
        raise CueError(f"Zeitangabe außerhalb des gültigen Bereichs: {value!r}")
    return minutes * 60 + seconds + frames / FRAMES_PER_SECOND


@dataclass
class CueTrack:
    number: int
    title: str = ""
    performer: str = ""
    isrc: str = ""
    start: Optional[float] = None       # INDEX 01
    pregap_start: Optional[float] = None  # INDEX 00
    duration: Optional[float] = None


@dataclass
class CueFile:
    name: str
    file_type: str = "WAVE"
    tracks: list[CueTrack] = field(default_factory=list)


@dataclass
class CueSheet:
    performer: str = ""
    title: str = ""
    date: str = ""
    genre: str = ""
    comment: str = ""
    catalog: str = ""
    files: list[CueFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def tracks(self) -> list[CueTrack]:
        return [t for f in self.files for t in f.tracks]


def _first_quoted(text: str) -> str:
    match = _QUOTED.search(text)
    if match:
        return match.group(1)
    return text.split()[0].strip('"') if text.strip() else ""


def parse_cue(text: str) -> CueSheet:
    sheet = CueSheet()
    current_file: Optional[CueFile] = None
    current_track: Optional[CueTrack] = None

    for raw in text.replace("\r\n", "\n").split("\n"):
        match = _LINE.match(raw)
        if not match:
            continue
        command = match.group("command")
        rest = match.group("rest").strip()
        in_track = current_track is not None

        if command == "REM":
            key, _, value = rest.partition(" ")
            key = key.upper()
            if key == "DATE":
                sheet.date = value.strip().strip('"')
            elif key == "GENRE":
                sheet.genre = value.strip().strip('"')
            elif key == "COMMENT":
                sheet.comment = value.strip().strip('"')
        elif command == "CATALOG":
            sheet.catalog = rest.strip().strip('"')
        elif command == "PERFORMER":
            if in_track:
                current_track.performer = _first_quoted(rest)
            else:
                sheet.performer = _first_quoted(rest)
        elif command == "TITLE":
            if in_track:
                current_track.title = _first_quoted(rest)
            else:
                sheet.title = _first_quoted(rest)
        elif command == "ISRC" and in_track:
            current_track.isrc = rest.strip().strip('"')
        elif command == "FILE":
            name = _first_quoted(rest)
            file_type = rest.rsplit('"', 1)[-1].strip() or "WAVE"
            current_file = CueFile(name=name, file_type=file_type)
            sheet.files.append(current_file)
            current_track = None
        elif command == "TRACK":
            found = _TRACK.match(rest)
            if not found:
                sheet.warnings.append(f"unlesbare TRACK-Zeile: {raw.strip()!r}")
                continue
            if current_file is None:
                current_file = CueFile(name="")
                sheet.files.append(current_file)
                sheet.warnings.append("TRACK ohne vorangehendes FILE")
            current_track = CueTrack(number=int(found.group("number")))
            current_file.tracks.append(current_track)
        elif command == "INDEX" and in_track:
            found = _INDEX.match(rest)
            if not found:
                sheet.warnings.append(f"unlesbare INDEX-Zeile: {raw.strip()!r}")
                continue
            try:
                seconds = parse_time(found.group("time"))
            except CueError as exc:
                sheet.warnings.append(str(exc))
                continue
            if int(found.group("number")) == 0:
                current_track.pregap_start = seconds
            elif current_track.start is None:
                current_track.start = seconds

    _fill_durations(sheet)
    return sheet


def _fill_durations(sheet: CueSheet) -> None:
    """Laufzeit aus dem Abstand zum nächsten Track. Der letzte bleibt offen."""
    for cue_file in sheet.files:
        tracks = cue_file.tracks
        for index, track in enumerate(tracks):
            if track.start is None:
                sheet.warnings.append(
                    f"Track {track.number} in {cue_file.name!r} hat kein INDEX 01")
                continue
            if index + 1 < len(tracks):
                following = tracks[index + 1]
                start = following.pregap_start
                if start is None:
                    start = following.start
                if start is not None:
                    track.duration = max(0.0, start - track.start)


def read_cue(path: str | Path, codepage: str = "utf-8") -> CueSheet:
    """Liest ein CUE. Fällt bei ungültigem UTF-8 auf CP1252 zurück."""
    raw = Path(path).read_bytes()
    for encoding in (codepage, "utf-8-sig", "cp1252", "cp437"):
        try:
            return parse_cue(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    return parse_cue(raw.decode("utf-8", errors="replace"))


def close_durations(sheet: CueSheet, file_lengths: dict[str, float]) -> None:
    """Ergänzt die Laufzeit des jeweils letzten Tracks.

    ``file_lengths`` bildet den Dateinamen aus dem CUE auf die tatsächliche
    Länge der Audiodatei ab - die steht nicht im CUE.
    """
    for cue_file in sheet.files:
        if not cue_file.tracks:
            continue
        total = file_lengths.get(cue_file.name)
        if total is None:
            total = file_lengths.get(Path(cue_file.name).name)
        last = cue_file.tracks[-1]
        if total is not None and last.start is not None and last.duration is None:
            last.duration = max(0.0, total - last.start)
