"""Rückgängig machen.

Zwei Operationen lassen sich nicht aus den Dateien zurückrechnen: Nach dem
Umbenennen weiß niemand mehr, wie es vorher hieß, und nach dem Tag-Schreiben
steht der alte Wert nirgends mehr. Beides wird deshalb protokolliert, bevor es
passiert.

**Wo.** Nicht im Releaseverzeichnis - das wird ja selbst umbenannt und beim
nächsten ``--clean`` womöglich aufgeräumt. Stattdessen im Zustandsverzeichnis
des Benutzers (``$XDG_STATE_HOME`` oder ``~/.local/state``).

**Wie.** Die Rücknahme läuft in umgekehrter Reihenfolge und erst, nachdem
geprüft wurde, dass jedes Ziel noch da ist und jeder Ursprung frei. Ein
halbes Undo wäre schlimmer als keines.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

#: Mehr als das wird nicht aufgehoben - alte Eintraege verfallen.
MAX_ENTRIES = 50
JOURNAL_NAME = "undo.json"


class UndoError(Exception):
    pass


def journal_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(base) / "mp3releaser" / JOURNAL_NAME


class Kind(Enum):
    RENAME = "rename"
    TAGS = "tags"

    @property
    def label(self) -> str:
        return {Kind.RENAME: "Umbenennungen",
                Kind.TAGS: "getaggte Dateien"}[self]


@dataclass
class Entry:
    """Ein ausgefuehrter Lauf - umbenannt oder getaggt."""

    timestamp: float
    release: str
    kind: Kind = Kind.RENAME
    #: (vorher, nachher), in Ausfuehrungsreihenfolge - beim Umbenennen
    moves: list[tuple[str, str]] = field(default_factory=list)
    #: Datei -> Feld -> vorheriger Wert - beim Taggen
    tags: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.timestamp))

    @property
    def count(self) -> int:
        return len(self.moves) if self.kind is Kind.RENAME else len(self.tags)

    def as_dict(self) -> dict:
        return {"timestamp": self.timestamp, "release": self.release,
                "kind": self.kind.value,
                "moves": [list(move) for move in self.moves],
                "tags": self.tags}

    @classmethod
    def from_dict(cls, data: dict) -> "Entry":
        # "kind" fehlt in Protokollen aelterer Fassungen - die kannten nur
        # das Umbenennen.
        try:
            kind = Kind(data.get("kind", Kind.RENAME.value))
        except ValueError:
            kind = Kind.RENAME
        tags = data.get("tags") or {}
        return cls(timestamp=float(data.get("timestamp", 0.0)),
                   release=str(data.get("release", "")),
                   kind=kind,
                   moves=[(str(a), str(b)) for a, b in data.get("moves", [])],
                   tags={str(path): {str(k): str(v) for k, v in values.items()}
                         for path, values in tags.items()
                         if isinstance(values, dict)})

    def describe(self) -> str:
        return f"{self.when}  {self.release}  ({self.count} {self.kind.label})"


def load(path: Optional[Path] = None) -> list[Entry]:
    target = path or journal_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [Entry.from_dict(item) for item in data if isinstance(item, dict)]


def save(entries: Iterable[Entry], path: Optional[Path] = None) -> Path:
    target = path or journal_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    kept = list(entries)[-MAX_ENTRIES:]
    target.write_text(json.dumps([e.as_dict() for e in kept], indent=1),
                      encoding="utf-8")
    return target


def _append(entry: Entry, path: Optional[Path]) -> Entry:
    try:
        save(load(path) + [entry], path)
    except OSError:
        # Ein nicht schreibbares Protokoll darf die Arbeit nicht stoppen
        pass
    return entry


def record(moves: Iterable[tuple[Path, Path]], release: str,
           path: Optional[Path] = None) -> Optional[Entry]:
    """Haelt einen Umbenennungslauf fest. Ohne Bewegungen passiert nichts."""
    pairs = [(str(src), str(dst)) for src, dst in moves if src != dst]
    if not pairs:
        return None
    return _append(Entry(timestamp=time.time(), release=release,
                         kind=Kind.RENAME, moves=pairs), path)


def record_tags(previous: dict, release: str,
                path: Optional[Path] = None) -> Optional[Entry]:
    """Haelt die *vorherigen* Tagwerte fest, bevor geschrieben wird.

    ``previous`` bildet Dateipfad auf Feld und alten Wert ab. Nur geaenderte
    Felder gehoeren hinein - alles andere zurueckzuschreiben waere unnoetig
    und wuerde Dateien anfassen, die niemand veraendert hat.
    """
    cleaned = {str(file): dict(values) for file, values in previous.items()
               if values}
    if not cleaned:
        return None
    return _append(Entry(timestamp=time.time(), release=release,
                         kind=Kind.TAGS, tags=cleaned), path)


def last(path: Optional[Path] = None) -> Optional[Entry]:
    entries = load(path)
    return entries[-1] if entries else None


def _forward(path: Path, moves: Iterable[tuple[str, str]]) -> Path:
    """Wo eine Datei heute liegt, wenn spaetere Umbenennungen sie mitgenommen haben.

    Eine Datei wird zuerst umbenannt, dann ihr CD-Ordner, dann das
    Wurzelverzeichnis. Der protokollierte Zielpfad der Datei zeigt deshalb auf
    einen Ordner, den es so nicht mehr gibt.
    """
    for src, dst in moves:
        source, target = Path(src), Path(dst)
        if path == source:
            path = target
        elif path.is_relative_to(source):
            path = target / path.relative_to(source)
    return path


def check(entry: Entry) -> list[str]:
    """Was einer Ruecknahme im Weg steht - leere Liste heisst: sie kann laufen."""
    if entry.kind is Kind.TAGS:
        return [f"nicht mehr vorhanden: {file}"
                for file in entry.tags if not Path(file).is_file()]

    problems: list[str] = []
    for index, (src, dst) in enumerate(entry.moves):
        location = _forward(Path(dst), entry.moves[index + 1:])
        if not location.exists():
            problems.append(f"nicht mehr vorhanden: {location}")

    # Nur den letzten Schritt auf Belegung pruefen: die uebrigen Urspruenge
    # entstehen erst, waehrend die Ruecknahme laeuft.
    if entry.moves:
        first_src, last_dst = Path(entry.moves[-1][0]), Path(entry.moves[-1][1])
        if first_src.exists() and first_src != last_dst:
            problems.append(f"Ursprung ist belegt: {first_src}")
    return problems


def undo(entry: Entry, path: Optional[Path] = None,
         force: bool = False) -> list[tuple[Path, Path]]:
    """Nimmt einen Lauf zurueck und entfernt ihn aus dem Protokoll.

    Umgekehrte Reihenfolge: zuerst das Wurzelverzeichnis, dann die
    CD-Ordner, zuletzt die Dateien - genau andersherum als beim Umbenennen.
    """
    problems = check(entry)
    if problems and not force:
        raise UndoError("; ".join(problems))

    if entry.kind is Kind.TAGS:
        done = _undo_tags(entry)
        _forget(entry, path)
        return done

    done: list[tuple[Path, Path]] = []
    for src, dst in reversed(entry.moves):
        origin, target = Path(src), Path(dst)
        if not target.exists():
            continue
        origin.parent.mkdir(parents=True, exist_ok=True)
        target.rename(origin)
        done.append((target, origin))

    _forget(entry, path)
    return done


def _forget(entry: Entry, path: Optional[Path]) -> None:
    remaining = [e for e in load(path) if e.timestamp != entry.timestamp]
    try:
        save(remaining, path)
    except OSError:
        pass


def _undo_tags(entry: Entry) -> list[tuple[Path, Path]]:
    """Schreibt die alten Werte zurueck.

    Zurueckgegeben wird (Datei, Datei) je wiederhergestellter Datei - so hat
    der Aufrufer dieselbe Form wie beim Umbenennen.
    """
    from .tagwriter import write_values

    done: list[tuple[Path, Path]] = []
    for file, values in entry.tags.items():
        target = Path(file)
        if not target.is_file():
            continue
        if write_values(target, values):
            done.append((target, target))
    return done
