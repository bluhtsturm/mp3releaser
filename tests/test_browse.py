"""Tests für die Dateiauswahl.

Der Schwerpunkt liegt auf :class:`MountedSource`: dort ist die Beschränkung
eine Zusage an den Betreiber, und die muss halten. Getestet wird deshalb nicht
nur, dass der Normalfall funktioniert, sondern vor allem, dass die
Ausbruchsversuche scheitern.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.browse import (
    AccessError,
    Entry,
    Kind,
    LocalSource,
    Mount,
    MountedSource,
    classify_file,
    count_audio,
    describe,
    from_environment,
)


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Ein kleiner Baum mit einem Release und etwas Beiwerk."""
    release = tmp_path / "eingang" / "Artist-Album-2026-GRP"
    (release / "CD1").mkdir(parents=True)
    (release / "CD2").mkdir()
    for disc, count in (("CD1", 2), ("CD2", 1)):
        for no in range(1, count + 1):
            (release / disc / f"0{no}-x.mp3").write_bytes(b"\xff\xfb")
    (release / "00-artist-album.nfo").write_bytes(b"nfo")
    (release / "folder.jpg").write_bytes(b"\xff\xd8")
    (tmp_path / "eingang" / "leer").mkdir()
    (tmp_path / "geheim").mkdir()
    (tmp_path / "geheim" / "passwoerter.txt").write_text("geheim")
    return tmp_path


def mounted(tree: Path) -> MountedSource:
    return MountedSource([Mount("eingang", tree / "eingang")])


# ------------------------------------------------------------- Einordnung


@pytest.mark.parametrize("name,kind", [
    ("a.mp3", Kind.AUDIO),
    ("a.flac", Kind.AUDIO),
    ("a.m4a", Kind.AUDIO),
    ("a.nfo", Kind.COMPANION),
    ("a.sfv", Kind.COMPANION),
    ("a.jpg", Kind.COVER),
    ("a.cue", Kind.CUE),
    ("a.txt", Kind.OTHER),
])
def test_classify_file(name, kind):
    assert classify_file(Path(name)) is kind


def test_count_audio_includes_one_level_of_subdirectories(tree):
    release = tree / "eingang" / "Artist-Album-2026-GRP"
    assert count_audio(release) == 3          # CD1 mit 2, CD2 mit 1
    assert count_audio(tree / "eingang" / "leer") == 0


def test_count_audio_survives_unreadable_directories(tmp_path):
    blocked = tmp_path / "gesperrt"
    blocked.mkdir()
    (blocked / "x.mp3").write_bytes(b"\xff\xfb")
    os.chmod(blocked, 0o000)
    try:
        assert count_audio(tmp_path) >= 0     # kein Absturz
    finally:
        os.chmod(blocked, 0o755)


# ---------------------------------------------------------- lokale Quelle


def test_local_source_lists_real_paths(tree):
    source = LocalSource(tree)
    entries = {e.name: e for e in source.list(str(tree / "eingang"))}
    assert set(entries) == {"Artist-Album-2026-GRP", "leer"}
    assert entries["Artist-Album-2026-GRP"].kind is Kind.RELEASE
    assert entries["leer"].kind is Kind.DIRECTORY
    assert entries["Artist-Album-2026-GRP"].path.startswith(str(tree))


def test_local_source_reaches_everywhere(tree):
    """Die lokale Form sieht das ganze Dateisystem - das ist Absicht."""
    source = LocalSource(tree / "eingang")
    entries = source.list(str(tree / "geheim"))
    assert [e.name for e in entries] == ["passwoerter.txt"]


def test_local_source_roots_include_home():
    roots = LocalSource().roots()
    assert roots
    assert any(e.path == str(Path.home().resolve()) for e in roots)


# ------------------------------------------------------ eingehängte Quelle


def test_mounted_source_lists_by_mount_name(tree):
    source = mounted(tree)
    assert [e.name for e in source.roots()] == ["eingang"]

    entries = source.list("eingang")
    assert sorted(e.name for e in entries) == ["Artist-Album-2026-GRP", "leer"]
    # Nach außen nur virtuelle Pfade, keine Wirtspfade
    assert all(not e.path.startswith("/") for e in entries)
    assert entries[0].path == "eingang/Artist-Album-2026-GRP"


def test_mounted_source_lists_release_contents(tree):
    source = mounted(tree)
    entries = {e.name: e for e in source.list("eingang/Artist-Album-2026-GRP")}
    assert entries["CD1"].kind is Kind.RELEASE
    assert entries["00-artist-album.nfo"].kind is Kind.COMPANION
    assert entries["folder.jpg"].kind is Kind.COVER


def test_releases_filters_to_release_directories(tree):
    source = mounted(tree)
    assert [e.name for e in source.releases("eingang")] == ["Artist-Album-2026-GRP"]


def test_hidden_files_need_to_be_asked_for(tree):
    (tree / "eingang" / ".versteckt").mkdir()
    source = mounted(tree)
    assert ".versteckt" not in [e.name for e in source.list("eingang")]
    assert ".versteckt" in [e.name for e in source.list("eingang", show_hidden=True)]


