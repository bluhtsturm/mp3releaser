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

            buffer = window.names_view.get_buffer()
            text = buffer.get_text(buffer.get_start_iter(),
                                   buffer.get_end_iter(), False)
            print("HASARROW", "->" in text)
            print("DIRENTRY", window.dirname_entry.get_text())

            window.pattern_entries["file"].set_text("#N-#Trk")
            window._on_pattern(window.pattern_entries["file"], "file")
            text = buffer.get_text(buffer.get_start_iter(),
                                   buffer.get_end_iter(), False)
            print("SHORTNAME", "01-titel_1" in text)

            window.dirname_entry.set_text("Von Hand")
            window._on_dirname(window.dirname_entry)
            print("MANUAL", window.dirname_entry.get_text())
            a.quit()

        app.connect("activate", activate)
        raise SystemExit(app.run([]))
    """)
    assert result.returncode == 0, result.stderr
    assert "HASARROW True" in result.stdout
    assert "DIRENTRY der_artist-das_album-2026-grp" in result.stdout
    assert "SHORTNAME True" in result.stdout
    assert "MANUAL von_hand" in result.stdout


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
    from releaser.config import Config, save
    from releaser.uistate import Level

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save(Config(build={"template": str(tmp_path / "weg.skl")}))

    state = gtkui.build_state()
    assert state.template is None
    assert state.last_message.level is Level.WARNING


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
            window._on_save_defaults()
            print("MSG", state.messages[-1].text)
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
            buffer = window.nfo_view.get_buffer()
            return buffer.get_text(buffer.get_start_iter(),
                                   buffer.get_end_iter(), False)

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
            buffer = window.nfo_view.get_buffer()
            print("TEXT", buffer.get_text(buffer.get_start_iter(),
                                          buffer.get_end_iter(), False)[:30])
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
