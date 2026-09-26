"""Tests für die Benutzbarkeit als Ganzes.

Deckt ab, was beim Durchgehen des Codes aufgefallen ist: öffentliche API,
Schichtentrennung, CLI-Fehlerverhalten, Sampler-Releases und die Audio-CRC-
Behandlung im MP4-Container.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import releaser
from releaser import cli
from releaser.checksums import audio_crc32, crc32_file
from releaser.model import Disc, Release, Track
from releaser.naming import check_filename_lengths

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


def encode(target: Path, *args: str, duration: str = "1") -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
                    *args, str(target), "-y"], check=True)
    return target


# ------------------------------------------------------------ Öffentliche API


def test_package_exports_are_importable():
    for name in releaser.__all__:
        assert hasattr(releaser, name), name


def test_version_is_set():
    assert releaser.__version__.count(".") == 2


def test_audio_layer_is_lazily_exposed():
    assert callable(releaser.scan_directory)
    assert callable(releaser.read_file)


def test_unknown_attribute_still_raises():
    with pytest.raises(AttributeError):
        releaser.gibtsnicht


def test_renderer_works_without_the_audio_layer():
    """Der NFO-Teil darf nicht von mutagen abhängen."""
    from releaser import NamingProfile, Release, Template, release_dirname

    release = Release(artist="X", album="Y", year=2026)
    assert Template.parse("#Artist  ").render(release).strip() == "X"
    assert release_dirname(release, NamingProfile(group="GRP")) == "x-y-2026-grp"


# ------------------------------------------------------------- CLI-Verhalten


@pytest.mark.parametrize("argv", [
    ["scan", "/gibt/es/nicht"],
    ["verify", "/gibt/es/nicht.sfv"],
    ["inspect", "/gibt/es/nicht.skl"],
])
def test_cli_reports_errors_without_traceback(capsys, argv):
    code = cli.main(argv)
    assert code == 2
    err = capsys.readouterr().err
    assert err.startswith("Fehler:")
    assert "Traceback" not in err


def test_cli_scan_on_empty_directory(tmp_path, capsys):
    assert cli.main(["scan", str(tmp_path)]) == 2
    assert "keine Audiodateien" in capsys.readouterr().err


def test_cli_inspect_lists_tags(tmp_path, capsys):
    template = tmp_path / "t.skl"
    template.write_bytes("#Artist   \n#Album    \n".encode("cp437"))
    assert cli.main(["inspect", str(template)]) == 0
    out = capsys.readouterr().out
    assert "#Artist" in out and "#Album" in out


@needs_ffmpeg
def test_cli_build_runs_end_to_end(tmp_path, capsys):
    root = tmp_path / "Artist-Album-2026-GRP"
    for no in (1, 2):
        encode(root / f"0{no}-x.mp3", "-c:a", "libmp3lame",
               "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
               "-metadata", "album=Das Album", "-metadata", f"track={no}/2")
    template = tmp_path / "t.skl"
    template.write_bytes("#Release        \n#N #Trk         \n".encode("cp437"))

    assert cli.main(["build", str(root), str(template)]) == 0
    # Begleitdateien folgen der Schreibweise der *Dateien* (Standard: klein),
    # nicht der des Verzeichnisses
    # Voreinstellung: "00-" vor allen Begleitdateien, Schreibweise der Dateien
    for suffix in (".nfo", ".sfv", ".m3u"):
        assert (root / f"00-artist-album-2026-grp{suffix}").is_file(), suffix


# -------------------------------------------------- Audio-CRC im MP4-Container


@needs_ffmpeg
@pytest.mark.parametrize("name,args", [
    ("a.m4a", ["-c:a", "aac"]),
    ("a.mp4", ["-c:a", "aac"]),
    ("a.m4a", ["-c:a", "alac"]),
])
def test_mp4_audio_crc_differs_from_file_crc(tmp_path, name, args):
    path = encode(tmp_path / name, *args)
    crc, bounds = audio_crc32(path)
    assert crc != crc32_file(path)
    assert any("mdat" in n for n in bounds.notes)


@needs_ffmpeg
def test_mp4_audio_crc_survives_tag_writing(tmp_path):
    from releaser.tagwriter import TagProfile, apply_tags, plan_tags

    path = encode(tmp_path / "a.m4a", "-c:a", "aac")
    before, _ = audio_crc32(path)
    release = Release(artist="X", album="Y", year=2026,
                      discs=[Disc(1, tracks=[Track(1, "Titel", 1.0, 1, str(path))])])
    apply_tags(plan_tags(release), TagProfile(comment="ein langer kommentar"))

    assert crc32_file(path) != before          # SFV wuerde meckern
    assert audio_crc32(path)[0] == before      # Audiodaten unberuehrt


@needs_ffmpeg
def test_verify_recognises_retagged_m4a(tmp_path):
    from releaser.sfv import build_sfv, verify_sfv, write_sfv
    from releaser.tagwriter import TagProfile, apply_tags, plan_tags

    path = encode(tmp_path / "a.m4a", "-c:a", "aac")
    write_sfv(tmp_path / "rel.sfv", build_sfv([path], with_audio_crc=True))

    release = Release(artist="X", album="Y", year=2026,
                      discs=[Disc(1, tracks=[Track(1, "Titel", 1.0, 1, str(path))])])
    apply_tags(plan_tags(release), TagProfile(comment="neuer kommentar"))

    result = verify_sfv(tmp_path / "rel.sfv")
    assert result.retagged == ["a.m4a"]
    assert result.failed == []


# ------------------------------------------------------------ Sampler (VA)


@needs_ffmpeg
def test_various_artists_keep_their_artist_on_the_track(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "VA-Sampler-2026-GRP"
    for no, artist in ((1, "Erster Act"), (2, "Zweiter Act")):
        encode(root / f"0{no}-x.mp3", "-c:a", "libmp3lame",
               "-metadata", f"title=Titel {no}", "-metadata", f"artist={artist}",
               "-metadata", "album=Der Sampler", "-metadata", f"track={no}/2")

    release = scan_directory(root).release
    assert release.artist == "VA"
    assert [t.artist for t in release.tracks] == ["Erster Act", "Zweiter Act"]
    # Titel bleibt sauber - der Artist steckt nicht im Titelfeld
    assert release.tracks[0].title == "Titel 1"


def test_nfo_tracklist_composes_artist_and_title():
    from releaser import Template

    release = Release(artist="VA", discs=[Disc(1, tracks=[
        Track(1, "Titel", 10.0, artist="Erster Act"),
        Track(2, "Anderer", 10.0),
    ])])
    lines = Template.parse("#N #Trk                        ").render(release).split("\n")
    assert lines[0].startswith("01 Erster Act - Titel")
    assert lines[1].startswith("02 Anderer")


@needs_ffmpeg
def test_tag_writing_puts_va_artist_in_the_artist_field(tmp_path):
    from releaser.audio import read_file
    from releaser.tagwriter import TagProfile, apply_tags, plan_tags

    path = encode(tmp_path / "01-x.mp3", "-c:a", "libmp3lame")
    release = Release(artist="VA", album="Der Sampler", year=2026, discs=[
        Disc(1, tracks=[Track(1, "Titel", 1.0, 1, str(path), artist="Erster Act")])])
    apply_tags(plan_tags(release), TagProfile())

    info = read_file(path)
    assert info.artist == "Erster Act"
    assert info.album_artist == "VA"
    assert info.title == "Titel"


# ------------------------------------------------------------ Weitere Formate


@needs_ffmpeg
def test_ogg_vorbis_is_read(tmp_path):
    from releaser.audio import read_file

    path = encode(tmp_path / "a.ogg", "-c:a", "libvorbis", "-ar", "44100", "-ac", "2",
                  "-metadata", "title=Ogg Titel", "-metadata", "artist=Der Artist",
                  "-metadata", "TRACKNUMBER=4/9")
    info = read_file(path)
    assert info.codec == "OGG"
    assert info.title == "Ogg Titel"
    assert (info.track_no, info.total_tracks) == (4, 9)
    assert info.vbr is True


@needs_ffmpeg
def test_opus_is_read_with_estimated_bitrate(tmp_path):
    from releaser.audio import read_file

    path = encode(tmp_path / "a.opus", "-c:a", "libopus",
                  "-metadata", "title=Opus Titel")
    info = read_file(path)
    assert info.codec == "OPUS"
    assert info.samplerate == 48000
    assert info.bitrate and info.bitrate > 0
    assert any("geschätzt" in w for w in info.warnings)


def test_every_registered_extension_is_listed():
    """AUDIO_EXTENSIONS und die Reader-Registry dürfen nicht auseinanderlaufen."""
    from releaser.audio.base import AUDIO_EXTENSIONS, READERS

    assert set(READERS) == set(AUDIO_EXTENSIONS)


# --------------------------------------------------------- Längenprüfung


def test_check_filename_lengths(tmp_path):
    kurz = tmp_path / "kurz.nfo"
    lang = tmp_path / ("x" * 80 + ".sfv")
    warnings = check_filename_lengths([kurz, lang], limit=64)
    assert len(warnings) == 1
    assert "84 Zeichen" in warnings[0]


# ------------------------------------------------------- Begleitdateien


def test_find_and_remove_companions(tmp_path):
    from releaser.companions import find_companions, remove_companions

    (tmp_path / "CD1").mkdir()
    for name in ("alt.nfo", "alt.sfv", "CD1/alt-cd1.m3u", "musik.mp3"):
        (tmp_path / name).write_bytes(b"x")

    found = find_companions(tmp_path)
    assert [p.name for p in found] == ["alt-cd1.m3u", "alt.nfo", "alt.sfv"]

    removed = remove_companions(tmp_path, keep=[tmp_path / "alt.nfo"])
    assert {p.name for p in removed} == {"alt-cd1.m3u", "alt.sfv"}
    assert (tmp_path / "alt.nfo").is_file()
    assert (tmp_path / "musik.mp3").is_file()      # Audiodateien bleiben


@needs_ffmpeg
def test_build_clean_removes_stale_companions(tmp_path, capsys):
    root = tmp_path / "Artist-Album-2026-GRP"
    for no in (1, 2):
        encode(root / f"0{no}-x.mp3", "-c:a", "libmp3lame",
               "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
               "-metadata", "album=Das Album", "-metadata", f"track={no}/2")
    (root / "veraltet.sfv").write_bytes(b"; alt\r\n")
    template = tmp_path / "t.skl"
    template.write_bytes("#Release        \n".encode("cp437"))

    assert cli.main(["build", str(root), str(template), "--clean"]) == 0
    assert not (root / "veraltet.sfv").exists()
    assert (root / "00-artist-album-2026-grp.sfv").is_file()


@needs_ffmpeg
def test_single_artist_release_gets_no_various_artists_warning(tmp_path):
    """Die VA-Meldung darf nur kommen, wenn die Artists sich unterscheiden."""
    from releaser.audio import scan_directory

    root = tmp_path / "rel"
    for no in (1, 2):
        encode(root / f"0{no}-x.mp3", "-c:a", "libmp3lame",
               "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
               "-metadata", "album=Das Album", "-metadata", f"track={no}/2")

    result = scan_directory(root)
    assert result.release.artist == "Der Artist"
    assert not any("VA" in w for w in result.warnings)


def test_unknown_naming_rule_is_reported_without_quotes(tmp_path, capsys):
    """str(KeyError) setzt Anfuehrungszeichen um die Meldung."""
    from releaser import cli

    config = tmp_path / "c.toml"
    config.write_text('[naming]\npipeline = ["gibtsnicht"]\n')
    release = tmp_path / "rel"
    release.mkdir()
    encode(release / "01-x.mp3", "-c:a", "libmp3lame", "-metadata", "artist=A")

    assert cli.main(["--config", str(config), "rename", str(release)]) == 2
    err = capsys.readouterr().err
    assert "unbekannte Namensregel: gibtsnicht" in err
    assert "'unbekannte" not in err


def test_tests_do_not_touch_the_real_user_directories():
    """Die Testabschottung in conftest.py muss greifen."""
    import os
    from pathlib import Path

    home = Path.home()
    for variable in ("XDG_STATE_HOME", "XDG_CONFIG_HOME"):
        value = os.environ.get(variable)
        assert value, variable
        assert not Path(value).is_relative_to(home / ".local"), variable
        assert not Path(value).is_relative_to(home / ".config"), variable


# ------------------------------------------------ Korrekturen (Fehlerdurchsicht)


def _naming_args(tmp_path: Path, config_text: str, *argv: str):
    import argparse

    from releaser.config import load
    from releaser.frontends import cli as frontend

    path = tmp_path / "c.toml"
    path.write_text(config_text, encoding="utf-8")
    parser = argparse.ArgumentParser()
    frontend._add_naming_args(parser)
    args = parser.parse_args(list(argv))
    args._config = load(path)
    return frontend._profile_from_args(args)


def test_no_prefix_beats_the_config(tmp_path):
    """Ein ausdruecklicher Schalter schlaegt die Datei - auch bei --no-prefix."""
    profile = _naming_args(tmp_path, '[naming]\ncompanion_prefix = "00-"\n',
                           "--no-prefix")
    assert profile.companion_prefix == ""


def test_companion_pattern_from_the_config_is_used(tmp_path):
    profile = _naming_args(tmp_path, '[naming]\ncompanion_pattern = "#Catnr"\n')
    assert profile.companion_pattern == "#Catnr"


def test_pipeline_help_names_the_real_default(capsys):
    from releaser.naming import DEFAULT_PIPELINE

    with pytest.raises(SystemExit):
        cli.main(["rename", "--help"])
    help_text = " ".join(capsys.readouterr().out.split())
    assert " ".join(DEFAULT_PIPELINE) in help_text


@needs_ffmpeg
def test_build_takes_the_sfv_comment_from_the_config(tmp_path):
    root = tmp_path / "Artist-Album-2026-GRP"
    encode(root / "01-x.mp3", "-c:a", "libmp3lame",
           "-metadata", "title=Eins", "-metadata", "artist=A",
           "-metadata", "album=B", "-metadata", "track=1")
    template = tmp_path / "t.skl"
    template.write_bytes(b"#Release        \n")
    config = tmp_path / "c.toml"
    config.write_text('[build]\nsfv_comment = "aus der datei"\n',
                      encoding="utf-8")

    assert cli.main(["--config", str(config), "build", str(root),
                     str(template), "--no-nfo", "--no-m3u"]) == 0
    sfv = next(root.glob("*.sfv"))
    assert "; aus der datei" in sfv.read_text(encoding="cp437")


def test_render_reports_an_unknown_track_field(tmp_path):
    import json

    template = tmp_path / "t.skl"
    template.write_bytes(b"#Release        \n")
    release = tmp_path / "r.json"
    release.write_text(json.dumps(
        {"artist": "A", "tracks": [{"no": 1, "title": "x", "titel": "y"}]}),
        encoding="utf-8")
    with pytest.raises(SystemExit, match="titel"):
        cli.main(["render", str(template), str(release)])
