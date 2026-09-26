"""Tests für das Naming-Schema."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.model import Disc, Release, Track
from releaser.naming import (
    companion_name,
    DEFAULT_PIPELINE,
    NameContext,
    NamingProfile,
    Pattern,
    RenameOp,
    Scope,
    apply_plan,
    disc_dirname,
    plan_rename,
    release_dirname,
    rule_collapse,
    rule_forbidden,
    rule_inch,
    rule_spaces,
    rule_transliterate,
    track_stem,
)
from releaser.text import CharCase


def make_release(tmp_path: Path, multi: bool = False, titles=None) -> tuple[Release, Path]:
    titles = titles or ["Erster Titel", "Zweiter Titel"]
    root = tmp_path / "ROHDATEN"
    discs = []
    if multi:
        layout = [(1, titles[:1]), (2, titles[1:])]
    else:
        layout = [(1, titles)]
    for number, names in layout:
        directory = root / f"CD{number}" if multi else root
        directory.mkdir(parents=True, exist_ok=True)
        tracks = []
        for no, title in enumerate(names, start=1):
            path = directory / f"{no:02d} RAW {title}.mp3"
            # eindeutiger Inhalt, damit sich Dateien nach dem Umbenennen
            # auseinanderhalten lassen
            path.write_bytes(b"\xff\xfb\x90\x00" + f"{number}-{no}".encode())
            tracks.append(Track(no, title, 100.0, number, str(path), 4))
        discs.append(Disc(number, tracks=tracks))
    release = Release(artist="Der Artist", album="Das Album", year=2026,
                      source="CDDA", dirname=root.name, discs=discs)
    return release, root


# ------------------------------------------------------------- Musterteil


def test_pattern_lists_its_tags():
    p = Pattern("#Artist-#Album-#Source-#Year-#Grp")
    assert p.tags() == ["#Artist", "#Album", "#Source", "#Year", "#Grp"]


def test_pattern_longest_match_for_naming_tags():
    assert Pattern("#Cd2").tags() == ["#Cd2"]
    assert Pattern("#Cd").tags() == ["#Cd"]
    # #Grp darf nicht als #Genre gelesen werden und umgekehrt
    assert Pattern("#Grp").tags() == ["#Grp"]
    assert Pattern("#Genre").tags() == ["#Genre"]


def test_pattern_keeps_literal_text():
    release = Release(artist="A", album="B")
    ctx = NameContext(release=release, group="GRP")
    assert Pattern("(#Artist)_[#Album]").render(ctx) == "(A)_[B]"


def test_pattern_renders_disc_number():
    release = Release(discs=[Disc(7)])
    ctx = NameContext(release=release, disc=release.discs[0])
    assert Pattern("CD#Cd").render(ctx) == "CD7"
    assert Pattern("CD#Cd2").render(ctx) == "CD07"


def test_unknown_tag_stays_literal():
    ctx = NameContext(release=Release(artist="A"))
    assert Pattern("#Artist-#GibtsNicht").render(ctx) == "A-#GibtsNicht"


# ------------------------------------------------------------- Regelkette


@pytest.mark.parametrize("value,expected", [
    ('12" Mix', "12INCH Mix"),
    ('7"', "7INCH"),
    ('Er sagte "hallo"', "Er sagte hallo"),
])
def test_rule_inch(value, expected):
    assert rule_inch(value) == expected


def test_rule_transliterate():
    assert rule_transliterate("Die Ärzte – Größe") == "Die Aerzte - Groesse"


def test_rule_forbidden_removes_path_characters():
    assert rule_forbidden('a/b\\c:d*e?f"g<h>i|j') == "abcdefghij"


def test_rule_spaces_uses_configured_character():
    assert rule_spaces("  a  b  ") == "a_b"
    assert rule_spaces("a b", "-") == "a-b"


def test_rule_collapse_merges_separator_runs():
    assert rule_collapse("a__b") == "a_b"
    assert rule_collapse("a---b") == "a-b"
    # Gemischte Folge: der Bindestrich gewinnt, er trennt im Muster
    assert rule_collapse("a_-_b") == "a-b"


def test_pipeline_order_is_configurable():
    profile = NamingProfile(pipeline=("forbidden",),
                            charcase={Scope.FILENAME: CharCase.UNCHANGED})
    # ohne "spaces" bleiben Leerzeichen stehen
    assert profile.sanitize("a b/c", Scope.FILENAME) == "a bc"


def test_unknown_rule_is_rejected():
    profile = NamingProfile(pipeline=("gibtsnicht",))
    with pytest.raises(KeyError):
        profile.sanitize("x", Scope.FILENAME)


def test_charcase_is_per_scope():
    profile = NamingProfile(charcase={
        Scope.DIRECTORY: CharCase.LOWER,
        Scope.TAG: CharCase.UPPER,
    })
    assert profile.sanitize("Ein Name", Scope.DIRECTORY) == "ein_name"
    assert profile.sanitize("Ein Name", Scope.TAG) == "EIN_NAME"


def test_default_pipeline_is_documented_order():
    assert DEFAULT_PIPELINE[0] == "inch"          # vor transliterate
    assert DEFAULT_PIPELINE.index("spaces") < DEFAULT_PIPELINE.index("collapse")


# --------------------------------------------------------------- Namen


def test_release_dirname_uses_pattern_and_group():
    release = Release(artist='Die Ärzte', album='Ein Album (12" Mix)',
                      year=2026, source="CDDA")
    name = release_dirname(release, NamingProfile(group="GRP"))
    # Klammern und andere Sonderzeichen gehoeren nicht in Dateinamen - der
    # Trennstrich des Musters bleibt aber erhalten
    assert name == "die_aerzte-ein_album_12inch_mix-cdda-2026-grp"


def test_disc_dirname():
    release = Release(discs=[Disc(2)])
    assert disc_dirname(release, release.discs[0], NamingProfile()) == "cd2"


def test_intro_gets_artist_prefix_only_when_pattern_lacks_it():
    release = Release(artist="Der Artist", discs=[Disc(1)])
    disc = release.discs[0]
    track = Track(2, "intro", 10.0)

    with_artist = NamingProfile(file_pattern="#N-#Artist-#Trk")
    without = NamingProfile(file_pattern="#N-#Trk")

    assert track_stem(release, track, disc, with_artist) == "02-der_artist-intro"
    assert track_stem(release, track, disc, without) == "02-der_artist-intro"
    # ohne die Regel bliebe der nackte Name stehen
    off = NamingProfile(file_pattern="#N-#Trk", rename_intro=False)
    assert track_stem(release, track, disc, off) == "02-intro"


# -------------------------------------------------------------- Planung


def test_plan_is_a_pure_preview(tmp_path):
    release, root = make_release(tmp_path)
    before = {p.name for p in root.rglob("*")}
    plan = plan_rename(release, root, NamingProfile(group="GRP"))
    assert plan.changes
    assert {p.name for p in root.rglob("*")} == before      # nichts angefasst


def test_plan_reports_no_change_when_names_already_match(tmp_path):
    release, root = make_release(tmp_path)
    profile = NamingProfile(group="GRP")
    apply_plan(plan_rename(release, root, profile), release)
    new_root = Path(release.tracks[0].path).parent

    second = plan_rename(release, new_root, profile)
    assert second.changes == []


def test_plan_detects_name_collision(tmp_path):
    release, root = make_release(tmp_path, titles=["Gleicher Titel", "Gleicher Titel"])
    plan = plan_rename(release, root, NamingProfile(file_pattern="#Trk"))
    assert plan.collisions
    assert plan.is_safe is False


def test_plan_warns_about_long_names(tmp_path):
    release, root = make_release(tmp_path)
    release.album = "A" * 200
    plan = plan_rename(release, root, NamingProfile(max_dir_length=60))
    assert any("Releasename" in w for w in plan.warnings)


def test_plan_warns_about_tracks_without_path(tmp_path):
    release, root = make_release(tmp_path)
    release.discs[0].tracks[0].path = None
    plan = plan_rename(release, root, NamingProfile())
    assert any("Dateipfad" in w for w in plan.warnings)


def test_plan_detects_existing_target_directory(tmp_path):
    release, root = make_release(tmp_path)
    (tmp_path / "der_artist-das_album-cdda-2026-grp").mkdir()
    plan = plan_rename(release, root, NamingProfile(group="GRP"))
    assert any("existiert bereits" in c for c in plan.collisions)


def test_plan_ignores_targets_that_are_own_sources(tmp_path):
    """Ein Ziel, das gerade noch eine Quelle ist, ist keine Kollision."""
    release, root = make_release(tmp_path, titles=["Titel", "Titel"])
    profile = NamingProfile(group="GRP")
    apply_plan(plan_rename(release, root, profile), release)
    a, b = release.discs[0].tracks
    a.no, b.no = b.no, a.no
    plan = plan_rename(release, Path(a.path).parent, profile)
    assert plan.is_safe


def test_apply_refuses_unsafe_plan(tmp_path):
    release, root = make_release(tmp_path, titles=["Gleich", "Gleich"])
    plan = plan_rename(release, root, NamingProfile(file_pattern="#Trk"))
    with pytest.raises(ValueError):
        apply_plan(plan)


# ------------------------------------------------------------ Ausführung


def test_apply_renames_files_and_root(tmp_path):
    release, root = make_release(tmp_path)
    profile = NamingProfile(group="GRP")
    apply_plan(plan_rename(release, root, profile), release)

    new_root = tmp_path / "der_artist-das_album-cdda-2026-grp"
    assert new_root.is_dir()
    assert not root.exists()
    assert sorted(p.name for p in new_root.glob("*.mp3")) == [
        "01-der_artist-erster_titel.mp3", "02-der_artist-zweiter_titel.mp3"]


def test_apply_updates_paths_in_the_model(tmp_path):
    release, root = make_release(tmp_path, multi=True)
    apply_plan(plan_rename(release, root, NamingProfile(group="GRP")), release)

    for track in release.tracks:
        assert Path(track.path).is_file()
    assert release.dirname == "der_artist-das_album-cdda-2026-grp"
    assert Path(release.tracks[1].path).parent.name == "cd2"


def test_apply_handles_multi_disc_directories(tmp_path):
    release, root = make_release(tmp_path, multi=True)
    apply_plan(plan_rename(release, root, NamingProfile(group="GRP")), release)

    new_root = tmp_path / "der_artist-das_album-cdda-2026-grp"
    assert sorted(p.name for p in new_root.iterdir()) == ["cd1", "cd2"]


def test_apply_survives_swapped_names(tmp_path):
    """Echter Zyklus: zwei Dateien tauschen ihre Namen.

    Dafür müssen die Namen schon im Zielformat vorliegen - deshalb erst
    normalisieren, dann die Tracknummern tauschen. Naives Umbenennen würde
    hier eine der beiden Dateien überschreiben.
    """
    release, root = make_release(tmp_path, titles=["Titel", "Titel"])
    profile = NamingProfile(group="GRP")
    apply_plan(plan_rename(release, root, profile), release)

    a, b = release.discs[0].tracks
    content_a = Path(a.path).read_bytes()
    content_b = Path(b.path).read_bytes()
    assert content_a != content_b

    a.no, b.no = b.no, a.no          # 1 <-> 2
    new_root = Path(a.path).parent
    plan = plan_rename(release, new_root, profile)
    assert plan.is_safe
    apply_plan(plan, release)

    assert Path(a.path).name == "02-der_artist-titel.mp3"
    assert Path(b.path).name == "01-der_artist-titel.mp3"
    assert Path(a.path).read_bytes() == content_a     # nichts überschrieben
    assert Path(b.path).read_bytes() == content_b


def test_apply_handles_case_only_rename(tmp_path):
    release, root = make_release(tmp_path, titles=["TITEL"])
    profile = NamingProfile(file_pattern="#Trk",
                            charcase={Scope.FILENAME: CharCase.LOWER,
                                      Scope.DIRECTORY: CharCase.LOWER})
    apply_plan(plan_rename(release, root, profile), release)
    assert Path(release.tracks[0].path).name == "titel.mp3"


def test_apply_leaves_no_temporary_files(tmp_path):
    release, root = make_release(tmp_path, multi=True)
    apply_plan(plan_rename(release, root, NamingProfile(group="GRP")), release)
    new_root = tmp_path / "der_artist-das_album-cdda-2026-grp"
    assert not any("mp3releaser-tmp" in p.name for p in new_root.rglob("*"))


def test_rename_op_change_detection(tmp_path):
    same = RenameOp(tmp_path / "a", tmp_path / "a", "file")
    other = RenameOp(tmp_path / "a", tmp_path / "b", "file")
    assert same.changed is False and other.changed is True


def test_failed_apply_rolls_everything_back(tmp_path, monkeypatch):
    """Bricht eine Umbenennung ab, bleibt nichts halb erledigt liegen."""
    release, root = make_release(tmp_path, multi=True)
    before = sorted(str(p.relative_to(tmp_path)) for p in root.rglob("*"))

    original_rename = Path.rename
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] == 5:
            raise OSError("simulierter Fehler")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky)

    with pytest.raises(OSError):
        apply_plan(plan_rename(release, root, NamingProfile(group="GRP")), release)

    monkeypatch.setattr(Path, "rename", original_rename)
    after = sorted(str(p.relative_to(tmp_path)) for p in root.rglob("*"))
    assert after == before
    assert not any(".mp3releaser-" in name for name in after)


def test_temporary_names_are_unique_per_run(tmp_path):
    """Eine Altlast aus einem frueheren Lauf darf den naechsten nicht blockieren."""
    release, root = make_release(tmp_path)
    (root / ".mp3releaser-deadbeef-0").write_bytes(b"altlast")
    apply_plan(plan_rename(release, root, NamingProfile(group="GRP")), release)
    assert Path(release.tracks[0].path).is_file()


# ================================ Schreibweisen von Ordner und Dateien


def test_capitalize_treats_underscores_as_word_boundaries():
    """Nach der Regelkette trennen Unterstriche die Wörter.

    In Python zählt ``_`` als Wortzeichen - ohne Sonderbehandlung wäre
    ``der_artist`` ein einziges Wort und würde zu ``Der_artist``.
    """
    from releaser.text import capitalize_words

    assert capitalize_words("der_artist-das_album") == "Der_Artist-Das_Album"


def test_capitalize_keeps_short_acronyms():
    from releaser.text import capitalize_words

    assert capitalize_words("Der_Artist-CDDA-2026-GRP") == \
        "Der_Artist-CDDA-2026-GRP"
    assert capitalize_words("DJ_Soundso") == "DJ_Soundso"
    # Ab fuenf Zeichen gilt Grossschreibung nicht mehr als Akronym
    assert capitalize_words("REMIXED") == "Remixed"
    assert capitalize_words("ALBUM_REMIXED") == "Album_Remixed"   # beide > 4


def test_directory_capitalized_while_files_stay_lowercase():
    release = Release(artist="die ärzte", album="ein Album", year=2026,
                      source="CDDA", dirname="roh",
                      discs=[Disc(1, tracks=[Track(1, "Erster Titel", 10.0)])])
    profile = NamingProfile(group="GRP", charcase={
        Scope.DIRECTORY: CharCase.CAPITALIZE,
        Scope.FILENAME: CharCase.LOWER,
    })

    directory = release_dirname(release, profile)
    assert directory == "Die_Aerzte-Ein_Album-CDDA-2026-GRP"

    stem = track_stem(release, release.tracks[0], release.discs[0], profile)
    assert stem == "01-die_aerzte-erster_titel"
    assert stem.islower()


def test_companions_follow_the_file_case_not_the_directory():
    """Begleitdateien sind Dateien - sie gehören zur Dateischreibweise."""
    release = Release(artist="A", album="B", dirname="Der_Ordner-2026-GRP")
    profile = NamingProfile(companion_prefix="", charcase={
        Scope.DIRECTORY: CharCase.CAPITALIZE,
        Scope.FILENAME: CharCase.LOWER,
    })
    for suffix in (".nfo", ".sfv", ".m3u", ".jpg"):
        name = companion_name(release, suffix, profile)
        assert name == f"der_ordner-2026-grp{suffix}", name


def test_cover_follows_the_file_case_too(tmp_path):
    """Ein Cover ist eine Begleitdatei - kein Verzeichnis."""
    from releaser.naming import future_companion_stem

    release, root = make_release(tmp_path)
    (root / "folder.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    profile = NamingProfile(group="GRP", companion_prefix="00-", charcase={
        Scope.DIRECTORY: CharCase.CAPITALIZE,
        Scope.FILENAME: CharCase.LOWER,
    })

    plan = plan_rename(release, root, profile)
    cover = next(op for op in plan.changes if op.src.suffix == ".jpg")
    assert cover.dst.name == "00-" + future_companion_stem(release, profile) + ".jpg"
    assert cover.dst.name.islower()

    root_op = next(op for op in plan.ops if op.kind == "root")
    assert not root_op.dst.name.islower()      # der Ordner bleibt kapitalisiert


# ============================================ Formatkennung im Ordnernamen


@pytest.mark.parametrize("audio_format,extra,expected", [
    ("MP3", "", ""),
    ("FLAC", "", "FLAC"),
    ("AAC", "", "AAC"),
    ("EAC3", "Dolby Atmos (JOC) (16 Objekte)", "ATMOS"),
    ("ALAC", "", ""),
    ("", "", ""),
])
def test_format_marker(audio_format, extra, expected):
    from releaser.naming import format_marker

    release = Release(audio_format=audio_format, released_with=extra)
    assert format_marker(release) == expected


def test_atmos_beats_the_container_format():
    """Eine EC-3-Datei mit JOC ist für den Hörer ein Atmos-Release."""
    from releaser.naming import format_marker

    assert format_marker(Release(audio_format="AAC",
                                 released_with="Dolby ATMOS (JOC)")) == "ATMOS"


@pytest.mark.parametrize("audio_format,expected", [
    ("MP3", "der_artist-das_album-cdda-2026-grp"),
    ("FLAC", "der_artist-das_album-cdda-flac-2026-grp"),
    ("AAC", "der_artist-das_album-cdda-aac-2026-grp"),
])
def test_format_appears_before_the_year(audio_format, expected):
    release = Release(artist="Der Artist", album="Das Album", year=2026,
                      source="CDDA", audio_format=audio_format)
    profile = NamingProfile(group="GRP", charcase={Scope.DIRECTORY: CharCase.LOWER})
    assert release_dirname(release, profile) == expected


def test_empty_format_leaves_no_double_separator():
    """Ohne Kennung darf kein '--' im Namen stehen bleiben."""
    release = Release(artist="A", album="B", year=2026, source="CDDA",
                      audio_format="MP3")
    name = release_dirname(release, NamingProfile(group="GRP"))
    assert "--" not in name


def test_format_tag_is_recognised_in_a_pattern():
    from releaser.naming import Pattern

    assert "#Fmt" in Pattern("#Artist-#Fmt-#Year").tags()


def test_format_tag_counts_as_the_format_field():
    """Für den Feldkatalog gehört #Fmt zum Feld „Format“."""
    from releaser.fields import Consumer, usage

    used = usage(naming=NamingProfile(dir_pattern="#Artist-#Fmt-#Year"))
    assert Consumer.DIRNAME in used["audio_format"]


