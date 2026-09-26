"""Tests für die mitgelieferte Standardvorlage."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.checks import check_template_file
from releaser.fields import FIELDS
from releaser.model import Disc, Release, Track
from releaser.skl import Template
from releaser.tags import REGISTRY

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "templates" / "standard.skl"

#: Tags, die bewusst fehlen: Ausrichtungsvarianten eines Wertes, der schon
#: drinsteht, reine Positionsmarker und ein im Original unbenutzter Tag.
DELIBERATELY_ABSENT = {
    # andere Ausrichtung desselben Wertes
    "Releasenc", "RName", "RNameCnt", "Cnt2ndUrl", "Y", "10Hz", "Size#",
    "Tpti#", "hhLTpti", "hhhTpti", "Cpti", "hhLCpti", "hhhCpti",
    "hhLPtit", "hhhPtit",
    # Positionsmarker ohne Inhalt, und im Original unbenutzt
    "Notesmark", "Notesmarkend", "Bm",
}


def template() -> Template:
    return Template.from_file(STANDARD)


def test_every_enterable_field_is_in_the_template():
    """Alles, was sich in einer Oberfläche eintragen lässt, muss drinstehen."""
    tags = template().tag_names()
    missing = [f.tag for f in FIELDS if f.tag and f.tag not in tags]
    assert not missing, missing


def test_every_tag_is_either_present_or_deliberately_absent():
    """Kein Tag darf einfach vergessen sein."""
    tags = template().tag_names()
    forgotten = set(REGISTRY) - tags - DELIBERATELY_ABSENT
    assert not forgotten, sorted(forgotten)
    # und die Ausnahmeliste darf nichts enthalten, was doch drinsteht
    assert not (DELIBERATELY_ABSENT & tags)


def test_the_template_passes_its_own_check():
    report = check_template_file(STANDARD)
    assert report.clean, report.render()


def test_every_line_has_the_same_width():
    lines = STANDARD.read_bytes().decode("cp437").split("\r\n")
    widths = {len(line) for line in lines if line}
    assert widths == {78}


def test_fits_the_conventional_nfo_width():
    lines = STANDARD.read_bytes().decode("cp437").split("\r\n")
    assert max(len(line) for line in lines) <= 80


def test_uses_crlf_like_an_nfo():
    assert b"\r\n" in STANDARD.read_bytes()


def test_renders_a_full_release_at_constant_width():
    release = Release(
        artist="Die Ärzte", album="Ein Album", album_addition="(Deluxe)",
        year=2026, genre="Punk", source="CDDA", audio_format="FLAC",
        catalog_no="HA-001", company="Label", ripper="jemand",
        url="https://example.invalid", samplerate=44100, bits_per_sample=16,
        notes=["Eine längere Notiz, die in die Fortsetzungszeile umbrechen "
               "muss, weil sie breiter ist als das Feld.", "Zweite."],
        group_news=["Neuigkeit"],
        discs=[Disc(1, tracks=[Track(1, "Kurz", 60.0), Track(
                   2, "Ein ziemlich langer Titel, der umbrechen muss, "
                   "weil er nicht passt", 200.0)]),
               Disc(2, tracks=[Track(1, "Bonus", 100.0)])])

    text = template().render(release, trim_trailing=False)
    widths = {len(line) for line in text.split("\n") if line}
    assert widths == {78}

    for expected in ("Die Ärzte", "Ein Album (Deluxe)", "HA-001", "CD1", "CD2",
                     "Zweite.", "Neuigkeit", "Samplerate (kHz): 44.1"):
        assert expected in text, expected


def test_track_titles_wrap_instead_of_being_cut():
    assert template().track_layout()[1] is True


def test_generator_is_reproducible(tmp_path):
    """Wer den Generator erneut laufen lässt, bekommt dieselbe Datei."""
    before = STANDARD.read_bytes()
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "make_standard_skl.py")],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert STANDARD.read_bytes() == before


# ============================================== automatisch geladen


def test_bundled_template_is_found():
    from releaser.service import bundled_template

    assert bundled_template() == STANDARD


def test_appimage_location_wins(tmp_path, monkeypatch):
    from releaser.service import bundled_template

    share = tmp_path / "usr" / "share" / "mp3releaser"
    share.mkdir(parents=True)
    (share / "standard.skl").write_bytes(STANDARD.read_bytes())
    monkeypatch.setenv("APPDIR", str(tmp_path))
    assert bundled_template() == share / "standard.skl"


def test_desktop_starts_with_the_standard_template():
    from releaser.frontends.gtkui import build_state

    assert build_state().template_path == STANDARD


def test_an_explicit_template_beats_the_standard(tmp_path):
    from releaser.frontends.gtkui import build_state

    own = tmp_path / "eigen.skl"
    own.write_bytes("#Artist   \n".encode("cp437"))
    assert build_state(template=str(own)).template_path == own


def test_web_session_starts_with_the_standard_template():
    import pytest

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from releaser.browse import Mount, MountedSource
    from releaser.frontends.web.app import create_app

    client = TestClient(create_app(MountedSource([Mount("m", ROOT)]),
                                   templates_dir=ROOT / "templates"))
    assert client.get("/api/state").json()["template"] == "standard.skl"
