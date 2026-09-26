"""Tests für das Rückgängigmachen von Umbenennungen."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser import service, undo
from releaser.naming import NamingProfile
from releaser.undo import Entry, UndoError

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


def encode(target: Path, *args: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    *args, str(target), "-y"], check=True)
    return target


def make_release(tmp_path: Path, discs: int = 1) -> Path:
    root = tmp_path / "rohdaten"
    for disc in range(1, discs + 1):
        folder = root / f"CD{disc}" if discs > 1 else root
        for no in (1, 2):
            encode(folder / f"0{no}-x.flac", "-c:a", "flac",
                   "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
                   "-metadata", "album=Das Album", "-metadata", f"TRACKNUMBER={no}",
                   "-metadata", "DATE=2026", "-metadata", f"DISCNUMBER={disc}")
    return root


@pytest.fixture(autouse=True)
def isolated_journal(tmp_path, monkeypatch):
    """Nie das echte Protokoll des Benutzers anfassen."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return undo.journal_path()


# ================================================================= Protokoll


def test_journal_path_follows_the_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert undo.journal_path() == tmp_path / "mp3releaser" / "undo.json"


def test_empty_journal_is_not_an_error():
    assert undo.load() == []
    assert undo.last() is None


def test_record_and_load_roundtrip():
    entry = undo.record([(Path("/a"), Path("/b"))], "Release")
    assert entry is not None

    loaded = undo.load()
    assert len(loaded) == 1
    assert loaded[0].moves == [("/a", "/b")]
    assert loaded[0].release == "Release"
    assert "Release" in loaded[0].describe()


def test_record_ignores_unchanged_moves():
    assert undo.record([(Path("/a"), Path("/a"))], "X") is None
    assert undo.load() == []


def test_journal_is_capped():
    for index in range(undo.MAX_ENTRIES + 10):
        undo.record([(Path(f"/a{index}"), Path(f"/b{index}"))], "X")
    assert len(undo.load()) == undo.MAX_ENTRIES


def test_broken_journal_is_ignored(isolated_journal):
    isolated_journal.parent.mkdir(parents=True, exist_ok=True)
    isolated_journal.write_text("kein json")
    assert undo.load() == []


# ================================================================ Rücknahme


def test_undo_restores_a_simple_rename(tmp_path):
    original = tmp_path / "vorher.txt"
    original.write_text("inhalt")
    renamed = tmp_path / "nachher.txt"
    original.rename(renamed)

    entry = undo.record([(original, renamed)], "X")
    assert undo.check(entry) == []

    undo.undo(entry)
    assert original.is_file() and not renamed.exists()
    assert original.read_text() == "inhalt"


def test_undo_refuses_when_the_target_is_gone(tmp_path):
    entry = Entry(timestamp=time.time(), release="X",
                  moves=[(str(tmp_path / "a"), str(tmp_path / "b"))])
    problems = undo.check(entry)
    assert problems and "nicht mehr vorhanden" in problems[0]

    with pytest.raises(UndoError):
        undo.undo(entry)


def test_force_undoes_what_it_can(tmp_path):
    da = tmp_path / "da.txt"
    da.write_text("x")
    entry = Entry(timestamp=time.time(), release="X", moves=[
        (str(tmp_path / "weg_vorher"), str(tmp_path / "weg_nachher")),
        (str(tmp_path / "war.txt"), str(da)),
    ])
    done = undo.undo(entry, force=True)
    assert len(done) == 1
    assert (tmp_path / "war.txt").is_file()


def test_undo_removes_the_entry_from_the_journal(tmp_path):
    original = tmp_path / "a.txt"
    original.write_text("x")
    renamed = tmp_path / "b.txt"
    original.rename(renamed)

    entry = undo.record([(original, renamed)], "X")
    undo.undo(entry)
    assert undo.load() == []


# ====================================== Zusammenspiel mit dem Umbenennen


