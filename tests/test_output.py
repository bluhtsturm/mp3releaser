"""Ausgabeordner: das fertige Release wandert aus dem Eingang heraus.

Im Container sind Eingang und Ausgang zwei Volumes - fuer den Kernel zwei
Dateisysteme. ``rename`` scheitert dort mit EXDEV; das wird hier nachgestellt,
indem ``Path.rename`` fuer Wege zwischen den beiden Ordnern genau so scheitert.
"""

import errno
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser import undo
from releaser.model import Disc, Release, Track
from releaser.output import check_move, move_path, move_release


def make_tree(tmp_path: Path) -> tuple[Path, Path, Release]:
    root = tmp_path / "eingang" / "Artist-Album-2026-GRP"
    (root / "CD1").mkdir(parents=True)
    (root / "CD1" / "01-a.mp3").write_bytes(b"a" * 10)
    (root / "x.nfo").write_bytes(b"nfo")
    out = tmp_path / "ausgang"
    out.mkdir()
    release = Release(artist="A", album="B", dirname=root.name, discs=[
        Disc(1, tracks=[Track(1, "a", 1.0, path=str(root / "CD1" / "01-a.mp3"))])])
    return root, out, release


@pytest.fixture
def other_filesystem(monkeypatch):
    """``rename`` von eingang nach ausgang (und zurueck) scheitert wie bei
    zwei Dateisystemen."""
    real = Path.rename
    calls = []

    def rename(self, target):
        src, dst = str(self), str(target)
        if ("eingang" in src) != ("eingang" in dst):
            calls.append((src, dst))
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    return calls


def test_move_release_moves_and_follows_the_paths(tmp_path):
    root, out, release = make_tree(tmp_path)
    new_root, entry = move_release(release, root, out)
    assert new_root == out / root.name
    assert not root.exists()
    assert (new_root / "CD1" / "01-a.mp3").read_bytes() == b"a" * 10
    assert release.tracks[0].path == str(new_root / "CD1" / "01-a.mp3")
    assert entry.kind is undo.Kind.MOVE
    assert undo.last().kind is undo.Kind.MOVE


def test_move_across_filesystems_copies_and_removes(tmp_path, other_filesystem):
    root, out, release = make_tree(tmp_path)
    new_root, _ = move_release(release, root, out)
    assert other_filesystem, "rename haette scheitern muessen"
    assert not root.exists()
    assert (new_root / "x.nfo").read_bytes() == b"nfo"


def test_failed_copy_leaves_the_original_and_no_half_copy(tmp_path, monkeypatch,
                                                          other_filesystem):
    import shutil

    root, out, _ = make_tree(tmp_path)

    def broken(src, dst, *args, **kwargs):
        Path(dst).mkdir()
        (Path(dst) / "halb").write_bytes(b"")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copytree", broken)
    with pytest.raises(OSError):
        move_path(root, out / root.name)
    assert (root / "x.nfo").is_file()
    assert not (out / root.name).exists()


def test_undo_brings_the_release_back_across_filesystems(tmp_path,
                                                         other_filesystem):
    root, out, release = make_tree(tmp_path)
    move_release(release, root, out)
    entry = undo.last()
    assert undo.check(entry) == []
    undo.undo(entry)
    assert (root / "CD1" / "01-a.mp3").is_file()
    assert not (out / root.name).exists()


def test_existing_target_is_never_overwritten(tmp_path):
    root, out, release = make_tree(tmp_path)
    (out / root.name).mkdir()
    (out / root.name / "alt.txt").write_text("alt")
    assert check_move(root, out) == [f"Im Ausgabeordner gibt es schon {root.name}"]
    with pytest.raises(ValueError):
        move_release(release, root, out)
    assert (out / root.name / "alt.txt").read_text() == "alt"
    assert root.is_dir()


def test_check_uses_the_name_after_renaming(tmp_path):
    root, out, _ = make_tree(tmp_path)
    (out / "neuer_name").mkdir()
    assert check_move(root, out) == []
    assert check_move(root, out, "neuer_name")


def test_output_inside_the_release_is_refused(tmp_path):
    root, _, _ = make_tree(tmp_path)
    assert "im Release selbst" in check_move(root, root / "CD1")[0]
    assert "im Release selbst" in check_move(root, root)[0]


def test_missing_output_dir_is_reported(tmp_path):
    root, out, _ = make_tree(tmp_path)
    assert "gibt es nicht" in check_move(root, out / "fehlt")[0]


def test_release_already_in_the_output_stays(tmp_path):
    root, _, release = make_tree(tmp_path)
    new_root, entry = move_release(release, root, root.parent)
    assert new_root == root and entry is None
    assert root.is_dir()
