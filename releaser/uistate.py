"""Zustand und Aktionen einer grafischen Oberfläche.

Diese Schicht enthält alles, was ein Fenster tut - nur ohne Fenster: welcher
Ordner gerade offen ist, welches Release geladen wurde, welche Felder geändert
wurden, welche Schaltflächen benutzbar sind und was beim Klicken passiert.

Der Sinn ist derselbe wie bei :mod:`releaser.service`: Die Desktop-Anwendung
und die Weboberfläche sollen sich nicht nur ähnlich verhalten, sondern gleich.
Was hier nicht steht, driftet auseinander. Zusätzlich lässt sich das gesamte
Verhalten ohne Grafikumgebung prüfen - die GTK- beziehungsweise
Browser-Schicht darüber bleibt reine Darstellung.

Alles, was Daten verändert, läuft auch hier zweistufig: erst ein Plan, den
die Oberfläche anzeigt, dann die Ausführung auf ausdrückliche Anweisung.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from . import service
from .browse import AccessError, Entry, LocalSource, Source
from .fields import FieldView, build_views, group_views, overflow_warnings
from .model import Release
from .naming import NamingProfile, RenamePlan
from .provenance import OriginMap
from .skl import Template
from .tags import Settings
from .tagwriter import TagPlan, TagProfile


class Level(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Message:
    level: Level
    text: str


class Action(Enum):
    """Was die Oberfläche anbietet. Namen sind Schaltflächen."""

    OPEN = "open"
    RELOAD = "reload"
    PREVIEW_TAGS = "preview_tags"
    APPLY_TAGS = "apply_tags"
    PREVIEW_RENAME = "preview_rename"
    APPLY_RENAME = "apply_rename"
    BUILD = "build"

    @property
    def label(self) -> str:
        return {
            Action.OPEN: "Öffnen",
            Action.RELOAD: "Neu einlesen",
            Action.PREVIEW_TAGS: "Tags vorschauen",
            Action.APPLY_TAGS: "Tags schreiben",
            Action.PREVIEW_RENAME: "Umbenennen vorschauen",
            Action.APPLY_RENAME: "Umbenennen",
            Action.BUILD: "Dateien erzeugen",
        }[self]


@dataclass
class AppState:
    """Der gesamte Zustand eines Fensters."""

    source: Source = field(default_factory=LocalSource)
    naming: NamingProfile = field(default_factory=NamingProfile)
    tags: TagProfile = field(default_factory=TagProfile)
    build_options: service.BuildOptions = field(default_factory=service.BuildOptions)

    #: linke Seite
    current_path: Optional[str] = None
    entries: list[Entry] = field(default_factory=list)
    #: die angeklickte Zeile - getrennt vom geöffneten Verzeichnis, weil man
    #: einen Ordner auswählen kann, ohne ihn zu öffnen
    selected_path: Optional[str] = None

    #: rechte Seite
    release: Optional[Release] = None
    root: Optional[Path] = None
    origins: OriginMap = field(default_factory=OriginMap)
    template: Optional[Template] = None
    template_path: Optional[Path] = None

    #: geänderte Felder, solange nicht geschrieben
    modified: set[str] = field(default_factory=set)

    rename_plan: Optional[RenamePlan] = None
    tag_plan: Optional[TagPlan] = None

    messages: list[Message] = field(default_factory=list)

    #: "global" - jeder Eintrag im Protokoll ist zuruecknehmbar (eine Person
    #: am eigenen Rechner). "session" - nur, was diese Sitzung selbst getan
    #: hat (ein Dienst, den mehrere benutzen).
    undo_scope: str = "global"
    #: Zeitstempel der Protokolleintraege, die diese Sitzung angelegt hat
    own_entries: list[float] = field(default_factory=list)
    #: wird nach jeder Zustandsänderung gerufen - die Oberfläche zeichnet neu
    on_change: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------ Schreibrecht

    @property
    def writable(self) -> bool:
        """Darf im geoeffneten Release geschrieben werden?

        Ein Einhaengepunkt kann als nur lesend erklaert sein (``:ro``). Das
        muss die Anwendung selbst beachten: Der Kernel wuerde es zwar auch
        abweisen, aber erst mitten im Vorgang und mit einem Systemfehler -
        statt vorher, mit einer Meldung, die sagt, warum.
        """
        from .browse import MountedSource

        if not isinstance(self.source, MountedSource) or not self.current_path:
            return True
        try:
            return self.source.is_writable(self.current_path)
        except AccessError:
            return False

    def _refuse_if_readonly(self, what: str) -> bool:
        if self.writable:
            return False
        self.say(f"{what} nicht möglich: dieser Ordner ist nur lesend "
                 "eingehängt.", Level.ERROR)
        self._changed()
        return True

    # ------------------------------------------------------------- Meldungen

    def say(self, text: str, level: Level = Level.INFO) -> None:
        self.messages.append(Message(level, text))

    def clear_messages(self) -> None:
        self.messages.clear()

    @property
    def last_message(self) -> Optional[Message]:
        return self.messages[-1] if self.messages else None

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def _failed(self, what: str, error: Exception) -> None:
        """Meldet einen Fehler einer schreibenden Aktion.

        Ohne das landete etwa ein fehlendes Schreibrecht in der
        Weboberflaeche als nackter Serverfehler 500, und die Oberflaeche
        zeigte nur "Internal Server Error".
        """
        detail = str(error) or type(error).__name__
        self.say(f"{what} fehlgeschlagen: {detail}", Level.ERROR)
        self._changed()

    # ------------------------------------------------------------ Navigation

    def show_roots(self) -> list[Entry]:
        self.current_path = None
        self.selected_path = None
        self.entries = self.source.roots()
        self._changed()
        return self.entries

    def select(self, path: Optional[str]) -> None:
        """Merkt sich die angeklickte Zeile."""
        self.selected_path = path
        self._changed()

    def navigate(self, path: Optional[str]) -> list[Entry]:
        """Öffnet ein Verzeichnis in der Auswahl."""
        if path is None:
            return self.show_roots()
        try:
            self.entries = self.source.list(path)
            self.current_path = path
            self.selected_path = None
        except AccessError as exc:
            self.say(str(exc), Level.ERROR)
        self._changed()
        return self.entries

    def parent_path(self) -> Optional[str]:
        """Der übergeordnete Pfad, oder None an der Wurzel."""
        if not self.current_path:
            return None
        parent = self.current_path.rsplit("/", 1)[0]
        return None if parent == self.current_path else (parent or None)

    def go_up(self) -> list[Entry]:
        return self.navigate(self.parent_path())

    # --------------------------------------------------------------- Laden

    def load(self, path: str) -> bool:
        """Liest ein Release ein. Rückgabe sagt, ob es geklappt hat."""
        try:
            real = self.source.resolve(path)
        except AccessError as exc:
            self.say(str(exc), Level.ERROR)
            self._changed()
            return False

        try:
            outcome = service.scan(real)
        except Exception as exc:               # noqa: BLE001 - Anzeige statt Absturz
            self.say(f"{Path(real).name}: {exc}", Level.ERROR)
            self._changed()
            return False

        self.release = outcome.release
        self.root = outcome.root
        self.origins = outcome.origins
        self.current_path = path
        self.modified.clear()
        self.rename_plan = None
        self.tag_plan = None
        for warning in outcome.warnings:
            self.say(warning, Level.WARNING)
        self.say(f"{outcome.release.total_tracks} Track(s) eingelesen")
        self._changed()
        return True

    def reload(self) -> bool:
        return self.load(self.current_path) if self.current_path else False

    def load_template(self, path: str | Path) -> bool:
        try:
            self.template = Template.from_file(path)
            self.template_path = Path(path)
        except OSError as exc:
            self.say(f"Vorlage nicht lesbar: {exc}", Level.ERROR)
            self._changed()
            return False
        self.build_options.template = Path(path)
        self.say(f"Vorlage geladen: {Path(path).name}")
        self._changed()
        return True

    # --------------------------------------------------------------- Felder

    def field_views(self) -> list[FieldView]:
        if self.release is None:
            return []
        return build_views(self.release, template=self.template,
                           naming=self.naming, tags=self.tags,
                           origins=self.origins)

    def field_groups(self) -> list[tuple[str, list[FieldView]]]:
        return group_views(self.field_views())

    def overflows(self) -> list[str]:
        return overflow_warnings(self.field_views())

    def set_field(self, name: str, text: str) -> bool:
        """Übernimmt eine Eingabe aus der Oberfläche ins Modell."""
        from .fields import BY_NAME

        if self.release is None:
            return False
        spec = BY_NAME.get(name)
        if spec is None:
            self.say(f"unbekanntes Feld: {name}", Level.ERROR)
            return False

        value: object
        if spec.kind == "number":
            stripped = text.strip()
            if stripped and not stripped.isdigit():
                self.say(f"{spec.label}: {text!r} ist keine Zahl", Level.ERROR)
                self._changed()
                return False
            value = int(stripped) if stripped else None
        elif spec.kind == "lines":
            value = [line for line in text.split("\n") if line.strip()]
        else:
            value = text

        if getattr(self.release, name) == value:
            return True

        setattr(self.release, name, value)
        self.modified.add(name)
        self.origins.mark_manual(name)
        # Die Pläne beziehen sich auf den alten Stand und sind jetzt hinfällig.
        self.rename_plan = None
        self.tag_plan = None
        self._changed()
        return True

    @property
    def dirty(self) -> bool:
        return bool(self.modified)

    # ---------------------------------------------------------- Prüfungen

    def check_template(self):
        """Befund zur geladenen Vorlage, oder None ohne Vorlage."""
        from .checks import check_template

        if self.template is None:
            self.say("Erst eine Vorlage laden.", Level.WARNING)
            self._changed()
            return None
        source = self.template_path.name if self.template_path else "Vorlage"
        return check_template(self.template, source=source)

    def check_release(self):
        """Befund zum geladenen Release, oder None ohne Release."""
        from .checks import check_release

        if self.release is None or self.root is None:
            self.say("Erst ein Release einlesen.", Level.WARNING)
            self._changed()
            return None
        return check_release(self.release, self.root, naming=self.naming)

    # ------------------------------------------------------- Rückgängig

    def _remember(self, entry) -> None:
        if entry is not None:
            self.own_entries.append(entry.timestamp)

    def undo_entries(self) -> list:
        """Was diese Sitzung zuruecknehmen darf.

        Im Dienst nur die eigenen Laeufe - sonst saehe jeder Nutzer, was die
        anderen umbenannt haben, und koennte es zuruecknehmen.
        """
        from . import undo

        entries = undo.load()
        if self.undo_scope == "session":
            entries = [e for e in entries if e.timestamp in self.own_entries]
        return entries

    def undo_candidate(self):
        """Der Eintrag, den ``undo_last`` zuruecknehmen wuerde."""
        entries = self.undo_entries()
        return entries[-1] if entries else None

    def undo_last(self, force: bool = False) -> bool:
        """Nimmt die letzte Umbenennung zurück und liest neu ein."""
        from . import undo

        if self._refuse_if_readonly("Zurücknehmen"):
            return False
        entry = self.undo_candidate()
        if entry is None:
            self.say("Nichts rückgängig zu machen.", Level.WARNING)
            self._changed()
            return False

        problems = undo.check(entry)
        if problems and not force:
            for problem in problems:
                self.say(problem, Level.ERROR)
            self._changed()
            return False

        try:
            done = undo.undo(entry, force=force)
        except undo.UndoError as exc:
            self.say(str(exc), Level.ERROR)
            self._changed()
            return False
        except Exception as exc:                # noqa: BLE001 - Anzeige statt Absturz
            self._failed("Zurücknehmen", exc)
            return False

        if entry.timestamp in self.own_entries:
            self.own_entries.remove(entry.timestamp)
        self.say(f"{len(done)} {entry.kind.label} zurückgenommen.")

        if entry.kind is undo.Kind.TAGS:
            # Die Dateien liegen noch da, nur ihre Tags sind andere - neu
            # einlesen, damit die Felder den Stand der Dateien zeigen.
            if self.current_path:
                self.reload()
            else:
                self._changed()
            return True

        # Nach einer Umbenennung zeigt der Pfad ins Leere - zurueck zur Wurzel.
        self.release = None
        self.root = None
        self.current_path = None
        self.show_roots()
        return True

    # ----------------------------------------------------------- NFO-Vorschau

    def nfo_preview(self, width_marker: bool = False) -> str:
        """Die fertige .nfo, wie sie geschrieben würde.

        Rein rechnerisch - es wird nichts geschrieben. Gedacht für eine
        Anzeige, die sich beim Tippen mitändert: man sieht sofort, ob ein
        Wert in sein Feld passt.
        """
        if self.template is None:
            return ("Keine Vorlage geladen.\n\n"
                    "Ohne .skl-Vorlage gibt es keine .nfo - nur .sfv und .m3u.")
        if self.release is None:
            return "Kein Release geladen."
        return self.template.render(self.release, Settings())

    def truncated_tracks(self) -> list[str]:
        """Tracktitel, die in der .nfo abgeschnitten würden.

        Nur wenn die Vorlage keine Fortsetzungszeile hat - sonst bricht der
        Titel um und geht nicht verloren. ``overflows()`` deckt das nicht ab:
        es kennt nur die Kopfdaten, nicht die Trackliste.
        """
        if self.template is None or self.release is None:
            return []
        width, wraps = self.template.track_layout()
        if wraps or not width:
            return []

        from .tags import compose_track_title

        cut: list[str] = []
        for track in self.release.tracks:
            title = compose_track_title(track, Settings())
            if len(title) > width:
                cut.append(title)
        return cut

    def nfo_dimensions(self) -> tuple[int, int]:
        """(Zeilen, längste Zeile) der Vorschau - für die Statusanzeige."""
        text = self.nfo_preview()
        lines = text.split("\n")
        return len(lines), max((len(line) for line in lines), default=0)

    # -------------------------------------------------------- Namensvorschau

    def preview_names(self) -> dict:
        """Wie Verzeichnis und Dateien nach dem Umbenennen hießen.

        Rein rechnerisch, ohne etwas anzufassen - gedacht für eine Anzeige,
        die sich beim Tippen mitändert.
        """
        from .naming import release_dirname, track_stem

        if self.release is None:
            return {"directory": None, "files": [], "collisions": []}

        directory = release_dirname(self.release, self.naming)
        files: list[tuple[str, str]] = []
        # Je Verzeichnis, wie beim echten Plan: CD1/01-intro.mp3 und
        # CD2/01-intro.mp3 kollidieren nicht. Mehrere CUE-Tracks teilen sich
        # eine Datei und zaehlen nur einmal.
        seen: set[tuple[str, str]] = set()
        sources: set[str] = set()
        collisions: list[str] = []
        for disc in self.release.discs:
            for track in disc.tracks:
                if track.path and track.path in sources:
                    continue
                if track.path:
                    sources.add(track.path)
                suffix = Path(track.path).suffix.lower() if track.path else ""
                name = track_stem(self.release, track, disc, self.naming) + suffix
                old = Path(track.path).name if track.path else ""
                folder = str(Path(track.path).parent) if track.path else ""
                if (folder, name.lower()) in seen:
                    collisions.append(name)
                seen.add((folder, name.lower()))
                files.append((old, name))
        return {
            "directory": (self.root.name if self.root else "", directory),
            "files": files,
            "collisions": collisions,
        }

    def set_pattern(self, which: str, value: str) -> bool:
        """Ändert ein Namensmuster oder das Gruppenkürzel.

        ``which`` ist ``dir``, ``file``, ``group``, ``case``, ``case_dir``
        oder ``case_file``. Verzeichnis und Dateien haben getrennte
        Schreibweisen - in der Szene ist der Ordner oft groß und die Dateien
        klein geschrieben.

        Bestehende Pläne verfallen, weil sie sich auf die alten Regeln
        beziehen.
        """
        from dataclasses import replace

        from .naming import Scope
        from .text import CharCase

        from .naming import unknown_tags

        if which in ("dir", "file"):
            for tag in unknown_tags(value):
                self.say(f"{tag} ist kein bekannter Tag - er landet wörtlich "
                         "im Namen", Level.WARNING)

        try:
            if which == "dir":
                self.naming = replace(self.naming, dir_pattern=value)
            elif which == "file":
                self.naming = replace(self.naming, file_pattern=value)
            elif which == "group":
                self.naming = replace(self.naming, group=value)
            elif which in ("case", "case_dir", "case_file"):
                case = CharCase(value)
                scopes = {"case_dir": (Scope.DIRECTORY,),
                          "case_file": (Scope.FILENAME,)}.get(
                              which, (Scope.DIRECTORY, Scope.FILENAME))
                self.naming = replace(self.naming, charcase={
                    **self.naming.charcase,
                    **{scope: case for scope in scopes}})
            else:
                self.say(f"unbekanntes Muster: {which}", Level.ERROR)
                return False
        except ValueError as exc:
            self.say(str(exc), Level.ERROR)
            self._changed()
            return False

        self.rename_plan = None
        self._changed()
        return True

    def set_companion_prefix(self, prefix: str, include_all: bool = True) -> None:
        """Präfix für die erzeugten Dateien, z. B. ``00-``.

        ``include_all`` nimmt auch ``.sfv`` und ``.m3u`` mit. Ohne die Option
        gilt es nur für ``.nfo`` und Bilder - so hielt es das Original.
        """
        from dataclasses import replace

        suffixes = {".nfo", ".jpg", ".jpeg", ".png", ".pdf"}
        if include_all:
            suffixes |= {".sfv", ".m3u", ".m3u8"}
        self.naming = replace(self.naming, companion_prefix=prefix,
                              prefixed_suffixes=frozenset(suffixes))
        self.rename_plan = None
        self._changed()

    def companion_preview(self) -> list[str]:
        """Wie die erzeugten Begleitdateien heißen würden."""
        from .naming import companion_name

        if self.release is None:
            return []
        from .naming import future_companion_stem

        # Den kuenftigen Namen verwenden, nicht den aktuellen: beim Erzeugen
        # nach dem Umbenennen heissen die Dateien danach.
        stem = future_companion_stem(self.release, self.naming)
        suffixes = [".nfo", ".sfv", ".m3u"]
        covers = self.covers()
        if covers:
            suffixes.append(covers[0].suffix.lower())
        return [companion_name(self.release, suffix, self.naming, stem=stem)
                for suffix in suffixes]

    def covers(self) -> list[Path]:
        """Bilddateien im Releaseverzeichnis."""
        from .companions import find_covers

        return find_covers(self.root) if self.root else []

    def set_literal_dirname(self, name: str) -> bool:
        """Legt den Verzeichnisnamen von Hand fest.

        Umgesetzt als Muster ohne Tags - dann liefert die Regelkette genau
        diesen Namen. Die Zeichenregeln (verbotene Zeichen, Leerzeichen)
        greifen weiter, damit nichts Unmögliches herauskommt.
        """
        if not name.strip():
            self.say("Der Verzeichnisname darf nicht leer sein.", Level.ERROR)
            self._changed()
            return False
        if "#" in name:
            self.say("Der Name darf kein '#' enthalten - das wäre ein Tag.",
                     Level.ERROR)
            self._changed()
            return False
        return self.set_pattern("dir", name)

    # ---------------------------------------------------------------- Pläne

    def preview_tags(self) -> Optional[TagPlan]:
        if self.release is None:
            return None
        self.tag_plan = service.preview_tags(self.release, self.tags)
        for warning in self.tag_plan.warnings:
            self.say(warning, Level.WARNING)
        if not self.tag_plan.changes:
            self.say("Die Tags sind bereits so, wie sie sein sollen.")
        self._changed()
        return self.tag_plan

    def apply_tags(self) -> int:
        """Schreibt die Tags. Rückgabe ist die Anzahl geschriebener Dateien."""
        if self.release is None or self.tag_plan is None:
            return 0
        if self._refuse_if_readonly("Tags schreiben"):
            return 0
        from .tagwriter import apply_tags as write_plan

        plan = service.preview_tags(self.release, self.tags)
        try:
            written = write_plan(plan, self.tags)
        except Exception as exc:                # noqa: BLE001 - Anzeige statt Absturz
            # Ein Teil der Dateien kann schon geschrieben sein - Protokoll
            # und Groessen muessen trotzdem nachgezogen werden.
            self._remember(plan.journal)
            service.refresh_sizes(self.release)
            self._failed("Tags schreiben", exc)
            return 0
        self._remember(plan.journal)
        # Tags aendern die Dateigroesse - sonst stuende in der .nfo die alte
        service.refresh_sizes(self.release)
        self.say(f"{len(written)} Datei(en) geschrieben")
        self.tag_plan = None
        self.modified.clear()
        self._changed()
        return len(written)

    def preview_rename(self) -> Optional[RenamePlan]:
        if self.release is None or self.root is None:
            return None
        self.rename_plan = service.preview_rename(self.release, self.root,
                                                  self.naming)
        for warning in self.rename_plan.warnings:
            self.say(warning, Level.WARNING)
        for collision in self.rename_plan.collisions:
            self.say(collision, Level.ERROR)
        if not self.rename_plan.changes:
            self.say("Die Namen passen bereits.")
        self._changed()
        return self.rename_plan

    def apply_rename(self) -> bool:
        if self.release is None or self.root is None:
            return False
        if self._refuse_if_readonly("Umbenennen"):
            return False
        if self.rename_plan is None or not self.rename_plan.is_safe:
            self.say("Kein ausführbarer Umbenennungsplan.", Level.ERROR)
            self._changed()
            return False
        try:
            plan, new_root = service.perform_rename(self.release, self.root,
                                                    self.naming)
        except Exception as exc:                # noqa: BLE001 - Anzeige statt Absturz
            # apply_plan hat bereits zurueckgerollt; die Pfade im Modell
            # zeigen deshalb weiter auf die alten Namen.
            self._failed("Umbenennen", exc)
            return False
        if not plan.is_safe:
            # Zwischen Vorschau und Ausfuehrung hat sich etwas geaendert -
            # perform_rename hat dann nichts angefasst. Frueher meldete die
            # Oberflaeche trotzdem "ausgefuehrt".
            for collision in plan.collisions:
                self.say(collision, Level.ERROR)
            self.say("Nichts umbenannt - der Plan hat inzwischen Kollisionen.",
                     Level.ERROR)
            self.rename_plan = plan
            self._changed()
            return False
        self._remember(plan.journal)
        self.root = new_root
        try:
            self.current_path = self.source.to_virtual(new_root)
        except AccessError:
            self.current_path = str(new_root)
        self.rename_plan = None
        self.say(f"{len(plan.changes)} Umbenennung(en) ausgeführt - "
                 f"neuer Ordner: {new_root.name}")
        self._changed()
        return True

    def build(self) -> list[Path]:
        if self.release is None or self.root is None:
            return []
        if self._refuse_if_readonly("Dateien erzeugen"):
            return []
        options = self.build_options
        if options.nfo and options.template is None:
            self.say("Für die .nfo wird eine Vorlage gebraucht.", Level.ERROR)
            self._changed()
            return []
        try:
            outcome = service.build(self.release, self.root, options, self.naming)
        except Exception as exc:                # noqa: BLE001 - Anzeige statt Absturz
            self._failed("Dateien erzeugen", exc)
            return []
        for warning in outcome.warnings:
            self.say(warning, Level.WARNING)
        for path in outcome.removed:
            self.say(f"{path.name} entfernt")
        self.say(f"{len(outcome.created)} Datei(en) erzeugt")
        self._changed()
        return outcome.created

    # ------------------------------------------------ was gerade benutzbar ist

    def enabled(self) -> dict[Action, bool]:
        """Welche Schaltflächen aktiv sein dürfen.

        Die Oberfläche fragt das nach jeder Änderung ab und setzt die
        Empfindlichkeit ihrer Knöpfe danach. Dadurch steht die Regel an einer
        Stelle statt verteilt über Ereignisbehandler.
        """
        selected = self.selected_entry()
        loaded = self.release is not None
        # Vorschauen bleiben erlaubt - sie aendern nichts. Ausfuehren nicht.
        can_write = self.writable
        return {
            Action.OPEN: selected is not None and selected.is_dir,
            Action.RELOAD: self.current_path is not None,
            Action.PREVIEW_TAGS: loaded,
            Action.APPLY_TAGS: can_write and bool(self.tag_plan
                                                  and self.tag_plan.changes),
            Action.PREVIEW_RENAME: loaded,
            Action.APPLY_RENAME: can_write and bool(self.rename_plan
                                                    and self.rename_plan.changes
                                                    and self.rename_plan.is_safe),
            Action.BUILD: can_write and loaded and (
                self.template is not None or not self.build_options.nfo),
        }

    def selected_entry(self) -> Optional[Entry]:
        if self.selected_path is None:
            return None
        for entry in self.entries:
            if entry.path == self.selected_path:
                return entry
        return None

    def status(self) -> str:
        """Eine Zeile für die Statusleiste."""
        if self.release is None:
            return "Kein Release geladen"
        release = self.release
        parts = [
            release.release_name or "(ohne Namen)",
            f"{release.total_tracks} Tracks",
            f"{release.size_mb:.1f} MB",
        ]
        if release.multi_disc:
            parts.insert(1, f"{len(release.discs)} CDs")
        if not self.writable:
            parts.append("nur lesend")
        if self.dirty:
            parts.append(f"{len(self.modified)} Feld(er) geändert")
        uncertain = self.origins.uncertain()
        if uncertain:
            parts.append(f"{len(uncertain)} unsicher")
        return "  |  ".join(parts)
