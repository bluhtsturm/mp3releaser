"""Tests für Herkunftsverfolgung und Feldkatalog."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.fields import (
    BY_NAME,
    FIELDS,
    Consumer,
    build_views,
    group_views,
    overflow_warnings,
    usage,
    widths,
)
from releaser.model import Release
from releaser.naming import NamingProfile
from releaser.provenance import Origin, OriginMap, first_known
from releaser.skl import Template
from releaser.tagwriter import TagProfile

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


def encode(target: Path, *args: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    *args, str(target), "-y"], check=True)
    return target


# =================================================================== Herkunft


def test_every_origin_has_a_label():
    for origin in Origin:
        assert origin.label


def test_trustworthiness():
    assert Origin.TAG.trustworthy
    assert Origin.CUE.trustworthy
    assert not Origin.FILENAME.trustworthy
    assert not Origin.DERIVED.trustworthy


def test_origin_map_release_and_tracks():
    origins = OriginMap()
    origins.set("artist", Origin.TAG)
    origins.set_track(1, 3, "title", Origin.FILENAME)

    assert origins.get("artist") is Origin.TAG
    assert origins.get("album") is Origin.UNKNOWN
    assert origins.get_track(1, 3, "title") is Origin.FILENAME
    assert origins.get_track(2, 1, "title") is Origin.UNKNOWN


def test_uncertain_lists_only_shaky_fields():
    origins = OriginMap()
    origins.set("artist", Origin.TAG)
    origins.set("album", Origin.DIRECTORY)
    origins.set("year", Origin.DERIVED)
    assert origins.uncertain() == ["album", "year"]


def test_manual_overrides_everything():
    origins = OriginMap()
    origins.set("artist", Origin.FILENAME)
    origins.mark_manual("artist")
    assert origins.get("artist") is Origin.MANUAL
    assert origins.uncertain() == []


def test_summary_counts_release_and_tracks():
    origins = OriginMap()
    origins.set("artist", Origin.TAG)
    origins.set_track(1, 1, "title", Origin.TAG)
    origins.set_track(1, 2, "title", Origin.FILENAME)
    assert origins.summary() == {"tag": 2, "filename": 1}


def test_first_known_skips_unknown():
    assert first_known(None, Origin.UNKNOWN, Origin.CUE) is Origin.CUE
    assert first_known(None, Origin.UNKNOWN) is Origin.UNKNOWN


@needs_ffmpeg
def test_scan_records_tag_origin(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "rel"
    encode(root / "01-x.mp3", "-c:a", "libmp3lame",
           "-metadata", "title=Titel", "-metadata", "artist=Der Artist",
           "-metadata", "album=Das Album", "-metadata", "date=2026",
           "-metadata", "genre=Electronic", "-metadata", "track=1/1")

    result = scan_directory(root)
    assert result.origins.get("artist") is Origin.TAG
    assert result.origins.get("album") is Origin.TAG
    assert result.origins.get("genre") is Origin.TAG
    assert result.origins.get_track(1, 1, "title") is Origin.TAG


@needs_ffmpeg
def test_scan_records_filename_origin(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "rel"
    encode(root / "03-aus-dem-dateinamen.mp3", "-c:a", "libmp3lame",
           "-metadata", "artist=Der Artist", "-metadata", "album=Das Album")

    result = scan_directory(root)
    assert result.origins.get_track(1, 3, "title") is Origin.FILENAME
    assert result.origins.get_track(1, 3, "no") is Origin.FILENAME


@needs_ffmpeg
def test_scan_records_directory_fallback(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "Ohne-Album-Tag"
    encode(root / "01-x.mp3", "-c:a", "libmp3lame", "-metadata", "artist=A")

    result = scan_directory(root)
    assert result.origins.get("album") is Origin.DIRECTORY
    assert "album" in result.origins.uncertain()


@needs_ffmpeg
def test_scan_records_cue_origin(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "rel"
    encode(root / "mix.flac", "-c:a", "flac")
    (root / "mix.cue").write_text(
        'PERFORMER "Der Artist"\nTITLE "Das Album"\n'
        'FILE "mix.flac" WAVE\n'
        '  TRACK 01 AUDIO\n    TITLE "Erster"\n    INDEX 01 00:00:00\n',
        encoding="utf-8")

    result = scan_directory(root)
    assert result.origins.get("artist") is Origin.CUE
    assert result.origins.get_track(1, 1, "title") is Origin.CUE


@needs_ffmpeg
def test_various_artists_are_marked_as_derived(tmp_path):
    from releaser.audio import scan_directory

    root = tmp_path / "rel"
    for no, artist in ((1, "Erster Act"), (2, "Zweiter Act")):
        encode(root / f"0{no}-x.mp3", "-c:a", "libmp3lame",
               "-metadata", f"title=Titel {no}", "-metadata", f"artist={artist}",
               "-metadata", "album=Sampler", "-metadata", f"track={no}/2")

    result = scan_directory(root)
    assert result.release.artist == "VA"
    assert result.origins.get("artist") is Origin.DERIVED


# =============================================================== Feldkatalog


def test_field_names_are_release_attributes():
    release = Release()
    for spec in FIELDS:
        assert hasattr(release, spec.name), spec.name


def test_field_tags_exist_in_the_registry():
    from releaser.tags import REGISTRY

    for spec in FIELDS:
        if spec.tag:
            assert spec.tag in REGISTRY, spec.tag


def test_every_consumer_has_a_label():
    for consumer in Consumer:
        assert consumer.label


def test_usage_without_anything_only_marks_tag_fields():
    used = usage()
    assert used["artist"] == {Consumer.TAGS}
    assert used["catalog_no"] == set()


def test_usage_marks_template_fields():
    template = Template.parse("#Artist   \n#Catnr    \n")
    used = usage(template=template)
    assert Consumer.NFO in used["artist"]
    assert Consumer.NFO in used["catalog_no"]


def test_usage_marks_naming_patterns():
    naming = NamingProfile(dir_pattern="#Artist-#Album-#Source-#Year",
                           file_pattern="#N-#Trk")
    used = usage(naming=naming)
    # #Source im Muster speist das eigene Namensfeld, nicht die NFO-Quelle
    assert Consumer.DIRNAME in used["dir_source"]
    assert Consumer.FILENAME not in used["dir_source"]
    assert Consumer.DIRNAME not in used["source"]


def test_usage_follows_tag_profile_options():
    """Ein Feld ohne Tag in jeder Vorlage kann trotzdem gebraucht werden."""
    plain = usage(tags=TagProfile())
    with_catalog = usage(tags=TagProfile(catalog_in_album=True))

    assert plain["catalog_no"] == set()
    assert with_catalog["catalog_no"] == {Consumer.TAGS}


def test_usage_marks_company_when_label_goes_into_the_comment():
    used = usage(tags=TagProfile(label_in_comment=True))
    assert Consumer.TAGS in used["company"]


def test_widths_come_from_the_template():
    template = Template.parse("|#Artist        |\n|#Album   |")
    sizes = widths(template)
    assert sizes["artist"] == 15
    assert sizes["album"] == 9
    assert "catalog_no" not in sizes


def test_widths_without_template_are_empty():
    assert widths(None) == {}


def test_build_views_reads_values_and_origins():
    release = Release(artist="Der Artist", album="Das Album", year=2026,
                      notes=["Zeile eins", "Zeile zwei"])
    origins = OriginMap()
    origins.set("artist", Origin.TAG)

    views = {v.spec.name: v for v in build_views(release, origins=origins)}
    assert views["artist"].value == "Der Artist"
    assert views["artist"].origin_label == "aus den Tags"
    assert views["year"].value == "2026"
    assert views["notes"].value == "Zeile eins\nZeile zwei"
    assert views["subgenre"].value == ""


def test_overflow_is_reported_before_it_happens():
    template = Template.parse("|#Artist   |")      # zehn Zeichen Platz
    release = Release(artist="Ein viel zu langer Artistname")
    views = build_views(release, template=template)

    warnings = overflow_warnings(views)
    assert len(warnings) == 1
    assert "Artist" in warnings[0]

    artist = next(v for v in views if v.spec.name == "artist")
    assert artist.overflows
    assert artist.truncated == "Ein viel z"


def test_no_overflow_when_it_fits():
    template = Template.parse("|#Artist                  |")
    views = build_views(Release(artist="Kurz"), template=template)
    assert overflow_warnings(views) == []


def test_group_views_puts_unused_last():
    template = Template.parse("#Artist   \n")
    views = build_views(Release(artist="A"), template=template,
                        naming=NamingProfile())
    groups = group_views(views)

    titles = [title for title, _ in groups]
    assert titles[-1] == "nicht verwendet"
    assert "in der Vorlage" in titles


def test_a_field_can_appear_in_several_groups():
    template = Template.parse("#Artist   \n")
    views = build_views(Release(artist="A"), template=template,
                        naming=NamingProfile(dir_pattern="#Artist"))
    groups = dict(group_views(views))

    assert "artist" in [v.spec.name for v in groups["in der Vorlage"]]
    assert "artist" in [v.spec.name for v in groups["im Verzeichnisnamen"]]


def test_unused_fields_stay_visible():
    """Sie werden eingeordnet, nicht ausgegraut - die Vorlage kann sich ändern."""
    views = build_views(Release())
    unused = [v for v in views if v.unused]
    assert unused
    assert all(v.value == "" for v in unused)
    assert BY_NAME["subgenre"] in [v.spec for v in unused]


def test_album_addition_is_a_profile_text_not_a_release_field():
    """Der Zusatz im Tag-Profil sagt nichts ueber das Releasefeld aus."""
    used = usage(tags=TagProfile(album_addition="CDDA"))
    assert used["album_addition"] == set()


# ================================ Quelle: NFO und Name sind eigene Felder


def test_nfo_source_and_name_source_are_independent():
    """"Quelle" in der Vorlage und im Verzeichnisnamen füllen sich nicht
    gegenseitig aus - es sind zwei Felder mit je eigenem Wert."""
    from releaser.model import Release
    from releaser.naming import release_dirname
    from releaser.tags import Settings

    naming = NamingProfile(dir_pattern="#Artist-#Source-#Year", group="")
    template = Template.parse("#Source          |")

    only_nfo = Release(artist="A", year=2026, source="Vinyl (180 g)")
    assert release_dirname(only_nfo, naming) == "a-2026"
    assert "Vinyl (180 g)" in template.render(only_nfo, Settings())

    only_name = Release(artist="A", year=2026, dir_source="VINYL")
    assert release_dirname(only_name, naming) == "a-vinyl-2026"
    assert "VINYL" not in template.render(only_name, Settings())


def test_both_source_fields_appear_in_their_own_group():
    from releaser.model import Release

    template = Template.parse("#Source          |")
    naming = NamingProfile(dir_pattern="#Artist-#Source")
    release = Release(artist="A", source="Vinyl (180 g)", dir_source="VINYL")
    groups = dict(group_views(build_views(release, template=template,
                                          naming=naming)))

    in_template = {v.spec.name: v.value for v in groups["in der Vorlage"]}
    in_dirname = {v.spec.name: v.value for v in groups["im Verzeichnisnamen"]}
    assert in_template.get("source") == "Vinyl (180 g)"
    assert "dir_source" not in in_template
    assert in_dirname.get("dir_source") == "VINYL"
    assert "source" not in in_dirname
