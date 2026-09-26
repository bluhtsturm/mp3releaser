"""Tests für Prüfsummen, SFV und Playlists."""

import shutil
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.checksums import audio_bounds, audio_crc32, crc32_file, format_crc
from releaser.model import Disc, Release, Track
from releaser.playlist import build_entries, m3u_name, render_m3u, write_release_m3us
from releaser.sfv import (
    build_sfv,
    parse_sfv,
    read_sfv,
    sfv_name,
    verify_sfv,
    write_release_sfvs,
    write_sfv,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


# ------------------------------------------------- unabhängige CRC32-Referenz


def reference_crc32(data: bytes) -> int:
    """Bitweise CRC32-Implementierung als unabhängiges Orakel.

    Bewusst nicht zlib - sonst würde der Test die Bibliothek gegen sich selbst
    prüfen.
    """
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def test_reference_matches_zlib():
    payload = bytes(range(256)) * 7
    assert reference_crc32(payload) == zlib.crc32(payload) & 0xFFFFFFFF


def test_crc32_file_matches_reference(tmp_path):
    payload = bytes(range(256)) * 300      # größer als ein Leseblock
    target = tmp_path / "blob.bin"
    target.write_bytes(payload)
    assert crc32_file(target) == reference_crc32(payload)


def test_crc32_file_range(tmp_path):
    payload = b"0123456789" * 10
    target = tmp_path / "blob.bin"
    target.write_bytes(payload)
    assert crc32_file(target, 10, 20) == reference_crc32(payload[10:20])


def test_format_crc_pads_to_eight_digits():
    assert format_crc(0x1234) == "00001234"
    assert format_crc(0xDEADBEEF, uppercase=False) == "deadbeef"


# ------------------------------------------------------------ Audio-Grenzen


def build_fake_mp3(tmp_path: Path, id3v2: int = 0, id3v1: bool = False,
                   ape: bool = False, lyrics: bool = False) -> tuple[Path, bytes]:
    """Baut eine MP3-artige Datei mit wählbaren Tag-Blöcken."""
    audio = b"\xff\xfb\x90\x00" + bytes(range(256)) * 4
    head = b""
    if id3v2:
        size = id3v2 - 10
        synchsafe = bytes(((size >> s) & 0x7F) for s in (21, 14, 7, 0))
        head = b"ID3\x04\x00\x00" + synchsafe + b"\x00" * size
    tail = b""
    if lyrics:
        body = b"L" * 50
        tail += body + f"{len(body):06d}".encode() + b"LYRICS200"
    if ape:
        body = b"A" * 40
        footer = (b"APETAGEX"                             # Magic (8)
                  + (2000).to_bytes(4, "little")           # Version
                  + (len(body) + 32).to_bytes(4, "little")  # Size inkl. Footer
                  + (1).to_bytes(4, "little")              # Item-Anzahl
                  + (0).to_bytes(4, "little")              # Flags
                  + b"\x00" * 8)                           # Reserved
        assert len(footer) == 32
        tail += body + footer
    if id3v1:
        tail += b"TAG" + b"\x00" * 125

    path = tmp_path / "fake.mp3"
    path.write_bytes(head + audio + tail)
    return path, audio


@pytest.mark.parametrize("kwargs", [
    {},
    {"id3v2": 64},
    {"id3v1": True},
    {"ape": True},
    {"lyrics": True},
    {"id3v2": 128, "id3v1": True, "ape": True, "lyrics": True},
])
def test_audio_bounds_strip_all_tag_variants(tmp_path, kwargs):
    path, audio = build_fake_mp3(tmp_path, **kwargs)
    bounds = audio_bounds(path)
    assert path.read_bytes()[bounds.start:bounds.end] == audio
    crc, _ = audio_crc32(path)
    assert crc == reference_crc32(audio)


def test_leading_junk_is_reported(tmp_path):
    path = tmp_path / "junk.mp3"
    path.write_bytes(b"JUNKJUNK" + b"\xff\xfb\x90\x00" * 20)
    bounds = audio_bounds(path)
    assert any("MPEG-Sync" in n for n in bounds.notes)


def test_wav_envelope_is_detected(tmp_path):
    audio = b"\x01\x02\x03\x04" * 16
    body = (b"WAVE" + b"fmt " + (16).to_bytes(4, "little") + b"\x00" * 16
            + b"data" + len(audio).to_bytes(4, "little") + audio)
    path = tmp_path / "env.wav"
    path.write_bytes(b"RIFF" + (len(body) + 4).to_bytes(4, "little") + body)
    bounds = audio_bounds(path)
    assert path.read_bytes()[bounds.start:bounds.end] == audio
    assert any("WAV" in n for n in bounds.notes)


@needs_ffmpeg
def test_retagging_changes_file_crc_but_not_audio_crc(tmp_path):
    from mutagen.id3 import ID3, TIT2

    path = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "libmp3lame", "-b:a", "320k",
                    "-metadata", "title=Alt", str(path), "-y"], check=True)
    file_before = crc32_file(path)
    audio_before, _ = audio_crc32(path)

    tags = ID3(path)
    tags.add(TIT2(encoding=3, text="Ein wesentlich längerer neuer Titel"))
    tags.save()

    assert crc32_file(path) != file_before      # SFV würde jetzt meckern
    assert audio_crc32(path)[0] == audio_before  # Audio ist unberührt


