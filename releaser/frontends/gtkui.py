"""GTK4-Oberfläche.

Reine Darstellung. Jede Entscheidung - was geladen ist, welcher Knopf
benutzbar ist, was ein Klick bewirkt - steht in :mod:`releaser.uistate` und
ist dort ohne Grafikumgebung geprüft. Hier stehen nur Widgets und die
Übersetzung zwischen ihnen und dem Zustand.

Das Modul lässt sich auch ohne GTK importieren: ``is_available()`` sagt, ob
die Bibliothek da ist, und ``main()`` gibt einen verständlichen Hinweis
statt eines Traceback. Sonst könnte man das Paket auf einem Server ohne
Grafikstack nicht einmal einlesen.

Aufbau des Fensters::

    +----------------------------------------------------------+
    | Kopfleiste: Öffnen  Vorlage  |  Tags  Umbenennen  Erzeugen|
    +--------------------+-------------------------------------+
    | Auswahl            | Felder, nach Verwendung gruppiert    |
    | (Baum links)       | mit Breite, Zeichenzähler, Herkunft  |
    +--------------------+-------------------------------------+
    | Statuszeile        | Meldungen (aufklappbar)              |
    +----------------------------------------------------------+
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from ..browse import Entry, Kind, LocalSource
from ..fields import FieldView
from ..naming import NamingProfile, Scope, format_plan as format_rename_plan
from ..text import CharCase
from ..tagwriter import format_plan as format_tag_plan
from ..uistate import Action, AppState, Level

APP_ID = "de.uniprojekt.mp3releaser"

#: Symbol je Eintragsart in der Auswahl.
KIND_ICONS = {
    Kind.RELEASE: "folder-music-symbolic",
    Kind.DIRECTORY: "folder-symbolic",
    Kind.AUDIO: "audio-x-generic-symbolic",
    Kind.COMPANION: "text-x-generic-symbolic",
    Kind.COVER: "image-x-generic-symbolic",
    Kind.CUE: "text-x-generic-symbolic",
    Kind.OTHER: "text-x-generic-symbolic",
}

LEVEL_PREFIX = {Level.INFO: "", Level.WARNING: "! ", Level.ERROR: "x "}

#: Reihenfolge der Schreibweisen in den Auswahlfeldern.
CASE_NAMES = ["unchanged", "lower", "upper", "capitalize"]




def _probe() -> tuple[bool, str]:
    try:
        import gi
    except ImportError as exc:
        return False, f"PyGObject fehlt ({exc})"
    try:
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        assert Gtk is not None          # nur die Verfuegbarkeit pruefen
    except (ValueError, ImportError) as exc:
        return False, f"GTK 4 nicht verfügbar ({exc})"
    return True, ""


GTK_AVAILABLE, GTK_ERROR = _probe()


def is_available() -> bool:
    return GTK_AVAILABLE


def requirements_hint() -> str:
    return (
        f"Die grafische Oberfläche steht nicht zur Verfügung: {GTK_ERROR}\n"
        "Benötigt werden GTK 4 und PyGObject, etwa unter Debian/Ubuntu:\n"
        "    apt install python3-gi gir1.2-gtk-4.0\n"
        "Die Kommandozeile funktioniert ohne beides:\n"
        "    python3 -m releaser wizard <verzeichnis> <vorlage.skl>"
    )


if GTK_AVAILABLE:  # pragma: no cover - braucht eine Grafikumgebung
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    def guarded(method):
        """Fängt Ausnahmen aus Ereignisbehandlern ab.

        Ohne das verschluckt GTK den Fehler: das Fenster bleibt stehen, ohne
        dass jemand erfährt, warum. Jetzt landet er in der Meldungsliste und
        zusätzlich auf der Standardfehlerausgabe, damit er beim Start aus
        einem Terminal sichtbar ist.
        """
        import functools
        import traceback

        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            try:
                return method(self, *args, **kwargs)
            except Exception as error:              # noqa: BLE001
                traceback.print_exc()
                self.state.say(f"{type(error).__name__}: {error}", Level.ERROR)
                try:
                    self.refresh()
                except Exception:                   # noqa: BLE001
                    traceback.print_exc()
                return None

        return wrapper


    class FieldRow:
        """Ein Feld: Beschriftung, Eingabe, Zähler, Herkunft."""

        def __init__(self, window: "ReleaserWindow", view: FieldView):
            self.window = window
            self.view = view

            self.multiline = view.spec.kind == "lines"
            if self.multiline:
                # Notizen und Gruppennachrichten sind mehrzeilig - eine
                # einzeilige Eingabe mit Ersatzzeichen war unbrauchbar.
                self.textview = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                             monospace=True)
                self.textview.get_buffer().set_text(view.value)
                self.entry = Gtk.ScrolledWindow(hexpand=True,
                                                min_content_height=90)
                self.entry.set_child(self.textview)
            else:
                self.textview = None
                self.entry = Gtk.Entry(hexpand=True)
                self.entry.set_text(view.value)
            if view.width and not self.multiline:
                # Die eigentliche Leistung der Vorlage: das Eingabefeld ist so
                # breit wie der Platz im NFO.
                self.entry.set_width_chars(min(view.width, 60))
                self.entry.set_max_width_chars(min(view.width, 60))
            if view.width:
                self.entry.set_tooltip_text(
                    f"{view.width} Zeichen Platz in der Vorlage")
            if view.spec.hint and not self.multiline:
                self.entry.set_placeholder_text(view.spec.hint)

            self.counter = Gtk.Label(xalign=1.0)
            self.counter.add_css_class("dim-label")
            self.origin = Gtk.Label(label=view.origin_label, xalign=0.0)
            self.origin.add_css_class("dim-label")

            if self.multiline:
                self.textview.get_buffer().connect("changed", self._on_changed)
                focus = Gtk.EventControllerFocus()
                focus.connect("leave", lambda *_: self._commit())
                self.textview.add_controller(focus)
            else:
                self.entry.connect("changed", self._on_changed)
                self.entry.connect("activate", self._commit)
                focus = Gtk.EventControllerFocus()
                focus.connect("leave", lambda *_: self._commit())
                self.entry.add_controller(focus)

            self._update_counter()

        def text(self) -> str:
            if self.multiline:
                buffer = self.textview.get_buffer()
                return buffer.get_text(buffer.get_start_iter(),
                                       buffer.get_end_iter(), False)
            return self.entry.get_text()

        def set_text(self, value: str) -> None:
            if self.multiline:
                self.textview.get_buffer().set_text(value)
            else:
                self.entry.set_text(value)

        # -- Anzeige -------------------------------------------------------

        def _update_counter(self) -> None:
            length = len(self.text())
            if self.view.width:
                self.counter.set_text(f"{length}/{self.view.width}")
                too_long = length > self.view.width
                self.counter.set_tooltip_text(
                    "wird im NFO abgeschnitten" if too_long else "")
                target = self.textview if self.multiline else self.entry
                for widget in (target, self.counter):
                    if too_long:
                        widget.add_css_class("error")
                    else:
                        widget.remove_css_class("error")
            else:
                self.counter.set_text(str(length) if length else "")

        def _on_changed(self, *_args) -> None:
            self._update_counter()

        def _commit(self, *_args) -> None:
            # Wird das Formular gerade abgeraeumt, ist dieses Widget bereits
            # auf dem Weg nach draussen. Dann darf nichts mehr geschrieben
            # werden, sonst baut sich das Formular aus sich selbst heraus neu.
            if self.window._rebuilding:
                return

            self.window._skip_form = True
            try:
                self._write_back()
            finally:
                self.window._skip_form = False

        def _write_back(self) -> None:
            if not self.window.state.set_field(self.view.spec.name, self.text()):
                # Abgelehnt - alten Wert zurückschreiben, damit Anzeige und
                # Modell nicht auseinanderlaufen.
                self.set_text(self.view.value)
            else:
                # Herkunft direkt an dieser Zeile nachziehen, statt das ganze
                # Formular neu zu bauen.
                from ..provenance import Origin

                origin = self.window.state.origins.get(self.view.spec.name)
                if origin is not Origin.UNKNOWN:
                    self.origin.set_text(origin.label)
            self._update_counter()

    class ReleaserWindow(Gtk.ApplicationWindow):
        def __init__(self, application: Gtk.Application, state: AppState):
            super().__init__(application=application, title="mp3releaser",
                             default_width=1100, default_height=720)
            self.state = state
            self.state.on_change = self.refresh
            self.buttons: dict[Action, Gtk.Button] = {}
            #: was zuletzt in die Liste gezeichnet wurde
            self._rendered: Optional[tuple] = None
            #: laeuft gerade ein Neuaufbau des Formulars?
            self._rebuilding = False
            #: waehrend einer Feldaenderung darf das Formular nicht neu
            #: gebaut werden - siehe _refresh_form
            self._skip_form = False
            #: Referenzen auf die Zeilen, damit sie nicht eingesammelt werden
            self.rows: list = []

            self.set_titlebar(self._build_header())

            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            self.set_child(outer)

            paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,
                              position=340, vexpand=True)
            paned.set_start_child(self._build_browser())
            paned.set_end_child(self._build_form())
            outer.append(paned)
            outer.append(self._build_footer())

            self.state.show_roots()
            self.refresh()

        # ------------------------------------------------------ Aufbau

        def _build_header(self) -> Gtk.HeaderBar:
            header = Gtk.HeaderBar()

            open_button = Gtk.Button(label="Einlesen")
            open_button.connect("clicked", self._on_load)
            header.pack_start(open_button)
            self.buttons[Action.OPEN] = open_button

            template_button = Gtk.Button(label="Vorlage…")
            template_button.connect("clicked", self._on_choose_template)
            header.pack_start(template_button)

            save_button = Gtk.Button(icon_name="document-save-symbolic")
            save_button.set_tooltip_text(
                "Vorlage, Muster und Schreibweisen als Standard speichern")
            save_button.connect("clicked", self._on_save_defaults)
            header.pack_start(save_button)

            undo_button = Gtk.Button(icon_name="edit-undo-symbolic")
            undo_button.set_tooltip_text(
                "Letzte Umbenennung oder letzten Tag-Lauf zuruecknehmen")
            undo_button.connect("clicked", self._on_undo)
            header.pack_start(undo_button)

            check_button = Gtk.Button(label="Prüfen")
            check_button.set_tooltip_text("Das eingelesene Release pruefen")
            check_button.connect("clicked", self._on_check_release)
            header.pack_end(check_button)

            for action, handler in (
                (Action.BUILD, self._on_build),
                (Action.PREVIEW_RENAME, self._on_rename),
                (Action.PREVIEW_TAGS, self._on_tags),
            ):
                button = Gtk.Button(label=action.label.replace(" vorschauen", "…"))
                button.connect("clicked", handler)
                header.pack_end(button)
                self.buttons[action] = button

            return header

        def _build_browser(self) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                          margin_top=6, margin_bottom=6,
                          margin_start=6, margin_end=6)

            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            up = Gtk.Button(icon_name="go-up-symbolic")
            up.connect("clicked", lambda *_: self.state.go_up())
            top.append(up)
            self.path_label = Gtk.Label(xalign=0.0, hexpand=True,
                                        ellipsize=3)  # PANGO_ELLIPSIZE_END
            top.append(self.path_label)
            box.append(top)

            self.listbox = Gtk.ListBox()
            # Ohne das loest schon ein einfacher Klick "row-activated" aus -
            # man waehlt dann nicht aus, sondern oeffnet sofort.
            self.listbox.set_activate_on_single_click(False)
            self.listbox.connect("row-activated", self._on_row_activated)
            self.listbox.connect("row-selected", self._on_row_selected)
            scroller = Gtk.ScrolledWindow(vexpand=True)
            scroller.set_child(self.listbox)
            box.append(scroller)

            self.scope_label = Gtk.Label(xalign=0.0, wrap=True)
            self.scope_label.add_css_class("dim-label")
            box.append(self.scope_label)
            return box

        def _build_form(self) -> Gtk.Widget:
            self.form_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                    spacing=12, margin_top=12, margin_bottom=12,
                                    margin_start=12, margin_end=12)
            fields = Gtk.ScrolledWindow(vexpand=True)
            fields.set_child(self.form_box)

            notebook = Gtk.Notebook()
            notebook.append_page(fields, Gtk.Label(label="Felder"))
            notebook.append_page(self._build_names(), Gtk.Label(label="Namen"))
            notebook.append_page(self._build_nfo(), Gtk.Label(label="NFO"))
            return notebook

        def _build_nfo(self) -> Gtk.Widget:
            """Die fertige .nfo, die sich beim Tippen mitaendert."""
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                          margin_top=12, margin_bottom=12,
                          margin_start=12, margin_end=12)

            self.nfo_view = Gtk.TextView(editable=False, monospace=True,
                                         cursor_visible=False)
            # Kein Zeilenumbruch: die Vorlage ist spaltengenau, ein Umbruch
            # wuerde den ASCII-Rahmen zerreissen.
            self.nfo_view.set_wrap_mode(Gtk.WrapMode.NONE)
            scroller = Gtk.ScrolledWindow(vexpand=True)
            scroller.set_child(self.nfo_view)
            box.append(scroller)

            bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            self.nfo_status = Gtk.Label(xalign=0.0, wrap=True, hexpand=True)
            self.nfo_status.add_css_class("dim-label")
            bottom.append(self.nfo_status)

            check = Gtk.Button(label="Vorlage prüfen")
            check.set_tooltip_text(
                "Prüft die geladene .skl auf zu schmale Felder, fehlende Tags "
                "und Tippfehler")
            check.connect("clicked", self._on_check_template)
            bottom.append(check)
            box.append(bottom)
            return box

        def _build_names(self) -> Gtk.Widget:
            """Reiter mit den Namensmustern und der Vorschau."""
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10,
                          margin_top=12, margin_bottom=12,
                          margin_start=12, margin_end=12)

            grid = Gtk.Grid(column_spacing=10, row_spacing=6)
            self.pattern_entries: dict[str, Gtk.Entry] = {}
            rows = (
                ("dir", "Verzeichnismuster", self.state.naming.dir_pattern),
                ("file", "Dateimuster", self.state.naming.file_pattern),
                ("group", "Gruppe", self.state.naming.group),
            )
            for index, (key, label, value) in enumerate(rows):
                entry = Gtk.Entry(hexpand=True, text=value)
                entry.connect("activate", self._on_pattern, key)
                focus = Gtk.EventControllerFocus()
                focus.connect("leave", lambda *_a, k=key: self._on_pattern(
                    self.pattern_entries[k], k))
                entry.add_controller(focus)
                grid.attach(Gtk.Label(label=label, xalign=0.0), 0, index, 1, 1)
                grid.attach(entry, 1, index, 1, 1)
                self.pattern_entries[key] = entry

            # Verzeichnis und Dateien getrennt: in der Szene ist der Ordner
            # oft gross und die Dateien klein geschrieben.
            self.case_dropdowns: dict[str, Gtk.DropDown] = {}
            for offset, (key, label, scope) in enumerate(
                    (("case_dir", "Schreibweise Verzeichnis", Scope.DIRECTORY),
                     ("case_file", "Schreibweise Dateien", Scope.FILENAME))):
                dropdown = Gtk.DropDown.new_from_strings(CASE_NAMES)
                # Aus dem Zustand ablesen statt festzulegen - sonst zeigt die
                # Auswahl etwas anderes an, als tatsaechlich gilt.
                current = self.state.naming.charcase.get(
                    scope, CharCase.UNCHANGED).value
                dropdown.set_selected(CASE_NAMES.index(current))
                dropdown.connect("notify::selected", self._on_case, key)
                grid.attach(Gtk.Label(label=label, xalign=0.0),
                            0, 3 + offset, 1, 1)
                grid.attach(dropdown, 1, 3 + offset, 1, 1)
                self.case_dropdowns[key] = dropdown

            self.prefix_check = Gtk.CheckButton(
                label="Begleitdateien mit „00-“ beginnen "
                      "(.nfo, .sfv, .m3u und Bild)")
            self.prefix_check.set_active(
                bool(self.state.naming.companion_prefix))
            self.prefix_check.connect("toggled", self._on_prefix)
            grid.attach(self.prefix_check, 1, 5, 1, 1)
            box.append(grid)

            hint = Gtk.Label(
                label="Verfügbare Tags: #Artist #Album #Year #Source #Fmt "
                      "#Grp #Typ #Catnr · Dateien: #N #Trk #Cd\n"
                      "#Fmt setzt FLAC, AAC oder ATMOS ein - bei MP3 nichts.\n"
                      "Ein Verzeichnisname ohne Tags wird wörtlich übernommen.",
                xalign=0.0, wrap=True)
            hint.add_css_class("dim-label")
            box.append(hint)

            box.append(Gtk.Separator())

            dir_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            dir_box.append(Gtk.Label(label="Verzeichnis", xalign=0.0))
            self.dirname_entry = Gtk.Entry(hexpand=True)
            self.dirname_entry.set_tooltip_text(
                "Von Hand änderbar - der Text wird wörtlich übernommen")
            self.dirname_entry.connect("activate", self._on_dirname)
            dir_box.append(self.dirname_entry)
            box.append(dir_box)

            self.companions_label = Gtk.Label(xalign=0.0, wrap=True)
            self.companions_label.add_css_class("dim-label")
            box.append(self.companions_label)

            self.names_view = Gtk.TextView(editable=False, monospace=True,
                                           cursor_visible=False)
            scroller = Gtk.ScrolledWindow(vexpand=True, min_content_height=220)
            scroller.set_child(self.names_view)
            box.append(scroller)
            return box

        def _build_footer(self) -> Gtk.Widget:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                          margin_start=12, margin_end=12, margin_bottom=8)
            self.status_label = Gtk.Label(xalign=0.0)
            box.append(self.status_label)

            self.messages_view = Gtk.TextView(editable=False, monospace=True,
                                              cursor_visible=False)
            scroller = Gtk.ScrolledWindow(min_content_height=120)
            scroller.set_child(self.messages_view)
            expander = Gtk.Expander(label="Meldungen")
            expander.set_child(scroller)
            box.append(expander)
            self.messages_expander = expander
            return box

        # --------------------------------------------------- Aktualisieren

        def refresh(self) -> None:
            self._refresh_browser()
            self._refresh_form()
            self._refresh_names()
            self._refresh_nfo()
            self._refresh_footer()
            self._refresh_actions()

        def _refresh_names(self) -> None:
            preview = self.state.preview_names()
            buffer = self.names_view.get_buffer()
            if preview["directory"] is None:
                self.dirname_entry.set_text("")
                buffer.set_text("Kein Release geladen.")
                return

            old_dir, new_dir = preview["directory"]
            if not self.dirname_entry.has_focus():
                self.dirname_entry.set_text(new_dir)

            # Auch die Musterfelder nachziehen: wer den Verzeichnisnamen von
            # Hand setzt, aendert damit das Muster - das Feld zeigte sonst
            # weiter das alte an.
            for key, value in (("dir", self.state.naming.dir_pattern),
                               ("file", self.state.naming.file_pattern),
                               ("group", self.state.naming.group)):
                entry = self.pattern_entries[key]
                if not entry.has_focus() and entry.get_text() != value:
                    entry.set_text(value)

            companions = self.state.companion_preview()
            covers = self.state.covers()
            text = "Erzeugt: " + ", ".join(companions) if companions else ""
            if covers:
                text += f"   ·   Bild erkannt: {covers[0].name}"
            self.companions_label.set_text(text)

            width = max((len(old) for old, _ in preview["files"]), default=0)
            lines = [f"{old_dir}  ->  {new_dir}", ""]
            lines += [f"  {old.ljust(width)}  ->  {new}"
                      for old, new in preview["files"]]
            if preview["collisions"]:
                lines.append("")
                lines += [f"  Kollision: {name}"
                          for name in preview["collisions"]]
            buffer.set_text("\n".join(lines))

        def _refresh_actions(self) -> None:
            enabled = self.state.enabled()
            for action, value in enabled.items():
                button = self.buttons.get(action)
                if button is not None:
                    button.set_sensitive(value)
            build = self.buttons.get(Action.BUILD)
            if build is not None and not enabled.get(Action.BUILD):
                build.set_tooltip_text(
                    "Erst eine Vorlage laden - oder ein Release einlesen."
                    if self.state.template is None
                    else "Erst ein Release einlesen.")
            elif build is not None:
                build.set_tooltip_text(
                    "Erzeugt .nfo, .sfv und .m3u im Releaseverzeichnis")

        def _refresh_browser(self) -> None:
            self.path_label.set_text(self.state.current_path or "(Wurzel)")
            self.scope_label.set_text(
                f"Sichtbar: {self.state.source.description}")

            # Nur neu zeichnen, wenn sich der Inhalt geaendert hat. Sonst
            # verlöre ein Klick seine eigene Auswahl: Auswählen loest ein
            # Neuzeichnen aus, und das Neuzeichnen wirft die Auswahl weg.
            key = (self.state.current_path,
                   tuple(e.path for e in self.state.entries))
            if key == self._rendered:
                return
            self._rendered = key

            while (row := self.listbox.get_first_child()) is not None:
                self.listbox.remove(row)
            for entry in self.state.entries:
                self.listbox.append(self._entry_row(entry))

        def _entry_row(self, entry: Entry) -> Gtk.Widget:
            row = Gtk.ListBoxRow()
            row.entry = entry                      # für die Auswahl gemerkt
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          margin_top=4, margin_bottom=4,
                          margin_start=6, margin_end=6)
            box.append(Gtk.Image(icon_name=KIND_ICONS.get(entry.kind,
                                                          "text-x-generic-symbolic")))
            box.append(Gtk.Label(label=entry.name, xalign=0.0, hexpand=True,
                                 ellipsize=3))
            if entry.audio_files:
                count = Gtk.Label(label=f"{entry.audio_files}")
                count.add_css_class("dim-label")
                box.append(count)
            row.set_child(box)
            return row

        def _refresh_form(self) -> None:
            # Zwei Absicherungen gegen denselben Absturz: Wird das Formular
            # neu gebaut, waehrend ein Eingabefeld den Fokus hat, zerstoert
            # GTK dieses Widget - sein Fokus-Controller loest daraufhin
            # "leave" aus, das wieder hier landet. Ein Neuaufbau mitten im
            # Neuaufbau greift auf bereits freigegebene Widgets zu und laesst
            # das Programm abstuerzen, nicht bloss eine Ausnahme werfen.
            if self._rebuilding:
                return
            # Eine reine Wertaenderung aendert weder Gruppen noch Breiten -
            # das Formular muss dafuer gar nicht neu gebaut werden.
            if self._skip_form:
                return

            self._rebuilding = True
            try:
                self._build_form_contents()
            finally:
                self._rebuilding = False

        def _build_form_contents(self) -> None:
            self.rows = []
            while (child := self.form_box.get_first_child()) is not None:
                self.form_box.remove(child)

            if self.state.release is None:
                placeholder = Gtk.Label(
                    label="Links einen Ordner wählen und auf „Einlesen“ klicken.")
                placeholder.add_css_class("dim-label")
                self.form_box.append(placeholder)
                return

            if self.state.template is None:
                hint = Gtk.Label(
                    label="Keine Vorlage geladen: ohne .skl entstehen nur "
                          ".sfv und .m3u, und die Feldbreiten fehlen. "
                          "Oben auf „Vorlage…“ klicken.",
                    xalign=0.0, wrap=True)
                hint.add_css_class("dim-label")
                self.form_box.append(hint)

            groups = self.state.field_groups()
            for title, views in groups:
                grid = Gtk.Grid(column_spacing=12, row_spacing=6,
                                margin_top=6, margin_start=6, margin_end=6)
                for index, view in enumerate(views):
                    row = FieldRow(self, view)
                    self.rows.append(row)
                    grid.attach(Gtk.Label(label=view.spec.label, xalign=0.0),
                                0, index, 1, 1)
                    grid.attach(row.entry, 1, index, 1, 1)
                    grid.attach(row.counter, 2, index, 1, 1)
                    grid.attach(row.origin, 3, index, 1, 1)

                expander = Gtk.Expander(label=f"{title} ({len(views)})")
                expander.set_child(grid)
                # Unbenutzte Felder bleiben sichtbar, aber eingeklappt - die
                # Vorlage kann sich jederzeit ändern. Ohne geladene Vorlage
                # steckt allerdings fast alles in dieser Gruppe, dann waere
                # Einklappen das Gegenteil von hilfreich.
                expander.set_expanded(title != "nicht verwendet"
                                      or self.state.template is None)
                self.form_box.append(expander)

        def _refresh_nfo(self) -> None:
            self.nfo_view.get_buffer().set_text(self.state.nfo_preview())

            if self.state.template is None or self.state.release is None:
                self.nfo_status.set_text("")
                return
            lines, width = self.state.nfo_dimensions()
            overflows = self.state.overflows()
            text = (f"{lines} Zeilen, breiteste {width} Zeichen · Vorlage: "
                    f"{self.state.template_path.name}")
            if overflows:
                text += f"   ·   {len(overflows)} Feld(er) werden abgeschnitten"
            cut = self.state.truncated_tracks()
            if cut:
                text += (f"   ·   {len(cut)} Tracktitel werden abgeschnitten "
                         "(die Vorlage hat keine Fortsetzungszeile)")
            self.nfo_status.set_text(text)

        def _refresh_footer(self) -> None:
            self.status_label.set_text(self.state.status())
            buffer = self.messages_view.get_buffer()
            buffer.set_text("\n".join(
                f"{LEVEL_PREFIX[m.level]}{m.text}" for m in self.state.messages))
            errors = sum(1 for m in self.state.messages if m.level is Level.ERROR)
            warnings = sum(1 for m in self.state.messages
                           if m.level is Level.WARNING)
            label = "Meldungen"
            if errors or warnings:
                label += f" ({errors} Fehler, {warnings} Hinweise)"
            self.messages_expander.set_label(label)
            if errors:
                self.messages_expander.set_expanded(True)

        # ------------------------------------------------------ Ereignisse

        @guarded
        def _on_row_selected(self, _listbox, row) -> None:
            entry = getattr(row, "entry", None) if row is not None else None
            self.state.selected_path = entry.path if entry is not None else None
            self._refresh_actions()

        def _selected_entry(self) -> Optional[Entry]:
            row = self.listbox.get_selected_row()
            return getattr(row, "entry", None) if row is not None else None

        @guarded
        def _on_row_activated(self, _listbox, row) -> None:
            entry = getattr(row, "entry", None)
            if entry is not None and entry.is_dir:
                self.state.navigate(entry.path)

        @guarded
        def _on_pattern(self, entry, key) -> None:
            value = entry.get_text()
            current = {"dir": self.state.naming.dir_pattern,
                       "file": self.state.naming.file_pattern,
                       "group": self.state.naming.group}[key]
            if value != current:
                self.state.set_pattern(key, value)

        @guarded
        def _on_case(self, dropdown, _param, key="case") -> None:
            self.state.set_pattern(key, CASE_NAMES[dropdown.get_selected()])

        @guarded
        def _on_prefix(self, check) -> None:
            self.state.set_companion_prefix(
                "00-" if check.get_active() else "", include_all=True)

        @guarded
        def _on_dirname(self, entry) -> None:
            self.state.set_literal_dirname(entry.get_text())

        @guarded
        def _on_check_release(self, *_args) -> None:
            report = self.state.check_release()
            if report is not None:
                _inform(self, "Release geprüft", report.render())
            self.refresh()

        @guarded
        def _on_undo(self, *_args) -> None:
            entry = self.state.undo_candidate()
            if entry is None:
                self.state.say("Nichts rückgängig zu machen.", Level.WARNING)
                self.refresh()
                return
            if entry.moves:
                detail = "\n".join(f"  {dst}\n     ->  {src}"
                                   for src, dst in entry.moves)
            else:
                # Pseudofelder wie "#containers" sind Buchhaltung, kein Tag
                detail = "\n".join(
                    f"  {Path(file).name}: "
                    + ", ".join(k for k in values if not k.startswith("#"))
                    for file, values in entry.tags.items())
            _confirm(self, "Zurücknehmen", entry.describe() + "\n\n" + detail,
                     lambda: self.state.undo_last())

        @guarded
        def _on_check_template(self, *_args) -> None:
            report = self.state.check_template()
            if report is None:
                self.refresh()
                return
            _inform(self, "Vorlage geprüft", report.render())

        @guarded
        def _on_save_defaults(self, *_args) -> None:
            """Speichert die aktuellen Einstellungen als Standard.

            Beim naechsten Start sind Vorlage, Muster, Gruppe und
            Schreibweisen gesetzt - kein Klicken mehr fuer eine Vorfuehrung.
            """
            target = save_defaults(self.state)
            self.state.say(f"Standard gespeichert: {target}")
            self.refresh()

        @guarded
        def _on_load(self, *_args) -> None:
            entry = self._selected_entry()
            if entry is None:
                self.state.say("Kein Ordner ausgewählt.", Level.WARNING)
                self.refresh()
                return
            self.state.load(entry.path)

        @guarded
        def _on_choose_template(self, *_args) -> None:
            def chosen(path: Optional[str]) -> None:
                if path:
                    self.state.load_template(path)

            _open_file_dialog(self, "SKL-Vorlage wählen", chosen)

        @guarded
        def _on_tags(self, *_args) -> None:
            plan = self.state.preview_tags()
            if plan is None or not plan.changes:
                self.refresh()
                return
            _confirm(self, "Tags schreiben",
                     format_tag_plan(plan, self.state.root),
                     lambda: self.state.apply_tags())

        @guarded
        def _on_rename(self, *_args) -> None:
            plan = self.state.preview_rename()
            if plan is None or not plan.changes:
                self.refresh()
                return
            text = format_rename_plan(plan, self.state.root)
            if not plan.is_safe:
                _inform(self, "Umbenennen nicht möglich", text)
                return
            def rename_then_hint():
                if self.state.apply_rename():
                    self.state.say("Umbenannt. Die Begleitdateien entstehen "
                                   "erst mit „Dateien erzeugen“.")
                    self.refresh()

            _confirm(self, "Umbenennen", text, rename_then_hint)

        @guarded
        def _on_build(self, *_args) -> None:
            created = self.state.build()
            if created:
                _inform(self, "Erzeugt",
                        "\n".join(str(p.name) for p in created))

    # ----------------------------------------------------------- Dialoge

    def _scrolled_text(text: str) -> Gtk.Widget:
        view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
        view.get_buffer().set_text(text)
        scroller = Gtk.ScrolledWindow(min_content_width=680,
                                      min_content_height=380)
        scroller.set_child(view)
        return scroller

    def _dialog(parent, title: str) -> Gtk.Window:
        window = Gtk.Window(transient_for=parent, modal=True, title=title,
                            default_width=720, default_height=460)
        return window

    def _inform(parent, title: str, text: str) -> None:
        window = _dialog(parent, title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        box.append(_scrolled_text(text))
        close = Gtk.Button(label="Schließen", halign=Gtk.Align.END)
        close.connect("clicked", lambda *_: window.close())
        box.append(close)
        window.set_child(box)
        window.present()

    def _confirm(parent, title: str, text: str, on_accept) -> None:
        """Zeigt den Plan und führt ihn erst auf Bestätigung aus."""
        window = _dialog(parent, title)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        box.append(_scrolled_text(text))

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                          halign=Gtk.Align.END)
        cancel = Gtk.Button(label="Abbrechen")
        cancel.connect("clicked", lambda *_: window.close())
        accept = Gtk.Button(label="Ausführen")
        accept.add_css_class("destructive-action")

        def run(*_args):
            window.close()
            on_accept()

        accept.connect("clicked", run)
        buttons.append(cancel)
        buttons.append(accept)
        box.append(buttons)
        window.set_child(box)
        window.present()

    def _open_file_dialog(parent, title: str, callback) -> None:
        """Dateiauswahl - GTK 4.10 brachte eine neue Schnittstelle mit."""
        if hasattr(Gtk, "FileDialog"):
            dialog = Gtk.FileDialog(title=title)

            def done(source, result):
                try:
                    chosen = source.open_finish(result)
                except GLib.Error:
                    return
                callback(chosen.get_path() if chosen else None)

            dialog.open(parent, None, done)
            return

        chooser = Gtk.FileChooserNative(title=title, transient_for=parent,
                                        action=Gtk.FileChooserAction.OPEN)

        def responded(source, response):
            if response == Gtk.ResponseType.ACCEPT:
                chosen = source.get_file()
                callback(chosen.get_path() if chosen else None)
            source.destroy()

        chooser.connect("response", responded)
        chooser.show()


# ------------------------------------------------------------- Einstiegspunkt


def run(state: Optional[AppState] = None) -> int:
    """Startet die Oberfläche. Setzt voraus, dass GTK vorhanden ist."""
    if not GTK_AVAILABLE:
        print(requirements_hint(), file=sys.stderr)
        return 3

    from gi.repository import Gio, Gtk

    app_state = state or AppState(source=LocalSource())
    application = Gtk.Application(application_id=APP_ID,
                                  flags=Gio.ApplicationFlags.FLAGS_NONE)

    def activate(app):
        ReleaserWindow(app, app_state).present()

    application.connect("activate", activate)
    return application.run([])


def main(argv: Optional[list[str]] = None) -> int:
    """Eigenständiger Einstiegspunkt, auch ohne die Kommandozeile nutzbar."""
    import argparse

    parser = argparse.ArgumentParser(prog="releaser-gui",
                                     description="mp3releaser, grafisch")
    parser.add_argument("--start", help="Startverzeichnis der Auswahl")
    parser.add_argument("--mounts", help="eingehaengte Verzeichnisse statt "
                                         "des ganzen Dateisystems")
    parser.add_argument("--template", help="SKL-Vorlage gleich laden")
    parser.add_argument("--group", help="Gruppenkuerzel")
    args = parser.parse_args(argv)

    if not GTK_AVAILABLE:
        print(requirements_hint(), file=sys.stderr)
        return 3

    state = build_state(start=args.start, mounts=args.mounts,
                        template=args.template, group=args.group)
    return run(state)


def save_defaults(state: AppState, path: Optional[Path] = None) -> Path:
    """Schreibt Vorlage, Muster, Gruppe und Schreibweisen als Standard.

    Ergaenzt die vorhandene Benutzerkonfiguration, statt sie zu ersetzen.
    Frueher entstand die Datei jedes Mal neu - ein von Hand gepflegter
    Abschnitt ``[tags]`` oder Schluessel wie ``audio_crc`` gingen beim
    Speichern verloren. Ohne GTK testbar.

    Ist die vorhandene Datei nicht lesbar, wird sie nicht ueberschrieben:
    der ``ConfigError`` geht an den Aufrufer, die Oberflaeche zeigt ihn an.
    """
    from ..config import Config, load, save, user_config_path

    target = Path(path) if path else user_config_path()
    config = load(target) if target.is_file() else Config()

    naming = state.naming
    config.naming = dict(config.naming)
    config.naming.update({
        "dir_pattern": naming.dir_pattern,
        "file_pattern": naming.file_pattern,
        "group": naming.group,
        "case_dir": naming.charcase.get(
            Scope.DIRECTORY, CharCase.UNCHANGED).value,
        "case_file": naming.charcase.get(
            Scope.FILENAME, CharCase.UNCHANGED).value,
        "companion_prefix": naming.companion_prefix,
        "prefix_all": ".sfv" in naming.prefixed_suffixes,
    })
    # case_dir/case_file stehen jetzt ausdruecklich da - ein allgemeines
    # "case" wuerde beim Lesen nicht mehr gebraucht, aber verwirren
    config.naming.pop("case", None)
    config.build = dict(config.build)
    if state.template_path:
        config.build["template"] = str(state.template_path)
    return save(config, target)


def build_state(start: Optional[str] = None, mounts: Optional[str] = None,
                template: Optional[str] = None,
                group: Optional[str] = None,
                config=None) -> AppState:
    """Baut den Anfangszustand - ohne GTK, deshalb auch hier testbar.

    Was nicht ausdruecklich uebergeben wird, kommt aus der gespeicherten
    Konfiguration. Beim Start ist damit alles gesetzt, was beim letzten Mal
    gespeichert wurde.
    """
    from ..browse import from_environment
    from ..config import load as load_config

    settings = config if config is not None else load_config()
    naming_cfg = settings.section("naming")
    build_cfg = settings.section("build")

    from ..service import (build_options_from_config, naming_from_config,
                           tags_from_config)

    source = from_environment(mounts) if mounts else LocalSource(start)
    profile = naming_from_config(settings, group=group or None)
    # [tags] und [build] gelten hier genauso wie auf der Kommandozeile -
    # frueher nahm die Desktop-Anwendung fest die Voreinstellungen.
    state = AppState(source=source, naming=profile,
                     tags=tags_from_config(settings),
                     build_options=build_options_from_config(settings))
    prefix = naming_cfg.get("companion_prefix", NamingProfile.companion_prefix)
    if prefix:
        state.set_companion_prefix(
            prefix, include_all=naming_cfg.get("prefix_all", True))

    from ..service import bundled_template

    # Reihenfolge: ausdruecklich angegeben, gespeichert, mitgeliefert. Ohne
    # die letzte Stufe waere "Vorlage waehlen" der erste Klick jeder
    # Vorfuehrung.
    chosen = template or build_cfg.get("template") or bundled_template()
    if chosen and Path(chosen).is_file():
        state.load_template(Path(chosen))
    elif chosen:
        state.say(f"Gespeicherte Vorlage nicht gefunden: {chosen}",
                  Level.WARNING)
    return state