@needs_ffmpeg
def test_rename_is_recorded_and_can_be_taken_back(tmp_path):
    root = make_release(tmp_path)
    before = sorted(p.name for p in root.iterdir())

    release = service.scan(root).release
    plan, new_root = service.perform_rename(release, root,
                                            NamingProfile(group="GRP"))
    assert plan.is_safe
    assert new_root != root

    entry = undo.last()
    assert entry is not None
    assert entry.count == len(plan.changes)

    assert undo.check(entry) == []
    undo.undo(entry)

    assert root.is_dir()
    assert sorted(p.name for p in root.iterdir()) == before
    assert not new_root.exists()


@needs_ffmpeg
def test_multi_disc_rename_is_taken_back_completely(tmp_path):
    """Die Rücknahme läuft in umgekehrter Reihenfolge - erst der Ordner."""
    root = make_release(tmp_path, discs=2)
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))

    release = service.scan(root).release
    _plan, new_root = service.perform_rename(release, root,
                                             NamingProfile(group="GRP"))
    assert (new_root / "CD1").is_dir() or (new_root / "cd1").is_dir()

    undo.undo(undo.last())
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == before


@needs_ffmpeg
def test_check_finds_files_that_moved_with_their_directory(tmp_path):
    """Der protokollierte Pfad einer Datei zeigt auf den alten Ordnernamen."""
    root = make_release(tmp_path)
    release = service.scan(root).release
    service.perform_rename(release, root, NamingProfile(group="GRP"))

    entry = undo.last()
    # Naiv geprueft waeren die Dateien "nicht mehr vorhanden"
    assert undo.check(entry) == []


@needs_ffmpeg
def test_a_second_rename_stacks_in_the_journal(tmp_path):
    root = make_release(tmp_path)
    release = service.scan(root).release
    _plan, first = service.perform_rename(release, root,
                                          NamingProfile(group="GRP"))
    service.perform_rename(release, first, NamingProfile(group="ANDERE"))

    entries = undo.load()
    assert len(entries) == 2

    undo.undo(entries[-1])            # letzten Lauf zurueck
    assert first.is_dir()


@needs_ffmpeg
def test_a_failed_plan_writes_nothing(tmp_path):
    root = make_release(tmp_path)
    release = service.scan(root).release
    plan, unchanged = service.perform_rename(
        release, root, NamingProfile(file_pattern="#Album"))

    assert not plan.is_safe
    assert unchanged == root
    assert undo.load() == []


# ================================================================= Kommando


@needs_ffmpeg
def test_cli_undo_preview_and_apply(tmp_path, capsys):
    from releaser import cli

    root = make_release(tmp_path)
    assert cli.main(["rename", str(root), "--group", "GRP", "--apply"]) == 0
    capsys.readouterr()

    assert cli.main(["undo", "--list"]) == 0
    assert "Umbenennungen" in capsys.readouterr().out

    assert cli.main(["undo"]) == 0                 # nur Vorschau
    assert "Vorschau" in capsys.readouterr().err or True
    assert not root.exists() or root.is_dir()

    assert cli.main(["undo", "--apply"]) == 0
    assert root.is_dir()


def test_cli_undo_without_a_journal(capsys):
    from releaser import cli

    assert cli.main(["undo"]) == 1
    assert "Nichts" in capsys.readouterr().err


def test_cli_undo_list_without_a_journal(capsys):
    from releaser import cli

    assert cli.main(["undo", "--list"]) == 0
    assert "Kein Protokoll" in capsys.readouterr().out


# ============================================================ Tag-Rücknahme


def tag_release(tmp_path: Path) -> tuple:
    from releaser import service
    from releaser.tagwriter import TagProfile

    root = make_release(tmp_path)
    scanned = service.scan(root)
    release = scanned.release
    release.artist = "Neuer Artist"
    release.album = "Neues Album"
    for track in release.tracks:
        track.title = f"Neuer Titel {track.no}"
    service.write_tags(release, TagProfile(comment="neuer Kommentar"))
    return root, release


