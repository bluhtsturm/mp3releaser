"""Tests für die Fensterlogik.

Die gesamte Zustands- und Aktionsschicht wird hier ohne Grafikumgebung
geprüft. Was danach noch schiefgehen kann, ist Darstellung - nicht Verhalten.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.browse import LocalSource, Mount, MountedSource
from releaser.naming import NamingProfile
from releaser.provenance import Origin
from releaser.uistate import Action, AppState, Level

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


def encode(target: Path, *args: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    *args, str(target), "-y"], check=True)
    return target


@pytest.fixture
def release_dir(tmp_path: Path) -> Path:
    root = tmp_path / "eingang" / "Artist-Album-2026-GRP"
    for no in (1, 2):
        encode(root / f"0{no}-x.mp3", "-c:a", "libmp3lame",
               "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
               "-metadata", "album=Das Album", "-metadata", f"track={no}/2",
               "-metadata", "date=2026", "-metadata", "genre=Electronic")
    return root


@pytest.fixture
def template_file(tmp_path: Path) -> Path:
    path = tmp_path / "vorlage.skl"
    path.write_bytes(("|#Release            |\n"
                      "|#Artist             |\n"
                      "|#Album              |\n"
                      "|#N #Trk             |\n").encode("cp437"))
    return path


def state_for(release_dir: Path) -> AppState:
    mount = release_dir.parent
    return AppState(source=MountedSource([Mount("eingang", mount)]),
                    naming=NamingProfile(group="GRP"))


# =================================================================== Meldungen


def test_messages_are_collected_not_printed():
    state = AppState()
    state.say("erste")
    state.say("zweite", Level.WARNING)
    assert [m.text for m in state.messages] == ["erste", "zweite"]
    assert state.last_message.level is Level.WARNING
    state.clear_messages()
    assert state.last_message is None


def test_on_change_is_called_for_every_state_change(tmp_path):
    calls = []
    state = AppState(source=LocalSource(tmp_path),
                     on_change=lambda: calls.append(1))
    state.show_roots()
    assert calls


# ================================================================== Navigation


@needs_ffmpeg
def test_roots_and_navigation(release_dir):
    state = state_for(release_dir)
    roots = state.show_roots()
    assert [e.name for e in roots] == ["eingang"]

    entries = state.navigate("eingang")
    assert [e.name for e in entries] == ["Artist-Album-2026-GRP"]
    assert state.current_path == "eingang"


@needs_ffmpeg
def test_parent_and_go_up(release_dir):
    state = state_for(release_dir)
    state.navigate("eingang/Artist-Album-2026-GRP")
    assert state.parent_path() == "eingang"

    state.go_up()
    assert state.current_path == "eingang"
    assert state.parent_path() is None


@needs_ffmpeg
def test_navigation_outside_the_mount_is_reported_not_raised(release_dir):
    state = state_for(release_dir)
    state.navigate("eingang/../..")
    assert state.last_message.level is Level.ERROR
    assert state.entries == []          # nichts angezeigt


# ====================================================================== Laden


@needs_ffmpeg
def test_load_fills_release_and_origins(release_dir):
    state = state_for(release_dir)
    assert state.load("eingang/Artist-Album-2026-GRP") is True

    assert state.release.total_tracks == 2
    assert state.release.artist == "Der Artist"
    assert state.origins.get("artist") is Origin.TAG
    assert state.root == release_dir


@needs_ffmpeg
def test_load_of_something_unreadable_reports_instead_of_crashing(tmp_path):
    (tmp_path / "leer").mkdir()
    state = AppState(source=MountedSource([Mount("m", tmp_path)]))
    assert state.load("m/leer") is False
    assert state.last_message.level is Level.ERROR
    assert state.release is None


def test_load_outside_the_mount_is_refused(tmp_path):
    state = AppState(source=MountedSource([Mount("m", tmp_path)]))
    assert state.load("m/../etc") is False
    assert state.last_message.level is Level.ERROR


@needs_ffmpeg
def test_reload_reverts_unsaved_field_changes(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_field("artist", "Von Hand")
    assert state.dirty

    state.reload()
    assert state.release.artist == "Der Artist"
    assert not state.dirty


def test_load_template(tmp_path, template_file):
    state = AppState()
    assert state.load_template(template_file) is True
    assert state.template is not None
    assert state.build_options.template == template_file


def test_load_broken_template_is_reported(tmp_path):
    state = AppState()
    assert state.load_template(tmp_path / "gibtsnicht.skl") is False
    assert state.last_message.level is Level.ERROR


# ====================================================================== Felder


@needs_ffmpeg
def test_field_views_carry_value_width_and_origin(release_dir, template_file):
    state = state_for(release_dir)
    state.load_template(template_file)
    state.load("eingang/Artist-Album-2026-GRP")

    views = {v.spec.name: v for v in state.field_views()}
    assert views["artist"].value == "Der Artist"
    assert views["artist"].origin_label == "aus den Tags"
    assert views["artist"].width is not None


@needs_ffmpeg
def test_setting_a_field_marks_it_manual(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    assert state.set_field("artist", "Neuer Artist") is True
    assert state.release.artist == "Neuer Artist"
    assert state.modified == {"artist"}
    assert state.origins.get("artist") is Origin.MANUAL


@needs_ffmpeg
def test_number_field_rejects_letters(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    assert state.set_field("year", "zweitausend") is False
    assert state.release.year == 2026          # unverändert
    assert state.last_message.level is Level.ERROR


@needs_ffmpeg
def test_number_field_accepts_empty(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    assert state.set_field("year", "") is True
    assert state.release.year is None


@needs_ffmpeg
def test_line_field_splits_and_drops_blank_lines(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    state.set_field("notes", "erste\n\nzweite\n")
    assert state.release.notes == ["erste", "zweite"]


@needs_ffmpeg
def test_unchanged_value_is_not_marked_dirty(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_field("artist", "Der Artist")
    assert not state.dirty


def test_unknown_field_is_reported():
    state = AppState()
    state.release = None
    assert state.set_field("gibtsnicht", "x") is False


@needs_ffmpeg
def test_changing_a_field_invalidates_existing_plans(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.preview_rename()
    assert state.rename_plan is not None

    state.set_field("album", "Anderes Album")
    assert state.rename_plan is None          # bezog sich auf den alten Stand


@needs_ffmpeg
def test_overflow_is_visible_in_the_state(release_dir, tmp_path):
    narrow = tmp_path / "eng.skl"
    narrow.write_bytes("|#Artist   |\n".encode("cp437"))
    state = state_for(release_dir)
    state.load_template(narrow)
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_field("artist", "Ein viel zu langer Artistname")

    assert any("Artist" in w for w in state.overflows())


# ======================================================================= Pläne


@needs_ffmpeg
def test_tag_preview_then_apply(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_field("genre", "electronic")

    plan = state.preview_tags()
    assert plan.changes
    assert state.apply_tags() == 2
    assert state.tag_plan is None
    assert not state.dirty


@needs_ffmpeg
def test_applying_tags_without_a_plan_does_nothing(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    assert state.apply_tags() == 0


@needs_ffmpeg
def test_rename_preview_then_apply(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    plan = state.preview_rename()
    assert plan.changes and plan.is_safe
    assert release_dir.is_dir()                # noch nichts passiert

    assert state.apply_rename() is True
    assert state.root.name == "der_artist-das_album-2026-grp"
    assert state.current_path == "eingang/der_artist-das_album-2026-grp"


@needs_ffmpeg
def test_rename_refuses_an_unsafe_plan(release_dir):
    state = state_for(release_dir)
    state.naming = NamingProfile(group="GRP", file_pattern="#Album")
    state.load("eingang/Artist-Album-2026-GRP")

    plan = state.preview_rename()
    assert not plan.is_safe
    assert state.apply_rename() is False
    assert release_dir.is_dir()


@needs_ffmpeg
def test_rename_without_preview_is_refused(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    assert state.apply_rename() is False
    assert state.last_message.level is Level.ERROR


@needs_ffmpeg
def test_build_needs_a_template_for_the_nfo(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    assert state.build() == []
    assert state.last_message.level is Level.ERROR


@needs_ffmpeg
def test_build_creates_the_files(release_dir, template_file):
    state = state_for(release_dir)
    state.load_template(template_file)
    state.load("eingang/Artist-Album-2026-GRP")

    created = state.build()
    assert sorted(p.suffix for p in created) == [".m3u", ".nfo", ".sfv"]


@needs_ffmpeg
def test_build_without_nfo_works_without_a_template(release_dir):
    state = state_for(release_dir)
    state.build_options.nfo = False
    state.load("eingang/Artist-Album-2026-GRP")

    assert [p.suffix for p in state.build()] == [".sfv", ".m3u"]


# ============================================== Was wann benutzbar sein darf


def test_nothing_is_enabled_without_a_release():
    state = AppState()
    enabled = state.enabled()
    assert not enabled[Action.PREVIEW_TAGS]
    assert not enabled[Action.PREVIEW_RENAME]
    assert not enabled[Action.BUILD]
    assert not enabled[Action.RELOAD]


@needs_ffmpeg
def test_previews_become_available_after_loading(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    enabled = state.enabled()
    assert enabled[Action.PREVIEW_TAGS]
    assert enabled[Action.PREVIEW_RENAME]
    assert enabled[Action.RELOAD]
    assert not enabled[Action.APPLY_TAGS]      # erst nach der Vorschau
    assert not enabled[Action.APPLY_RENAME]


@needs_ffmpeg
def test_apply_becomes_available_only_after_a_usable_preview(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    state.preview_rename()
    assert state.enabled()[Action.APPLY_RENAME]

    state.set_field("album", "Anderes")        # Plan verfaellt
    assert not state.enabled()[Action.APPLY_RENAME]


@needs_ffmpeg
def test_unsafe_plan_does_not_enable_the_button(release_dir):
    state = state_for(release_dir)
    state.naming = NamingProfile(group="GRP", file_pattern="#Album")
    state.load("eingang/Artist-Album-2026-GRP")
    state.preview_rename()
    assert not state.enabled()[Action.APPLY_RENAME]


@needs_ffmpeg
def test_build_button_needs_a_template(release_dir, template_file):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    assert not state.enabled()[Action.BUILD]

    state.load_template(template_file)
    assert state.enabled()[Action.BUILD]


def test_every_action_has_a_label_and_an_entry():
    state = AppState()
    enabled = state.enabled()
    for action in Action:
        assert action.label
        assert action in enabled


# ================================================================ Statuszeile


def test_status_without_a_release():
    assert AppState().status() == "Kein Release geladen"


@needs_ffmpeg
def test_status_shows_counts_and_changes(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    assert "Der Artist - Das Album" in state.status()
    assert "2 Tracks" in state.status()

    state.set_field("artist", "Anders")
    assert "1 Feld(er) geändert" in state.status()


@needs_ffmpeg
def test_status_mentions_uncertain_fields(tmp_path):
    root = tmp_path / "eingang" / "Ohne-Tags"
    encode(root / "03-aus-dem-dateinamen.mp3", "-c:a", "libmp3lame")
    state = AppState(source=MountedSource([Mount("eingang", tmp_path / "eingang")]))
    state.load("eingang/Ohne-Tags")
    assert "unsicher" in state.status()


# ========================================= Dieselbe Logik fuer beide Formen


@needs_ffmpeg
def test_the_same_state_works_with_either_source(release_dir, template_file):
    """Desktop und Web unterscheiden sich nur in der Quelle."""
    results = []
    for source, path in (
        (LocalSource(release_dir.parent), str(release_dir)),
        (MountedSource([Mount("eingang", release_dir.parent)]),
         "eingang/Artist-Album-2026-GRP"),
    ):
        state = AppState(source=source, naming=NamingProfile(group="GRP"))
        state.load_template(template_file)
        assert state.load(path) is True
        results.append((state.release.release_name, state.release.total_tracks,
                        [v.spec.name for v in state.field_views()]))

    assert results[0] == results[1]


# ============================================ Auswahl getrennt vom Oeffnen


@needs_ffmpeg
def test_selecting_does_not_open(release_dir):
    """Eine Zeile anklicken waehlt sie aus - geoeffnet wird sie erst danach."""
    state = state_for(release_dir)
    state.navigate("eingang")
    state.select("eingang/Artist-Album-2026-GRP")

    assert state.current_path == "eingang"          # unveraendert
    assert state.selected_entry().name == "Artist-Album-2026-GRP"
    assert state.enabled()[Action.OPEN]


@needs_ffmpeg
def test_navigating_clears_the_selection(release_dir):
    state = state_for(release_dir)
    state.navigate("eingang")
    state.select("eingang/Artist-Album-2026-GRP")
    state.navigate("eingang/Artist-Album-2026-GRP")

    assert state.selected_path is None
    assert state.selected_entry() is None
    assert not state.enabled()[Action.OPEN]


def test_open_stays_disabled_without_a_selection():
    assert not AppState().enabled()[Action.OPEN]


# ====================================================== Namensvorschau


@needs_ffmpeg
def test_preview_names_shows_old_and_new(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    preview = state.preview_names()
    assert preview["directory"] == ("Artist-Album-2026-GRP",
                                    "der_artist-das_album-2026-grp")
    assert len(preview["files"]) == 2
    old, new = preview["files"][0]
    assert old.endswith(".mp3") and new.endswith(".mp3")
    assert new.startswith("01-der_artist-")
    assert preview["collisions"] == []


@needs_ffmpeg
def test_preview_names_touches_nothing(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    before = sorted(p.name for p in release_dir.iterdir())
    state.preview_names()
    assert sorted(p.name for p in release_dir.iterdir()) == before


@needs_ffmpeg
def test_changing_a_pattern_changes_the_preview(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    assert state.set_pattern("file", "#N-#Trk") is True
    assert state.preview_names()["files"][0][1].startswith("01-titel")

    assert state.set_pattern("group", "ANDERE") is True
    assert state.preview_names()["directory"][1].endswith("-andere")


@needs_ffmpeg
def test_changing_a_pattern_invalidates_the_plan(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.preview_rename()
    assert state.rename_plan is not None

    state.set_pattern("dir", "#Artist-#Album")
    assert state.rename_plan is None


@needs_ffmpeg
def test_case_can_be_switched(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    state.set_pattern("case", "upper")
    assert state.preview_names()["directory"][1].isupper()
    state.set_pattern("case", "lower")
    assert state.preview_names()["directory"][1].islower()


def test_unknown_pattern_is_reported():
    state = AppState()
    assert state.set_pattern("gibtsnicht", "x") is False
    assert state.last_message.level is Level.ERROR


def test_unknown_case_is_reported():
    state = AppState()
    assert state.set_pattern("case", "schraeg") is False
    assert state.last_message.level is Level.ERROR


@needs_ffmpeg
def test_directory_name_can_be_set_by_hand(release_dir):
    """Das Muster ohne Tags liefert genau diesen Namen."""
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    assert state.set_literal_dirname("Mein eigener Name") is True
    assert state.preview_names()["directory"][1] == "mein_eigener_name"

    plan = state.preview_rename()
    assert plan.is_safe
    assert any(op.dst.name == "mein_eigener_name" for op in plan.changes)


@needs_ffmpeg
def test_a_hash_in_a_manual_name_is_refused(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    assert state.set_literal_dirname("Mit #Artist drin") is False
    assert state.last_message.level is Level.ERROR


@needs_ffmpeg
def test_preview_reports_colliding_filenames(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_pattern("file", "#Album")          # beide Tracks gleich
    assert state.preview_names()["collisions"]


# ============================== Schreibweisen, Präfix, Begleitdateien


@needs_ffmpeg
def test_directory_and_files_have_separate_cases(release_dir):
    """In der Szene ist der Ordner groß und die Dateien klein geschrieben."""
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    state.set_pattern("case_dir", "upper")
    state.set_pattern("case_file", "lower")

    preview = state.preview_names()
    assert preview["directory"][1].isupper()
    assert preview["files"][0][1].islower()


@needs_ffmpeg
def test_case_without_scope_still_sets_both(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_pattern("case", "upper")

    preview = state.preview_names()
    assert preview["directory"][1].isupper()
    # Die Endung bleibt klein - verglichen wird deshalb nur der Namensrumpf
    assert Path(preview["files"][0][1]).stem.isupper()


@needs_ffmpeg
def test_companion_prefix_covers_all_generated_files(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    state.set_companion_prefix("00-", include_all=True)
    names = state.companion_preview()
    assert all(name.startswith("00-") for name in names)
    assert sorted(Path(n).suffix for n in names) == [".m3u", ".nfo", ".sfv"]


@needs_ffmpeg
def test_prefix_can_stay_off_for_sfv_and_m3u(release_dir):
    """So hielt es das Original - Prüfprogramme finden das SFV sonst schlechter."""
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    state.set_companion_prefix("00-", include_all=False)
    names = {Path(n).suffix: n for n in state.companion_preview()}
    assert names[".nfo"].startswith("00-")
    assert not names[".sfv"].startswith("00-")


@needs_ffmpeg
def test_companion_names_follow_the_future_directory_name(release_dir):
    """Vor dem Umbenennen heißt der Ordner noch anders - gezeigt wird das Ziel."""
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_pattern("case_dir", "capitalize")
    state.set_pattern("case_file", "lower")

    # Der kuenftige Ordner heisst Der_Artist-… - die Begleitdateien folgen
    # aber der Dateischreibweise, sind also klein
    assert all("der_artist-das_album" in name
               for name in state.companion_preview())


@needs_ffmpeg
def test_cover_is_detected_and_renamed_along(release_dir):
    state = state_for(release_dir)
    (release_dir / "folder.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_companion_prefix("00-", include_all=True)

    assert [p.name for p in state.covers()] == ["folder.jpg"]
    assert any(name.endswith(".jpg") for name in state.companion_preview())

    plan = state.preview_rename()
    cover_ops = [op for op in plan.changes if op.src.suffix == ".jpg"]
    assert len(cover_ops) == 1
    assert cover_ops[0].dst.name.startswith("00-")


def test_covers_without_a_release_is_empty():
    assert AppState().covers() == []
    assert AppState().companion_preview() == []


@needs_ffmpeg
def test_a_typo_in_a_pattern_is_reported(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.clear_messages()

    state.set_pattern("dir", "#Artist-#Quatsch-#Year")
    assert state.last_message.level is Level.WARNING
    assert "#Quatsch" in state.last_message.text


@needs_ffmpeg
def test_a_correct_pattern_produces_no_warning(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.clear_messages()

    state.set_pattern("dir", "#Artist-#Album-#Fmt-#Year-#Grp")
    assert not any(m.level is Level.WARNING for m in state.messages)


@needs_ffmpeg
def test_an_empty_directory_name_is_refused(release_dir):
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")

    assert state.set_literal_dirname("   ") is False
    assert state.last_message.level is Level.ERROR
    assert state.naming.dir_pattern  # unveraendert


# ================================================== NFO-Vorschau


def test_nfo_preview_without_a_template():
    state = AppState()
    assert "Keine Vorlage" in state.nfo_preview()


@needs_ffmpeg
def test_nfo_preview_without_a_release(release_dir, template_file):
    state = state_for(release_dir)
    state.load_template(template_file)
    assert state.nfo_preview() == "Kein Release geladen."


@needs_ffmpeg
def test_nfo_preview_renders_the_release(release_dir, template_file):
    state = state_for(release_dir)
    state.load_template(template_file)
    state.load("eingang/Artist-Album-2026-GRP")

    text = state.nfo_preview()
    assert "Der Artist" in text
    assert "Das Album" in text
    assert "01 Titel 1" in text          # Trackliste


@needs_ffmpeg
def test_nfo_preview_changes_with_a_field(release_dir, template_file):
    state = state_for(release_dir)
    state.load_template(template_file)
    state.load("eingang/Artist-Album-2026-GRP")

    before = state.nfo_preview()
    state.set_field("artist", "Ganz Anders")
    after = state.nfo_preview()

    assert before != after
    assert "Ganz Anders" in after


@needs_ffmpeg
def test_nfo_preview_touches_nothing(release_dir, template_file):
    state = state_for(release_dir)
    state.load_template(template_file)
    state.load("eingang/Artist-Album-2026-GRP")
    before = sorted(p.name for p in release_dir.iterdir())

    state.nfo_preview()
    assert sorted(p.name for p in release_dir.iterdir()) == before


@needs_ffmpeg
def test_nfo_dimensions(release_dir, template_file):
    state = state_for(release_dir)
    state.load_template(template_file)
    state.load("eingang/Artist-Album-2026-GRP")

    lines, width = state.nfo_dimensions()
    assert lines >= 4
    assert width == 22               # Breite der Testvorlage


@needs_ffmpeg
def test_truncated_tracks_are_reported_without_a_continuation_line(release_dir,
                                                                   tmp_path):
    """Ohne Fortsetzungszeile wird ein langer Titel abgeschnitten, nicht umbrochen."""
    narrow = tmp_path / "ohne.skl"
    narrow.write_bytes("|#N #Trk    |\n".encode("cp437"))

    state = state_for(release_dir)
    state.load_template(narrow)
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_field("artist", "A")
    state.release.discs[0].tracks[0].title = "Ein sehr langer Tracktitel"

    cut = state.truncated_tracks()
    assert cut == ["Ein sehr langer Tracktitel"]
    assert cut[0] not in state.nfo_preview()        # tatsaechlich abgeschnitten


@needs_ffmpeg
def test_a_continuation_line_prevents_the_warning(release_dir, tmp_path):
    wide = tmp_path / "mit.skl"
    wide.write_bytes("|#N #Trk    |\n|   #Trk    |\n".encode("cp437"))

    state = state_for(release_dir)
    state.load_template(wide)
    state.load("eingang/Artist-Album-2026-GRP")
    state.release.discs[0].tracks[0].title = "Ein sehr langer Tracktitel"

    assert state.truncated_tracks() == []


def test_truncated_tracks_without_template_or_release():
    assert AppState().truncated_tracks() == []


# ==================================== Prüfen und Rückgängig im Zustand


def test_check_without_template_or_release_reports_back():
    state = AppState()
    assert state.check_template() is None
    assert state.last_message.level is Level.WARNING

    assert state.check_release() is None
    assert state.last_message.level is Level.WARNING


@needs_ffmpeg
def test_check_release_from_the_state(release_dir, template_file):
    state = state_for(release_dir)
    state.load_template(template_file)
    state.load("eingang/Artist-Album-2026-GRP")

    report = state.check_release()
    assert report is not None
    assert report.checked == "Artist-Album-2026-GRP"


@needs_ffmpeg
def test_check_template_from_the_state(release_dir, template_file):
    state = state_for(release_dir)
    state.load_template(template_file)
    report = state.check_template()
    assert report is not None
    assert report.checked == template_file.name


@needs_ffmpeg
def test_undo_from_the_state(release_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.preview_rename()
    assert state.apply_rename() is True
    assert not release_dir.exists()

    assert state.undo_last() is True
    assert release_dir.is_dir()
    # Der alte Pfad zeigt ins Leere - die Auswahl steht wieder auf der Wurzel
    assert state.release is None
    assert state.current_path is None


def test_undo_without_a_journal(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    state = AppState()
    assert state.undo_last() is False
    assert state.last_message.level is Level.WARNING


@needs_ffmpeg
def test_tag_undo_reloads_instead_of_discarding(release_dir):
    """Nach einer Tag-Rücknahme liegen die Dateien noch da - neu einlesen."""
    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.set_field("artist", "Von Hand")
    state.preview_tags()
    state.apply_tags()

    state.load("eingang/Artist-Album-2026-GRP")
    assert state.release.artist == "Von Hand"

    assert state.undo_last() is True
    assert state.release is not None                 # nicht verworfen
    assert state.release.artist == "Der Artist"      # Stand der Dateien
    # Das Neueinlesen meldet sich danach auch noch - gesucht wird im Verlauf
    assert any("getaggte Dateien zurückgenommen" in m.text
               for m in state.messages)


@needs_ffmpeg
def test_session_scope_only_offers_own_entries(release_dir):
    from releaser import undo

    other = undo.record([(Path("/fremd/a"), Path("/fremd/b"))], "Fremdes Release")
    assert other is not None

    state = state_for(release_dir)
    state.undo_scope = "session"
    assert state.undo_entries() == []                # das Fremde ist unsichtbar
    assert state.undo_candidate() is None

    state.load("eingang/Artist-Album-2026-GRP")
    state.preview_rename()
    state.apply_rename()
    # der Testaufbau benutzt das Bibliotheksprofil (klein geschrieben)
    assert [e.release for e in state.undo_entries()] == [state.release.dirname]


@needs_ffmpeg
def test_global_scope_offers_everything(release_dir):
    """Am eigenen Rechner darf man auch zurücknehmen, was die CLI getan hat."""
    from releaser import undo

    undo.record([(Path("/a"), Path("/b"))], "Von der Kommandozeile")
    state = state_for(release_dir)
    assert state.undo_scope == "global"
    assert state.undo_candidate().release == "Von der Kommandozeile"


# ======================================== Nur lesend eingehängte Ordner


@pytest.fixture
def readonly_state(release_dir):
    return AppState(source=MountedSource([Mount("eingang", release_dir.parent,
                                                writable=False)]),
                    naming=NamingProfile(group="GRP"))


@needs_ffmpeg
def test_readonly_mount_allows_previews(readonly_state):
    state = readonly_state
    state.load("eingang/Artist-Album-2026-GRP")
    assert not state.writable

    assert state.preview_rename().changes              # ansehen ja
    assert state.preview_tags() is not None
    assert state.nfo_preview()


@needs_ffmpeg
def test_readonly_mount_refuses_every_write(readonly_state, release_dir,
                                            template_file):
    state = readonly_state
    state.load_template(template_file)
    state.load("eingang/Artist-Album-2026-GRP")
    before = sorted(p.name for p in release_dir.iterdir())

    state.preview_rename()
    assert state.apply_rename() is False
    state.set_field("artist", "Anders")
    state.preview_tags()
    assert state.apply_tags() == 0
    assert state.build() == []

    assert sorted(p.name for p in release_dir.iterdir()) == before
    assert "nur lesend" in state.last_message.text


@needs_ffmpeg
def test_readonly_mount_disables_the_buttons(readonly_state, template_file):
    state = readonly_state
    state.load_template(template_file)
    state.load("eingang/Artist-Album-2026-GRP")
    state.preview_rename()
    state.set_field("artist", "Anders")
    state.preview_tags()

    enabled = state.enabled()
    assert enabled[Action.PREVIEW_RENAME] and enabled[Action.PREVIEW_TAGS]
    assert not enabled[Action.APPLY_RENAME]
    assert not enabled[Action.APPLY_TAGS]
    assert not enabled[Action.BUILD]
    assert "nur lesend" in state.status()


def test_local_source_is_always_writable(tmp_path):
    from releaser.browse import LocalSource

    state = AppState(source=LocalSource(tmp_path))
    state.current_path = str(tmp_path)
    assert state.writable


# ------------------------------------------------ Korrekturen (Fehlerdurchsicht)


@needs_ffmpeg
def test_name_preview_has_no_collisions_across_disc_folders(tmp_path):
    """CD1/01-intro.mp3 und CD2/01-intro.mp3 stehen in verschiedenen
    Ordnern - der echte Plan wusste das, die Vorschau nicht."""
    root = tmp_path / "eingang" / "Rel"
    for disc in (1, 2):
        encode(root / f"CD{disc}" / "01.mp3", "-c:a", "libmp3lame",
               "-metadata", "title=Intro", "-metadata", "artist=A",
               "-metadata", "album=B", "-metadata", "track=1",
               "-metadata", f"disc={disc}")
    state = AppState(source=MountedSource([Mount("eingang", tmp_path / "eingang")]),
                     naming=NamingProfile(group="GRP"))
    assert state.load("eingang/Rel")
    assert state.preview_names()["collisions"] == []


@needs_ffmpeg
def test_rename_that_became_unsafe_is_not_reported_as_done(release_dir):
    state = state_for(release_dir)
    assert state.load("eingang/Artist-Album-2026-GRP")
    plan = state.preview_rename()
    assert plan.is_safe and plan.changes

    # zwischen Vorschau und Ausfuehrung belegt jemand das Ziel
    next(op.dst for op in plan.ops if op.kind == "root").mkdir()

    assert state.apply_rename() is False
    assert release_dir.is_dir()
    assert any("Nichts umbenannt" in m.text for m in state.messages)
    assert state.messages[-1].level is Level.ERROR


@needs_ffmpeg
def test_failed_build_is_reported_instead_of_raised(release_dir, template_file,
                                                    monkeypatch):
    from releaser import service

    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.load_template(template_file)

    def refuse(*_args, **_kwargs):
        raise PermissionError(13, "Keine Berechtigung")

    monkeypatch.setattr(service, "build", refuse)
    assert state.build() == []
    assert state.messages[-1].level is Level.ERROR
    assert "Keine Berechtigung" in state.messages[-1].text


@needs_ffmpeg
def test_tag_writing_updates_the_sizes_in_the_model(release_dir):
    from releaser.tagwriter import TagProfile

    state = state_for(release_dir)
    state.load("eingang/Artist-Album-2026-GRP")
    state.tags = TagProfile(comment="neu")
    state.preview_tags()
    assert state.apply_tags() == 2

    actual = sum(p.stat().st_size for p in release_dir.glob("*.mp3"))
    assert state.release.size_bytes == actual