# ================================================= Fehlerhafte Muster


def test_unknown_tags_are_detected():
    from releaser.naming import unknown_tags

    assert unknown_tags("#Artist-#Quatsch-#Year") == ["#Quatsch"]
    assert unknown_tags("#Artist-#Album-#Fmt-#Year-#Grp") == []
    # Ein '#' ohne Wort dahinter ist kein Tag-Versuch
    assert unknown_tags("Nummer # 3") == []


def test_empty_directory_pattern_is_refused(tmp_path):
    """Ein leeres Muster zielte sonst auf das übergeordnete Verzeichnis."""
    release, root = make_release(tmp_path)
    plan = plan_rename(release, root, NamingProfile(dir_pattern=""))

    assert not plan.is_safe
    assert any("leer" in collision for collision in plan.collisions)
    assert not any(op.kind == "root" for op in plan.ops)


# ====================================== Nur Buchstaben, Ziffern, Trenner


@pytest.mark.parametrize("value,expected", [
    # Der Gedankenstrich wird zum Bindestrich - er war ja einer
    ("Die Ärzte – Größe, Teil 2!", "die_aerzte-groesse_teil_2"),
    ("Rock'n'Roll (Live @ Köln)", "rocknroll_live_koeln"),
    ("Über/Unter: Test?", "ueber_unter_test"),
    ("A.I. [Remix] #1", "a_i_remix_1"),
    ("Ü-Wagen & Co.", "ue-wagen_co"),
    ('12" Mix', "12inch_mix"),
])
def test_only_letters_digits_and_separators_survive(value, expected):
    profile = NamingProfile(charcase={Scope.FILENAME: CharCase.LOWER})
    assert profile.sanitize(value, Scope.FILENAME) == expected


