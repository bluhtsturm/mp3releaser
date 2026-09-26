"""Tests fuer den Audio-Layer.

Zwei Ebenen:

* **synthetisch** - selbst gebaute EC-3-Syncframes und ``dec3``-Boxen. Damit
  laesst sich auch der JOC-Pfad testen, den FFmpegs EC-3-Encoder gar nicht
  erzeugen kann.
* **gegen ffprobe** - echte Dateien, erzeugt mit ffmpeg, und ein unabhaengiger
  Soll-Wert aus ffprobe. Diese Tests werden uebersprungen, wenn ffmpeg fehlt.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.audio.bitreader import BitReader
from releaser.audio.eac3 import (
    analyse_stream,
    detect_joc,
    parse_dec3,
    parse_syncframe,
    summarise_channels,
)
from releaser.audio.scan import parse_filename

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe nicht vorhanden")


# ------------------------------------------------------------------ Bitleser


class BitWriter:
    def __init__(self):
        self.bits: list[int] = []

    def write(self, value: int, n: int) -> "BitWriter":
        for i in range(n - 1, -1, -1):
            self.bits.append((value >> i) & 1)
        return self

    def bytes(self, pad_to: int | None = None) -> bytes:
        bits = list(self.bits)
        while len(bits) % 8:
            bits.append(0)
        out = bytearray()
        for i in range(0, len(bits), 8):
            byte = 0
            for b in bits[i:i + 8]:
                byte = (byte << 1) | b
            out.append(byte)
        if pad_to:
            out.extend(b"\x00" * max(0, pad_to - len(out)))
        return bytes(out)


def test_bitreader_reads_msb_first():
    br = BitReader(b"\xb0")
    assert br.read(3) == 0b101
    assert br.read(1) == 1
    assert br.read(4) == 0


# ------------------------------------------------- synthetische EC-3-Frames


def build_frame(strmtyp=0, substreamid=0, frame_bytes=64, fscod=0, numblkscod=3,
                acmod=7, lfeon=1, bsid=16, chanmap=None, addbsi=None) -> bytes:
    w = BitWriter()
    w.write(0x0B77, 16)
    w.write(strmtyp, 2)
    w.write(substreamid, 3)
    w.write(frame_bytes // 2 - 1, 11)     # frmsiz
    w.write(fscod, 2)
    w.write(numblkscod, 2)
    w.write(acmod, 3)
    w.write(lfeon, 1)
    w.write(bsid, 5)
    w.write(0, 5)                         # dialnorm
    w.write(0, 1)                         # compre
    if acmod == 0:
        w.write(0, 5).write(0, 1)
    if strmtyp == 1:
        if chanmap is None:
            w.write(0, 1)                 # chanmape
        else:
            w.write(1, 1).write(chanmap, 16)
    w.write(0, 1)                         # mixmdate
    w.write(0, 1)                         # infomdate
    if strmtyp == 0 and numblkscod != 3:
        w.write(0, 1)                     # convsync
    if addbsi is None:
        w.write(0, 1)                     # addbsie
    else:
        w.write(1, 1).write(len(addbsi) - 1, 6)
        for byte in addbsi:
            w.write(byte, 8)
    return w.bytes(pad_to=frame_bytes)


def test_parses_core_bsi_fields():
    sub = parse_syncframe(build_frame(acmod=7, lfeon=1, frame_bytes=128), 0)
    assert sub.strmtyp == 0
    assert sub.frame_bytes == 128
    assert sub.samplerate == 48000
    assert sub.numblks == 6
    assert sub.acmod == 7 and sub.lfeon == 1
    assert sub.channels == 6
    assert sub.bsid == 16
    assert sub.fully_parsed


def test_halved_samplerate_via_fscod2():
    # fscod == 3 bedeutet: die folgenden 2 Bit sind fscod2 (halbierte Raten)
    sub = parse_syncframe(build_frame(fscod=3, numblkscod=0), 0)
    assert sub.samplerate == 24000
    assert sub.numblks == 6


def test_reserved_fscod2_is_rejected():
    from releaser.audio.base import AudioError

    with pytest.raises(AudioError):
        parse_syncframe(build_frame(fscod=3, numblkscod=3), 0)


def test_dependent_substream_chanmap_counts_channels():
    # L, C, R, Ls, Rs, Vhl/Vhr -> 5 + 2 = 7 Kanaele
    bits = 0
    for i in (0, 1, 2, 3, 4, 11):
        bits |= 1 << (15 - i)
    sub = parse_syncframe(build_frame(strmtyp=1, chanmap=bits), 0)
    assert sub.chanmap == bits
    assert sub.chanmap_channels == 7


def test_joc_flag_and_object_count_from_addbsi():
    ind = build_frame(strmtyp=0, frame_bytes=64)
    dep = build_frame(strmtyp=1, substreamid=0, frame_bytes=64, addbsi=[0x01, 15])
    summary = analyse_stream(ind + dep + ind + dep)
    assert len(summary.independent) == 1
    assert len(summary.dependent) == 1
    atmos, objects = detect_joc(summary)
    assert atmos is True
    assert objects == 15


def test_no_dependent_substream_means_no_joc():
    summary = analyse_stream(build_frame() * 4)
    assert detect_joc(summary) == (False, None)


def test_joc_unknown_when_bsi_traversal_fails():
    # abgeschnittener abhaengiger Substream: Kernfelder lesbar, Rest nicht
    dep = build_frame(strmtyp=1, frame_bytes=64)[:8]
    summary = analyse_stream(build_frame() + dep)
    for s in summary.dependent:
        s.fully_parsed = False
    atmos, _ = detect_joc(summary)
    assert atmos is None


def test_channel_label():
    summary = analyse_stream(build_frame(acmod=7, lfeon=1) * 2)
    channels, label = summarise_channels(summary)
    assert channels == 6
    assert label == "3/2 + LFE (5.1)"


def test_resync_is_reported():
    stream = b"\x00" * 16 + build_frame() * 2
    summary = analyse_stream(stream)
    assert summary.warnings
    assert summary.frame_count == 2


# ------------------------------------------------------------- dec3-Box (MP4)


def test_parse_dec3_box():
    # 1 unabhaengiger Substream, 48 kHz, bsid 16, acmod 3/2, LFE an, 448 kbps
    w = BitWriter()
    w.write(448, 13).write(0, 3)
    w.write(0, 2).write(16, 5).write(0, 1).write(0, 1).write(0, 3)
    w.write(7, 3).write(1, 1).write(0, 3).write(0, 4).write(0, 1)
    box = parse_dec3(w.bytes())
    assert box.data_rate == 448
    assert len(box.substreams) == 1
    assert box.substreams[0]["acmod"] == 7
    assert box.substreams[0]["lfeon"] == 1


def test_parse_dec3_box_with_atmos_extension():
    w = BitWriter()
    w.write(768, 13).write(0, 3)
    w.write(0, 2).write(16, 5).write(0, 1).write(0, 1).write(0, 3)
    w.write(7, 3).write(1, 1).write(0, 3).write(1, 4).write(0, 9)
    w.write(0, 7).write(1, 1)        # flag_ec3_extension_type_a
    w.write(16, 8)                   # complexity_index_type_a
    box = parse_dec3(w.bytes())
    assert box.substreams[0]["num_dep_sub"] == 1
    assert box.ext_type_a is True
    assert box.complexity_index == 16


# --------------------------------------------------------- Dateinamen-Heuristik


@pytest.mark.parametrize("name,expected", [
    ("01-artist-titel.mp3", (None, 1, "artist-titel")),
    ("103 - Der Titel.flac", (1, 3, "Der Titel")),
    ("07. Noch ein Titel.ec3", (None, 7, "Noch ein Titel")),
    ("ohne_nummer.mp3", (None, None, "ohne_nummer")),
])
def test_parse_filename(name, expected):
    assert parse_filename(Path(name)) == expected


# ------------------------------------------------------ Abgleich gegen ffprobe


def ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def encode(tmp_path: Path, name: str, *args: str) -> Path:
    target = tmp_path / name
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    *args, str(target), "-y"], check=True)
    return target


@needs_ffmpeg
@pytest.mark.parametrize("layout,expected_channels", [
    ("mono", 1), ("stereo", 2), ("5.1", 6),
])
def test_raw_ec3_matches_ffprobe(tmp_path, layout, expected_channels):
    from releaser.audio import read_file

    path = encode(tmp_path, f"{layout}.ec3",
                  "-f", "lavfi", "-i", f"anullsrc=channel_layout={layout}:sample_rate=48000",
                  "-t", "1", "-c:a", "eac3")
    info = read_file(path)
    probe = ffprobe(path)["streams"][0]

    assert info.codec == "EAC3"
    assert info.samplerate == int(probe["sample_rate"])
    assert info.channels == expected_channels == int(probe["channels"])
    assert info.bitrate == int(probe["bit_rate"]) // 1000
    assert info.tagless is True


@needs_ffmpeg
def test_raw_ec3_duration_matches_ffprobe(tmp_path):
    from releaser.audio import read_file

    path = encode(tmp_path, "dur.ec3",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                  "-c:a", "eac3", "-ac", "6")
    info = read_file(path)
    expected = float(ffprobe(path)["format"]["duration"])
    assert abs(info.duration - expected) < 0.05


@needs_ffmpeg
def test_mp3_tags_and_technical_values(tmp_path):
    from releaser.audio import read_file

    path = encode(tmp_path, "a.mp3",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                  "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", "-ac", "2",
                  "-metadata", "title=Der Titel", "-metadata", "artist=Der Artist",
                  "-metadata", "album=Das Album", "-metadata", "track=3/12",
                  "-metadata", "date=2026", "-metadata", "genre=Electronic")
    info = read_file(path)
    assert info.codec == "MP3"
    assert info.title == "Der Titel" and info.artist == "Der Artist"
    assert (info.track_no, info.total_tracks) == (3, 12)
    assert info.year == 2026
    assert info.samplerate == 44100
    assert info.bitrate == 320
    assert info.channel_mode in {"Full Stereo", "Joint-Stereo"}


@needs_ffmpeg
def test_flac_compression_ratio_is_plausible(tmp_path):
    from releaser.audio import read_file

    path = encode(tmp_path, "a.flac",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                  "-c:a", "flac", "-ar", "44100", "-ac", "2", "-sample_fmt", "s16",
                  "-metadata", "title=Flac Titel", "-metadata", "tracknumber=2")
    info = read_file(path)
    assert info.codec == "FLAC"
    assert info.bits_per_sample == 16
    assert 0.0 < info.compression_ratio < 1.0
    assert info.title == "Flac Titel"


@needs_ffmpeg
def test_scan_groups_multi_disc_release(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "Artist-Album-2CD-2026-GRP"
    for disc, count in ((1, 3), (2, 2)):
        folder = root / f"CD{disc}"
        folder.mkdir(parents=True)
        for no in range(1, count + 1):
            encode(folder, f"0{no}-artist-track_{no}.mp3",
                   "-f", "lavfi", "-i", f"sine=frequency={300 + no * 40}:duration=1",
                   "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "44100", "-ac", "2",
                   "-metadata", f"title=Track {no} auf CD {disc}",
                   "-metadata", "artist=Der Artist", "-metadata", "album=Das Album",
                   "-metadata", f"track={no}/{count}", "-metadata", f"disc={disc}/2",
                   "-metadata", "date=2026")

    result = scan_directory(root)
    rel = result.release
    assert [d.number for d in rel.discs] == [1, 2]
    assert [len(d.tracks) for d in rel.discs] == [3, 2]
    assert rel.total_tracks == 5
    assert rel.multi_disc is True
    assert rel.artist == "Der Artist"
    assert rel.dirname == root.name
    assert rel.bitrate == 320
    assert rel.audio_format == "MP3"


@needs_ffmpeg
def test_scan_flags_mixed_bitrates(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "mixed"
    root.mkdir()
    for no, rate in ((1, "320k"), (2, "192k")):
        encode(root, f"0{no}-t.mp3",
               "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
               "-c:a", "libmp3lame", "-b:a", rate, "-ar", "44100", "-ac", "2",
               "-metadata", f"title=T{no}", "-metadata", "artist=A",
               "-metadata", "album=B", "-metadata", f"track={no}/2")
    result = scan_directory(root)
    assert any("Bitraten" in w for w in result.warnings)


@needs_ffmpeg
def test_tagless_ec3_falls_back_to_filename(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "atmos"
    root.mkdir()
    encode(root, "01-artist-erster_track.ec3",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=5.1:sample_rate=48000",
           "-t", "1", "-c:a", "eac3")
    result = scan_directory(root)
    track = result.release.tracks[0]
    assert track.no == 1
    assert "erster_track" in track.title
    assert any("Dateinamen" in w for w in result.warnings)


# ------------------------------------------------------------ MP4 / AAC


def test_describe_codec_maps_aac_profiles():
    from releaser.audio.mp4 import describe_codec

    assert describe_codec("mp4a.40.2", "AAC LC") == ("AAC", "AAC-LC")
    assert describe_codec("mp4a.40.5", "") == ("AAC", "HE-AAC")
    assert describe_codec("mp4a.40.29", "") == ("AAC", "HE-AACv2")
    assert describe_codec("alac", "ALAC") == ("ALAC", "")
    assert describe_codec("ec-3", "EC-3") == ("EAC3", "")


def test_sample_sizes_uniform_table():
    from releaser.audio.mp4 import looks_variable, sample_sizes

    stsz = (b"\x00\x00\x00\x00" + (417).to_bytes(4, "big")
            + (100).to_bytes(4, "big"))
    sizes = sample_sizes(stsz)
    assert sizes == [417] * 100
    assert looks_variable(sizes) is False


def test_sample_sizes_variable_table():
    from releaser.audio.mp4 import looks_variable, sample_sizes

    values = [200 + (i % 7) * 60 for i in range(60)]
    stsz = (b"\x00\x00\x00\x00" + (0).to_bytes(4, "big")
            + len(values).to_bytes(4, "big")
            + b"".join(v.to_bytes(4, "big") for v in values))
    assert sample_sizes(stsz) == values
    assert looks_variable(sample_sizes(stsz)) is True


def test_looks_variable_needs_enough_samples():
    from releaser.audio.mp4 import looks_variable

    assert looks_variable([100, 900, 100]) is None
    assert looks_variable([]) is None


@needs_ffmpeg
def test_aac_in_m4a_is_read_completely(tmp_path):
    from releaser.audio import read_file

    path = encode(tmp_path, "a.m4a",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                  "-c:a", "aac", "-b:a", "256k", "-ar", "44100", "-ac", "2",
                  "-metadata", "title=AAC Titel", "-metadata", "artist=Der Artist",
                  "-metadata", "album=Das Album", "-metadata", "track=3/12",
                  "-metadata", "disc=1/2", "-metadata", "date=2026",
                  "-metadata", "genre=Electronic")
    info = read_file(path)

    assert info.codec == "AAC"
    assert "AAC-LC" in info.encoder
    assert info.samplerate == 44100
    assert info.channels == 2
    assert info.channel_mode == "Stereo"
    assert info.title == "AAC Titel" and info.artist == "Der Artist"
    assert (info.track_no, info.total_tracks) == (3, 12)
    assert (info.disc_no, info.total_discs) == (1, 2)
    assert info.year == 2026
    assert info.tagless is False


@needs_ffmpeg
@pytest.mark.parametrize("channels,expected", [(1, "Mono"), (2, "Stereo"), (6, "5.1")])
def test_aac_channel_mode_labels(tmp_path, channels, expected):
    from releaser.audio import read_file

    path = encode(tmp_path, f"c{channels}.m4a",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                  "-c:a", "aac", "-ac", str(channels))
    assert read_file(path).channel_mode == expected


@needs_ffmpeg
def test_alac_is_not_reported_as_aac(tmp_path):
    from releaser.audio import read_file

    path = encode(tmp_path, "a.m4a",
                  "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                  "-c:a", "alac")
    info = read_file(path)
    assert info.codec == "ALAC"
    assert info.vbr is False


@needs_ffmpeg
def test_scan_handles_aac_release(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "Artist-Album-2026-GRP"
    root.mkdir()
    for no in (1, 2):
        encode(root, f"0{no}-artist-track.m4a",
               "-f", "lavfi", "-i", f"sine=frequency={400 + no * 50}:duration=1",
               "-c:a", "aac", "-b:a", "256k",
               "-metadata", f"title=Track {no}", "-metadata", "artist=Der Artist",
               "-metadata", "album=Das Album", "-metadata", f"track={no}/2",
               "-metadata", "date=2026")
    release = scan_directory(root).release
    assert release.audio_format == "AAC"
    assert release.total_tracks == 2
    assert release.artist == "Der Artist"


@needs_ffmpeg
def test_lossless_bitrate_spread_is_not_reported(tmp_path):
    """FLAC hat je Datei eine andere Bitrate - das ist keine Auffälligkeit."""
    from releaser.audio import scan_directory

    root = tmp_path / "rel"
    root.mkdir()
    for no in (1, 2):
        # unterschiedliche Signale -> unterschiedliche Kompression
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", f"sine=frequency={300 + no * 411}:duration=1",
             "-c:a", "flac",
             "-metadata", f"title=Titel {no}", "-metadata", "artist=A",
             "-metadata", "album=B", "-metadata", f"TRACKNUMBER={no}",
             str(root / f"0{no}-x.flac"), "-y"], check=True)
    result = scan_directory(root)
    assert not any("Bitraten" in w for w in result.warnings)


@needs_ffmpeg
def test_mixed_bitrates_are_still_reported_for_lossy(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "rel"
    root.mkdir()
    for no, rate in ((1, "320k"), (2, "192k")):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=1",
             "-c:a", "libmp3lame", "-b:a", rate,
             "-metadata", f"title=Titel {no}", "-metadata", "artist=A",
             "-metadata", "album=B", "-metadata", f"track={no}/2",
             str(root / f"0{no}-x.mp3"), "-y"], check=True)
    result = scan_directory(root)
    assert any("Bitraten" in w for w in result.warnings)
