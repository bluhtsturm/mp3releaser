"""Rückgängig machen.

Vier Operationen lassen sich nicht aus den Dateien zurückrechnen: Nach dem
Umbenennen weiß niemand mehr, wie es vorher hieß, nach dem Tag-Schreiben
steht der alte Wert nirgends mehr, nach dem Verschieben in den
Ausgabeordner niemand, wo das Release herkam - und welche ``.nfo``,
``.sfv`` und ``.m3u`` das Programm angelegt hat und welche schon da waren,
sieht man ihnen auch nicht an. Alles wird deshalb protokolliert.

**Wo.** Nicht im Releaseverzeichnis - das wird ja selbst umbenannt und beim
nächsten ``--clean`` womöglich aufgeräumt. Stattdessen im Zustandsverzeichnis
des Benutzers (``$XDG_STATE_HOME`` oder ``~/.local/state``).

**Wie.** Die Rücknahme läuft in umgekehrter Reihenfolge und erst, nachdem
geprüft wurde, dass jedes Ziel noch da ist und jeder Ursprung frei. Ein
halbes Undo wäre schlimmer als keines.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

#: Mehr als das wird nicht aufgehoben - alte Eintraege verfallen.
MAX_ENTRIES = 50
JOURNAL_NAME = "undo.json"

#: Lesen, aendern, schreiben - immer am Stueck. Der Webdienst bedient
#: mehrere Sitzungen in Threads; zwei, die gleichzeitig ein Release
#: erstellten, lasen dasselbe Protokoll und schrieben es nacheinander
#: zurueck - die Eintraege der ersten waren dann weg.
_LOCK = threading.RLock()


class UndoError(Exception):
    pass


def journal_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(base) / "mp3releaser" / JOURNAL_NAME


class Kind(Enum):
    RENAME = "rename"
    TAGS = "tags"
    #: in den Ausgabeordner geschoben - laeuft wie ein Umbenennen, nur ueber
    #: Ordnergrenzen und notfalls Dateisystemgrenzen hinweg
    MOVE = "move"
    #: .nfo, .sfv und .m3u angelegt - zurueckgenommen heisst: wieder entfernt
    CREATED = "created"

    @property
    def label(self) -> str:
        return {Kind.RENAME: "Umbenennungen",
                Kind.TAGS: "getaggte Dateien",
                Kind.MOVE: "Verschiebung(en) in den Ausgabeordner",
                Kind.CREATED: "erzeugte Datei(en)"}[self]


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
    #: Datei -> SHA-256 des Inhalts beim Anlegen - bei erzeugten Dateien.
    #: Entfernt wird nur, was noch genau so aussieht.
    created: dict[str, str] = field(default_factory=dict)

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.timestamp))

    @property
    def count(self) -> int:
        if self.kind is Kind.TAGS:
            return len(self.tags)
        if self.kind is Kind.CREATED:
            return len(self.created)
        return len(self.moves)

    def as_dict(self) -> dict:
        data = {"timestamp": self.timestamp, "release": self.release,
                "kind": self.kind.value,
                "moves": [list(move) for move in self.moves],
                "tags": self.tags}
        if self.created:
            data["created"] = self.created
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Entry":
        # "kind" fehlt in Protokollen aelterer Fassungen - die kannten nur
        # das Umbenennen.
        try:
            kind = Kind(data.get("kind", Kind.RENAME.value))
        except ValueError:
            kind = Kind.RENAME
        tags = data.get("tags") or {}
        created = data.get("created") or {}
        return cls(timestamp=float(data.get("timestamp", 0.0)),
                   release=str(data.get("release", "")),
                   kind=kind,
                   moves=[(str(a), str(b)) for a, b in data.get("moves", [])],
                   tags={str(path): {str(k): str(v) for k, v in values.items()}
                         for path, values in tags.items()
                         if isinstance(values, dict)},
                   created={str(path): str(digest)
                            for path, digest in created.items()})

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
    entries: list[Entry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        # Ein einzelner beschaedigter Eintrag (etwa eine Bewegung ohne Ziel)
        # darf das Protokoll nicht unlesbar machen - sonst liesse sich auch
        # alles andere darin nicht mehr zuruecknehmen.
        try:
            entries.append(Entry.from_dict(item))
        except (TypeError, ValueError, AttributeError):
            continue
    return entries


def save(entries: Iterable[Entry], path: Optional[Path] = None) -> Path:
    """Schreibt das Protokoll - erst daneben, dann an seinen Platz.

    Bricht das Schreiben ab (Absturz, voller Datentraeger), bleibt das alte
    Protokoll stehen. Vorher lag dann eine halbe Datei da, ``load`` las sie
    als leer, und nichts liess sich mehr zuruecknehmen.
    """
    target = path or journal_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    kept = list(entries)[-MAX_ENTRIES:]
    temporary = target.with_name(f".{target.name}.{os.getpid()}."
                                 f"{threading.get_ident()}.tmp")
    try:
        temporary.write_text(json.dumps([e.as_dict() for e in kept], indent=1),
                             encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _append(entry: Entry, path: Optional[Path]) -> Entry:
    with _LOCK:
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


def record_move(src: Path, dst: Path, release: str,
                path: Optional[Path] = None) -> Optional[Entry]:
    """Haelt das Verschieben in den Ausgabeordner fest."""
    if Path(src) == Path(dst):
        return None
    return _append(Entry(timestamp=time.time(), release=release,
                         kind=Kind.MOVE, moves=[(str(src), str(dst))]), path)


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


def fingerprint(path: Path) -> str:
    """SHA-256 des Dateiinhalts - woran eine erzeugte Datei erkannt wird."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_created(files: Iterable[Path], release: str,
                   path: Optional[Path] = None) -> Optional[Entry]:
    """Haelt die frisch angelegten Begleitdateien fest.

    Nur Dateien, die es vorher *nicht* gab, gehoeren hinein - der Aufrufer
    sortiert die anderen aus. Eine vorhandene ``.nfo``, die neu geschrieben
    wurde, darf die Ruecknahme nicht loeschen: Sie war vorher schon da.
    """
    created: dict[str, str] = {}
    for file in files:
        try:
            created[str(file)] = fingerprint(Path(file))
        except OSError:
            continue
    if not created:
        return None
    return _append(Entry(timestamp=time.time(), release=release,
                         kind=Kind.CREATED, created=created), path)


