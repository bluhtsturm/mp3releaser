"""Tests für die GTK-Schicht.

Zwei Ebenen:

* **ohne GTK** - das Modul muss sich auf einem Rechner ohne Grafikstack
  importieren lassen und einen verständlichen Hinweis geben.
* **mit GTK unter Xvfb** - das Fenster wird tatsächlich aufgebaut. Das prüft
  die GTK-Aufrufe selbst, die sonst erst beim ersten Start auffallen würden.
  Diese Tests laufen in einem Unterprozess, weil GTK ohne Display abstürzt
  und einen Absturz nicht als Ausnahme meldet.
"""

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.browse import Kind, LocalSource, MountedSource
from releaser.frontends import gtkui
from releaser.uistate import Level

ROOT = Path(__file__).resolve().parents[1]
HAS_FFMPEG = shutil.which("ffmpeg") is not None
HAS_XVFB = shutil.which("xvfb-run") is not None
CAN_RUN_GTK = gtkui.is_available() and HAS_XVFB

needs_gtk = pytest.mark.skipif(
    not CAN_RUN_GTK, reason="GTK 4 oder xvfb-run nicht vorhanden")
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


def run_in_display(script: str) -> subprocess.CompletedProcess:
    """Führt ein Skript unter einem virtuellen Display aus."""
    return subprocess.run(
        ["xvfb-run", "-a", sys.executable, "-c", textwrap.dedent(script)],
        capture_output=True, text=True, timeout=120,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "NO_AT_BRIDGE": "1"},
    )


@pytest.fixture
def release_tree(tmp_path: Path) -> Path:
    root = tmp_path / "eingang" / "Artist-Album-2026-GRP"
    root.mkdir(parents=True)
    for no in (1, 2):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"sine=frequency={400 + no * 50}:duration=1",
             "-c:a", "libmp3lame",
             "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
             "-metadata", "album=Das Album", "-metadata", f"track={no}/2",
             "-metadata", "date=2026", "-metadata", "genre=Electronic",
             str(root / f"0{no}-x.mp3"), "-y"], check=True)
    template = tmp_path / "vorlage.skl"
    template.write_bytes(("|#Release            |\n"
                          "|#Artist             |\n"
                          "|#Album   |\n"
                          "|#N #Trk             |\n").encode("cp437"))
    return tmp_path


# ============================================================== ohne Grafik


def test_module_imports_without_a_graphics_stack():
    """Auf einem Server ohne GTK muss das Paket trotzdem einlesbar sein."""
    assert hasattr(gtkui, "is_available")
    assert isinstance(gtkui.is_available(), bool)


def test_requirements_hint_is_helpful():
    hint = gtkui.requirements_hint()
    assert "GTK" in hint
    assert "apt install" in hint
    # Der Hinweis muss einen Weg zeigen, der ohne GTK funktioniert
    assert "wizard" in hint


def test_every_entry_kind_has_an_icon():
    for kind in Kind:
        assert kind in gtkui.KIND_ICONS


def test_every_message_level_has_a_prefix():
    for level in Level:
        assert level in gtkui.LEVEL_PREFIX


def test_build_state_defaults_to_the_whole_filesystem():
    state = gtkui.build_state()
    assert isinstance(state.source, LocalSource)


def test_build_state_with_mounts_is_restricted(tmp_path):
    (tmp_path / "ein").mkdir()
    state = gtkui.build_state(mounts=f"eingang:{tmp_path / 'ein'}")
    assert isinstance(state.source, MountedSource)
    assert state.source.names == ["eingang"]


def test_build_state_takes_group_and_template(tmp_path):
    template = tmp_path / "v.skl"
    template.write_bytes("#Artist   \n".encode("cp437"))
    state = gtkui.build_state(template=str(template), group="GRP")
    assert state.naming.group == "GRP"
    assert state.template is not None


def test_run_without_gtk_returns_a_clear_code(monkeypatch):
    monkeypatch.setattr(gtkui, "GTK_AVAILABLE", False)
    assert gtkui.run() == 3


def test_cli_gui_reports_missing_gtk(monkeypatch, capsys):
    from releaser import cli

    monkeypatch.setattr(gtkui, "GTK_AVAILABLE", False)
    monkeypatch.setattr(gtkui, "is_available", lambda: False)
    assert cli.main(["gui"]) == 3
    assert "GTK" in capsys.readouterr().err


# ======================================================= mit GTK unter Xvfb


