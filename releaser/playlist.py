"""M3U-Playlists.

Das Original schrieb bei Mehr-CD-Releases zusätzlich zu den CD-Playlists eine
zusammenfassende „Super-M3U" im Wurzelverzeichnis (Changelog 3.1.0 build 401,
per Default an). Die Pfade darin sind relativ zum Wurzelverzeichnis, damit sie
nach dem Entpacken überall funktionieren.

Kodierung standardmäßig CP437 wie beim NFO. Wer UTF-8 braucht, gibt es
explizit an — dann wird ``#EXTM3U`` beibehalten, aber nichts transliteriert.

**Pfadtrenner.** Das Original schrieb Rückwärts-Schrägstriche; es lief unter
Windows. Dieses Programm läuft unter Linux, und dort findet kein Abspieler
eine Datei hinter ``CD1\\01-….flac``. Voreinstellung sind deshalb normale
Schrägstriche; ``windows_paths=True`` stellt das alte Verhalten her.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

from .model import Disc, Release, Track
from .text import to_codepage


@dataclass
class M3uEntry:
    path: str
    seconds: float
    label: str


def _label(release: Release, track: Track) -> str:
    artist = release.artist or ""
    if not artist:
        return track.title
    return f"{artist} - {track.title}"


def build_entries(
    release: Release,
    tracks: Sequence[Track],
    base: Optional[Path] = None,
) -> list[M3uEntry]:
    # Bei CUE-Releases zeigen viele Tracks auf dieselbe Datei. Die Datei wird
    # einmal gelistet, ihre Spieldauer ist die Summe aller Tracks darin.
    totals: dict[str, float] = {}
    for track in tracks:
        if track.path:
            totals[track.path] = totals.get(track.path, 0.0) + track.seconds

    entries: list[M3uEntry] = []
    seen: set[str] = set()
    for track in tracks:
        if track.path:
            p = Path(track.path)
            name = str(p.relative_to(base)) if base else p.name
        else:
            name = track.title
        seconds = track.seconds
        if track.path:
            if track.path in seen:
                continue
            seen.add(track.path)
            seconds = totals[track.path]
        entries.append(M3uEntry(name, seconds, _label(release, track)))
    return entries


def render_m3u(entries: Iterable[M3uEntry], extended: bool = True,
               windows_paths: bool = False) -> str:
    lines: list[str] = ["#EXTM3U"] if extended else []
    for entry in entries:
        path = entry.path.replace("/", "\\") if windows_paths else entry.path
        if extended:
            lines.append(f"#EXTINF:{int(round(entry.seconds))},{entry.label}")
        lines.append(path)
    return "\r\n".join(lines) + "\r\n"


def write_m3u(path: str | Path, entries: Iterable[M3uEntry],
              extended: bool = True, codepage: str = "cp437",
              windows_paths: bool = False) -> None:
    text = render_m3u(entries, extended, windows_paths)
    Path(path).write_bytes(to_codepage(text, codepage))


# ------------------------------------------------------- Release-Integration


def m3u_name(release: Release, disc: Optional[Disc] = None,
             use_catalog_no: bool = False,
             stem: Optional[str] = None) -> str:
    """Wie ``sfv_name``, damit beide Begleitdateien gleich heissen."""
    base = stem if stem is not None else (release.dirname or release.release_name)
    if use_catalog_no and release.catalog_no:
        base = release.catalog_no
    if disc is not None and release.multi_disc:
        base = f"{base}-cd{disc.number}"
    return f"{base}.m3u"


def write_release_m3us(
    release: Release,
    root: str | Path,
    extended: bool = True,
    super_m3u: bool = True,
    use_catalog_no: bool = False,
    codepage: str = "cp437",
    windows_paths: bool = False,
    stem: Optional[str] = None,
) -> list[Path]:
    """Schreibt je CD eine Playlist und optional die Super-M3U.

    Bei einer einzelnen CD entsteht genau eine Playlist im Wurzelverzeichnis;
    eine Super-M3U wäre dort nur eine Dopplung und entfällt.
    """
    root = Path(root)
    written: list[Path] = []

    for disc in release.discs:
        directory = disc.directory(root)
        entries = build_entries(release, disc.tracks, base=directory)
        target = directory / m3u_name(release, disc, use_catalog_no, stem)
        write_m3u(target, entries, extended, codepage, windows_paths)
        written.append(target)

    if super_m3u and release.multi_disc:
        entries = build_entries(release, release.tracks, base=root)
        target = root / m3u_name(release, None, use_catalog_no, stem)
        write_m3u(target, entries, extended, codepage, windows_paths)
        written.append(target)

    return written
