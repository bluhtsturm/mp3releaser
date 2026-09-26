"""Tests für das Tag-Schreiben."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.checksums import crc32_file
from releaser.model import Disc, Release, Track
from releaser.tagwriter import (
    FIELDS,
    TagProfile,
    _append_once,
    _strip_suffix,
    apply_tags,
    current_tags,
    desired_tags,
    format_plan,
    plan_tags,
)
from releaser.text import CharCase

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


def encode(target: Path, *args: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    *args, str(target), "-y"], check=True)
    return target


def sample_release(paths=()) -> Release:
    tracks = [Track(no, f"Titel {no}", 100.0, 1, str(p) if p else None)
              for no, p in enumerate(paths or [None, None], start=1)]
    return Release(artist="Der Artist", album="Das Album", year=2026,
                   genre="Electronic", catalog_no="CAT001", company="Das Label",
                   discs=[Disc(1, tracks=tracks)])


# --------------------------------------------------------------- Sollwerte


def test_desired_tags_cover_all_fields_by_default():
    release = sample_release()
    values = desired_tags(release, release.discs[0], release.tracks[0], TagProfile())
    assert set(values) == set(FIELDS)


def test_charcase_applies_to_text_but_not_to_numbers_or_comment():
    release = sample_release()
    profile = TagProfile(charcase=CharCase.UPPER, comment="kleiner kommentar")
    values = desired_tags(release, release.discs[0], release.tracks[0], profile)
    assert values["artist"] == "DER ARTIST"
    assert values["title"] == "TITEL 1"
    assert values["comment"] == "kleiner kommentar"      # ausgenommen
    assert values["date"] == "2026"
    assert values["tracknumber"] == "1/2"


def test_totals_can_be_switched_off():
    release = sample_release()
    values = desired_tags(release, release.discs[0], release.tracks[0],
                          TagProfile(write_totals=False))
    assert values["tracknumber"] == "1"


def test_disc_number_only_for_multi_disc():
    release = sample_release()
    single = desired_tags(release, release.discs[0], release.tracks[0], TagProfile())
    assert single["discnumber"] == ""

    forced = desired_tags(release, release.discs[0], release.tracks[0],
                          TagProfile(write_disc_for_single=True))
    assert forced["discnumber"] == "1"

    release.discs.append(Disc(2, tracks=[Track(1, "X", 10.0, 2)]))
    multi = desired_tags(release, release.discs[0], release.tracks[0], TagProfile())
    assert multi["discnumber"] == "1/2"


def test_album_addition_keeps_its_own_spelling():
    release = sample_release()
    profile = TagProfile(charcase=CharCase.CAPITALIZE, album_addition="CDDA")
    values = desired_tags(release, release.discs[0], release.tracks[0], profile)
    assert values["album"] == "Das Album (CDDA)"         # nicht "(Cdda)"


def test_catalog_number_in_album():
    release = sample_release()
    profile = TagProfile(catalog_in_album=True)
    values = desired_tags(release, release.discs[0], release.tracks[0], profile)
    assert values["album"] == "Das Album (CAT001)"


def test_label_in_comment_overrides_free_text():
    release = sample_release()
    profile = TagProfile(comment="ignoriert", label_in_comment=True)
    values = desired_tags(release, release.discs[0], release.tracks[0], profile)
    assert values["comment"] == "Das Label"


def test_field_selection_limits_what_is_written():
    release = sample_release()
    profile = TagProfile(fields=frozenset({"title", "artist"}))
    values = desired_tags(release, release.discs[0], release.tracks[0], profile)
    assert set(values) == {"title", "artist"}


@pytest.mark.parametrize("existing,expected", [
    ("Das Album", "Das Album (CDDA)"),
    ("Das Album (CDDA)", "Das Album (CDDA)"),
    ("Das Album (cdda)", "Das Album (CDDA)"),
    ("Das Album  (CDDA)  ", "Das Album (CDDA)"),
])
def test_append_once_is_idempotent(existing, expected):
    assert _append_once(existing, "CDDA") == expected


def test_strip_suffix_ignores_case():
    assert _strip_suffix("Das Album (cdda)", "CDDA") == "Das Album"
    assert _strip_suffix("Das Album", "CDDA") == "Das Album"


def test_desired_tags_survive_a_round_trip():
    """Ein zweiter Lauf auf bereits geschriebenen Werten ändert nichts mehr."""
    release = sample_release()
    profile = TagProfile(charcase=CharCase.CAPITALIZE, album_addition="CDDA")
    first = desired_tags(release, release.discs[0], release.tracks[0], profile)

    release.album = first["album"]          # wie vom Scanner zurückgelesen
    second = desired_tags(release, release.discs[0], release.tracks[0], profile)
    assert second == first


# ----------------------------------------------------------------- Planung


@needs_ffmpeg
def test_plan_does_not_touch_files(tmp_path):
    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame")
    before = crc32_file(path)
    plan = plan_tags(sample_release([path]))
    assert plan.changes
    assert crc32_file(path) == before


@needs_ffmpeg
def test_plan_lists_only_actual_differences(tmp_path):
    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame",
                  "-metadata", "artist=Der Artist")
    plan = plan_tags(sample_release([path]))
    fields = {c.field for c in plan.changes if c.path == path}
    assert "artist" not in fields
    assert "title" in fields


def test_plan_skips_formats_without_tag_support(tmp_path):
    path = tmp_path / "a.ec3"
    path.write_bytes(b"\x0b\x77" + b"\x00" * 32)
    plan = plan_tags(sample_release([path]))
    assert plan.skipped == [path]
    assert any("keine Tags" in w for w in plan.warnings)
    assert plan.changes == []


def test_plan_warns_about_tracks_without_path():
    plan = plan_tags(sample_release())
    assert any("Dateipfad" in w for w in plan.warnings)


def test_format_plan_without_changes():
    assert "nichts zu tun" in format_plan(plan_tags(Release()))


# -------------------------------------------------------------- Ausführung


@needs_ffmpeg
@pytest.mark.parametrize("name,args", [
    ("a.mp3", ["-c:a", "libmp3lame"]),
    ("a.flac", ["-c:a", "flac"]),
    ("a.m4a", ["-c:a", "aac"]),
])
def test_write_and_read_back_every_format(tmp_path, name, args):
    from releaser.audio import read_file

    path = encode(tmp_path / name, *args, "-metadata", "title=alter titel")
    release = sample_release([path])
    profile = TagProfile(comment="testlauf")

    apply_tags(plan_tags(release, profile), profile)
    info = read_file(path)

    assert info.title == "Titel 1"
    assert info.artist == "Der Artist"
    assert info.album == "Das Album"
    assert info.year == 2026
    assert info.genre == "Electronic"
    assert info.comment == "testlauf"
    # nur ein Track in dieser Disc -> Gesamtzahl 1
    assert (info.track_no, info.total_tracks) == (1, 1)


@needs_ffmpeg
@pytest.mark.parametrize("name,args", [
    ("a.mp3", ["-c:a", "libmp3lame"]),
    ("a.flac", ["-c:a", "flac"]),
    ("a.m4a", ["-c:a", "aac"]),
])
def test_second_run_has_nothing_to_do(tmp_path, name, args):
    from releaser.audio import read_file

    path = encode(tmp_path / name, *args)
    release = sample_release([path])
    profile = TagProfile(charcase=CharCase.CAPITALIZE, album_addition="CDDA")

    apply_tags(plan_tags(release, profile), profile)

    info = read_file(path)
    release.album = info.album                 # wie nach erneutem Scan
    assert plan_tags(release, profile).changes == []


@needs_ffmpeg
def test_empty_value_removes_existing_frame(tmp_path):
    from releaser.audio import read_file

    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame",
                  "-metadata", "genre=Falsch")
    release = sample_release([path])
    release.genre = ""
    apply_tags(plan_tags(release), TagProfile())
    assert read_file(path).genre == ""


@needs_ffmpeg
def test_id3v1_can_be_switched_off(tmp_path):
    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame")
    release = sample_release([path])

    apply_tags(plan_tags(release), TagProfile(write_id3v1=True))
    with path.open("rb") as fh:
        fh.seek(-128, 2)
        assert fh.read(3) == b"TAG"

    apply_tags(plan_tags(release), TagProfile(write_id3v1=False))
    with path.open("rb") as fh:
        fh.seek(-128, 2)
        assert fh.read(3) != b"TAG"


@needs_ffmpeg
def test_id3v2_version_is_configurable(tmp_path):
    from mutagen.id3 import ID3

    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame")
    release = sample_release([path])
    apply_tags(plan_tags(release), TagProfile(id3v2_version=3))
    assert ID3(path).version[:2] == (2, 3)


@needs_ffmpeg
def test_audio_data_survives_tag_writing(tmp_path):
    """Tags schreiben darf die Audiodaten nicht anfassen."""
    from releaser.checksums import audio_crc32

    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame")
    before, _ = audio_crc32(path)
    release = sample_release([path])
    apply_tags(plan_tags(release), TagProfile(comment="viel laengerer kommentar"))
    assert audio_crc32(path)[0] == before


@needs_ffmpeg
def test_current_tags_mirror_desired_shape(tmp_path):
    from releaser.audio import read_file

    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame")
    release = sample_release([path])
    profile = TagProfile()
    apply_tags(plan_tags(release, profile), profile)

    info = read_file(path)
    current = current_tags(info, profile)
    desired = desired_tags(release, release.discs[0], release.tracks[0], profile)
    assert {k: current[k] for k in desired} == desired


@needs_ffmpeg
@pytest.mark.parametrize("case", [CharCase.UNCHANGED, CharCase.UPPER,
                                  CharCase.LOWER, CharCase.CAPITALIZE])
def test_id3v1_genre_number_survives_every_charcase(tmp_path, case):
    """ID3v1 kennt Genres nur als Zahl - und nur bei exakter Schreibweise."""
    path = encode(tmp_path / f"{case.value}.mp3", "-c:a", "libmp3lame")
    release = sample_release([path])
    release.genre = "drum and bass"
    profile = TagProfile(charcase=case)
    apply_tags(plan_tags(release, profile), profile)

    assert path.read_bytes()[-1] == 127        # Drum & Bass
    values = desired_tags(release, release.discs[0], release.tracks[0], profile)
    assert values["genre"] == "Drum & Bass"    # kanonisch, nicht umgestellt
    # Andere Felder folgen der Regel weiterhin
    assert values["artist"] == case.apply("Der Artist")


@needs_ffmpeg
def test_unknown_genre_still_follows_the_charcase(tmp_path):
    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame")
    release = sample_release([path])
    release.genre = "progressive trance"
    profile = TagProfile(charcase=CharCase.UPPER)
    values = desired_tags(release, release.discs[0], release.tracks[0], profile)
    assert values["genre"] == "PROGRESSIVE TRANCE"


def test_every_readable_format_can_also_be_written_or_is_declared_tagless():
    """Lesen ohne Schreiben waere eine stille Luecke."""
    from releaser.audio.base import AUDIO_EXTENSIONS
    from releaser.tagwriter import TAGLESS_EXTENSIONS, WRITERS

    for extension in AUDIO_EXTENSIONS:
        assert extension in WRITERS or extension in TAGLESS_EXTENSIONS, extension


@needs_ffmpeg
@pytest.mark.parametrize("name,args", [
    ("a.ogg", ["-c:a", "libvorbis"]),
    ("a.opus", ["-c:a", "libopus"]),
])
def test_vorbis_family_round_trip(tmp_path, name, args):
    from releaser.audio import read_file

    path = encode(tmp_path / name, *args)
    release = sample_release([path])
    profile = TagProfile(comment="testlauf")
    apply_tags(plan_tags(release, profile), profile)

    info = read_file(path)
    assert info.title == "Titel 1"
    assert info.artist == "Der Artist"
    assert info.album == "Das Album"
    assert info.year == 2026
    assert info.genre == "Electronic"
    assert info.track_no == 1


@needs_ffmpeg
def test_raw_ec3_is_still_skipped(tmp_path):
    path = encode(tmp_path / "a.ec3", "-c:a", "eac3", "-ac", "6")
    plan = plan_tags(sample_release([path]))
    assert plan.skipped == [path]
    assert any("keine Tags" in w for w in plan.warnings)