@needs_gtk
@needs_ffmpeg
def test_window_builds_and_shows_the_release(release_tree):
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.naming import NamingProfile
        from releaser.uistate import Action, AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]),
            naming=NamingProfile(group="GRP"))
        state.load_template({str(release_tree / 'vorlage.skl')!r})

        app = Gtk.Application(application_id="de.test.window",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            print("ROOTS", [e.name for e in state.entries])
            state.navigate("eingang")
            state.load("eingang/Artist-Album-2026-GRP")
            print("TRACKS", state.release.total_tracks)
            print("GROUPS", [t for t, _ in state.field_groups()])
            print("APPLY_BEFORE", state.enabled()[Action.APPLY_RENAME])
            state.preview_rename()
            print("APPLY_AFTER", state.enabled()[Action.APPLY_RENAME])
            window.present()
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "ROOTS ['eingang']" in result.stdout
    assert "TRACKS 2" in result.stdout
    assert "nicht verwendet" in result.stdout
    assert "APPLY_BEFORE False" in result.stdout
    assert "APPLY_AFTER True" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_field_row_writes_through_and_rejects_bad_input(release_tree):
    """Die Eingabezeile schreibt ins Modell - und nimmt Unsinn nicht an."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import FieldRow, ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        state.load_template({str(release_tree / 'vorlage.skl')!r})

        app = Gtk.Application(application_id="de.test.fields",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")
            views = {{v.spec.name: v for v in state.field_views()}}

            artist = FieldRow(window, views["artist"])
            artist.entry.set_text("Von Hand")
            artist._commit()
            print("ARTIST", state.release.artist)
            print("ORIGIN", state.origins.get("artist").value)

            year = FieldRow(window, views["year"])
            year.entry.set_text("zweitausend")
            year._commit()
            print("YEAR", state.release.year)
            print("ENTRY_RESET", year.entry.get_text())

            # Zu langer Wert im engen Album-Feld muss auffallen
            album = FieldRow(window, views["album"])
            album.entry.set_text("Ein viel zu langer Albumtitel")
            print("COUNTER", album.counter.get_text())
            print("MARKED", album.counter.has_css_class("error"))
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "ARTIST Von Hand" in result.stdout
    assert "ORIGIN manual" in result.stdout
    assert "YEAR 2026" in result.stdout            # unveraendert
    assert "ENTRY_RESET 2026" in result.stdout     # Anzeige zurueckgesetzt
    assert "COUNTER 29/9" in result.stdout
    assert "MARKED True" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_dialogs_can_be_constructed(release_tree):
    """Die Planfenster müssen sich bauen lassen, bevor jemand darauf klickt."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends import gtkui
        from releaser.naming import NamingProfile
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]),
            naming=NamingProfile(group="GRP"))
        state.load_template({str(release_tree / 'vorlage.skl')!r})

        app = Gtk.Application(application_id="de.test.dialogs",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = gtkui.ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")

            gtkui._inform(window, "Hinweis", "eine Zeile\\nnoch eine")
            calls = []
            gtkui._confirm(window, "Bestaetigen", "Plan", lambda: calls.append(1))
            print("DIALOGS_OK")
            print("NOT_RUN_YET", calls == [])
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "DIALOGS_OK" in result.stdout
    assert "NOT_RUN_YET True" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_browser_rows_and_navigation(release_tree):
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        app = Gtk.Application(application_id="de.test.browser",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            rows = []
            child = window.listbox.get_first_child()
            while child is not None:
                rows.append(child.entry.name)
                child = child.get_next_sibling()
            print("ROWS", rows)

            first = window.listbox.get_first_child()
            window._on_row_activated(window.listbox, first)
            print("AFTER_ACTIVATE", state.current_path)

            window.listbox.select_row(window.listbox.get_first_child())
            window._on_load()
            print("LOADED", state.release is not None)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "ROWS ['eingang']" in result.stdout
    assert "AFTER_ACTIVATE eingang" in result.stdout
    assert "LOADED True" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_names_tab_shows_and_accepts_patterns(release_tree):
    """Der Reiter „Namen“ zeigt die Vorschau und nimmt Änderungen an."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.naming import NamingProfile
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]),
            naming=NamingProfile(group="GRP"))

        app = Gtk.Application(application_id="de.test.names",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")

            print("HASARROW", "->" in window.dir_line.get_text())
            print("DIRENTRY", window.dirname_entry.get_text())

            window.pattern_entries["file"].set_text("#N-#Trk")
            window._on_pattern(window.pattern_entries["file"], "file")
            stems = [row["entry"].get_text() for row in window.file_rows]
            print("SHORTNAME", "01-titel_1" in stems)

            window.dirname_entry.set_text("Von Hand")
            window._on_dirname(window.dirname_entry)
            print("MANUAL", window.dirname_entry.get_text())
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "HASARROW True" in result.stdout
    assert "DIRENTRY der_artist-das_album-2026-GRP" in result.stdout
    assert "SHORTNAME True" in result.stdout
    assert "MANUAL von_hand" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_names_tab_edits_file_names_by_hand(release_tree):
    """Jeder Dateiname lässt sich im Reiter „Namen“ von Hand überschreiben."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.naming import NamingProfile
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]),
            naming=NamingProfile(group="GRP"))

        app = Gtk.Application(application_id="de.test.filenames",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")
            rows = window.file_rows
            print("ROWS", len(rows) == len(state.release.tracks))
            first = rows[0]
            print("RESET_OFF", first["reset"].get_sensitive())

            first["entry"].set_text("01 Mein Titel - Teil_2.mp3")
            first["entry"].emit("activate")
            print("STEM", first["entry"].get_text())
            print("MODEL", state.release.tracks[0].manual_stem)
            print("MARK", first["mark"].get_text())
            print("RESET_ON", first["reset"].get_sensitive())
            print("SAME_WIDGET", window.file_rows[0]["entry"] is first["entry"])
            print("PLAN", any(new.endswith("01_mein_titel_-_teil_2.mp3")
                              or new.endswith("01_Mein_Titel_-_Teil_2.mp3")
                              for _, new in state.preview_names()["files"]))

            first["reset"].emit("clicked")
            print("AFTER_RESET", first["entry"].get_text(),
                  repr(state.release.tracks[0].manual_stem))
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "ROWS True" in result.stdout
    assert "RESET_OFF False" in result.stdout
    assert "STEM 01_Mein_Titel_-_Teil_2" in result.stdout
    assert "MODEL 01_Mein_Titel_-_Teil_2" in result.stdout
    assert "MARK von Hand" in result.stdout
    assert "RESET_ON True" in result.stdout
    assert "SAME_WIDGET True" in result.stdout
    assert "PLAN True" in result.stdout
    assert "AFTER_RESET 01-der_artist-titel_1 ''" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_multiline_field_round_trip(release_tree):
    """Notizen sind mehrzeilig - vorher war es eine einzeilige Eingabe."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import FieldRow, ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        app = Gtk.Application(application_id="de.test.notes",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")
            views = {{v.spec.name: v for v in state.field_views()}}

            row = FieldRow(window, views["notes"])
            print("MULTILINE", row.multiline)
            row.set_text("erste Zeile\\nzweite Zeile")
            row._commit()
            print("NOTES", state.release.notes)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "MULTILINE True" in result.stdout
    assert "NOTES ['erste Zeile', 'zweite Zeile']" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_handler_errors_become_messages(release_tree):
    """Ein Fehler im Ereignisbehandler darf das Fenster nicht lahmlegen."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.uistate import AppState, Level

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        app = Gtk.Application(application_id="de.test.errors",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")

            def boom():
                raise RuntimeError("absichtlich kaputt")
            state.preview_tags = boom

            window._on_tags()                      # darf nicht durchschlagen
            last = state.messages[-1]
            print("LEVEL", last.level.value)
            print("TEXT", last.text)
            print("ALIVE", window.get_sensitive())
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "LEVEL error" in result.stdout
    assert "absichtlich kaputt" in result.stdout
    assert "ALIVE True" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_editing_a_field_does_not_rebuild_the_form(release_tree):
    """Der Absturz beim Ändern eines Tags.

    Wurde das Formular bei jeder Wertänderung neu gebaut, zerstörte GTK das
    Eingabefeld, das gerade den Fokus hatte. Dessen Fokus-Controller löste
    daraufhin erneut aus und griff auf bereits freigegebene Widgets zu - das
    Programm stürzte ab, statt eine Ausnahme zu werfen.
    """
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        app = Gtk.Application(application_id="de.test.norebuild",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")

            rows_before = list(window.rows)
            row = next(r for r in window.rows if r.view.spec.name == "artist")
            row.set_text("Von Hand")
            row._commit()

            print("SAME_ROWS", window.rows is not None
                  and [id(r) for r in window.rows] == [id(r) for r in rows_before])
            print("VALUE", state.release.artist)
            print("ORIGIN_SHOWN", row.origin.get_text())
            print("NOT_REBUILDING", window._rebuilding is False)
            print("FLAG_RESET", window._skip_form is False)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "SAME_ROWS True" in result.stdout      # Widgets bleiben bestehen
    assert "VALUE Von Hand" in result.stdout
    assert "ORIGIN_SHOWN von Hand" in result.stdout
    assert "NOT_REBUILDING True" in result.stdout
    assert "FLAG_RESET True" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_commit_during_teardown_is_ignored(release_tree):
    """Ein Feld, das beim Abräumen noch „leave“ meldet, darf nichts schreiben."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        app = Gtk.Application(application_id="de.test.teardown",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")

            row = next(r for r in window.rows if r.view.spec.name == "artist")
            row.set_text("Waehrend des Abraeumens")

            window._rebuilding = True          # wie mitten im Neuaufbau
            row._commit()
            window._rebuilding = False

            print("UNCHANGED", state.release.artist)
            print("NOT_DIRTY", state.dirty is False)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "UNCHANGED Der Artist" in result.stdout
    assert "NOT_DIRTY True" in result.stdout


def test_build_state_reads_the_saved_defaults(tmp_path, monkeypatch):
    """Beim Start soll alles gesetzt sein, was zuletzt gespeichert wurde."""
    from releaser.config import Config, save
    from releaser.naming import Scope

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    template = tmp_path / "v.skl"
    template.write_bytes("#Artist   \n".encode("cp437"))
    save(Config(naming={"group": "TESTGRP", "case_dir": "upper",
                        "case_file": "lower", "companion_prefix": "00-",
                        "prefix_all": True},
                build={"template": str(template)}))

    state = gtkui.build_state()
    assert state.naming.group == "TESTGRP"
    assert state.naming.charcase[Scope.DIRECTORY].value == "upper"
    assert state.naming.charcase[Scope.FILENAME].value == "lower"
    assert state.naming.companion_prefix == "00-"
    assert ".sfv" in state.naming.prefixed_suffixes
    assert state.template is not None


def test_explicit_arguments_beat_the_saved_defaults(tmp_path, monkeypatch):
    from releaser.config import Config, save

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save(Config(naming={"group": "AUSDATEI"}))
    assert gtkui.build_state(group="VONHAND").naming.group == "VONHAND"


def test_missing_saved_template_is_reported(tmp_path, monkeypatch):
    """Gemeldet - und statt gar keiner die mitgelieferte Vorlage geladen."""
    from releaser.config import Config, save
    from releaser.service import bundled_template
    from releaser.uistate import Level

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save(Config(build={"template": str(tmp_path / "weg.skl")}))

    state = gtkui.build_state()
    warnings = [m.text for m in state.messages if m.level is Level.WARNING]
    assert any("weg.skl" in text for text in warnings), warnings
    assert state.template_path == bundled_template()


@needs_gtk
@needs_ffmpeg
def test_single_click_selects_and_does_not_open(release_tree):
    """Ein einfacher Klick löste zuvor schon „row-activated“ aus."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        app = Gtk.Application(application_id="de.test.click",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            print("SINGLE", window.listbox.get_activate_on_single_click())
            row = window.listbox.get_first_child()
            window.listbox.select_row(row)          # wie ein einfacher Klick
            print("PATH_AFTER_SELECT", state.current_path)
            print("SELECTED", state.selected_path)
            window._on_row_activated(window.listbox, row)   # Doppelklick
            print("PATH_AFTER_ACTIVATE", state.current_path)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "SINGLE False" in result.stdout
    assert "PATH_AFTER_SELECT None" in result.stdout      # nicht geoeffnet
    assert "SELECTED eingang" in result.stdout
    assert "PATH_AFTER_ACTIVATE eingang" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_saving_defaults_writes_a_config(release_tree, tmp_path):
    result = run_in_display(f"""
        import sys, os; sys.path.insert(0, {str(ROOT)!r})
        os.environ["XDG_CONFIG_HOME"] = {str(tmp_path)!r}
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.naming import NamingProfile
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]),
            naming=NamingProfile(group="GRP"))
        state.load_template({str(release_tree / 'vorlage.skl')!r})

        app = Gtk.Application(application_id="de.test.save",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            state.set_pattern("case_dir", "upper")
            state.set_pattern("case_file", "lower")
            state.set_companion_prefix("00-", include_all=True)
            state.navigate("eingang")
            window._on_save_defaults()
            print("MSG", state.messages[-1].text)
            # Die Bestaetigung ist ein Fenster - in der eingeklappten
            # Meldungsliste sah man sie vorher nicht
            titles = [w.get_title() for w in Gtk.Window.list_toplevels()]
            print("DIALOG", "Als Standard gespeichert" in titles)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr

    written = tmp_path / "mp3releaser" / "config.toml"
    assert written.is_file()

    from releaser.config import load

    config = load(written)
    assert config.naming["group"] == "GRP"
    assert config.naming["case_dir"] == "upper"
    assert config.naming["case_file"] == "lower"
    assert config.naming["prefix_all"] is True
    assert config.build["template"].endswith("vorlage.skl")
    assert config.gui["start"] == "eingang"
    assert "DIALOG True" in result.stdout


def test_desktop_preset_is_capitalized_directory_and_lowercase_files(monkeypatch,
                                                                     tmp_path):
    from releaser.naming import Scope

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    naming = gtkui.build_state().naming
    assert naming.charcase[Scope.DIRECTORY].value == "capitalize"
    assert naming.charcase[Scope.FILENAME].value == "lower"


@needs_gtk
@needs_ffmpeg
def test_case_dropdowns_show_what_actually_applies(release_tree):
    """Anzeige und Zustand dürfen nicht auseinanderlaufen."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import CASE_NAMES, ReleaserWindow
        from releaser.naming import NamingProfile, Scope
        from releaser.text import CharCase
        from releaser.uistate import AppState

        naming = NamingProfile(charcase={{
            Scope.DIRECTORY: CharCase.CAPITALIZE,
            Scope.FILENAME: CharCase.LOWER,
        }})
        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]),
            naming=naming)
        app = Gtk.Application(application_id="de.test.case",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            for key, scope in (("case_dir", Scope.DIRECTORY),
                               ("case_file", Scope.FILENAME)):
                shown = CASE_NAMES[window.case_dropdowns[key].get_selected()]
                print(key.upper(), shown,
                      state.naming.charcase[scope].value)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "CASE_DIR capitalize capitalize" in result.stdout
    assert "CASE_FILE lower lower" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_nfo_preview_follows_the_fields(release_tree):
    """Der Reiter „NFO“ zeigt die fertige Datei und ändert sich beim Tippen."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        state.load_template({str(release_tree / 'vorlage.skl')!r})

        app = Gtk.Application(application_id="de.test.nfo",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def text_of(window):
            return window.nfo_view.text

        def activate(a):
            window = ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")
            print("BEFORE", "Der Artist" in text_of(window))

            row = next(r for r in window.rows if r.view.spec.name == "artist")
            row.set_text("Ganz Anders")
            row._commit()
            print("AFTER", "Ganz Anders" in text_of(window))
            print("STATUS", window.nfo_status.get_text()[:40])
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "BEFORE True" in result.stdout
    assert "AFTER True" in result.stdout      # ohne Neuaufbau des Formulars
    assert "Zeilen" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_nfo_preview_without_a_template_explains_itself(release_tree):
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        app = Gtk.Application(application_id="de.test.nonfo",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            state.load("eingang/Artist-Album-2026-GRP")
            print("TEXT", window.nfo_view.text[:30])
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "Keine Vorlage geladen" in result.stdout


@needs_gtk
@needs_ffmpeg
def test_template_check_button_opens_a_report(release_tree):
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        app = Gtk.Application(application_id="de.test.lint",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            window._on_check_template()              # ohne Vorlage
            print("NOTEMPLATE", state.messages[-1].level.value)

            state.load_template({str(release_tree / 'vorlage.skl')!r})
            before = len(Gtk.Window.get_toplevels())
            window._on_check_template()
            print("OPENED", len(Gtk.Window.get_toplevels()) > before)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "NOTEMPLATE warning" in result.stdout
    assert "OPENED True" in result.stdout


# ------------------------------------------------ Korrekturen (Fehlerdurchsicht)


def test_save_defaults_keeps_the_rest_of_the_config(tmp_path, monkeypatch):
    """Speichern schrieb die Datei neu - [tags] und audio_crc gingen verloren."""
    from releaser.config import load

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    target = tmp_path / "mp3releaser" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text('[tags]\ncase = "capitalize"\n\n[build]\naudio_crc = true\n',
                      encoding="utf-8")

    state = gtkui.build_state()
    state.set_pattern("group", "NEU")
    assert gtkui.save_defaults(state) == target

    saved = load(target)
    assert saved.tags == {"case": "capitalize"}
    assert saved.build["audio_crc"] is True
    assert saved.naming["group"] == "NEU"


def test_desktop_reads_the_tags_and_build_sections():
    from releaser.config import parse

    config = parse('[tags]\ncase = "upper"\n\n[build]\naudio_crc = true\n'
                   'sfv_include = ["log"]\n')
    state = gtkui.build_state(config=config)
    assert state.tags.charcase.value == "upper"
    assert state.build_options.audio_crc is True
    assert state.build_options.sfv_include == ("log",)


def test_save_defaults_does_not_overwrite_a_broken_config(tmp_path, monkeypatch):
    from releaser.config import Config, ConfigError

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    target = tmp_path / "mp3releaser" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text("[naming\nkaputt", encoding="utf-8")

    state = gtkui.build_state(config=Config())
    with pytest.raises(ConfigError):
        gtkui.save_defaults(state)
    assert target.read_text(encoding="utf-8") == "[naming\nkaputt"


# ------------------------------------------ Standard speichern und laden


def _write_skl(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("#Artist   \n".encode("cp437"))
    return path


def test_saved_directory_is_opened_at_start(tmp_path, monkeypatch):
    from releaser.config import Config, save

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    eingang = tmp_path / "Musik" / "Eingang"
    (eingang / "Artist-Album-2026-GRP").mkdir(parents=True)
    save(Config(gui={"start": str(eingang)}))

    state = gtkui.build_state()
    state.show_start()
    assert state.listed_path == state.current_path == str(eingang)
    assert [e.name for e in state.entries] == ["Artist-Album-2026-GRP"]
    # "Nach oben" fuehrt aus dem Startverzeichnis heraus
    state.go_up()
    assert state.listed_path == str(eingang.parent)


def test_missing_saved_directory_falls_back_to_the_roots(tmp_path, monkeypatch):
    from releaser.config import Config, save

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    save(Config(gui={"start": str(tmp_path / "weg")}))

    state = gtkui.build_state()
    state.show_start()
    assert state.listed_path is None and state.current_path is None
    assert state.entries                                   # die Wurzeln
    assert any("Startverzeichnis" in m.text for m in state.messages
               if m.level is Level.WARNING)


def test_explicit_start_beats_the_saved_directory(tmp_path, monkeypatch):
    from releaser.config import Config, save

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    saved, given = tmp_path / "gespeichert", tmp_path / "angegeben"
    saved.mkdir()
    given.mkdir()
    save(Config(gui={"start": str(saved)}))

    state = gtkui.build_state(start=str(given))
    state.show_start()
    assert state.listed_path == str(given)


def test_without_a_saved_directory_the_roots_are_shown(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    state = gtkui.build_state()
    assert state.start_path is None
    state.show_start()
    assert state.listed_path is None and state.entries


def test_saving_at_the_roots_forgets_the_directory(tmp_path):
    from releaser.config import Config, load, save

    target = save(Config(gui={"start": str(tmp_path)}), tmp_path / "c.toml")
    state = gtkui.build_state(config=Config())
    state.show_roots()
    gtkui.save_defaults(state, target)
    assert "start" not in load(target).gui


@needs_ffmpeg
def test_saving_remembers_the_listed_directory_not_the_loaded_release(
        release_tree, tmp_path):
    """Nach dem Einlesen zeigt current_path auf das Release selbst. Beim
    naechsten Start soll aber der Ordner offen sein, in dem die Releases
    liegen - mit dem naechsten darin."""
    from releaser.config import Config, load

    eingang = release_tree / "eingang"
    state = gtkui.build_state(config=Config())
    state.navigate(str(eingang))
    assert state.load(str(eingang / "Artist-Album-2026-GRP"))
    assert state.current_path.endswith("Artist-Album-2026-GRP")

    target = gtkui.save_defaults(state, tmp_path / "c.toml")
    assert load(target).gui["start"] == str(eingang)


def test_saved_settings_survive_a_restart(tmp_path, monkeypatch):
    """Der ganze Weg: speichern, neu starten - alles wieder eingestellt."""
    from releaser.naming import Scope

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    own = _write_skl(tmp_path / "vorlagen" / "meine.skl")
    eingang = tmp_path / "Eingang"
    eingang.mkdir()

    state = gtkui.build_state()
    assert state.load_template(own)
    state.set_pattern("group", "MEINE")
    state.set_pattern("case_dir", "upper")
    state.set_pattern("case_file", "lower")
    state.set_pattern("dir", "#Artist-#Album-#Year-#Grp")
    state.navigate(str(eingang))
    gtkui.save_defaults(state)

    again = gtkui.build_state()
    again.show_start()
    assert again.template_path == own
    assert again.naming.group == "MEINE"
    assert again.naming.charcase[Scope.DIRECTORY].value == "upper"
    assert again.naming.charcase[Scope.FILENAME].value == "lower"
    assert again.naming.dir_pattern == "#Artist-#Album-#Year-#Grp"
    assert again.listed_path == str(eingang)
    assert not [m for m in again.messages if m.level is not Level.INFO]


def test_the_bundled_template_is_saved_by_name(tmp_path, monkeypatch):
    from releaser.config import load
    from releaser.service import bundled_template

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    state = gtkui.build_state()
    assert state.template_path == bundled_template()

    target = gtkui.save_defaults(state)
    assert load(target).build["template"] == "standard.skl"
    assert gtkui.build_state().template_path == bundled_template()


def test_the_bundled_template_is_found_in_the_next_appimage_mount(tmp_path,
                                                                  monkeypatch):
    """Das AppImage haengt sich bei jedem Start unter einem neuen Namen ein
    (/tmp/.mount_…). Ein gespeicherter Pfad dorthin zeigte beim naechsten
    Start ins Leere - die Vorlage fehlte."""
    import shutil as sh

    from releaser.service import bundled_template

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    standard = bundled_template()
    mounts = []
    for name in (".mount_abc", ".mount_xyz"):
        share = tmp_path / name / "usr" / "share" / "mp3releaser"
        share.mkdir(parents=True)
        sh.copy(standard, share / "standard.skl")
        mounts.append(tmp_path / name)

    monkeypatch.setenv("APPDIR", str(mounts[0]))
    state = gtkui.build_state()
    assert mounts[0] in state.template_path.parents
    gtkui.save_defaults(state)

    monkeypatch.setenv("APPDIR", str(mounts[1]))
    again = gtkui.build_state()
    assert mounts[1] in again.template_path.parents
    assert not [m for m in again.messages if m.level is Level.WARNING]


def test_own_template_is_saved_with_an_absolute_path(tmp_path, monkeypatch):
    from releaser.service import find_template, template_setting

    monkeypatch.chdir(tmp_path)
    _write_skl(tmp_path / "v.skl")
    assert template_setting("v.skl") == str(tmp_path / "v.skl")
    assert find_template(str(tmp_path / "v.skl")) == tmp_path / "v.skl"
    assert find_template(str(tmp_path / "fehlt.skl")) is None


def test_a_broken_config_does_not_prevent_the_start(tmp_path, monkeypatch):
    """Per Doppelklick gestartet gibt es kein Terminal fuer eine Meldung."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    target = tmp_path / "mp3releaser" / "config.toml"
    target.parent.mkdir(parents=True)
    target.write_text("[naming\nkaputt", encoding="utf-8")

    state = gtkui.build_state()
    errors = [m.text for m in state.messages if m.level is Level.ERROR]
    assert errors and "nicht lesbar" in errors[0]
    assert state.template is not None             # trotzdem arbeitsfaehig


def test_an_unusable_config_value_does_not_prevent_the_start(tmp_path,
                                                             monkeypatch):
    from releaser.config import Config, save

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save(Config(naming={"case_dir": "schraeg"}))

    state = gtkui.build_state()
    errors = [m.text for m in state.messages if m.level is Level.ERROR]
    assert errors and "schraeg" in errors[0]


def test_saving_goes_back_to_the_file_the_settings_came_from(tmp_path,
                                                             monkeypatch):
    """Eine mp3releaser.toml im Arbeitsverzeichnis gewinnt beim Start. Ging
    das Speichern nach ~/.config, war es beim naechsten Start verdeckt."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    work = tmp_path / "arbeit"
    work.mkdir()
    monkeypatch.chdir(work)
    (work / "mp3releaser.toml").write_text('[naming]\ngroup = "ALT"\n',
                                           encoding="utf-8")

    state = gtkui.build_state()
    assert state.config_path == work / "mp3releaser.toml"
    state.set_pattern("group", "NEU")
    assert gtkui.save_defaults(state) == work / "mp3releaser.toml"
    assert gtkui.build_state().naming.group == "NEU"
    assert not (tmp_path / "cfg" / "mp3releaser" / "config.toml").exists()


def test_cli_gui_hands_over_the_config_it_read(tmp_path, monkeypatch):
    """--config erreichte die Oberflaeche nicht - sie las selbst nach."""
    from releaser import cli

    captured = {}

    def fake_run(state=None):
        captured["state"] = state
        return 0

    monkeypatch.setattr(gtkui, "is_available", lambda: True)
    monkeypatch.setattr(gtkui, "run", fake_run)
    config = tmp_path / "eigen.toml"
    config.write_text('[naming]\ngroup = "AUSDATEI"\n', encoding="utf-8")

    assert cli.main(["--config", str(config), "gui"]) == 0
    assert captured["state"].naming.group == "AUSDATEI"
    assert captured["state"].config_path == config


def test_summary_names_everything_that_was_saved(tmp_path):
    from releaser.config import Config

    state = gtkui.build_state(config=Config())
    state.navigate(str(tmp_path))
    state.set_pattern("group", "GRP")
    text = gtkui.defaults_summary(state, tmp_path / "c.toml")
    for part in (str(tmp_path / "c.toml"), "GRP", str(tmp_path),
                 "standard.skl", "capitalize", "lower", "„00-“"):
        assert part in text, part


@needs_gtk
def test_start_without_arguments_uses_the_saved_settings(tmp_path):
    """So startet das AppImage per Doppelklick. Vorher entstand dabei ein
    leerer Zustand - Gespeichertes kam nie an."""
    from releaser.config import Config, save

    own = _write_skl(tmp_path / "vorlagen" / "meine.skl")
    eingang = tmp_path / "Eingang"
    eingang.mkdir()
    save(Config(naming={"group": "GESPEICHERT", "case_dir": "upper"},
                build={"template": str(own)},
                gui={"start": str(eingang)}),
         tmp_path / "cfg" / "mp3releaser" / "config.toml")

    result = run_in_display(f"""
        import os, sys
        sys.path.insert(0, {str(ROOT)!r})
        sys.path.insert(0, {str(ROOT / 'packaging')!r})
        os.environ["XDG_CONFIG_HOME"] = {str(tmp_path / 'cfg')!r}
        sys.argv = ["mp3releaser"]                 # ohne Argumente
        from releaser.frontends import gtkui

        class Probe(gtkui.ReleaserWindow):
            def __init__(self, app, state):
                super().__init__(app, state)
                print("GROUP", state.naming.group)
                print("TEMPLATE", state.template_path)
                print("LABEL", self.path_label.get_text())
                app.quit()

        gtkui.ReleaserWindow = Probe
        import entrypoint
        raise SystemExit(entrypoint.main())
    """)
    assert result.returncode == 0, result.stderr
    assert "GROUP GESPEICHERT" in result.stdout
    assert f"TEMPLATE {own}" in result.stdout
    assert f"LABEL {eingang}" in result.stdout


# ------------------------------------------------- NFO im festen Raster


@needs_gtk
def test_nfo_view_draws_blocks_without_gaps_on_a_fixed_grid():
    """Blockzeichen als Flaechen: zwei mal zwei Vollbloecke ergeben eine
    lueckenlose Flaeche, die Grafik ist so breit wie Spalten mal Zelle -
    gleich, welche Schrift eingestellt ist. Vorher verrutschten Zeilen mit
    Blockzeichen, wenn die Schrift sie nicht hatte."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi
        gi.require_version("Gtk", "4.0"); gi.require_version("Gsk", "4.0")
        from gi.repository import Gsk, Gtk
        from releaser.frontends.gtkui import NfoView

        def color_rects(node, out):
            kind = node.get_node_type()
            if kind == Gsk.RenderNodeType.COLOR_NODE:
                b = node.get_bounds()
                out.append((round(b.get_x()), round(b.get_y()),
                            round(b.get_width()), round(b.get_height())))
            elif kind == Gsk.RenderNodeType.CONTAINER_NODE:
                for i in range(node.get_n_children()):
                    color_rects(node.get_child(i), out)
            return out

        for font in ("DejaVu Sans Mono 10", "Noto Mono 10", "Monospace 13"):
            NfoView.FONT = font
            view = NfoView()
            window = Gtk.Window()
            window.set_child(view)
            view.set_text("\\u2588\\u2588 abc\\n\\u2588\\u2588\\n\\u2554\\u2550\\u2557")
            width, height, _base = view.cell()
            snapshot = Gtk.Snapshot()
            view.do_snapshot(snapshot)
            rects = color_rects(snapshot.to_node(), [])
            pad = NfoView.PAD
            pixels = set()
            for x, y, w, h in rects:
                pixels |= {{(px, py) for px in range(x, x + w)
                            for py in range(y, y + h)}}
            block = {{(px, py) for px in range(pad, pad + 2 * width)
                      for py in range(pad, pad + 2 * height)}}
            print("SOLID", font, block <= pixels)
            measured = view.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
            print("WIDTH", font, measured == 6 * width + 2 * pad)
            # die obere Rahmenlinie in Zeile 3 laeuft ueber alle drei Zellen
            top = pad + 2 * height
            line_rows = {{py for px, py in pixels
                          if py >= top and px == pad + width + width // 2}}
            print("FRAME", font, any(all((px, py) in pixels
                  for px in range(pad + width // 2, pad + 3 * width - width // 2))
                  for py in line_rows))
    """)
    assert result.returncode == 0, result.stderr
    for line in result.stdout.splitlines():
        if line.startswith(("SOLID", "WIDTH", "FRAME")):
            assert line.endswith("True"), line
    assert result.stdout.count("True") == 9, result.stdout


@needs_gtk
@needs_ffmpeg
def test_nfo_text_can_be_copied(release_tree):
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.uistate import AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]))
        state.load_template({str(release_tree / 'vorlage.skl')!r})
        app = Gtk.Application(application_id="de.test.copy",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            window._on_copy_nfo()
            print("MSG", state.messages[-1].text)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "MSG NFO-Text in die Zwischenablage kopiert" in result.stdout


# ------------------------------------------------- Ein Knopf


@needs_gtk
@needs_ffmpeg
def test_one_button_makes_the_release(release_tree):
    """"Release erstellen" ersetzt die drei Knoepfe Tags, Umbenennen und
    Dateien erzeugen; die Einzelschritte stehen im Menue daneben."""
    result = run_in_display(f"""
        import sys; sys.path.insert(0, {str(ROOT)!r})
        import gi; gi.require_version("Gtk", "4.0")
        from gi.repository import Gio, Gtk
        from releaser.browse import Mount, MountedSource
        from releaser.frontends.gtkui import ReleaserWindow
        from releaser.naming import NamingProfile
        from releaser.uistate import Action, AppState

        state = AppState(
            source=MountedSource([Mount("eingang", {str(release_tree / 'eingang')!r})]),
            naming=NamingProfile(group="GRP"))
        state.load_template({str(release_tree / 'vorlage.skl')!r})
        app = Gtk.Application(application_id="de.test.produce",
                              flags=Gio.ApplicationFlags.FLAGS_NONE)

        def activate(a):
            window = ReleaserWindow(a, state)
            button = window.buttons[Action.PRODUCE]
            print("BEFORE", button.get_sensitive())
            state.load("eingang/Artist-Album-2026-GRP")
            print("AFTER_LOAD", button.get_sensitive())
            print("LABEL", button.get_label())
            # die Einzelschritte sind noch da, nur nicht mehr in der Leiste
            print("STEPS", all(window.buttons[x].get_parent() is not None
                               for x in (Action.PREVIEW_TAGS,
                                         Action.PREVIEW_RENAME, Action.BUILD)))
            button.emit("clicked")
            titles = [w.get_title() for w in Gtk.Window.list_toplevels()]
            print("DIALOG", "Release erstellt" in titles)
            print("ROOT", state.root.name)
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "BEFORE False" in result.stdout
    assert "AFTER_LOAD True" in result.stdout
    assert "LABEL Release erstellen" in result.stdout
    assert "STEPS True" in result.stdout
    assert "DIALOG True" in result.stdout
    assert "ROOT der_artist-das_album-2026-GRP" in result.stdout
    target = release_tree / "eingang" / "der_artist-das_album-2026-GRP"
    assert sorted(p.suffix for p in target.iterdir()) == [
        ".m3u", ".mp3", ".mp3", ".nfo", ".sfv"]
