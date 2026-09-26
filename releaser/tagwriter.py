"""Tags schreiben.

Wie beim Umbenennen gilt: erst ein Plan, dann die Ausführung. ``plan_tags()``
liest die vorhandenen Tags, berechnet die Sollwerte und liefert eine Liste von
Feldänderungen — ohne eine Datei anzufassen. Erst ``apply_tags()`` schreibt.

Die Sollwerte entstehen aus dem ``Release``-Modell, nicht aus den Dateien.
Damit ist das Schreiben der Gegenlauf zum Scannen: was der Scanner
zusammengeführt und korrigiert hat, landet zurück in den Dateien.

Formate: MP3 (ID3v2 plus optional ID3v1), FLAC (Vorbis-Comments), MP4/M4A
(iTunes-Atoms). Rohe EC-3-Streams können keine Tags tragen — sie werden
übersprungen und gemeldet, nicht stillschweigend ignoriert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .audio import AudioError, AudioInfo, read_file
from .model import Disc, Release, Track
from .text import CharCase

#: Normalisierte Feldnamen. Jeder Writer bildet sie auf sein Format ab.
FIELDS: tuple[str, ...] = (
    "title", "artist", "albumartist", "album", "date", "genre",
    "comment", "tracknumber", "discnumber",
)

#: Felder, deren Schreibweise die Charcase-Regel nicht anfasst. Das Original
#: hatte dafür eine eigene Option ("dont touch Comment tag's charcase field").
CHARCASE_EXEMPT: frozenset[str] = frozenset({"comment", "date",
                                             "tracknumber", "discnumber"})


@dataclass
class TagProfile:
    charcase: CharCase = CharCase.UNCHANGED
    fields: frozenset[str] = frozenset(FIELDS)

    #: fester Kommentartext für alle Dateien
    comment: str = ""
    #: Label/Company statt des freien Texts in den Kommentar schreiben
    label_in_comment: bool = False
    #: Katalognummer ans Album anhängen
    catalog_in_album: bool = False
    #: freier Zusatz hinter dem Albumnamen, z. B. "CDDA"
    album_addition: str = ""

    #: "3/12" statt "3"
    write_totals: bool = True
    #: auch bei Einzel-CD eine Disc-Nummer schreiben
    write_disc_for_single: bool = False
    #: ID3v1.1 zusätzlich schreiben
    write_id3v1: bool = True
    #: 3 oder 4 - ID3v2.3 wird von älterer Software besser verstanden
    id3v2_version: int = 4
    #: vorhandene Tags vorher restlos entfernen
    strip_existing: bool = False
    #: Genrenamen auf die kanonische ID3v1-Schreibweise bringen
    normalise_genre: bool = True
    #: zusätzlich APEv2 schreiben (MP3)
    write_apev2: bool = False
    #: zusätzlich Lyrics3v2 schreiben (MP3)
    write_lyrics3: bool = False


@dataclass
class TagChange:
    path: Path
    field: str
    old: str
    new: str


@dataclass
class TagPlan:
    changes: list[TagChange] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Pfad -> vollständige Sollwerte, von apply_tags verwendet
    targets: dict[Path, dict[str, str]] = field(default_factory=dict)
    #: der Rueckgaengig-Eintrag, nachdem der Plan ausgefuehrt wurde
    journal: Optional[object] = None

    @property
    def files(self) -> list[Path]:
        return list(self.targets)


# ---------------------------------------------------------------- Sollwerte


def _pair(number: Optional[int], total: Optional[int], write_totals: bool) -> str:
    if not number:
        return ""
    if write_totals and total:
        return f"{number}/{total}"
    return str(number)


def _strip_suffix(value: str, addition: str) -> str:
    """Entfernt ein bereits vorhandenes ``(addition)`` am Ende, unabhängig von
    der Schreibweise."""
    if not addition:
        return value
    suffix = f"({addition})".lower()
    stripped = value.rstrip()
    if stripped.lower().endswith(suffix):
        return stripped[:-len(suffix)].rstrip()
    return value


def _append_once(value: str, addition: str) -> str:
    if not addition:
        return value
    return f"{_strip_suffix(value, addition)} ({addition})".strip()


def desired_tags(release: Release, disc: Disc, track: Track,
                 profile: TagProfile) -> dict[str, str]:
    """Sollwerte eines Tracks, bereits in normalisierter Form."""
    comment = release.company if profile.label_in_comment else profile.comment
    write_disc = release.multi_disc or profile.write_disc_for_single

    # Zusätze vom gelesenen Albumnamen abtrennen, bevor die Schreibweisenregel
    # greift. Sonst würde ein zweiter Lauf aus "(CDDA)" ein "(Cdda)" machen und
    # den Zusatz anschließend erneut anhängen.
    album = release.album
    if profile.catalog_in_album and release.catalog_no:
        album = _strip_suffix(album, release.catalog_no)
    album = _strip_suffix(album, profile.album_addition)

    values = {
        "title": track.title,
        "artist": track.artist or release.artist,
        "albumartist": release.artist,
        "album": album,
        "date": str(release.year or disc.year or ""),
        "genre": release.genre,
        "comment": comment,
        "tracknumber": _pair(track.no, len(disc.tracks), profile.write_totals),
        "discnumber": _pair(disc.number, len(release.discs),
                            profile.write_totals and release.multi_disc)
        if write_disc else "",
    }

    exempt = set(CHARCASE_EXEMPT)
    if profile.normalise_genre and values.get("genre"):
        from .genres import normalise

        canonical, number, _warning = normalise(values["genre"])
        values["genre"] = canonical
        if number is not None:
            # ID3v1 kennt Genres nur als Zahl, und mutagen findet die Zahl nur
            # bei exakter Schreibweise. Wuerde die Schreibweisenregel hier
            # zugreifen, waere das Genre in ID3v1 wieder verloren (255).
            exempt.add("genre")

    out: dict[str, str] = {}
    for name in FIELDS:
        if name not in profile.fields:
            continue
        value = values.get(name, "")
        if value and name not in exempt:
            value = profile.charcase.apply(value)
        out[name] = value

    # Zusätze erst nach der Schreibweisenregel anhängen - "CDDA" soll "CDDA"
    # bleiben und nicht zu "Cdda" werden.
    if "album" in out:
        if profile.catalog_in_album and release.catalog_no:
            out["album"] = _append_once(out["album"], release.catalog_no)
        out["album"] = _append_once(out["album"], profile.album_addition)
    return out


def current_tags(info: AudioInfo, profile: TagProfile) -> dict[str, str]:
    """Vorhandene Tags einer Datei in derselben normalisierten Form."""
    return {
        "title": info.title,
        "artist": info.artist,
        "albumartist": info.album_artist,
        "album": info.album,
        "date": str(info.year or ""),
        "genre": info.genre,
        "comment": info.comment,
        "tracknumber": _pair(info.track_no, info.total_tracks, profile.write_totals),
        "discnumber": _pair(info.disc_no, info.total_discs, profile.write_totals),
    }


# ------------------------------------------------------------------ Planung


def plan_tags(release: Release, profile: Optional[TagProfile] = None) -> TagPlan:
    """Berechnet alle Tag-Änderungen, ohne eine Datei anzufassen."""
    profile = profile or TagProfile()
    plan = TagPlan()

    for disc in release.discs:
        for track in disc.tracks:
            if not track.path:
                plan.warnings.append(
                    f"Track {disc.number}-{track.no} hat keinen Dateipfad")
                continue
            path = Path(track.path)
            if path.suffix.lower() not in WRITERS:
                plan.skipped.append(path)
                plan.warnings.append(
                    f"{path.name}: {path.suffix} kann keine Tags tragen")
                continue
            try:
                info = read_file(path)
            except AudioError as exc:
                plan.warnings.append(str(exc))
                continue

            if profile.normalise_genre and release.genre:
                from .genres import normalise

                warning = normalise(release.genre)[2]
                if warning and warning not in plan.warnings:
                    plan.warnings.append(warning)

            target = desired_tags(release, disc, track, profile)
            plan.targets[path] = target
            existing = current_tags(info, profile)
            for name, new in target.items():
                old = existing.get(name, "")
                if old != new:
                    plan.changes.append(TagChange(path, name, old, new))
    return plan


def format_plan(plan: TagPlan, root: Optional[Path] = None) -> str:
    lines: list[str] = []
    by_file: dict[Path, list[TagChange]] = {}
    for change in plan.changes:
        by_file.setdefault(change.path, []).append(change)

    for path, changes in by_file.items():
        name = path.relative_to(root) if root and path.is_relative_to(root) else path.name
        lines.append(f"  {name}")
        for change in changes:
            old = change.old or "-"
            new = change.new or "-"
            lines.append(f"      {change.field:<12} {old}  ->  {new}")
    if not lines:
        lines.append("  (nichts zu tun)")
    for warning in plan.warnings:
        lines.append(f"  ! {warning}")
    return "\n".join(lines)


# ---------------------------------------------------------------- Ausführung


def apply_tags(plan: TagPlan, profile: Optional[TagProfile] = None,
               journal: bool = True) -> list[Path]:
    """Schreibt die Sollwerte in alle Dateien des Plans.

    Hier - und nicht in der Dienstschicht - werden die alten Werte
    protokolliert: das ist die einzige Stelle, durch die jedes Schreiben
    muss. In der Schicht darueber haette es jeder Aufrufer umgehen koennen,
    der ``apply_tags`` direkt nimmt.
    """
    profile = profile or TagProfile()
    if journal:
        plan.journal = _record_previous(plan)
    written: list[Path] = []
    for path, values in plan.targets.items():
        writer = WRITERS.get(path.suffix.lower())
        if writer is None:
            continue
        writer(path, values, profile)
        written.append(path)
    return written


#: Pseudofeld im Rueckgaengig-Protokoll: welche Tag-Bloecke am Dateiende
#: vorher existierten. Beginnt mit "#", damit es mit keinem echten Feld
#: verwechselt wird.
CONTAINERS_FIELD = "#containers"


def trailing_containers(path: Path) -> set[str]:
    """Welche Tag-Bloecke am Ende einer MP3 stehen: id3v1, apev2, lyrics3."""
    from .checksums import audio_bounds

    notes = audio_bounds(path).notes
    return {name for name, marker in (("id3v1", "ID3v1"), ("apev2", "APE"),
                                      ("lyrics3", "Lyrics3"))
            if any(marker in note for note in notes)}


def write_values(path: Path, values: dict[str, str],
                 profile: Optional[TagProfile] = None) -> bool:
    """Schreibt genau die uebergebenen Felder. Rueckgabe: ob es ein Format war,
    das Tags tragen kann.

    Enthaelt ``values`` das Pseudofeld fuer die Tag-Bloecke, wird der
    damalige Zustand auch dort wiederhergestellt: Bloecke, die vorher nicht
    da waren, verschwinden wieder.
    """
    target = Path(path)
    writer = WRITERS.get(target.suffix.lower())
    if writer is None:
        return False

    values = dict(values)
    containers = values.pop(CONTAINERS_FIELD, None)
    if containers is None:
        writer(target, values, profile or TagProfile())
        return True

    before = {c for c in containers.split(",") if c}
    writer(target, values, TagProfile(write_id3v1="id3v1" in before))
    if "apev2" not in before:
        from mutagen.apev2 import delete as delete_ape

        delete_ape(target)
    if "lyrics3" not in before:
        from . import lyrics3

        lyrics3.remove(target)
    return True


def _record_previous(plan: TagPlan):
    """Haelt die alten Werte der geaenderten Felder fest.

    Bei MP3 zusaetzlich, welche Tag-Bloecke am Dateiende standen: der
    Tag-Lauf legt ggf. ID3v1, APEv2 oder Lyrics3v2 an, und eine Ruecknahme
    soll nichts hinterlassen, was vorher nicht da war.
    """
    previous: dict[str, dict[str, str]] = {}
    for change in plan.changes:
        previous.setdefault(str(change.path), {})[change.field] = change.old
    if not previous:
        return None
    for name, values in previous.items():
        if name.lower().endswith(".mp3"):
            values[CONTAINERS_FIELD] = ",".join(
                sorted(trailing_containers(Path(name))))

    from . import undo

    # Der Releasename dient nur der Anzeige im Protokoll
    folders = {Path(name).parent.name for name in previous}
    release = folders.pop() if len(folders) == 1 else "mehrere Ordner"
    return undo.record_tags(previous, release)


def _split_pair(value: str) -> tuple[Optional[int], Optional[int]]:
    if not value:
        return None, None
    head, _, tail = value.partition("/")
    return (int(head) if head.strip().isdigit() else None,
            int(tail) if tail.strip().isdigit() else None)


def write_mp3(path: Path, values: dict[str, str], profile: TagProfile) -> None:
    from mutagen.id3 import (
        COMM, ID3, ID3NoHeaderError, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK,
    )

    if profile.strip_existing:
        # Ueber die Datei, nicht ueber ein ID3-Objekt: ein leeres ``ID3()``
        # (Datei ganz ohne Tag) kennt keinen Dateinamen, und ``delete`` brach
        # dann mit einem TypeError ab. "Restlos" heisst ausserdem: auch
        # APEv2 und Lyrics3v2 gehen, nicht nur ID3.
        from mutagen.apev2 import delete as delete_ape
        from mutagen.id3 import delete as delete_id3

        from . import lyrics3

        lyrics3.remove(path)
        delete_ape(path)
        delete_id3(path, delete_v1=True, delete_v2=True)

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    frames = {
        "title": TIT2, "artist": TPE1, "albumartist": TPE2, "album": TALB,
        "genre": TCON, "date": TDRC, "tracknumber": TRCK, "discnumber": TPOS,
    }
    for name, frame_class in frames.items():
        if name not in values:
            continue
        value = values[name]
        tags.delall(frame_class.__name__)
        if value:
            tags.add(frame_class(encoding=3, text=value))

    if "comment" in values:
        tags.delall("COMM")
        if values["comment"]:
            tags.add(COMM(encoding=3, lang="eng", desc="",
                          text=values["comment"]))

    # Die übliche Reihenfolge am Dateiende ist [Lyrics3v2][APEv2][ID3v1].
    # Deshalb erst die Altformate schreiben und ID3v1 zuletzt anhängen -
    # mutagen setzt es immer an das Dateiende.
    tags.save(path, v2_version=profile.id3v2_version, v1=0)

    if profile.write_lyrics3:
        from . import lyrics3

        lyrics3.write(path, {
            "title": values.get("title", ""),
            "artist": values.get("artist", ""),
            "album": values.get("album", ""),
            "comment": values.get("comment", ""),
        })
    if profile.write_apev2:
        _write_apev2(path, values)
    if profile.write_id3v1:
        tags.save(path, v2_version=profile.id3v2_version, v1=2)


#: normalisierter Feldname -> APEv2-Schluessel
APE_KEYS = {
    "title": "Title", "artist": "Artist", "albumartist": "Album Artist",
    "album": "Album", "genre": "Genre", "comment": "Comment",
    "date": "Year", "tracknumber": "Track", "discnumber": "Disc",
}


def _fill_ape(tags, values: dict[str, str]) -> None:
    for name, key in APE_KEYS.items():
        if name not in values:
            continue
        if values[name]:
            tags[key] = values[name]
        elif key in tags:
            del tags[key]


def _write_apev2(path: Path, values: dict[str, str]) -> None:
    from mutagen.apev2 import APENoHeaderError, APEv2

    try:
        ape = APEv2(path)
    except APENoHeaderError:
        ape = APEv2()
    _fill_ape(ape, values)
    ape.save(path)


def _write_vorbis_like(audio, values: dict[str, str], profile: TagProfile) -> None:
    """Vorbis-Comments schreiben - gleich fuer FLAC, Ogg Vorbis und Opus."""
    if profile.strip_existing:
        audio.delete()

    mapping = {
        "title": "title", "artist": "artist", "albumartist": "albumartist",
        "album": "album", "genre": "genre", "date": "date", "comment": "comment",
    }
    for name, key in mapping.items():
        if name not in values:
            continue
        if values[name]:
            audio[key] = values[name]
        elif key in audio:
            del audio[key]

    # Vorbis trennt Nummer und Gesamtzahl in eigene Felder.
    for name, num_key, total_key in (("tracknumber", "tracknumber", "tracktotal"),
                                     ("discnumber", "discnumber", "disctotal")):
        if name not in values:
            continue
        number, total = _split_pair(values[name])
        for key, value in ((num_key, number), (total_key, total)):
            if value:
                audio[key] = str(value)
            elif key in audio:
                del audio[key]

    audio.save()


def write_flac(path: Path, values: dict[str, str], profile: TagProfile) -> None:
    from mutagen.flac import FLAC

    _write_vorbis_like(FLAC(path), values, profile)


def write_ogg(path: Path, values: dict[str, str], profile: TagProfile) -> None:
    from mutagen.oggvorbis import OggVorbis

    _write_vorbis_like(OggVorbis(path), values, profile)


def write_opus(path: Path, values: dict[str, str], profile: TagProfile) -> None:
    from mutagen.oggopus import OggOpus

    _write_vorbis_like(OggOpus(path), values, profile)


def write_musepack(path: Path, values: dict[str, str], profile: TagProfile) -> None:
    """Musepack traegt APEv2 - dieselbe Abbildung wie beim MP3-Zusatztag."""
    from mutagen.musepack import Musepack

    audio = Musepack(path)
    if audio.tags is None:
        audio.add_tags()
    if profile.strip_existing:
        audio.delete()
        audio.add_tags()
    _fill_ape(audio.tags, values)
    audio.save()


def write_mp4(path: Path, values: dict[str, str], profile: TagProfile) -> None:
    from mutagen.mp4 import MP4

    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()
    if profile.strip_existing:
        audio.tags.clear()

    atoms = {
        "title": "\xa9nam", "artist": "\xa9ART", "albumartist": "aART",
        "album": "\xa9alb", "genre": "\xa9gen", "comment": "\xa9cmt",
        "date": "\xa9day",
    }
    for name, atom in atoms.items():
        if name not in values:
            continue
        if values[name]:
            audio.tags[atom] = [values[name]]
        elif atom in audio.tags:
            del audio.tags[atom]

    for name, atom in (("tracknumber", "trkn"), ("discnumber", "disk")):
        if name not in values:
            continue
        number, total = _split_pair(values[name])
        if number:
            audio.tags[atom] = [(number, total or 0)]
        elif atom in audio.tags:
            del audio.tags[atom]

    audio.save()


#: Endung -> Writer. Was hier fehlt, kann keine Tags tragen.
WRITERS: dict[str, Callable[[Path, dict[str, str], TagProfile], None]] = {
    ".mp3": write_mp3,
    ".flac": write_flac,
    ".ogg": write_ogg,
    ".oga": write_ogg,
    ".opus": write_opus,
    ".mpc": write_musepack,
    ".mp+": write_musepack,
    ".m4a": write_mp4,
    ".mp4": write_mp4,
    ".m4b": write_mp4,
}

#: Endungen, die gelesen, aber nicht beschrieben werden koennen - rohe
#: Bitstroeme ohne Tag-Container.
TAGLESS_EXTENSIONS: frozenset[str] = frozenset({".ec3", ".eac3"})
