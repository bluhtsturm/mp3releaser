"""Sampler (VA) und Split-Releases.

Die Artists je Track stehen hier fuer sich: in den Tags, in den Dateinamen
und in der Trackliste der .nfo. Das Artist-Feld des Releases ist zugleich der
Schalter - "VA" fuer einen Sampler, "A / B / C" fuer einen Split, alles
andere ein normales Release. Beim Einlesen wird es passend vorbelegt.

Bis 0.27.6 gingen die Artists je Track verloren, sobald ein Albumartist
gesetzt war ("Various Artists" - so taggen fast alle Shops), und "Release
erstellen" schrieb dann den Albumartist in jeden Track.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.audio import scan_directory  # noqa: E402
from releaser.audio.scan import _release_artist  # noqa: E402
from releaser.config import Config  # noqa: E402
from releaser.model import Disc, Release, Track  # noqa: E402
from releaser.naming import (  # noqa: E402
    NamingProfile, Pattern, Scope, companion_name, plan_rename,
    release_dirname)
from releaser.service import naming_from_config  # noqa: E402
from releaser.skl import Template  # noqa: E402
from releaser.tagwriter import TagProfile, plan_tags  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None,
                                  reason="ffmpeg nicht vorhanden")

TEMPLATE = Template.parse("#Artist                         |\n"
                          "#N. #Trk                        |")


def encode(target: Path, *meta: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    args = []
    for item in meta:
        args += ["-metadata", item]
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=duration=1",
                    "-c:a", "libmp3lame", *args, str(target), "-y"], check=True)
    return target


def release_dir(tmp_path: Path, name: str, album_artist: str,
                tracks: list[tuple[str, str]]) -> Path:
    root = tmp_path / name
    for no, (artist, title) in enumerate(tracks, start=1):
        meta = [f"artist={artist}", f"title={title}", "album=Sampler",
                f"track={no}/{len(tracks)}", "date=2026"]
        if album_artist:
            meta.append(f"album_artist={album_artist}")
        encode(root / f"0{no}.mp3", *meta)
    return root


def preset() -> NamingProfile:
    """Wie die Oberflaechen: Ordner "Wörter Groß", Dateien klein."""
    return naming_from_config(Config(), group="GRP")


def names(release: Release, root: Path) -> tuple[str, list[str]]:
    plan = plan_rename(release, root, preset())
    directory = next(op.dst.name for op in plan.ops if op.kind == "root")
    return directory, [op.dst.name for op in plan.ops if op.kind == "file"]


# ================================================================== Erkennung


@pytest.mark.parametrize("artists,album_artist,dirname,expected", [
    # Albumartist eines Samplers, wie Shops ihn setzen
    (["Eins", "Zwei", "Drei"], "Various Artists", "", ("VA", "va")),
    (["Eins", "Zwei", "Drei"], "VA", "", ("VA", "va")),
    # ohne Albumartist: drei Artists mit je einem Track sind ein Sampler
    (["Eins", "Zwei", "Drei"], "", "", ("VA", "va")),
    # der Ordner kuendigt ihn schon an
    (["Eins", "Zwei"], "", "VA-Sampler-2026-GRP", ("VA", "va")),
    # zwei Artists - die typische Split-Single
    (["Artist A", "Artist B"], "", "", ("Artist A / Artist B", "split")),
    # drei in Bloecken, mehrere Tracks je Artist
    (["A1", "A1", "B2", "B2", "C3", "C3"], "", "", ("A1 / B2 / C3", "split")),
    # Albumartist nennt alle - wird zur Schreibweise des Feldes
    (["Artist A", "Artist A", "Artist B"], "Artist A & Artist B", "",
     ("Artist A / Artist B", "split")),
    # Album mit Gaesten bleibt ein normales Album
    (["Band", "Band feat. Gast", "Band"], "Band", "", ("Band", "normal")),
    (["Band", "Band feat. Gast"], "", "", ("Band", "normal")),
    # ein DJ-Mix: der Albumartist bleibt
    (["P", "Q", "R", "S", "T"], "Some DJ", "", ("Some DJ", "normal")),
    # nur ein Artist
    (["Band", "Band"], "", "", ("Band", "normal")),
])
def test_release_artist_rules(artists, album_artist, dirname, expected):
    assert _release_artist(artists, album_artist, dirname) == expected


# ============================================== Einlesen, Taggen, Benennen


@needs_ffmpeg
def test_various_artists_album_artist_no_longer_loses_the_track_artists(tmp_path):
    """Der Fehler bis 0.27.6: Albumartist "Various Artists" warf die Artists
    je Track weg - und beim Taggen stand danach "Various Artists" in jedem
    Track."""
    root = release_dir(tmp_path, "rel", "Various Artists", [
        ("Artist Eins", "Erster Song"), ("Artist Zwei", "Zweiter Song"),
        ("Artist Drei", "Dritter Song")])
    release = scan_directory(root).release
    assert release.artist == "VA" and release.multi_artist
    assert [t.artist for t in release.tracks] == [
        "Artist Eins", "Artist Zwei", "Artist Drei"]

    targets = plan_tags(release, TagProfile()).targets
    written = [targets[p] for p in sorted(targets)]
    assert [t["artist"] for t in written] == [
        "Artist Eins", "Artist Zwei", "Artist Drei"]
    assert {t["albumartist"] for t in written} == {"Various Artists"}
    assert [t["title"] for t in written] == [
        "Erster Song", "Zweiter Song", "Dritter Song"]

    directory, files = names(release, root)
    assert directory == "VA-Sampler-2026-GRP"
    assert files == ["01-artist_eins-erster_song.mp3",
                     "02-artist_zwei-zweiter_song.mp3",
                     "03-artist_drei-dritter_song.mp3"]

    nfo = TEMPLATE.render(release).split("\n")
    assert nfo[0].startswith("VA")
    assert nfo[1].startswith("01. Artist Eins - Erster Song")


@needs_ffmpeg
def test_va_without_album_artist_has_no_doubled_name(tmp_path):
    """Ohne Albumartist hiessen die Dateien "01-va-artist_eins-…"."""
    root = release_dir(tmp_path, "rel", "", [
        ("Artist Eins", "Erster Song"), ("Artist Zwei", "Zweiter Song"),
        ("Artist Drei", "Dritter Song")])
    release = scan_directory(root).release
    _directory, files = names(release, root)
    assert files[0] == "01-artist_eins-erster_song.mp3"


@needs_ffmpeg
def test_split_release(tmp_path):
    root = release_dir(tmp_path, "rel", "Artist A & Artist B", [
        ("Artist A", "Song A1"), ("Artist A", "Song A2"),
        ("Artist B", "Song B1"), ("Artist B", "Song B2")])
    release = scan_directory(root).release
    assert release.artist == "Artist A / Artist B"

    directory, files = names(release, root)
    # Jeder Artist fuer sich in "Wörter Groß" - das "A" ist kein Fuellwort
    assert directory == "Artist_A__Artist_B-Sampler-2026-GRP"
    assert files[2] == "03-artist_b-song_b1.mp3"

    targets = plan_tags(release, TagProfile()).targets
    first = targets[sorted(targets)[0]]
    assert (first["artist"], first["albumartist"]) == (
        "Artist A", "Artist A / Artist B")
    assert TEMPLATE.render(release).split("\n")[3].startswith(
        "03. Artist B - Song B1")


@needs_ffmpeg
def test_album_with_guests_stays_a_normal_album(tmp_path):
    """"Band feat. Gast" bleibt im Tag - die Trackliste zeigt den Titel, und
    der Albumartist wird nicht in den Track geschrieben."""
    root = release_dir(tmp_path, "rel", "Band", [
        ("Band", "Eins"), ("Band feat. Gast", "Zwei"), ("Band", "Drei")])
    release = scan_directory(root).release
    assert release.artist == "Band" and not release.multi_artist
    targets = plan_tags(release, TagProfile()).targets
    assert [targets[p]["artist"] for p in sorted(targets)] == [
        "Band", "Band feat. Gast", "Band"]
    assert TEMPLATE.render(release).split("\n")[2].startswith("02. Zwei")
    _directory, files = names(release, root)
    assert files[1] == "02-band-zwei.mp3"


# ============================================================ Artist-Feld


@pytest.mark.parametrize("artist,expected", [
    ("Artist 1 / Artist 2 / Artist 3",
     "Artist_1__Artist_2__Artist_3-Das_Album-2026-GRP"),
    ("Artist A / Artist B", "Artist_A__Artist_B-Das_Album-2026-GRP"),
    ("VA", "VA-Das_Album-2026-GRP"),
    # ohne Leerzeichen um den Schraegstrich ist es ein Artist
    ("AC/DC", "AC_DC-Das_Album-2026-GRP"),
])
def test_artist_field_decides_the_directory(artist, expected):
    release = Release(artist=artist, album="Das Album", year=2026)
    assert release_dirname(release, preset()) == expected


def test_split_in_lowercase():
    profile = naming_from_config(Config(naming={"case_dir": "lower"}),
                                 group="GRP")
    release = Release(artist="Artist A / Artist B", album="Das Album", year=2026)
    assert release_dirname(release, profile) == \
        "artist_a__artist_b-das_album-2026-GRP"


def test_hand_written_split_directory_keeps_its_double_separator():
    """Ein von Hand eingetragener Verzeichnisname ist ein Muster ohne Tags -
    die Regelkette fasste "__" sonst zu "_" zusammen."""
    profile = preset()
    pattern = Pattern("Artist_1__Artist_2-Das_Album-2026-GRP")
    from releaser.naming import NameContext

    name = profile.render_name(pattern, NameContext(
        release=Release(), group="GRP"), Scope.DIRECTORY)
    assert name == "Artist_1__Artist_2-Das_Album-2026-GRP"


def test_multi_artist_follows_the_artist_field():
    tracks = [Track(1, "Eins", 1.0, artist="Artist Eins"),
              Track(2, "Zwei", 1.0, artist="Artist Zwei")]
    release = Release(artist="VA", discs=[Disc(1, tracks=tracks)])
    assert release.multi_artist
    release.artist = "Artist Eins / Artist Zwei"
    assert release.multi_artist
    # Ein normales Album mit Gast: der Gast enthaelt den Release-Artist
    guest = Release(artist="Band", discs=[Disc(1, tracks=[
        Track(1, "Eins", 1.0, artist="Band feat. Gast")])])
    assert not guest.multi_artist


def test_split_companions_keep_the_double_separator():
    """Aus dem Test im Container: Die Begleitdateien eines Splits leiten sich
    vom fertigen Verzeichnisnamen ab (#Fullrelease) - die Regelkette machte
    aus "__" dabei "_". Die .nfo hiess "00-artist_a_artist_b-…", ein Cover
    aber "00-artist_a__artist_b-…"."""
    from releaser.naming import companion_name, future_companion_stem

    profile = preset()
    release = Release(artist="Artist A / Artist B", album="Split EP", year=2026)
    release.dirname = release_dirname(release, profile)
    assert release.dirname == "Artist_A__Artist_B-Split_EP-2026-GRP"
    stem = "artist_a__artist_b-split_ep-2026-grp"
    assert companion_name(release, ".nfo", profile) == f"00-{stem}.nfo"
    assert companion_name(release, ".sfv", profile) == f"00-{stem}.sfv"
    assert future_companion_stem(release, profile) == stem


@needs_ffmpeg
def test_split_release_end_to_end_names(tmp_path):
    """Einlesen, Umbenennen und Begleitdateien eines Splits - alle Namen mit
    demselben doppelten Trenner."""
    from releaser.service import BuildOptions, process

    root = release_dir(tmp_path, "rel", "Artist A & Artist B", [
        ("Artist A", "Song A1"), ("Artist B", "Song B1")])
    template = tmp_path / "t.skl"
    template.write_bytes("#Artist                    \n#N #Trk              \n"
                         .encode("cp437"))
    outcome = process(root, BuildOptions(template=template), naming=preset(),
                      tags=TagProfile(), do_tag=True, do_rename=True)
    assert outcome.root.name == "Artist_A__Artist_B-Sampler-2026-GRP"
    assert sorted(p.name for p in outcome.created) == [
        "00-artist_a__artist_b-sampler-2026-grp.m3u",
        "00-artist_a__artist_b-sampler-2026-grp.nfo",
        "00-artist_a__artist_b-sampler-2026-grp.sfv"]


# =================== Doppelter Trenner nur bei Splits (Fund der Durchsicht)


def spaced(space: str) -> NamingProfile:
    profile = preset()
    profile.space_char = space
    return profile


def plain_release(titles: list[str], artist: str = "Band",
                  track_artists: tuple = ()) -> Release:
    tracks = [Track(no, title, 1.0, path=f"/x/rohdaten/0{no}.mp3",
                    artist=track_artists[no - 1] if track_artists else "")
              for no, title in enumerate(titles, start=1)]
    return Release(artist=artist, album="Das Album", year=2026,
                   discs=[Disc(1, tracks=tracks)])


@pytest.mark.parametrize("space,directory,files", [
    ("-", "Band-Das-Album-2026-GRP",
     ["01-band-warten.mp3", "02-band-ende-teil-2.mp3", "03-band-a_b.mp3"]),
    (".", "Band-Das.Album-2026-GRP",
     ["01-band-warten.mp3", "02-band-ende-teil.2.mp3", "03-band-a_b.mp3"]),
    ("_", "Band-Das_Album-2026-GRP",
     ["01-band-warten.mp3", "02-band-ende-teil_2.mp3", "03-band-a_b.mp3"]),
])
def test_normal_release_has_no_double_separator(space, directory, files):
    """Seit 0.28.1 galt jedes doppelte Ersatzzeichen als Split-Trenner: Mit
    "-" hiess ein Ordner mit zwei leeren Feldern ``…-album--2026-GRP``, mit
    "." wurde aus "Warten..." ``warten...mp3``."""
    release = plain_release(["Warten...", "Ende -- Teil 2", "A__B"])
    plan = plan_rename(release, Path("/x/rohdaten"), spaced(space))
    assert next(op.dst.name for op in plan.ops if op.kind == "root") == directory
    assert [op.dst.name for op in plan.ops if op.kind == "file"] == files
    release.dirname = directory
    assert companion_name(release, ".nfo", spaced(space)) == \
        f"00-{directory.lower()}.nfo"


@pytest.mark.parametrize("space", ["-", ".", "_"])
def test_split_keeps_its_double_separator_with_any_spacer(space):
    release = plain_release(["Lied", "Song"], artist="Artist A / Artist B",
                            track_artists=("Artist A", "Artist B"))
    plan = plan_rename(release, Path("/x/rohdaten"), spaced(space))
    directory = next(op.dst.name for op in plan.ops if op.kind == "root")
    pair = space * 2
    assert directory.startswith(f"Artist{space}A{pair}Artist{space}B-")
    release.dirname = directory
    assert companion_name(release, ".nfo", spaced(space)).startswith(
        f"00-artist{space}a{pair}artist{space}b-")