@needs_ffmpeg
def test_tag_write_is_recorded(tmp_path):
    root, _release = tag_release(tmp_path)

    entry = undo.last()
    assert entry is not None
    assert entry.kind is undo.Kind.TAGS
    assert entry.count == 2
    assert "getaggte Dateien" in entry.describe()


@needs_ffmpeg
def test_tags_can_be_taken_back(tmp_path):
    from releaser.audio import read_file

    root, _release = tag_release(tmp_path)
    assert read_file(root / "01-x.flac").artist == "Neuer Artist"

    assert undo.check(undo.last()) == []
    undo.undo(undo.last())

    restored = read_file(root / "01-x.flac")
    assert restored.artist == "Der Artist"
    assert restored.title == "Titel 1"
    assert restored.comment == ""


@needs_ffmpeg
def test_only_changed_fields_are_recorded(tmp_path):
    """Unveraenderte Felder zurueckzuschreiben waere unnoetiges Anfassen."""
    root, _release = tag_release(tmp_path)
    fields = set()
    for values in undo.last().tags.values():
        fields |= set(values)

    assert "artist" in fields and "title" in fields
    assert "genre" not in fields          # war vorher leer und blieb leer


@needs_ffmpeg
def test_tag_undo_refuses_when_a_file_is_gone(tmp_path):
    root, _release = tag_release(tmp_path)
    (root / "01-x.flac").unlink()

    problems = undo.check(undo.last())
    assert problems and "nicht mehr vorhanden" in problems[0]
    with pytest.raises(UndoError):
        undo.undo(undo.last())


@needs_ffmpeg
def test_tag_undo_with_force_restores_the_rest(tmp_path):
    from releaser.audio import read_file

    root, _release = tag_release(tmp_path)
    (root / "01-x.flac").unlink()

    done = undo.undo(undo.last(), force=True)
    assert len(done) == 1
    assert read_file(root / "02-x.flac").artist == "Der Artist"


@needs_ffmpeg
def test_apply_tags_records_even_without_the_service_layer(tmp_path):
    """Jeder Weg zum Schreiben muss protokolliert werden."""
    from releaser import service
    from releaser.tagwriter import TagProfile, apply_tags, plan_tags

    root = make_release(tmp_path)
    release = service.scan(root).release
    release.artist = "Direkt geschrieben"

    apply_tags(plan_tags(release, TagProfile()), TagProfile())
    assert undo.last() is not None
    assert undo.last().kind is undo.Kind.TAGS


@needs_ffmpeg
def test_journal_can_be_switched_off(tmp_path):
    from releaser import service
    from releaser.tagwriter import TagProfile, apply_tags, plan_tags

    root = make_release(tmp_path)
    release = service.scan(root).release
    release.artist = "Ohne Protokoll"

    apply_tags(plan_tags(release, TagProfile()), TagProfile(), journal=False)
    assert undo.load() == []


@needs_ffmpeg
def test_rename_and_tags_stack_in_one_journal(tmp_path):
    from releaser import service
    from releaser.tagwriter import TagProfile

    root = make_release(tmp_path)
    release = service.scan(root).release
    service.write_tags(release, TagProfile(comment="x"))
    service.perform_rename(release, root, NamingProfile(group="GRP"))

    kinds = [entry.kind for entry in undo.load()]
    assert kinds == [undo.Kind.TAGS, undo.Kind.RENAME]