def test_apostrophes_vanish_instead_of_becoming_separators():
    from releaser.naming import rule_alnum

    assert rule_alnum("Don't") == "Dont"
    assert rule_alnum("Rock’n’Roll") == "RocknRoll"


def test_umlauts_become_two_letters_not_nothing():
    """Die Reihenfolge zählt: erst umschreiben, dann aussortieren."""
    profile = NamingProfile(charcase={Scope.FILENAME: CharCase.UNCHANGED})
    assert profile.sanitize("Ärger Öl Über", Scope.FILENAME) == "Aerger_Oel_Ueber"


def test_alnum_runs_after_transliterate_in_the_default_pipeline():
    from releaser.naming import DEFAULT_PIPELINE

    assert (DEFAULT_PIPELINE.index("transliterate")
            < DEFAULT_PIPELINE.index("alnum"))


def test_the_rule_does_not_touch_tags(tmp_path):
    """Kommas und Klammern gehören ins Tag - nur nicht in den Dateinamen."""
    from releaser.tagwriter import TagProfile, desired_tags

    release = Release(artist="Die Ärzte", album="Ein Album (12\" Mix), Teil 2",
                      discs=[Disc(1, tracks=[Track(1, "Titel, mit Komma", 10.0)])])
    values = desired_tags(release, release.discs[0], release.tracks[0],
                          TagProfile())
    assert values["title"] == "Titel, mit Komma"
    assert values["album"] == 'Ein Album (12" Mix), Teil 2'
    assert values["artist"] == "Die Ärzte"


