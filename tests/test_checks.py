"""Tests für die Prüfungen."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.checks import (
    CONVENTIONAL_WIDTH,
    Level,
    Report,
    check_release,
    check_template,
    check_template_file,
)
from releaser.model import Release
from releaser.naming import NamingProfile
from releaser.skl import Template

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")

ROOT = Path(__file__).resolve().parents[1]


def encode(target: Path, *args: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    *args, str(target), "-y"], check=True)
    return target


def wide_template() -> Template:
    """Eine Vorlage ohne Beanstandungen."""
    line = lambda tag: "|" + tag.ljust(60) + "|"
    return Template.parse("\n".join([
        line("#Release"), line("#Artist"), line("#Album"), line("#Genre"),
        line("#Enc"), line("#Url"), line("#Rnotes"),
        line("#N #Trk"), line("   #Trk"),
    ]))


# ================================================================= Befundtyp


def test_report_counts_and_ok():
    report = Report(checked="x")
    assert report.clean and report.ok
    assert report.summary() == "keine Beanstandungen"

    report.add(Level.WARNING, "ein Hinweis")
    assert report.ok and not report.clean
    report.add(Level.ERROR, "ein Fehler")
    assert not report.ok
    assert "1 Fehler" in report.summary() and "1 Hinweise" in report.summary()


def test_issue_renders_with_subject():
    report = Report()
    report.add(Level.ERROR, "geht nicht", "#Artist")
    assert str(report.issues[0]) == "x geht nicht [#Artist]"


def test_render_starts_with_the_summary():
    report = Report(checked="vorlage.skl")
    report.add(Level.INFO, "nur so")
    assert report.render().splitlines()[0].startswith("vorlage.skl:")


# =========================================================== Vorlagenprüfung


def test_a_good_template_has_nothing_to_report():
    assert check_template(wide_template()).clean


def test_missing_tags_are_reported():
    report = check_template(Template.parse("|#Artist" + " " * 40 + "|"))
    messages = " ".join(i.message for i in report.issues)
    assert "#Album" in messages
    assert "#Trk" in messages


def test_narrow_fields_are_reported():
    report = check_template(Template.parse("|#Artist |\n|#Album  |"))
    narrow = [i for i in report.issues if "Platz" in i.message]
    assert {i.subject for i in narrow} >= {"#Artist", "#Album"}


def test_missing_continuation_line_is_reported():
    template = Template.parse("|#N #Trk" + " " * 30 + "|")
    report = check_template(template)
    assert any("Fortsetzungszeile" in i.message for i in report.issues)


def test_continuation_line_silences_that_warning():
    line = "|#N #Trk" + " " * 30 + "|"
    template = Template.parse(line + "\n|   #Trk" + " " * 30 + "|")
    report = check_template(template)
    assert not any("Fortsetzungszeile" in i.message for i in report.issues)


def test_typos_in_tags_are_reported():
    template = Template.parse("|#Artist" + " " * 40 + "#Quatsch  |")
    report = check_template(template)
    assert any("#Quatsch" in i.message for i in report.issues)


def test_overwide_template_is_mentioned():
    template = Template.parse("|#Artist" + " " * (CONVENTIONAL_WIDTH + 10) + "|")
    report = check_template(template)
    assert any(i.level is Level.INFO and "breit" in i.message
               for i in report.issues)


def test_empty_template_is_an_error():
    report = check_template(Template.parse("\n\n"))
    assert not report.ok


def test_the_shipped_template_passes():
    report = check_template_file(ROOT / "templates" / "example.skl")
    assert report.ok, report.render()
    assert report.clean, report.render()


def test_unreadable_template_is_an_error(tmp_path):
    report = check_template_file(tmp_path / "gibtsnicht.skl")
    assert not report.ok
    assert "nicht lesbar" in report.issues[0].message


# =========================================================== Releaseprüfung


def build_release(tmp_path: Path, count: int = 2) -> tuple[Release, Path]:
    from releaser import service

    root = tmp_path / "Artist-Album-2026-GRP"
    for no in range(1, count + 1):
        encode(root / f"0{no}-x.flac", "-c:a", "flac",
               "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
               "-metadata", "album=Das Album", "-metadata", f"TRACKNUMBER={no}",
               "-metadata", "DATE=2026")
    return service.scan(root).release, root


@needs_ffmpeg
def test_missing_companions_are_reported(tmp_path):
    release, root = build_release(tmp_path)
    report = check_release(release, root)

    missing = {i.subject for i in report.issues if "vorhanden" in i.message}
    assert missing == {"*.nfo", "*.sfv", "*.m3u"}
    assert report.ok          # fehlend ist ein Hinweis, kein Fehler


@needs_ffmpeg
def test_a_complete_release_passes(tmp_path):
    from releaser import service

    release, root = build_release(tmp_path)
    template = tmp_path / "v.skl"
    template.write_bytes(("|#Release" + " " * 50 + "|\n"
                          "|#N #Trk" + " " * 50 + "|\n"
                          "|   #Trk" + " " * 50 + "|\n").encode("cp437"))
    service.build(release, root, service.BuildOptions(template=template))

    report = check_release(release, root)
    assert report.ok, report.render()
    assert not [i for i in report.issues if i.level is Level.WARNING]


@needs_ffmpeg
def test_a_broken_checksum_is_an_error(tmp_path):
    from releaser import service

    release, root = build_release(tmp_path)
    service.build(release, root, service.BuildOptions(nfo=False))
    with (root / "01-x.flac").open("ab") as handle:
        handle.write(b"kaputt")

    report = check_release(release, root)
    assert not report.ok
    assert any("Prüfsumme" in i.message for i in report.issues)


@needs_ffmpeg
def test_a_missing_file_is_an_error(tmp_path):
    from releaser import service

    release, root = build_release(tmp_path)
    service.build(release, root, service.BuildOptions(nfo=False))
    (root / "02-x.flac").unlink()

    report = check_release(release, root)
    assert not report.ok
    assert any("fehlen laut SFV" in i.message for i in report.issues)


@needs_ffmpeg
def test_untagged_tracks_are_reported(tmp_path):
    release, root = build_release(tmp_path)
    release.tracks[0].title = ""
    release.artist = ""

    report = check_release(release, root)
    messages = " ".join(i.message for i in report.issues)
    assert "Titel fehlt" in messages
    assert "Artist ist nicht gesetzt" in messages


@needs_ffmpeg
def test_duplicate_track_numbers_are_an_error(tmp_path):
    release, root = build_release(tmp_path)
    release.tracks[1].no = release.tracks[0].no

    report = check_release(release, root)
    assert not report.ok
    assert any("doppelte Tracknummern" in i.message for i in report.issues)


@needs_ffmpeg
def test_overlong_names_are_reported(tmp_path):
    release, root = build_release(tmp_path)
    report = check_release(release, root, NamingProfile(max_dir_length=5))
    assert any("Verzeichnisname" in i.message for i in report.issues)


@needs_ffmpeg
def test_dupe_check_is_optional(tmp_path):
    release, root = build_release(tmp_path)

    without = check_release(release, root)
    assert not any("bekannt" in i.message for i in without.issues)

    with_known = check_release(release, root,
                               known_releases=["Artist-Album-CDDA-2026-ANDERE"])
    assert any("gleiches Release bekannt" in i.message
               for i in with_known.issues)


def test_release_without_tracks_is_an_error(tmp_path):
    report = check_release(Release(artist="A", album="B"), tmp_path)
    assert not report.ok
    assert "keine Audiodateien" in report.issues[0].message


# ================================================================= Kommando


@needs_ffmpeg
def test_cli_check_dispatches_by_path(tmp_path, capsys):
    from releaser import cli

    release, root = build_release(tmp_path)
    assert cli.main(["check", str(root)]) == 0
    assert "Artist-Album-2026-GRP" in capsys.readouterr().out

    assert cli.main(["check", str(ROOT / "templates" / "example.skl")]) == 0
    assert "example.skl" in capsys.readouterr().out


def test_cli_check_reports_a_missing_path(tmp_path, capsys):
    from releaser import cli

    assert cli.main(["check", str(tmp_path / "weg")]) == 2
    assert "nicht gefunden" in capsys.readouterr().err


@needs_ffmpeg
def test_cli_check_exit_code_reflects_errors(tmp_path):
    from releaser import cli, service

    release, root = build_release(tmp_path)
    service.build(release, root, service.BuildOptions(nfo=False))
    with (root / "01-x.flac").open("ab") as handle:
        handle.write(b"kaputt")

    assert cli.main(["check", str(root)]) == 1