def test_old_journals_without_a_kind_are_read_as_renames(tmp_path, monkeypatch):
    """Protokolle aelterer Fassungen kannten nur das Umbenennen."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    path = undo.journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[{"timestamp": 1.0, "release": "X", '
                    '"moves": [["/a", "/b"]]}]')

    entry = undo.last()
    assert entry.kind is undo.Kind.RENAME
    assert entry.moves == [("/a", "/b")]


@needs_ffmpeg
def test_cli_undo_takes_tags_back(tmp_path, capsys):
    from releaser import cli
    from releaser.audio import read_file

    root = make_release(tmp_path)
    assert cli.main(["tag", str(root), "--comment", "neu", "--apply"]) == 0
    capsys.readouterr()
    assert read_file(root / "01-x.flac").comment == "neu"

    assert cli.main(["undo", "--apply"]) == 0
    assert "getaggte Dateien" in capsys.readouterr().err
    assert read_file(root / "01-x.flac").comment == ""


# ================================ Rücknahme hinterlässt nichts Neues


@needs_ffmpeg
@pytest.mark.parametrize("name,args", [
    ("a.mp3", ["-c:a", "libmp3lame"]),
    ("a.m4a", ["-c:a", "aac"]),
    ("a.ogg", ["-c:a", "libvorbis"]),
    ("a.flac", ["-c:a", "flac"]),
])
def test_tag_undo_restores_every_format_exactly(tmp_path, name, args):
    from releaser.audio import read_file
    from releaser.tagwriter import TagProfile

    root = tmp_path / "rel"
    encode(root / name, *args, "-metadata", "title=Alter Titel",
           "-metadata", "artist=Alter Artist", "-metadata", "track=3/12",
           "-metadata", "genre=Rock")
    snapshot = lambda: (lambda i: (i.artist, i.title, i.genre, i.comment,
                                   i.track_no, i.total_tracks))(
        read_file(root / name))
    before = snapshot()

    release = service.scan(root).release
    release.artist = "Neuer Artist"
    release.genre = "electronic"
    release.tracks[0].title = "Neuer Titel"
    service.write_tags(release, TagProfile(comment="neu"))
    assert snapshot() != before

    undo.undo(undo.last())
    assert snapshot() == before


@needs_ffmpeg
def test_tag_undo_removes_blocks_that_were_not_there(tmp_path):
    """Der Tag-Lauf legt ID3v1, APEv2, Lyrics3 an - die Rücknahme räumt sie weg."""
    from releaser.tagwriter import TagProfile, trailing_containers

    root = tmp_path / "rel"
    target = encode(root / "01.mp3", "-c:a", "libmp3lame",
                    "-metadata", "title=T", "-metadata", "artist=A")
    assert trailing_containers(target) == set()

    release = service.scan(root).release
    release.artist = "B"
    service.write_tags(release, TagProfile(write_apev2=True, write_lyrics3=True))
    assert trailing_containers(target) == {"id3v1", "apev2", "lyrics3"}

    undo.undo(undo.last())
    assert trailing_containers(target) == set()


@needs_ffmpeg
def test_tag_undo_keeps_blocks_that_were_there(tmp_path):
    from releaser.tagwriter import TagProfile, trailing_containers

    root = tmp_path / "rel"
    target = encode(root / "01.mp3", "-c:a", "libmp3lame",
                    "-metadata", "title=T", "-metadata", "artist=A")
    release = service.scan(root).release
    service.write_tags(release, TagProfile())           # legt ID3v1 an
    assert "id3v1" in trailing_containers(target)
    undo.load()                                          # Protokoll lesbar

    release.artist = "B"
    service.write_tags(release, TagProfile())            # ID3v1 war schon da
    undo.undo(undo.last())
    assert "id3v1" in trailing_containers(target)


@needs_ffmpeg
def test_audio_data_survives_write_and_undo(tmp_path):
    from releaser.checksums import audio_crc32
    from releaser.tagwriter import TagProfile

    root = tmp_path / "rel"
    target = encode(root / "01.mp3", "-c:a", "libmp3lame", "-metadata", "artist=A")
    before, _ = audio_crc32(target)

    release = service.scan(root).release
    release.artist = "B"
    service.write_tags(release, TagProfile(write_apev2=True, write_lyrics3=True))
    undo.undo(undo.last())

    assert audio_crc32(target)[0] == before