def changed_files(entry: Entry) -> list[Path]:
    """Erzeugte Dateien, die seitdem jemand veraendert hat - sie bleiben."""
    changed: list[Path] = []
    for file, digest in entry.created.items():
        target = Path(file)
        try:
            if target.is_file() and fingerprint(target) != digest:
                changed.append(target)
        except OSError:
            changed.append(target)
    return changed


def detail(entry: Entry) -> str:
    """Was die Ruecknahme genau tut - fuer den Bestaetigungsdialog."""
    if entry.kind is Kind.CREATED:
        # Der Ordner einmal, darunter die Namen: Volle Pfade liefen im
        # Dialog aus dem Bild, samt dem Hinweis dahinter.
        changed = set(changed_files(entry))
        place = release_place(entry)
        root = place[0] if place else None
        lines = [f"  in {root}:"] if root else []
        for file in entry.created:
            path = Path(file)
            name = path.relative_to(root).as_posix() if root else file
            note = ("   (verändert – bleibt)" if path in changed
                    else "   (gibt es nicht mehr)" if not path.exists() else "")
            lines.append(f"    {name}{note}")
        return "\n".join(lines)
    if entry.moves:
        return "\n".join(f"  {dst}\n     ->  {src}" for src, dst in entry.moves)
    # Pseudofelder wie "#containers" sind Buchhaltung, kein Tag
    return "\n".join(
        f"  {Path(file).name}: "
        + ", ".join(k for k in values if not k.startswith("#"))
        for file, values in entry.tags.items())