def test_a_special_character_does_not_eat_the_pattern_separator():
    """„…(Mix)-CDDA…" darf nicht zu „…mix_cdda…" werden."""
    from releaser.naming import rule_collapse

    assert rule_collapse("mix_-cdda") == "mix-cdda"
    assert rule_collapse("mix -_- cdda") == "mix-cdda"
    # Ohne Strich bleibt es beim Unterstrich
    assert rule_collapse("wort   wort") == "wort_wort"


# ------------------------------------------------ Korrekturen (Fehlerdurchsicht)


def test_unknown_tags_checks_each_text_part_on_its_own():
    """Zusammengefuegte Textteile ergaben Tags, die niemand geschrieben hat."""
    from releaser.naming import unknown_tags

    assert unknown_tags("x##Albumfoo") == []
    assert unknown_tags("#Artist-#Quatsch") == ["#Quatsch"]


def test_another_name_for_the_same_file_is_no_collision(tmp_path):
    """Auf FAT oder SMB ist ``track.mp3`` dieselbe Datei wie ``Track.mp3``.

    Nachgestellt mit einem harten Link: zwei Namen, eine Datei.
    """
    from releaser.naming import RenamePlan, _check_existing_targets

    src = tmp_path / "Track.mp3"
    src.write_bytes(b"x")
    dst = tmp_path / "track.mp3"
    dst.hardlink_to(src)
    plan = RenamePlan(ops=[RenameOp(src, dst, "file")])
    _check_existing_targets(plan)
    assert plan.collisions == []


def test_a_foreign_file_at_the_target_is_still_a_collision(tmp_path):
    from releaser.naming import RenamePlan, _check_existing_targets

    src = tmp_path / "Track.mp3"
    src.write_bytes(b"x")
    dst = tmp_path / "track.mp3"
    dst.write_bytes(b"fremd")
    plan = RenamePlan(ops=[RenameOp(src, dst, "file")])
    _check_existing_targets(plan)
    assert plan.collisions
