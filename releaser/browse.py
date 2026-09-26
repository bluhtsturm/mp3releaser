"""Dateiauswahl.

Beide Oberflächen zeigen links einen Baum zum Auswählen eines Releases. Was
sie zeigen dürfen, ist aber verschieden:

* :class:`LocalSource` - das ganze Dateisystem. Der Normalfall für ein
  Programm, das auf dem eigenen Rechner läuft.
* :class:`MountedSource` - nur die Verzeichnisse, die jemand vorher
  eingehängt hat. Der Normalfall für einen Dienst im Container.

Der Unterschied ist nicht bloß technisch. Bei der lokalen Form entscheidet
der Nutzer, worauf er zugreift; bei der eingehängten Form hat das jemand
anderes vorher entschieden - wer den Container betreibt.

Beide liefern dieselbe Struktur an die Oberfläche, und die Dienstschicht
merkt keinen Unterschied. Dadurch liegt die Beschränkung an genau einer
Stelle und ist prüfbar, statt über zwei Oberflächen verstreut zu sein.

**Pfade nach außen.** ``MountedSource`` gibt niemals Pfade des Wirtsystems
heraus, sondern virtuelle Pfade der Form ``einhaengepunkt/unterordner``. Ein
Client kann damit nichts über den Aufbau des Wirts erfahren, und der Weg
zurück läuft ausschließlich über :meth:`Source.resolve`, wo geprüft wird.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence

from .audio.base import AUDIO_EXTENSIONS
from .companions import COMPANION_SUFFIXES, COVER_SUFFIXES


class AccessError(Exception):
    """Der Pfad liegt außerhalb dessen, was diese Quelle zeigen darf,
    oder lässt sich nicht öffnen."""


#: Laengengrenze eines einzelnen Pfadbestandteils auf gaengigen Dateisystemen.
#: Ohne die Pruefung wirft erst das Betriebssystem - und zwar mitten in der
#: Anzeige, als unbehandelter Systemfehler.
MAX_NAME_LENGTH = 255


class Kind(Enum):
    DIRECTORY = "directory"
    RELEASE = "release"        # Verzeichnis mit Audiodateien
    AUDIO = "audio"
    COMPANION = "companion"    # .nfo, .sfv, .m3u
    COVER = "cover"
    CUE = "cue"
    OTHER = "other"


@dataclass
class Entry:
    """Ein Eintrag im Baum, wie ihn die Oberfläche anzeigt."""

    name: str
    #: virtueller Pfad - das, was die Oberfläche zurückschickt
    path: str
    kind: Kind
    size: int = 0
    #: nur bei Verzeichnissen gefüllt
    audio_files: int = 0
    has_children: bool = False

    @property
    def is_dir(self) -> bool:
        return self.kind in (Kind.DIRECTORY, Kind.RELEASE)


def classify_file(path: Path) -> Kind:
    suffix = path.suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return Kind.AUDIO
    if suffix in COMPANION_SUFFIXES:
        return Kind.COMPANION
    if suffix in COVER_SUFFIXES:
        return Kind.COVER
    if suffix == ".cue":
        return Kind.CUE
    return Kind.OTHER


def count_audio(path: Path) -> int:
    """Audiodateien direkt in diesem Verzeichnis und eine Ebene darunter.

    Eine Ebene reicht, weil Mehr-CD-Releases ihre Dateien in ``CD1``/``CD2``
    ablegen. Tiefer zu suchen würde bei großen Sammlungen jede Baumanzeige
    ausbremsen.
    """
    total = 0
    try:
        for entry in path.iterdir():
            if entry.is_file() and entry.suffix.lower() in AUDIO_EXTENSIONS:
                total += 1
            elif entry.is_dir():
                try:
                    total += sum(1 for sub in entry.iterdir()
                                 if sub.is_file()
                                 and sub.suffix.lower() in AUDIO_EXTENSIONS)
                except OSError:
                    continue
    except OSError:
        return 0
    return total


class Source:
    """Gemeinsame Schnittstelle der Dateiauswahl."""

    #: kurze Beschreibung für die Oberfläche
    description: str = ""

    def roots(self) -> list[Entry]:            # pragma: no cover - Schnittstelle
        raise NotImplementedError

    def resolve(self, virtual: str) -> Path:   # pragma: no cover
        raise NotImplementedError

    def to_virtual(self, path: Path) -> str:   # pragma: no cover
        raise NotImplementedError

    def list(self, virtual: str, show_hidden: bool = False) -> list[Entry]:
        """Inhalt eines Verzeichnisses, Ordner zuerst."""
        target = self.resolve(virtual)
        try:
            is_directory = target.is_dir()
        except OSError as exc:
            raise AccessError(f"{virtual} ist nicht lesbar: {exc.strerror}") from exc
        if not is_directory:
            raise AccessError(f"kein Verzeichnis: {virtual}")

        entries: list[Entry] = []
        try:
            children = sorted(target.iterdir(),
                              key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError as exc:
            raise AccessError(f"kein Zugriff auf {virtual}") from exc
        except OSError as exc:
            # Etwa ein Ein-/Ausgabefehler auf einem Netzlaufwerk - als Meldung
            # statt als unbehandelter Systemfehler
            raise AccessError(f"{virtual} ist nicht lesbar: {exc.strerror}") from exc

        for child in children:
            if not show_hidden and child.name.startswith("."):
                continue
            try:
                entries.append(self._entry(child))
            except OSError:
                continue
        return entries

    def _entry(self, path: Path) -> Entry:
        virtual = self.to_virtual(path)
        if path.is_dir():
            audio = count_audio(path)
            return Entry(
                name=path.name,
                path=virtual,
                kind=Kind.RELEASE if audio else Kind.DIRECTORY,
                audio_files=audio,
                has_children=_has_children(path),
            )
        return Entry(name=path.name, path=virtual, kind=classify_file(path),
                     size=path.stat().st_size)

    def releases(self, virtual: str) -> list[Entry]:
        """Nur die Unterordner, die wie ein Release aussehen."""
        return [e for e in self.list(virtual) if e.kind is Kind.RELEASE]


def _has_children(path: Path) -> bool:
    try:
        next(iter(path.iterdir()))
        return True
    except (StopIteration, OSError):
        return False


# ------------------------------------------------------------------ lokal


class LocalSource(Source):
    """Das ganze Dateisystem, wie es eine lokale Anwendung sieht.

    Virtuelle Pfade sind hier schlicht die echten Pfade - es gibt nichts zu
    verbergen, das Programm läuft mit den Rechten des Nutzers.
    """

    description = "lokales Dateisystem"

    def __init__(self, start: Optional[str | Path] = None):
        self.start = Path(start).expanduser() if start else Path.home()

    def roots(self) -> list[Entry]:
        candidates = [self.start, Path.home(), Path("/")]
        seen: set[Path] = set()
        out: list[Entry] = []
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved in seen or not resolved.is_dir():
                continue
            seen.add(resolved)
            out.append(self._entry(resolved))
        return out

    def resolve(self, virtual: str) -> Path:
        path = Path(virtual).expanduser()
        if any(len(part) > MAX_NAME_LENGTH for part in path.parts):
            raise AccessError("Pfadbestandteil zu lang")
        if not path.is_absolute():
            path = self.start / path
        return path

    def to_virtual(self, path: Path) -> str:
        return str(path)


# --------------------------------------------------------------- eingehängt


@dataclass
class Mount:
    """Ein eingehängtes Verzeichnis, wie es in der Compose-Datei steht."""

    name: str
    path: Path
    writable: bool = True

    def __post_init__(self) -> None:
        self.path = Path(self.path).resolve()


class MountedSource(Source):
    """Nur die eingehängten Verzeichnisse - der Fall im Container.

    Alles außerhalb ist unsichtbar und unerreichbar. Der Weg von außen nach
    innen führt ausschließlich über :meth:`resolve`, und dort wird gegen
    Ausbrüche geprüft: ``..``, absolute Pfade und Symlinks, die aus dem
    Einhängepunkt herausführen.
    """

    description = "eingehängte Verzeichnisse"

    def __init__(self, mounts: Sequence[Mount] | Sequence[tuple[str, str]]):
        prepared: list[Mount] = []
        for mount in mounts:
            prepared.append(mount if isinstance(mount, Mount)
                            else Mount(mount[0], Path(mount[1])))
        names = [m.name for m in prepared]
        if len(set(names)) != len(names):
            raise ValueError(f"doppelte Einhängepunkte: {names}")
        self.mounts = prepared

    @property
    def names(self) -> list[str]:
        return [m.name for m in self.mounts]

    def mount_for(self, name: str) -> Mount:
        for mount in self.mounts:
            if mount.name == name:
                return mount
        raise AccessError(f"unbekannter Einhängepunkt: {name!r}")

    def roots(self) -> list[Entry]:
        out: list[Entry] = []
        for mount in self.mounts:
            if not mount.path.is_dir():
                continue
            audio = count_audio(mount.path)
            out.append(Entry(
                name=mount.name,
                path=mount.name,
                kind=Kind.RELEASE if audio else Kind.DIRECTORY,
                audio_files=audio,
                has_children=_has_children(mount.path),
            ))
        return out

    def resolve(self, virtual: str) -> Path:
        parts = PurePosixPath(str(virtual).strip("/")).parts
        if not parts:
            raise AccessError("leerer Pfad")
        if any(part in ("..", "") or "\x00" in part for part in parts):
            raise AccessError(f"unzulässiger Pfad: {virtual!r}")
        too_long = next((p for p in parts if len(p) > MAX_NAME_LENGTH), None)
        if too_long is not None:
            raise AccessError(
                f"Bestandteil zu lang ({len(too_long)} Zeichen, "
                f"erlaubt sind {MAX_NAME_LENGTH})")

        mount = self.mount_for(parts[0])
        target = mount.path.joinpath(*parts[1:])

        # Symlinks können aus dem Einhängepunkt herausführen - deshalb nach
        # dem Auflösen noch einmal prüfen, nicht davor.
        try:
            resolved = target.resolve()
        except OSError as exc:
            raise AccessError(f"nicht auflösbar: {virtual!r}") from exc
        if resolved != mount.path and mount.path not in resolved.parents:
            raise AccessError(
                f"{virtual!r} führt aus dem Einhängepunkt {mount.name!r} heraus")
        return resolved

    def to_virtual(self, path: Path) -> str:
        resolved = Path(path).resolve()
        for mount in self.mounts:
            if resolved == mount.path:
                return mount.name
            if mount.path in resolved.parents:
                return f"{mount.name}/{resolved.relative_to(mount.path).as_posix()}"
        raise AccessError(f"{path} liegt außerhalb der eingehängten Verzeichnisse")

    def is_writable(self, virtual: str) -> bool:
        name = PurePosixPath(str(virtual).strip("/")).parts[0]
        return self.mount_for(name).writable


def from_environment(value: Optional[str] = None) -> MountedSource:
    """Baut die Quelle aus einer Umgebungsvariablen.

    Format wie bei Docker, durch Doppelpunkt getrennte Paare, mehrere durch
    Komma::

        RELEASER_MOUNTS=eingang:/data/eingang,archiv:/data/archiv:ro
    """
    import os

    raw = value if value is not None else os.environ.get("RELEASER_MOUNTS", "")
    mounts: list[Mount] = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        fields = item.split(":")
        if len(fields) < 2:
            raise ValueError(f"unlesbarer Einhängepunkt: {item!r}")
        name, path = fields[0], fields[1]
        writable = not (len(fields) > 2 and fields[2] == "ro")
        mounts.append(Mount(name=name, path=Path(path), writable=writable))
    return MountedSource(mounts)


def describe(source: Source) -> dict:
    """Kurzbeschreibung für die Oberfläche und für ``metrics``."""
    info: dict = {"kind": type(source).__name__, "description": source.description}
    if isinstance(source, MountedSource):
        info["mounts"] = [
            {"name": m.name, "writable": m.writable, "exists": m.path.is_dir()}
            for m in source.mounts
        ]
        info["scope"] = "nur was eingehängt wurde"
    else:
        info["scope"] = "das gesamte Dateisystem des Nutzers"
    return info