def produce_hint(moved: bool) -> str:
    """In welcher Reihenfolge ↶ ein fertiges Release zuruecknimmt.

    Steht nach "Release erstellen" in allen Oberflaechen - deshalb hier,
    an einer Stelle.
    """
    steps = ["die erzeugten Dateien", "die Umbenennung", "die Tags"]
    if moved:
        steps.insert(0, "das Verschieben")
    return "erst " + ", dann ".join(steps)


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


def release_place(entry: Entry) -> Optional[tuple[Path, Path]]:
    """Wo der Releaseordner nach der Ruecknahme liegt - und wo jetzt.

    Rueckgabe ``(danach, jetzt)``, ``None`` bei Tag-Laeufen oder wenn sich
    der Ordner nicht ausmachen laesst. Gebraucht von den Oberflaechen: Sie
    zeigen nach der Ruecknahme den Ordner, in dem das Release wieder liegt,
    statt zur Wurzel zu springen.

    Beim Umbenennen traegt der Eintrag den *neuen* Ordnernamen; die
    Bewegung mit diesem Ziel ist die des Wurzelordners. Wurde er nicht
    umbenannt (nur Dateien), ist es der Ordner dieses Namens ueber den
    Dateien.
    """
    if entry.kind is Kind.CREATED:
        # Die Dateien liegen im Releaseordner oder einem CD-Ordner darin
        for file in entry.created:
            for parent in Path(file).parents:
                if parent.name == entry.release:
                    return parent, parent
        return None
    if entry.kind is Kind.TAGS or not entry.moves:
        return None
    if entry.kind is Kind.MOVE:
        src, dst = entry.moves[-1]
        return Path(src), Path(dst)
    for src, dst in entry.moves:
        if Path(dst).name == entry.release:
            return Path(src), _forward(Path(src), entry.moves)
    for parent in Path(entry.moves[0][0]).parents:
        if parent.name == entry.release:
            return parent, parent
    return None


def check(entry: Entry) -> list[str]:
    """Was einer Ruecknahme im Weg steht - leere Liste heisst: sie kann laufen."""
    if entry.kind is Kind.TAGS:
        return [f"nicht mehr vorhanden: {file}"
                for file in entry.tags if not Path(file).is_file()]
    if entry.kind is Kind.CREATED:
        # Nichts haelt die Ruecknahme auf: Was fehlt, ist schon weg, und was
        # veraendert wurde, bleibt liegen (siehe changed_files). Sonst
        # blockierte eine von Hand ergaenzte .nfo die Ruecknahme von
        # Umbenennung und Tags dahinter.
        return []

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
    if entry.kind is Kind.CREATED:
        done = _remove_created(entry)
        _forget(entry, path)
        return done

    from .output import move_path

    done: list[tuple[Path, Path]] = []
    for src, dst in reversed(entry.moves):
        origin, target = Path(src), Path(dst)
        if not target.exists():
            continue
        origin.parent.mkdir(parents=True, exist_ok=True)
        # Ein Verschieben kann ueber Dateisystemgrenzen gegangen sein (zwei
        # Volumes im Container) - dann geht der Rueckweg nur per Kopie.
        move_path(target, origin)
        done.append((target, origin))

    _forget(entry, path)
    return done


def _forget(entry: Entry, path: Optional[Path]) -> None:
    with _LOCK:
        remaining = [e for e in load(path) if e.timestamp != entry.timestamp]
        try:
            save(remaining, path)
        except OSError:
            pass


def _remove_created(entry: Entry) -> list[tuple[Path, Path]]:
    """Entfernt die erzeugten Dateien, die noch so aussehen wie angelegt.

    Zurueckgegeben wird (Datei, Datei) je entfernter Datei. Fehlende und
    veraenderte fehlen in der Liste - der Aufrufer erfaehrt sie ueber
    :func:`changed_files`, bevor er zuruecknimmt.
    """
    done: list[tuple[Path, Path]] = []
    for file, digest in entry.created.items():
        target = Path(file)
        try:
            if not target.is_file() or fingerprint(target) != digest:
                continue
            target.unlink()
        except OSError:
            continue
        done.append((target, target))
    return done


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