# ------------------------------------------------------- Ausbruchsversuche


@pytest.mark.parametrize("attempt", [
    "eingang/..",
    "eingang/../geheim",
    "eingang/../../etc",
    "../geheim",
    "eingang/./../geheim",
    "/etc",
    "/etc/passwd",
    "",
    "   ",
])
def test_mounted_source_refuses_to_leave_the_mount(tree, attempt):
    source = mounted(tree)
    with pytest.raises(AccessError):
        source.resolve(attempt)


def test_unknown_mount_name_is_refused(tree):
    with pytest.raises(AccessError):
        mounted(tree).resolve("geheim/passwoerter.txt")


def test_symlink_out_of_the_mount_is_refused(tree):
    """Ein Symlink zeigt beim Auflösen nach draußen - das muss auffallen."""
    link = tree / "eingang" / "abkuerzung"
    link.symlink_to(tree / "geheim")
    source = mounted(tree)
    with pytest.raises(AccessError):
        source.resolve("eingang/abkuerzung/passwoerter.txt")


def test_symlink_inside_the_mount_stays_allowed(tree):
    link = tree / "eingang" / "kurz"
    link.symlink_to(tree / "eingang" / "Artist-Album-2026-GRP")
    source = mounted(tree)
    assert source.resolve("kurz" if False else "eingang/kurz").is_dir()


def test_null_byte_is_refused(tree):
    with pytest.raises(AccessError):
        mounted(tree).resolve("eingang/x\x00y")


def test_to_virtual_refuses_outside_paths(tree):
    with pytest.raises(AccessError):
        mounted(tree).to_virtual(tree / "geheim")


def test_duplicate_mount_names_are_rejected(tree):
    with pytest.raises(ValueError):
        MountedSource([Mount("a", tree), Mount("a", tree / "eingang")])


# ---------------------------------------------------------- Konfiguration


def test_from_environment_parses_docker_style(tmp_path):
    (tmp_path / "ein").mkdir()
    (tmp_path / "archiv").mkdir()
    source = from_environment(
        f"eingang:{tmp_path / 'ein'},archiv:{tmp_path / 'archiv'}:ro")
    assert source.names == ["eingang", "archiv"]
    assert source.is_writable("eingang") is True
    assert source.is_writable("archiv/irgendwas") is False


def test_from_environment_empty_gives_no_mounts():
    assert from_environment("").mounts == []


def test_from_environment_rejects_broken_entries():
    with pytest.raises(ValueError):
        from_environment("nurname")


def test_missing_mount_directory_is_not_listed(tmp_path):
    source = MountedSource([Mount("fehlt", tmp_path / "gibtsnicht")])
    assert source.roots() == []
    assert describe(source)["mounts"][0]["exists"] is False


# ------------------------------------------------------------ Beschreibung


def test_describe_makes_the_difference_visible(tree):
    local = describe(LocalSource(tree))
    remote = describe(mounted(tree))

    assert local["scope"] == "das gesamte Dateisystem des Nutzers"
    assert remote["scope"] == "nur was eingehängt wurde"
    assert remote["mounts"][0]["name"] == "eingang"


def test_both_sources_return_the_same_entry_type(tree):
    local = LocalSource(tree).list(str(tree / "eingang"))
    remote = mounted(tree).list("eingang")
    assert all(isinstance(e, Entry) for e in local + remote)
    assert {e.name for e in local} == {e.name for e in remote}


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg nicht vorhanden")
def test_service_accepts_a_path_from_either_source(tmp_path):
    """Was die Auswahl liefert, muss die Dienstschicht verarbeiten können."""
    from releaser import service

    release = tmp_path / "eingang" / "Artist-Album-2026-GRP"
    release.mkdir(parents=True)
    for no in (1, 2):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        "-c:a", "libmp3lame",
                        "-metadata", f"title=Titel {no}",
                        "-metadata", "artist=Der Artist",
                        "-metadata", "album=Das Album",
                        str(release / f"0{no}-x.mp3"), "-y"], check=True)

    source = MountedSource([Mount("eingang", tmp_path / "eingang")])
    entry = source.releases("eingang")[0]
    real = source.resolve(entry.path)

    assert entry.path == "eingang/Artist-Album-2026-GRP"   # virtuell nach aussen
    outcome = service.scan(real)                            # echt nach innen
    assert outcome.release.total_tracks == 2


# ============================================ Nicht lesbare Pfade


@pytest.mark.parametrize("length", [256, 5000])
def test_overlong_path_components_are_refused(tree, length):
    """Sonst wirft erst das Betriebssystem - mitten in der Anzeige."""
    source = mounted(tree)
    with pytest.raises(AccessError) as error:
        source.resolve("eingang/" + "a" * length)
    assert "zu lang" in str(error.value)


def test_local_source_also_refuses_overlong_names(tree):
    with pytest.raises(AccessError):
        LocalSource(tree).resolve("x" * 300)


def test_listing_a_file_is_reported(tree):
    source = mounted(tree)
    with pytest.raises(AccessError) as error:
        source.list("eingang/Artist-Album-2026-GRP/00-artist-album.nfo")
    assert "kein Verzeichnis" in str(error.value)
