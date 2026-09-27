"""Tests für die nachgezogenen Funktionen des Originals."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser import config as config_module
from releaser import cue as cue_module
from releaser import dupecheck, genres, lyrics3
from releaser.model import Disc, Release, Track
from releaser.naming import NamingProfile, companion_name, plan_rename

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


def encode(target: Path, *args: str, duration: str = "1") -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
                    *args, str(target), "-y"], check=True)
    return target


# =============================================================== ID3v1-Genres


def test_genre_list_matches_mutagen():
    """Unsere Liste darf nicht von mutagens abweichen."""
    from mutagen.id3 import TCON

    assert list(genres.GENRES) == list(TCON.GENRES)


@pytest.mark.parametrize("value,expected,number", [
    ("electronic", "Electronic", 52),
    ("Hip Hop", "Hip-Hop", 7),
    ("hip-hop", "Hip-Hop", 7),
    ("DnB", "Drum & Bass", 127),
    ("rock n roll", "Rock & Roll", 78),
    ("R&B", "R&B", 14),
    ("  TRANCE  ", "Trance", 31),
])
def test_genre_normalisation(value, expected, number):
    name, num, warning = genres.normalise(value)
    assert (name, num) == (expected, number)
    assert warning is None


def test_unknown_genre_survives_with_a_warning():
    name, number, warning = genres.normalise("Progressive Trance")
    assert name == "Progressive Trance"          # nicht verworfen
    assert number is None
    assert "ID3v1" in warning


def test_empty_genre_is_silent():
    assert genres.normalise("") == ("", None, None)


@needs_ffmpeg
def test_written_genre_is_canonical(tmp_path):
    from releaser.audio import read_file
    from releaser.tagwriter import TagProfile, apply_tags, plan_tags

    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame")
    release = Release(artist="X", album="Y", genre="electronic",
                      discs=[Disc(1, tracks=[Track(1, "T", 1.0, 1, str(path))])])
    apply_tags(plan_tags(release), TagProfile())
    assert read_file(path).genre == "Electronic"


# ================================================================== Lyrics3v2


def test_lyrics3_block_structure():
    block = lyrics3.build({"title": "Ein Titel", "artist": "Ein Artist"})
    assert block.startswith(b"LYRICSBEGIN")
    assert block.endswith(b"LYRICS200")
    size = int(block[-15:-9])
    assert size == len(block) - 15          # Groesse ohne Ziffern und Endmarke
    assert b"ETT00009Ein Titel" in block


def test_lyrics3_roundtrip(tmp_path):
    path = tmp_path / "a.mp3"
    path.write_bytes(b"\xff\xfb\x90\x00" * 20)
    values = {"title": "Der Titel", "artist": "Der Artist",
              "album": "Das Album", "comment": "Ein Kommentar"}
    lyrics3.write(path, values)
    assert lyrics3.read(path) == {**values, "indications": "00"}


def test_lyrics3_sits_before_id3v1(tmp_path):
    path = tmp_path / "a.mp3"
    audio = b"\xff\xfb\x90\x00" * 20
    path.write_bytes(audio + b"TAG" + b"\x00" * 125)
    lyrics3.write(path, {"title": "T"})

    data = path.read_bytes()
    assert data[-128:-125] == b"TAG"        # ID3v1 bleibt ganz hinten
    assert lyrics3.read(path)["title"] == "T"
    assert data.startswith(audio)           # Audiodaten unberuehrt


def test_lyrics3_replaces_instead_of_stacking(tmp_path):
    path = tmp_path / "a.mp3"
    path.write_bytes(b"\xff\xfb\x90\x00" * 20)
    lyrics3.write(path, {"title": "Erster"})
    first = len(path.read_bytes())
    lyrics3.write(path, {"title": "Zweiter"})

    assert lyrics3.read(path)["title"] == "Zweiter"
    assert path.read_bytes().count(b"LYRICSBEGIN") == 1
    assert abs(len(path.read_bytes()) - first) < 10


def test_lyrics3_remove(tmp_path):
    path = tmp_path / "a.mp3"
    audio = b"\xff\xfb\x90\x00" * 20
    path.write_bytes(audio)
    lyrics3.write(path, {"title": "T"})
    assert lyrics3.remove(path) is True
    assert path.read_bytes() == audio
    assert lyrics3.remove(path) is False


def test_lyrics3_rejects_oversized_field():
    with pytest.raises(lyrics3.Lyrics3Error):
        lyrics3.build({"lyrics": "x" * 100000})


@needs_ffmpeg
def test_all_legacy_tags_coexist_in_the_right_order(tmp_path):
    from mutagen.apev2 import APEv2
    from releaser.checksums import audio_crc32
    from releaser.tagwriter import TagProfile, apply_tags, plan_tags

    path = encode(tmp_path / "a.mp3", "-c:a", "libmp3lame")
    before, _ = audio_crc32(path)
    release = Release(artist="Der Artist", album="Das Album", year=2026,
                      discs=[Disc(1, tracks=[Track(1, "Der Titel", 1.0, 1, str(path))])])
    profile = TagProfile(write_apev2=True, write_lyrics3=True, comment="Kommentar")

    for _ in range(2):                      # zweimal - muss stabil bleiben
        apply_tags(plan_tags(release, profile), profile)

    data = path.read_bytes()
    assert data[-128:-125] == b"TAG"        # ID3v1 ganz hinten
    assert data.count(b"LYRICSBEGIN") == 1
    assert len(APEv2(path)) > 0
    assert lyrics3.read(path)["title"] == "Der Titel"
    assert audio_crc32(path)[0] == before   # Audiodaten unberuehrt


# ======================================================================= CUE


CUE_TEXT = '''REM GENRE Electronic
REM DATE 2026
PERFORMER "Der Artist"
TITLE "Das Album"
FILE "mix.flac" WAVE
  TRACK 01 AUDIO
    TITLE "Erster Teil"
    PERFORMER "Der Artist"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Zweiter Teil"
    PERFORMER "Gastauftritt"
    INDEX 01 04:30:00
  TRACK 03 AUDIO
    TITLE "Dritter Teil"
    INDEX 01 08:15:00
'''


#: Dieselben Tracks, aber auf eine 12 Sekunden lange Datei zugeschnitten.
SHORT_CUE = (CUE_TEXT.replace("04:30:00", "00:04:00")
             .replace("08:15:00", "00:08:00"))


def test_parse_time():
    assert cue_module.parse_time("00:00:00") == 0.0
    assert cue_module.parse_time("01:30:00") == 90.0
    # Frames laufen von 0 bis 74 - 75 Frames sind bereits die naechste Sekunde
    assert cue_module.parse_time("00:00:74") == pytest.approx(74 / 75)
    assert cue_module.parse_time("99:59:74") > 5000


@pytest.mark.parametrize("value", ["1:2", "00:70:00", "00:00:75", "abc"])
def test_parse_time_rejects_nonsense(value):
    with pytest.raises(cue_module.CueError):
        cue_module.parse_time(value)


def test_parse_cue_header_and_tracks():
    sheet = cue_module.parse_cue(CUE_TEXT)
    assert sheet.performer == "Der Artist"
    assert sheet.title == "Das Album"
    assert (sheet.date, sheet.genre) == ("2026", "Electronic")
    assert len(sheet.files) == 1
    assert [t.number for t in sheet.tracks] == [1, 2, 3]
    assert sheet.tracks[1].performer == "Gastauftritt"


def test_cue_durations_from_index_distance():
    sheet = cue_module.parse_cue(CUE_TEXT)
    assert sheet.tracks[0].duration == pytest.approx(270.0)   # 4:30
    assert sheet.tracks[1].duration == pytest.approx(225.0)   # 3:45
    assert sheet.tracks[2].duration is None                   # bis Dateiende


def test_cue_last_duration_needs_the_file_length():
    sheet = cue_module.parse_cue(CUE_TEXT)
    cue_module.close_durations(sheet, {"mix.flac": 600.0})
    assert sheet.tracks[2].duration == pytest.approx(105.0)


def test_cue_reports_missing_index():
    sheet = cue_module.parse_cue(
        'FILE "a.flac" WAVE\n  TRACK 01 AUDIO\n    TITLE "Ohne Index"\n')
    assert any("INDEX 01" in w for w in sheet.warnings)


@needs_ffmpeg
def test_scan_takes_the_tracklist_from_the_cue(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "rel"
    encode(root / "mix.flac", "-c:a", "flac", duration="12")
    (root / "mix.cue").write_text(SHORT_CUE, encoding="utf-8")

    result = scan_directory(root)
    release = result.release
    assert release.total_tracks == 3
    assert [t.title for t in release.tracks] == [
        "Erster Teil", "Zweiter Teil", "Dritter Teil"]
    assert release.artist == "Der Artist"
    assert release.album == "Das Album"
    assert any("CUE" in w for w in result.warnings)


@needs_ffmpeg
def test_cue_release_touches_the_file_only_once(tmp_path):
    """Alle Tracks zeigen auf dieselbe Datei - Umbenennen und M3U duerfen
    sie nicht mehrfach anfassen."""
    from releaser.audio import scan_directory
    from releaser.playlist import build_entries

    root = tmp_path / "rel"
    encode(root / "mix.flac", "-c:a", "flac", duration="12")
    (root / "mix.cue").write_text(SHORT_CUE, encoding="utf-8")
    release = scan_directory(root).release

    plan = plan_rename(release, root, NamingProfile(group="GRP"))
    file_ops = [op for op in plan.ops if op.kind == "file"]
    assert len(file_ops) == 1
    assert plan.is_safe

    entries = build_entries(release, release.tracks, base=root)
    assert len(entries) == 1
    assert entries[0].seconds == pytest.approx(12.0, abs=0.5)   # Summe


@needs_ffmpeg
def test_cue_size_is_not_multiplied(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "rel"
    audio = encode(root / "mix.flac", "-c:a", "flac", duration="12")
    (root / "mix.cue").write_text(SHORT_CUE, encoding="utf-8")
    release = scan_directory(root).release
    assert abs(release.size_bytes - audio.stat().st_size) < 10


# ============================================================== Dupe-Pruefung


@pytest.mark.parametrize("name,expected", [
    ("Der_Artist-Das_Album-CDDA-2026-GRP", "der-artist-das-album"),
    ("der.artist-das.album-WEB-2026-ANDERE", "der-artist-das-album"),
    ("VA-Sampler_Vol_3-2CD-2026-GRP", "sampler-vol-3-2cd"),
])
def test_dupe_normalisation_ignores_noise(name, expected):
    assert dupecheck.normalise(name) == expected


def test_split_group():
    assert dupecheck.split_group("A-B-2026-GRP") == ("A-B-2026", "GRP")
    assert dupecheck.split_group("ohnegruppe") == ("ohnegruppe", "")


def test_dupe_finds_the_same_release_in_another_source():
    index = dupecheck.DupeIndex()
    index.add("Der_Artist-Das_Album-CDDA-2026-GRP")
    matches = index.check("der.artist-das.album-WEB-2026-ANDERE")
    assert matches and matches[0].exact
    assert matches[0].name == "Der_Artist-Das_Album-CDDA-2026-GRP"


def test_dupe_finds_similar_spelling():
    index = dupecheck.DupeIndex()
    index.add("Der_Artist-Das_Albumm-2026-GRP")
    matches = index.check("Der_Artist-Das_Album-2026-GRP", threshold=0.8)
    assert matches and not matches[0].exact
    assert 80 <= matches[0].percent < 100


def test_dupe_ignores_unrelated_names():
    index = dupecheck.DupeIndex()
    index.add("Ganz_Anderer-Anderes_Werk-2020-XYZ")
    assert index.check("Der_Artist-Das_Album-2026-GRP") == []


def test_dupe_index_from_directory(tmp_path):
    for name in ("A-B-2026-GRP", "C-D-2025-GRP"):
        (tmp_path / name).mkdir()
    (tmp_path / "keine-release.txt").write_text("x")
    index = dupecheck.from_directory(tmp_path)
    assert len(index) == 2


def test_dupe_index_from_file(tmp_path):
    listing = tmp_path / "dupes.txt"
    listing.write_text("# Kommentar\nA-B-2026-GRP\n\nC-D-2025-GRP\n")
    index = dupecheck.load(listing)
    assert len(index) == 2


# ============================================================= Konfiguration


def test_config_parses_all_sections():
    config = config_module.parse('[naming]\ngroup = "GRP"\n'
                                 '[tags]\ncase = "upper"\n'
                                 '[build]\naudio_crc = true\n')
    assert config.get("naming", "group") == "GRP"
    assert config.get("tags", "case") == "upper"
    assert config.get("build", "audio_crc") is True


def test_config_rejects_unknown_sections():
    with pytest.raises(config_module.ConfigError) as err:
        config_module.parse('[gibtsnicht]\nx = 1\n')
    assert "gibtsnicht" in str(err.value)


def test_config_rejects_broken_toml():
    with pytest.raises(config_module.ConfigError):
        config_module.parse("das ist kein toml [[[")


def test_config_section_must_be_a_table():
    with pytest.raises(config_module.ConfigError):
        config_module.parse('naming = 5\n')


def test_config_example_is_valid():
    config = config_module.parse(config_module.EXAMPLE)
    assert config.get("naming", "group") == "GRP"
    assert config.get("tags", "id3v2") == 4


def test_resolve_precedence():
    config = config_module.parse('[naming]\ngroup = "AUSDATEI"\n')
    assert config_module.resolve(config, "naming", "group", "CLI", "STD") == "CLI"
    assert config_module.resolve(config, "naming", "group", None, "STD") == "AUSDATEI"
    assert config_module.resolve(config, "naming", "space", None, "_") == "_"


def test_config_load_missing_path_raises(tmp_path):
    with pytest.raises(config_module.ConfigError):
        config_module.load(tmp_path / "gibtsnicht.toml")


# ============================================== Begleitdateien und Cover


@pytest.mark.parametrize("suffix", [".nfo", ".jpg", ".pdf", ".sfv", ".m3u"])
def test_zero_prefix_is_the_default_for_every_companion(suffix):
    release = Release(artist="A", album="B", dirname="rel")
    profile = NamingProfile(charcase={}, companion_pattern="#Fullrelease")
    assert companion_name(release, suffix, profile) == f"00-rel{suffix}"


@pytest.mark.parametrize("suffix,expected", [
    (".nfo", "00-rel.nfo"),
    (".jpg", "00-rel.jpg"),
    (".sfv", "rel.sfv"),
    (".m3u", "rel.m3u"),
])
def test_prefix_can_be_limited_to_nfo_and_images(suffix, expected):
    """So hielt es das Original - Pruefprogramme finden das SFV sonst schlechter."""
    release = Release(artist="A", album="B", dirname="rel")
    profile = NamingProfile(
        companion_prefix="00-", charcase={}, companion_pattern="#Fullrelease",
        prefixed_suffixes=frozenset({".nfo", ".jpg", ".jpeg", ".png", ".pdf"}))
    assert companion_name(release, suffix, profile) == expected


def test_prefix_can_be_switched_off():
    release = Release(artist="A", album="B", dirname="rel")
    profile = NamingProfile(companion_prefix="", charcase={},
                            companion_pattern="#Fullrelease")
    assert companion_name(release, ".nfo", profile) == "rel.nfo"


@needs_ffmpeg
def test_cover_is_renamed_with_the_release(tmp_path):
    from releaser.audio import scan_directory
    from releaser.naming import apply_plan

    root = tmp_path / "rohdaten"
    encode(root / "01-x.mp3", "-c:a", "libmp3lame",
           "-metadata", "title=Titel", "-metadata", "artist=Der Artist",
           "-metadata", "album=Das Album", "-metadata", "date=2026")
    (root / "folder.jpg").write_bytes(b"\xff\xd8\xff\xe0")

    release = scan_directory(root).release
    profile = NamingProfile(group="GRP", companion_prefix="00-")
    apply_plan(plan_rename(release, root, profile), release)

    new_root = tmp_path / "der_artist-das_album-2026-grp"
    assert (new_root / "00-der_artist-das_album-2026-grp.jpg").is_file()
    assert not (new_root / "folder.jpg").exists()


@needs_ffmpeg
def test_several_covers_get_numbered(tmp_path):
    from releaser.audio import scan_directory
    from releaser.naming import apply_plan

    root = tmp_path / "rohdaten"
    encode(root / "01-x.mp3", "-c:a", "libmp3lame",
           "-metadata", "title=Titel", "-metadata", "artist=Der Artist",
           "-metadata", "album=Das Album", "-metadata", "date=2026")
    for name in ("front.jpg", "back.jpg"):
        (root / name).write_bytes(b"\xff\xd8\xff\xe0")

    release = scan_directory(root).release
    apply_plan(plan_rename(release, root, NamingProfile(group="GRP")), release)

    new_root = tmp_path / "der_artist-das_album-2026-grp"
    covers = sorted(p.name for p in new_root.glob("*.jpg"))
    assert covers == ["00-der_artist-das_album-2026-grp-01.jpg",
                      "00-der_artist-das_album-2026-grp-02.jpg"]


def test_config_warns_about_unknown_keys():
    config = config_module.parse('[naming]\ngrupp = "GRP"\n')
    assert len(config.warnings) == 1
    assert "grupp" in config.warnings[0]
    assert "group" in config.warnings[0]        # Vorschlag


def test_config_known_keys_produce_no_warning():
    config = config_module.parse(
        '[naming]\ngroup = "GRP"\n[tags]\nnormalise_genre = true\n')
    assert config.warnings == []


def test_every_known_key_exists_on_its_profile():
    """Die Schluesselliste darf nicht von den Profilen abweichen."""
    from releaser.naming import NamingProfile
    from releaser.tagwriter import TagProfile

    naming_fields = set(NamingProfile.__dataclass_fields__)
    # CLI-Namen, die bewusst kuerzer sind als das Profilfeld, und Schluessel,
    # die mehrere Profilfelder auf einmal setzen
    aliases = {"case": "charcase", "space": "space_char",
               "case_dir": "charcase", "case_file": "charcase",
               "prefix_all": "prefixed_suffixes"}
    for key in config_module.KNOWN_KEYS["naming"]:
        assert aliases.get(key, key) in naming_fields, key

    tag_fields = set(TagProfile.__dataclass_fields__)
    tag_aliases = {"case": "charcase", "id3v2": "id3v2_version"}
    for key in config_module.KNOWN_KEYS["tags"]:
        assert tag_aliases.get(key, key) in tag_fields, key

    from releaser.service import BuildOptions

    build_fields = set(BuildOptions.__dataclass_fields__) | {"catalog_no"}
    build_aliases = {"catalog_no": "use_catalog_no"}
    for key in config_module.KNOWN_KEYS["build"]:
        assert build_aliases.get(key, key) in build_fields, key


# ================================================ Konfiguration speichern


def test_dump_roundtrip():
    config = config_module.Config(
        naming={"group": "GRP", "case_dir": "upper", "prefix_all": True},
        build={"template": "/pfad/v.skl", "sfv_include": ["log", "pdf"]})
    back = config_module.parse(config_module.dump(config))

    assert back.naming == config.naming
    assert back.build == config.build
    assert back.warnings == []


def test_dump_escapes_quotes_and_backslashes():
    config = config_module.Config(naming={"group": 'mit "Zitat" und \\ Strich'})
    back = config_module.parse(config_module.dump(config))
    assert back.naming["group"] == 'mit "Zitat" und \\ Strich'


def test_dump_skips_empty_sections():
    text = config_module.dump(config_module.Config(naming={"group": "X"}))
    assert "[naming]" in text
    assert "[tags]" not in text


def test_save_writes_to_the_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    target = config_module.save(config_module.Config(naming={"group": "GRP"}))

    assert target == tmp_path / "mp3releaser" / "config.toml"
    assert config_module.load(target).naming["group"] == "GRP"


def test_save_accepts_an_explicit_path(tmp_path):
    target = config_module.save(
        config_module.Config(build={"audio_crc": True}),
        tmp_path / "unter" / "eigen.toml")
    assert target.is_file()
    assert config_module.load(target).build["audio_crc"] is True


def test_new_keys_are_known():
    for key in ("case_dir", "case_file", "prefix_all", "companion_prefix"):
        assert key in config_module.KNOWN_KEYS["naming"], key
    assert "template" in config_module.KNOWN_KEYS["build"]


# ================================================ Korrekturen (Fehlerdurchsicht)


def test_every_genre_alias_resolves():
    for alias, target in genres.ALIASES.items():
        assert genres.lookup(target) is not None, alias
    assert genres.normalise("Alternative Rock")[:2] == ("Alt. Rock", 40)


def test_cue_with_utf8_bom_keeps_its_first_line(tmp_path):
    """Der BOM verschluckte die erste Zeile - meist PERFORMER oder REM GENRE."""
    path = tmp_path / "bom.cue"
    path.write_bytes('\ufeffPERFORMER "Der Artist"\nTITLE "Das Album"\n'
                     .encode("utf-8"))
    sheet = cue_module.read_cue(path)
    assert sheet.performer == "Der Artist"
    assert sheet.title == "Das Album"


@pytest.mark.parametrize("line,name,kind", [
    ('FILE "a b.flac" WAVE', "a b.flac", "WAVE"),
    ("FILE mix.mp3 MP3", "mix.mp3", "MP3"),
    ("FILE mix.wav", "mix.wav", "WAVE"),
])
def test_cue_file_type_with_and_without_quotes(line, name, kind):
    sheet = cue_module.parse_cue(line + "\n")
    assert sheet.files[0].name == name
    assert sheet.files[0].file_type == kind


def test_cue_can_be_applied_without_an_origin_map(tmp_path):
    from releaser.audio.base import AudioInfo
    from releaser.audio.scan import _apply_cue_sheets

    audio = tmp_path / "mix.flac"
    (tmp_path / "mix.cue").write_text(
        'FILE "mix.flac" WAVE\n'
        '  TRACK 01 AUDIO\n    TITLE "Eins"\n    INDEX 01 00:00:00\n'
        '  TRACK 02 AUDIO\n    TITLE "Zwei"\n    INDEX 01 01:00:00\n',
        encoding="utf-8")
    info = AudioInfo(path=audio, duration=120.0, size_bytes=1200)
    release = Release(discs=[Disc(1, tracks=[
        Track(1, "mix", 120.0, path=str(audio), size_bytes=1200)])])

    _apply_cue_sheets(tmp_path, release, [info], [])
    assert [t.title for t in release.tracks] == ["Eins", "Zwei"]


def test_split_group_needs_three_parts():
    assert dupecheck.split_group("Artist-Album") == ("Artist-Album", "")
    assert dupecheck.split_group("Artist-Album-GRP") == ("Artist-Album", "GRP")


def test_albums_of_one_artist_without_group_are_not_dupes():
    """Bei zwei Bestandteilen galt das Album als Gruppenkuerzel - dann war
    jedes Album eines Artists ein "identischer" Treffer."""
    index = dupecheck.DupeIndex()
    index.add("Der_Artist-Das_Album")
    assert index.check("Der_Artist-Ein_ganz_anderes_Werk") == []


def test_config_save_ignores_an_empty_xdg_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    target = config_module.save(config_module.Config(naming={"group": "G"}))
    assert target == tmp_path / ".config" / "mp3releaser" / "config.toml"
    assert target.is_file()


def test_config_dump_escapes_control_characters():
    """Ein Zeilenumbruch im Wert machte die gespeicherte Datei unlesbar."""
    value = 'zwei\nZeilen\tmit "Zitat" \\ und \x01'
    again = config_module.parse(config_module.dump(
        config_module.Config(tags={"comment": value})))
    assert again.tags["comment"] == value


def test_config_with_invalid_utf8_is_a_config_error(tmp_path):
    path = tmp_path / "kaputt.toml"
    path.write_bytes(b'[naming]\ngroup = "\xff"\n')
    with pytest.raises(config_module.ConfigError, match="UTF-8"):
        config_module.load(path)
