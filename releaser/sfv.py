"""SFV-Dateien schreiben, lesen und prüfen.

Format: Kommentarzeilen beginnen mit ``;``, danach je eine Zeile
``dateiname CRC32`` mit acht Hexziffern. Zeilenenden CRLF, Kodierung CP437 —
wie beim NFO, damit Umlaute in Dateinamen nicht zu Mojibake werden.

Bei Mehr-CD-Releases entsteht standardmäßig ein SFV je CD-Verzeichnis mit
nackten Dateinamen. Das entspricht dem, was Prüfprogramme erwarten: das SFV
liegt neben den Dateien, die es beschreibt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .checksums import audio_crc32, crc32_file, format_crc
from .model import Disc, Release
from .text import to_codepage

_LINE = re.compile(r"^(?P<name>.+?)\s+(?P<crc>[0-9A-Fa-f]{8})\s*$")
#: Eigene Kommentarzeile mit dem tagfreien Audio-CRC. Fremde Prüfprogramme
#: überlesen sie, wir können damit "beschädigt" von "umgetaggt" unterscheiden.
_AUDIO = re.compile(r"^audio-crc\s+(?P<crc>[0-9A-Fa-f]{8})\s+(?P<name>.+)$")


@dataclass
class SfvEntry:
    filename: str
    crc: int
    #: CRC nur über die Audiodaten - nicht Teil des SFV, aber nützlich
    audio_crc: Optional[int] = None
    notes: list[str] = field(default_factory=list)


@dataclass
class SfvFile:
    entries: list[SfvEntry] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    #: aus den audio-crc-Kommentarzeilen gelesen
    audio_crcs: dict[str, int] = field(default_factory=dict)

    def render(self, uppercase: bool = True) -> str:
        lines = [f"; {c}" for c in self.comments]
        for entry in self.entries:
            if entry.audio_crc is not None:
                lines.append(f"; audio-crc {format_crc(entry.audio_crc, uppercase)} "
                             f"{entry.filename}")
        width = max((len(e.filename) for e in self.entries), default=0)
        lines += [f"{e.filename.ljust(width)} {format_crc(e.crc, uppercase)}"
                  for e in self.entries]
        return "\r\n".join(lines) + "\r\n"


@dataclass
class VerifyResult:
    ok: list[str] = field(default_factory=list)
    failed: list[tuple[str, int, int]] = field(default_factory=list)   # name, soll, ist
    missing: list[str] = field(default_factory=list)
    #: Dateien, deren Datei-CRC abweicht, deren Audio-CRC aber passt
    retagged: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.failed and not self.missing


def build_sfv(
    files: Sequence[Path],
    base: Optional[Path] = None,
    comments: Iterable[str] = (),
    with_audio_crc: bool = False,
) -> SfvFile:
    """Berechnet die Prüfsummen für eine Dateiliste."""
    sfv = SfvFile(comments=list(comments))
    for path in files:
        name = str(path.relative_to(base)) if base else path.name
        entry = SfvEntry(filename=name, crc=crc32_file(path))
        if with_audio_crc:
            entry.audio_crc, bounds = audio_crc32(path)
            entry.notes.extend(bounds.notes)
        sfv.entries.append(entry)
    return sfv


def parse_sfv(text: str) -> SfvFile:
    sfv = SfvFile()
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(";"):
            body = line[1:].strip()
            m = _AUDIO.match(body)
            if m:
                sfv.audio_crcs[m.group("name").strip()] = int(m.group("crc"), 16)
            else:
                sfv.comments.append(body)
            continue
        m = _LINE.match(line)
        if m:
            sfv.entries.append(SfvEntry(filename=m.group("name").strip(),
                                        crc=int(m.group("crc"), 16)))
    return sfv


def read_sfv(path: str | Path, codepage: str = "cp437") -> SfvFile:
    return parse_sfv(Path(path).read_bytes().decode(codepage, errors="replace"))


def write_sfv(path: str | Path, sfv: SfvFile, codepage: str = "cp437",
              uppercase: bool = True) -> None:
    Path(path).write_bytes(to_codepage(sfv.render(uppercase), codepage))


def verify_sfv(path: str | Path, directory: Optional[Path] = None) -> VerifyResult:
    """Prüft ein SFV gegen die Dateien daneben.

    Weicht der Datei-CRC ab, wurde aber beim Erzeugen ein Audio-CRC mitnotiert
    und stimmt dieser noch, dann wurde die Datei nur umgetaggt und ist nicht
    beschädigt - das landet in ``retagged`` statt in ``failed``. Ohne
    mitnotierten Audio-CRC ist diese Unterscheidung nicht möglich; dann gilt
    jede Abweichung als Fehler.
    """
    sfv_path = Path(path)
    base = Path(directory) if directory else sfv_path.parent
    result = VerifyResult()
    parsed = read_sfv(sfv_path)
    reference = parsed.audio_crcs

    for entry in parsed.entries:
        target = base / entry.filename
        if not target.is_file():
            result.missing.append(entry.filename)
            continue
        actual = crc32_file(target)
        if actual == entry.crc:
            result.ok.append(entry.filename)
            continue
        try:
            audio, _ = audio_crc32(target)
        except OSError:
            audio = None
        if audio is not None and reference.get(entry.filename) == audio:
            result.retagged.append(entry.filename)
        else:
            result.failed.append((entry.filename, entry.crc, actual))
    return result


# ------------------------------------------------------- Release-Integration


def sfv_targets(release: Release, root: Path) -> dict[Path, list[Path]]:
    """Ordnet jedem SFV-Verzeichnis seine Dateien zu.

    Ein SFV je Verzeichnis, in dem Audiodateien liegen - bei Mehr-CD-Releases
    ergibt das automatisch ein SFV je CD.
    """
    groups: dict[Path, list[Path]] = {}
    for track in release.tracks:
        if not track.path:
            continue
        p = Path(track.path)
        groups.setdefault(p.parent, []).append(p)
    if not groups:
        groups[root] = []
    return groups


def sfv_name(release: Release, disc: Optional[Disc] = None,
             use_catalog_no: bool = False,
             stem: Optional[str] = None) -> str:
    """Dateiname des SFV.

    Die CD-Kennung kommt aus der *Nummer*, nicht aus dem Verzeichnisnamen -
    sonst hiesse das SFV neben einem Ordner "Disc 2" auch "…-disc 2.sfv",
    mit Leerzeichen, und wiche von der gleichnamigen M3U ab.

    ``stem`` erlaubt es dem Aufrufer, denselben Namensrumpf wie für .nfo und
    Cover zu verwenden. Das Original konnte statt des Releasenamens die
    Katalognummer nehmen.
    """
    base = stem if stem is not None else (release.dirname or release.release_name)
    if use_catalog_no and release.catalog_no:
        base = release.catalog_no
    if disc is not None and release.multi_disc:
        base = f"{base}-cd{disc.number}"
    return f"{base}.sfv"


def write_release_sfvs(
    release: Release,
    root: str | Path,
    comments: Iterable[str] = (),
    extra_extensions: Iterable[str] = (),
    use_catalog_no: bool = False,
    uppercase: bool = True,
    with_audio_crc: bool = False,
    stem: Optional[str] = None,
) -> list[Path]:
    """Schreibt ein SFV je Verzeichnis und gibt die erzeugten Pfade zurück.

    ``extra_extensions`` nimmt zusätzliche Endungen auf (das Original bot
    ``.log`` und ``.pdf`` an). ``.nfo``, ``.m3u`` und das SFV selbst gehören
    nach den üblichen Regeln nicht hinein.
    """
    root = Path(root)
    written: list[Path] = []
    # Einmal festhalten: ein Generator waere nach dem ersten Verzeichnis
    # erschoepft, und die SFVs der uebrigen CDs bekaemen keinen Kommentar.
    comments = list(comments)
    extras = {e.lower() if e.startswith(".") else f".{e.lower()}"
              for e in extra_extensions}

    # Verzeichnis -> zugehoerige CD, damit der Name aus der Nummer entsteht
    disc_for: dict[Path, Disc] = {}
    for disc in release.discs:
        disc_for.setdefault(disc.directory(root), disc)

    for directory, files in sfv_targets(release, root).items():
        candidates = list(files)
        for extra in sorted(directory.glob("*")):
            if extra.is_file() and extra.suffix.lower() in extras:
                candidates.append(extra)
        if not candidates:
            continue
        sfv = build_sfv(sorted(set(candidates)), comments=comments,
                        with_audio_crc=with_audio_crc)
        target = directory / sfv_name(release, disc_for.get(directory),
                                      use_catalog_no, stem)
        write_sfv(target, sfv, uppercase=uppercase)
        written.append(target)
    return written