@needs_ffmpeg
def test_flac_metadata_blocks_are_skipped(tmp_path):
    path = tmp_path / "a.flac"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "flac", "-metadata", "title=Titel",
                    str(path), "-y"], check=True)
    bounds = audio_bounds(path)
    assert bounds.start > 4
    assert any("FLAC" in n for n in bounds.notes)
    assert audio_crc32(path)[0] != crc32_file(path)


# ------------------------------------------------------------------- SFV


def make_files(tmp_path: Path, names: list[str]) -> list[Path]:
    paths = []
    for i, name in enumerate(names):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\xff\xfb\x90\x00" + bytes([i]) * 512)
        paths.append(p)
    return paths


def test_sfv_render_and_parse_roundtrip(tmp_path):
    files = make_files(tmp_path, ["01-a.mp3", "02-b.mp3"])
    sfv = build_sfv(files, comments=["Beispielkommentar"])
    text = sfv.render()

    assert text.startswith("; Beispielkommentar\r\n")
    assert text.endswith("\r\n")

    back = parse_sfv(text)
    assert back.comments == ["Beispielkommentar"]
    assert [e.filename for e in back.entries] == ["01-a.mp3", "02-b.mp3"]
    assert [e.crc for e in back.entries] == [e.crc for e in sfv.entries]


def test_sfv_crc_matches_reference(tmp_path):
    files = make_files(tmp_path, ["x.mp3"])
    sfv = build_sfv(files)
    assert sfv.entries[0].crc == reference_crc32(files[0].read_bytes())


def test_sfv_columns_are_aligned(tmp_path):
    files = make_files(tmp_path, ["kurz.mp3", "ein_viel_laengerer_name.mp3"])
    lines = build_sfv(files).render().strip().split("\r\n")
    assert len({len(l) for l in lines}) == 1


def test_audio_crc_comments_roundtrip(tmp_path):
    files = make_files(tmp_path, ["a.mp3"])
    sfv = build_sfv(files, with_audio_crc=True)
    back = parse_sfv(sfv.render())
    assert back.audio_crcs["a.mp3"] == sfv.entries[0].audio_crc
    assert back.comments == []          # audio-crc-Zeilen sind keine Kommentare


def test_verify_detects_ok_missing_and_corrupt(tmp_path):
    files = make_files(tmp_path, ["a.mp3", "b.mp3", "c.mp3"])
    write_sfv(tmp_path / "rel.sfv", build_sfv(files))

    files[1].write_bytes(b"kaputt")
    files[2].unlink()

    result = verify_sfv(tmp_path / "rel.sfv")
    assert result.ok == ["a.mp3"]
    assert [n for n, _, _ in result.failed] == ["b.mp3"]
    assert result.missing == ["c.mp3"]
    assert result.success is False


@needs_ffmpeg
def test_verify_separates_retagged_from_corrupt(tmp_path):
    from mutagen.id3 import ID3, TIT2

    path = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "libmp3lame", "-metadata", "title=Alt",
                    str(path), "-y"], check=True)
    write_sfv(tmp_path / "rel.sfv", build_sfv([path], with_audio_crc=True))

    tags = ID3(path)
    tags.add(TIT2(encoding=3, text="Neuer deutlich längerer Titel"))
    tags.save()

    result = verify_sfv(tmp_path / "rel.sfv")
    assert result.retagged == ["a.mp3"]
    assert result.failed == []


def test_sfv_name_uses_dirname_and_catalog_no():
    release = Release(artist="A", album="B", dirname="A-B-2026-GRP",
                      catalog_no="CAT001")
    assert sfv_name(release) == "A-B-2026-GRP.sfv"
    assert sfv_name(release, use_catalog_no=True) == "CAT001.sfv"
    assert sfv_name(release, stem="eigener-rumpf") == "eigener-rumpf.sfv"


def test_sfv_disc_suffix_comes_from_the_number_not_the_directory():
    """Ein Ordner "Disc 2" darf kein Leerzeichen in den Dateinamen tragen."""
    release = Release(artist="A", album="B", dirname="a-b",
                      discs=[Disc(1), Disc(2)])
    assert sfv_name(release, release.discs[1]) == "a-b-cd2.sfv"
    # und genauso wie die M3U daneben
    assert (sfv_name(release, release.discs[1]).removesuffix(".sfv")
            == m3u_name(release, release.discs[1]).removesuffix(".m3u"))


def test_single_disc_gets_no_suffix():
    release = Release(artist="A", album="B", dirname="a-b", discs=[Disc(1)])
    assert sfv_name(release, release.discs[0]) == "a-b.sfv"


