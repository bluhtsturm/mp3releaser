"""Verzeichnis einlesen und daraus eine ``Release`` bauen.

Hier laufen die Entscheidungen zusammen, die im Original ueber Dutzende von
Checkboxen verteilt waren: Woher kommt der Tracktitel, wenn kein Tag da ist?
Was passiert bei uneinheitlichen Bitraten? Wie werden Mehr-CD-Releases
erkannt?

Alle Auffaelligkeiten landen in ``ScanResult.warnings`` statt in einem
Dialogfenster - die GUI kann sie spaeter anzeigen, die CLI druckt sie.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Iterable, Optional

from ..model import Disc, Release, Track
from ..provenance import Origin, OriginMap
from .base import AUDIO_EXTENSIONS, AudioError, AudioInfo, read_file

#: "01-artist-title", "01 - Title", "101 - Title", "A1. Title"
_FILENAME_PATTERNS = [
    re.compile(r"^\s*(?P<no>\d{1,3})\s*[-._)]\s*(?P<rest>.+)$"),
    re.compile(r"^\s*(?P<disc>\d)(?P<no>\d{2})\s*[-._)]\s*(?P<rest>.+)$"),
]

_CD_DIR = re.compile(r"^(?:cd|disc|disk)\s*(\d{1,2})$", re.IGNORECASE)

#: Verlustfreie Formate - bei ihnen sagt eine schwankende Bitrate nichts aus.
LOSSLESS: frozenset[str] = frozenset({"FLAC", "ALAC", "WAV"})


@dataclass
class ScanResult:
    release: Release
    infos: list[AudioInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Woher die einzelnen Werte stammen - für Oberflächen
    origins: OriginMap = field(default_factory=OriginMap)


def _natural_key(path: Path):
    return [int(p) if p.isdigit() else p.lower()
            for p in re.split(r"(\d+)", path.name)]


def find_audio_files(root: Path) -> list[Path]:
    files = [p for p in root.rglob("*")
             if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
    return sorted(files, key=lambda p: (len(p.relative_to(root).parts),
                                        _natural_key(p.parent), _natural_key(p)))


def parse_filename(path: Path) -> tuple[Optional[int], Optional[int], str]:
    """(disc, track, titel) aus dem Dateinamen raten."""
    stem = path.stem
    for pattern in _FILENAME_PATTERNS[::-1]:
        m = pattern.match(stem)
        if not m:
            continue
        groups = m.groupdict()
        rest = groups["rest"].strip(" -._")
        disc = int(groups["disc"]) if groups.get("disc") else None
        return disc, int(groups["no"]), rest or stem
    return None, None, stem


def _disc_from_dir(path: Path, root: Path) -> Optional[int]:
    for part in path.relative_to(root).parts[:-1]:
        m = _CD_DIR.match(part.strip())
        if m:
            return int(m.group(1))
    return None


def _majority(values: Iterable) -> Optional[object]:
    counted = Counter(v for v in values if v not in (None, ""))
    return counted.most_common(1)[0][0] if counted else None


def scan_directory(root: str | Path, strict: bool = False) -> ScanResult:
    root = Path(root)
    if not root.is_dir():
        raise AudioError(f"kein Verzeichnis: {root}")

    paths = find_audio_files(root)
    if not paths:
        raise AudioError(f"keine Audiodateien in {root}")

    infos: list[AudioInfo] = []
    warnings: list[str] = []
    for p in paths:
        try:
            info = read_file(p)
        except AudioError as exc:
            warnings.append(str(exc))
            if strict:
                raise
            continue
        warnings.extend(f"{p.name}: {w}" for w in info.warnings)
        infos.append(info)

    if not infos:
        raise AudioError("keine lesbare Audiodatei gefunden")

    codecs = {i.codec for i in infos}
    if len(codecs) > 1:
        warnings.append(f"gemischte Formate im Verzeichnis: {sorted(codecs)}")

    # Verlustfreie Formate haben je Datei eine andere Bitrate - das ist keine
    # Auffaelligkeit, sondern die Natur der Sache. Nur bei verlustbehafteten
    # Formaten deutet Ungleichheit auf gemischte Quellen hin.
    lossless = any(i.compression_ratio is not None or i.codec in LOSSLESS
                   for i in infos)
    bitrates = {i.bitrate for i in infos if i.bitrate}
    if (len(bitrates) > 1 and not lossless
            and not any(i.vbr for i in infos)):
        warnings.append(
            f"unterschiedliche Bitraten: {sorted(bitrates)} kbps "
            "(das Original brach hier ab, sofern nicht ausdruecklich erlaubt)"
        )
    samplerates = {i.samplerate for i in infos if i.samplerate}
    if len(samplerates) > 1:
        warnings.append(f"unterschiedliche Samplerates: {sorted(samplerates)} Hz")

    origins = OriginMap()
    release = _build_release(root, infos, warnings, origins)
    _apply_cue_sheets(root, release, infos, warnings, origins)
    if not release.album:
        release.album = root.name
        origins.set("album", Origin.DIRECTORY)
        warnings.append("kein Albumtitel gefunden - Verzeichnisname verwendet")
    return ScanResult(release=release, infos=infos, warnings=warnings,
                      origins=origins)


def _apply_cue_sheets(root: Path, release: Release, infos: list[AudioInfo],
                      warnings: list[str],
                      origins: Optional[OriginMap] = None) -> None:
    """Ersetzt die Trackliste durch die eines CUE-Sheets, wo eines vorliegt.

    Angewandt wird nur, wenn das CUE genau eine der eingelesenen Audiodateien
    beschreibt. Alle daraus entstehenden Tracks zeigen dann auf dieselbe Datei;
    Umbenennen, SFV und M3U fassen sie deshalb nur einmal an.
    """
    from ..cue import close_durations, read_cue

    origins = origins if origins is not None else OriginMap()
    # AudioInfo.path ist ein Path, Track.path ein String - hier konsequent
    # über Strings vergleichen, sonst schlägt die Gleichheit stillschweigend fehl.
    by_name = {i.path.name.lower(): i for i in infos}
    for cue_path in sorted(root.rglob("*.cue")):
        try:
            sheet = read_cue(cue_path)
        except OSError as exc:
            warnings.append(f"{cue_path.name}: {exc}")
            continue
        warnings.extend(f"{cue_path.name}: {w}" for w in sheet.warnings)

        targets = [f for f in sheet.files
                   if _cue_basename(f.name).lower() in by_name]
        if len(targets) != 1:
            warnings.append(
                f"{cue_path.name}: verweist auf {len(sheet.files)} Datei(en), "
                "davon keine eindeutig zuzuordnen - CUE wird ignoriert")
            continue

        cue_file = targets[0]
        info = by_name[_cue_basename(cue_file.name).lower()]
        close_durations(sheet, {cue_file.name: info.duration,
                                _cue_basename(cue_file.name): info.duration})

        target_path = str(info.path)
        disc = next((d for d in release.discs
                     if any(t.path == target_path for t in d.tracks)), None)
        if disc is None:
            continue
        if len(disc.tracks) != 1:
            warnings.append(
                f"{cue_path.name}: Anzahl der Tracks im CUE "
                f"({len(cue_file.tracks)}) passt nicht zu {len(disc.tracks)} "
                "Audiodateien im Verzeichnis - CUE wird ignoriert")
            continue

        total = info.size_bytes
        length = sum(t.duration or 0.0 for t in cue_file.tracks) or 1.0
        disc.tracks = [
            Track(
                no=t.number,
                title=t.title or f"Track {t.number}",
                seconds=t.duration or 0.0,
                disc=disc.number,
                path=target_path,
                # Die Dateigröße anteilig verteilen, damit die Gesamtgröße
                # des Releases stimmt und nicht mit jedem Track wächst.
                size_bytes=int(total * (t.duration or 0.0) / length),
                artist=t.performer if t.performer != sheet.performer else "",
            )
            for t in cue_file.tracks
        ]
        for track in disc.tracks:
            for name in ("title", "no", "seconds"):
                origins.set_track(disc.number, track.no, name, Origin.CUE)
        warnings.append(
            f"{cue_path.name}: Trackliste aus dem CUE übernommen "
            f"({len(disc.tracks)} Tracks)")
        if sheet.performer and not release.artist:
            release.artist = sheet.performer
            origins.set("artist", Origin.CUE)
        if sheet.title and not release.album:
            release.album = sheet.title
            origins.set("album", Origin.CUE)
        if sheet.genre and not release.genre:
            release.genre = sheet.genre
            origins.set("genre", Origin.CUE)
        # REM DATE - ohne das fehlte bei einem ungetaggten Image das Jahr im
        # Verzeichnisnamen und in der .nfo
        year = sheet.date[:4]
        if year.isdigit() and not release.year:
            release.year = int(year)
            disc.year = disc.year or release.year
            origins.set("year", Origin.CUE)
        # Was das Einlesen zum Image selbst angemerkt hat (keine Nummer, Titel
        # aus dem Dateinamen), ist durch die Trackliste des CUE ueberholt
        stale = (f"{info.path.name}: keine Tracknummer",
                 f"{info.path.name}: Titel aus dem Dateinamen")
        warnings[:] = [w for w in warnings if not w.startswith(stale)]


def _cue_basename(name: str) -> str:
    """Dateiname aus einer FILE-Zeile - auch aus einem Windows-Pfad.

    Unter Linux trennt ``Path`` nur an "/", ein ``C:\\rips\\mix.flac`` blieb
    dann ein einziger Name, und das CUE wurde ignoriert.
    """
    return PureWindowsPath(name).name


#: Ein Ordnername, der schon einen Sampler ankuendigt: "VA-…", "Various_…"
_VA_DIRNAME = re.compile(r"^(?:va|v\.a\.|various)(?:[\s_.\-]|$)", re.IGNORECASE)


def _release_artist(artists: list[str], album_artist: str,
                    dirname: str = "") -> tuple[str, str]:
    """Der Artist des Releases und welche Art es ist: normal, VA oder Split.

    ``artists`` sind die Artists der Tracks in Dateireihenfolge. Die Regeln,
    in dieser Reihenfolge:

    1. Albumartist "Various Artists", "VA" ... oder ein Ordnername, der mit
       "VA-" beginnt, bei mehr als einem Artist -> Sampler, Artist "VA"
    2. nur ein Artist -> normales Release
    3. jeder Track-Artist enthaelt den des Releases ("Band feat. X") ->
       normales Album mit Gaesten
    4. zwei Artists, oder drei bis vier in zusammenhaengenden Bloecken mit
       mehr als einem Track je Artist - und ein gesetzter Albumartist nennt
       sie alle -> Split, Artist "A / B / C". Ein kleiner Sampler mit drei
       Tracks von drei Artists ist kein Split.
    5. ein anderer Albumartist ist gesetzt (etwa der DJ eines Mixes) -> er
       bleibt, die Tracks behalten ihre Artists
    6. sonst -> Sampler
    """
    from ..model import SPLIT_SEPARATOR, is_various

    distinct = list(dict.fromkeys(artists))
    if album_artist and is_various(album_artist):
        return "VA", "va"
    if len(distinct) > 1 and _VA_DIRNAME.match(dirname):
        return "VA", "va"
    if len(distinct) <= 1:
        return album_artist or (distinct[0] if distinct else ""), "normal"
    base = album_artist or _majority(artists) or ""
    if base and all(base.lower() in a.lower() for a in distinct):
        return base, "normal"
    blocks = 1 + sum(1 for a, b in zip(artists, artists[1:]) if a != b)
    split_shape = len(distinct) == 2 or (len(distinct) <= 4
                                         and blocks == len(distinct)
                                         and len(artists) > len(distinct))
    named = not album_artist or all(a.lower() in album_artist.lower()
                                    for a in distinct)
    if split_shape and named:
        return SPLIT_SEPARATOR.join(distinct), "split"
    if album_artist:
        return album_artist, "normal"
    return "VA", "va"


def _build_release(root: Path, infos: list[AudioInfo], warnings: list[str],
                   origins: Optional[OriginMap] = None) -> Release:
    origins = origins if origins is not None else OriginMap()
    artists = [i.artist for i in infos if i.artist]
    album_artist = _majority(i.album_artist for i in infos) or ""
    main_artist, kind = _release_artist(artists, album_artist, root.name)
    if kind == "va":
        origins.set("artist", Origin.DERIVED)
        warnings.append("Sampler erkannt - Artist auf 'VA' gesetzt, die "
                        "Artists bleiben je Track")
    elif kind == "split":
        origins.set("artist", Origin.DERIVED)
        warnings.append(f"Split erkannt - Artist auf '{main_artist}' gesetzt, "
                        "die Artists bleiben je Track")
    elif main_artist:
        origins.set("artist", Origin.TAG)

    # Kein Rückfall auf den Verzeichnisnamen an dieser Stelle - ein CUE darf
    # den Albumtitel noch liefern. Der Rückfall greift erst danach.
    album = _majority(i.album for i in infos) or ""
    if album:
        origins.set("album", Origin.TAG)

    # ---- Discs zuordnen ---------------------------------------------------
    buckets: dict[int, list[tuple[AudioInfo, Optional[int], str]]] = {}
    for info in infos:
        f_disc, f_no, f_title = parse_filename(info.path)
        disc = info.disc_no or _disc_from_dir(info.path, root) or f_disc or 1
        no = info.track_no or f_no
        title = info.title or f_title
        origins.set_track(disc, no or 0, "title",
                          Origin.TAG if info.title else Origin.FILENAME)
        origins.set_track(disc, no or 0, "no",
                          Origin.TAG if info.track_no else
                          Origin.FILENAME if f_no else Origin.DERIVED)
        if not info.title:
            warnings.append(f"{info.path.name}: Titel aus dem Dateinamen abgeleitet")
        buckets.setdefault(disc, []).append((info, no, title))

    discs: list[Disc] = []
    for number in sorted(buckets):
        entries = buckets[number]
        tracks: list[Track] = []
        for position, (info, no, title) in enumerate(entries, start=1):
            if no is None:
                warnings.append(f"{info.path.name}: keine Tracknummer, "
                                f"Position {position} verwendet")
            tracks.append(Track(
                no=no or position,
                title=title,
                # Der eigene Artist des Tracks bleibt, sobald er vom Release
                # abweicht. Frueher ging er verloren, wenn ein Albumartist
                # gesetzt war ("Various Artists") - und beim Taggen schrieb
                # das Programm dann den Albumartist in jeden Track.
                artist=(info.artist if info.artist and info.artist != main_artist
                        else ""),
                seconds=info.duration,
                disc=number,
                path=str(info.path),
                size_bytes=info.size_bytes,
                bitrate=info.bitrate,
                samplerate=info.samplerate,
                channel_mode=info.channel_mode,
                vbr=info.vbr,
            ))
        tracks.sort(key=lambda t: t.no)
        year = _majority(i.year for i, _, _ in entries)
        discs.append(Disc(number=number, year=year, tracks=tracks))

    # ---- Gesamtwerte ------------------------------------------------------
    vbr = any(i.vbr for i in infos)
    codec = _majority(i.codec for i in infos) or ""
    ratios = [i.compression_ratio for i in infos if i.compression_ratio]

    for name, present in (("year", _majority(i.year for i in infos)),
                          ("genre", _majority(i.genre for i in infos)),
                          ("encoder", _majority(i.encoder for i in infos))):
        if present:
            origins.set(name, Origin.TAG)
    for name in ("audio_format", "bitrate", "samplerate", "channel_mode"):
        origins.set(name, Origin.DERIVED)
    origins.set("dirname", Origin.DIRECTORY)

    release = Release(
        artist=main_artist,
        album=album,
        year=_majority(i.year for i in infos),
        genre=_majority(i.genre for i in infos) or "",
        audio_format=codec,
        encoder=_majority(i.encoder for i in infos) or "",
        dirname=root.name,
        bitrate=_majority(i.bitrate for i in infos),
        samplerate=_majority(i.samplerate for i in infos),
        bits_per_sample=_majority(i.bits_per_sample for i in infos),
        channel_mode=_majority(i.channel_mode for i in infos) or "",
        vbr=vbr,
        vbr_string="VBR" if vbr else "",
        flac_compression=sum(ratios) / len(ratios) if ratios else None,
        discs=discs,
    )

    atmos = [i for i in infos if i.atmos]
    if atmos:
        objects = {i.object_count for i in atmos if i.object_count}
        suffix = f" ({max(objects)} Objekte)" if objects else ""
        release.released_with = f"Dolby Atmos (JOC){suffix}"
    unknown = [i for i in infos if i.codec == "EAC3" and i.atmos is None]
    if unknown:
        warnings.append(f"{len(unknown)} EC-3-Datei(en): JOC-Status unbestimmbar")

    return release