def test_one_sfv_per_disc_directory(tmp_path):
    root = tmp_path / "A-B-2CD-2026-GRP"
    files = make_files(root, ["CD1/01-a.mp3", "CD1/02-b.mp3", "CD2/01-c.mp3"])
    (root / "CD1" / "rip.log").write_bytes(b"log")

    release = Release(artist="A", album="B", dirname=root.name, discs=[
        Disc(1, tracks=[Track(1, "a", 10, 1, str(files[0])),
                        Track(2, "b", 10, 1, str(files[1]))]),
        Disc(2, tracks=[Track(1, "c", 10, 2, str(files[2]))]),
    ])

    written = write_release_sfvs(release, root, extra_extensions=[".log"])
    assert sorted(p.name for p in written) == [
        "A-B-2CD-2026-GRP-cd1.sfv", "A-B-2CD-2026-GRP-cd2.sfv"]

    cd1 = read_sfv(root / "CD1" / "A-B-2CD-2026-GRP-cd1.sfv")
    assert [e.filename for e in cd1.entries] == ["01-a.mp3", "02-b.mp3", "rip.log"]


# ------------------------------------------------------------------- M3U


def make_release(tmp_path: Path, multi: bool = True) -> tuple[Release, Path]:
    root = tmp_path / "A-B-2026-GRP"
    names = ["CD1/01-a.mp3", "CD1/02-b.mp3", "CD2/01-c.mp3"] if multi \
        else ["01-a.mp3", "02-b.mp3"]
    files = make_files(root, names)
    if multi:
        discs = [Disc(1, tracks=[Track(1, "Erster", 215, 1, str(files[0])),
                                 Track(2, "Zweiter", 301, 1, str(files[1]))]),
                 Disc(2, tracks=[Track(1, "Dritter", 180, 2, str(files[2]))])]
    else:
        discs = [Disc(1, tracks=[Track(1, "Erster", 215, 1, str(files[0])),
                                 Track(2, "Zweiter", 301, 1, str(files[1]))])]
    return Release(artist="Der Artist", album="Das Album",
                   dirname=root.name, discs=discs), root


def test_extinf_carries_duration_and_label(tmp_path):
    release, root = make_release(tmp_path, multi=False)
    entries = build_entries(release, release.tracks, base=root)
    text = render_m3u(entries)
    lines = text.strip().split("\r\n")
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#EXTINF:215,Der Artist - Erster"
    assert lines[2] == "01-a.mp3"
    assert lines[3] == "#EXTINF:301,Der Artist - Zweiter"


def test_plain_m3u_has_no_extinf(tmp_path):
    release, root = make_release(tmp_path, multi=False)
    entries = build_entries(release, release.tracks, base=root)
    text = render_m3u(entries, extended=False)
    assert "#EXT" not in text
    assert text.strip().split("\r\n") == ["01-a.mp3", "02-b.mp3"]


def test_single_disc_gets_one_playlist_and_no_super(tmp_path):
    release, root = make_release(tmp_path, multi=False)
    written = write_release_m3us(release, root)
    assert [p.name for p in written] == ["A-B-2026-GRP.m3u"]


def test_multi_disc_gets_per_cd_plus_super(tmp_path):
    release, root = make_release(tmp_path, multi=True)
    written = write_release_m3us(release, root)
    names = [p.name for p in written]
    assert names == ["A-B-2026-GRP-cd1.m3u", "A-B-2026-GRP-cd2.m3u",
                     "A-B-2026-GRP.m3u"]

    cd1 = (root / "CD1" / "A-B-2026-GRP-cd1.m3u").read_bytes().decode("cp437")
    assert "01-a.mp3" in cd1 and "CD1" not in cd1      # nackte Namen je CD

    super_m3u = (root / "A-B-2026-GRP.m3u").read_bytes().decode("cp437")
    # normale Schraegstriche - das Programm laeuft unter Linux
    assert "CD1/01-a.mp3" in super_m3u                 # relativ zur Wurzel
    assert "CD2/01-c.mp3" in super_m3u


def test_super_m3u_keeps_disc_order(tmp_path):
    release, root = make_release(tmp_path, multi=True)
    write_release_m3us(release, root)
    text = (root / "A-B-2026-GRP.m3u").read_bytes().decode("cp437")
    paths = [l for l in text.split("\r\n") if l.endswith(".mp3")]
    assert paths == ["CD1/01-a.mp3", "CD1/02-b.mp3", "CD2/01-c.mp3"]


def test_windows_paths_when_requested(tmp_path):
    """Das Original schrieb Rueckwaerts-Schraegstriche - abrufbar bleibt es."""
    release, root = make_release(tmp_path, multi=True)
    write_release_m3us(release, root, windows_paths=True)
    text = (root / "A-B-2026-GRP.m3u").read_bytes().decode("cp437")
    assert "CD1\\01-a.mp3" in text


def test_m3u_name_follows_release(tmp_path):
    release, _ = make_release(tmp_path, multi=True)
    assert m3u_name(release) == "A-B-2026-GRP.m3u"
    assert m3u_name(release, release.discs[1]) == "A-B-2026-GRP-cd2.m3u"
