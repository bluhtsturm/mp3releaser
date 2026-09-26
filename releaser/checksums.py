"""Prüfsummen.

Zwei verschiedene CRC32-Werte, die im Original beide vorkamen:

* **Datei-CRC** — über die komplette Datei. Das ist, was im ``.sfv`` landet.
* **Audio-CRC** — nur über die Audiodaten, ohne ID3v2/APE/ID3v1/Lyrics3 und
  ohne eine eventuelle WAV-Hülle. Das Original nannte das „mp3-crc" und bot
  eine Option „check for stuff in front of the mp3 (WAV envelope, ID3v2 ...)".

Der Unterschied ist praktisch relevant: Umtaggen ändert den Datei-CRC und
damit das SFV, lässt den Audio-CRC aber unberührt. Damit lässt sich
unterscheiden, ob eine Datei wirklich beschädigt ist oder nur neu getaggt
wurde.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

CHUNK = 1 << 20

#: Ein reiner MPEG-Audioframe beginnt mit 11 gesetzten Sync-Bits.
MPEG_SYNC_MASK = 0xFFE0


@dataclass
class PayloadBounds:
    """Der Bereich einer Datei, der tatsächlich Audiodaten enthält."""

    start: int
    end: int
    notes: list[str] = field(default_factory=list)

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)


def crc32_file(path: str | Path, start: int = 0, end: int | None = None) -> int:
    """CRC32 über einen Byte-Bereich der Datei (Standard: alles)."""
    p = Path(path)
    end = p.stat().st_size if end is None else end
    crc = 0
    with p.open("rb") as fh:
        fh.seek(start)
        remaining = max(0, end - start)
        while remaining:
            block = fh.read(min(CHUNK, remaining))
            if not block:
                break
            remaining -= len(block)
            crc = zlib.crc32(block, crc)
    return crc & 0xFFFFFFFF


def _synchsafe(data: bytes) -> int:
    value = 0
    for byte in data:
        value = (value << 7) | (byte & 0x7F)
    return value


def _id3v2_size(fh: BinaryIO) -> int:
    """Länge eines ID3v2-Blocks am Dateianfang, sonst 0."""
    fh.seek(0)
    head = fh.read(10)
    if len(head) < 10 or head[:3] != b"ID3":
        return 0
    size = 10 + _synchsafe(head[6:10])
    if head[5] & 0x10:          # Footer vorhanden
        size += 10
    return size


def _riff_data_chunk(fh: BinaryIO, size: int) -> tuple[int, int] | None:
    """Sucht den ``data``-Chunk einer WAV-Hülle."""
    fh.seek(0)
    if fh.read(4) != b"RIFF":
        return None
    fh.seek(8)
    if fh.read(4) != b"WAVE":
        return None
    pos = 12
    while pos + 8 <= size:
        fh.seek(pos)
        header = fh.read(8)
        if len(header) < 8:
            break
        chunk_id = header[:4]
        chunk_size = int.from_bytes(header[4:8], "little")
        if chunk_id == b"data":
            return pos + 8, min(size, pos + 8 + chunk_size)
        pos += 8 + chunk_size + (chunk_size & 1)
    return None


def _mp4_mdat(fh: BinaryIO, size: int) -> tuple[int, int] | None:
    """Sucht die ``mdat``-Box eines MP4/M4A - dort liegen die Audiodaten.

    Ohne das waere der "Audio-CRC" einer M4A-Datei mit dem Datei-CRC identisch,
    und die Unterscheidung zwischen beschaedigt und nur umgetaggt wuerde fuer
    AAC gar nicht funktionieren.
    """
    fh.seek(0)
    if fh.read(8)[4:8] not in (b"ftyp", b"styp"):
        return None
    pos = 0
    while pos + 8 <= size:
        fh.seek(pos)
        header = fh.read(8)
        if len(header) < 8:
            return None
        box_size = int.from_bytes(header[:4], "big")
        name = header[4:8]
        payload = pos + 8
        if box_size == 1:
            box_size = int.from_bytes(fh.read(8), "big")
            payload = pos + 16
        elif box_size == 0:
            box_size = size - pos
        if box_size < 8:
            return None
        if name == b"mdat":
            return payload, min(size, pos + box_size)
        pos += box_size
    return None


def _flac_audio_start(fh: BinaryIO, start: int, size: int) -> int | None:
    """Überspringt die FLAC-Metadatenblöcke bis zum ersten Audioframe."""
    fh.seek(start)
    if fh.read(4) != b"fLaC":
        return None
    pos = start + 4
    while pos + 4 <= size:
        fh.seek(pos)
        header = fh.read(4)
        if len(header) < 4:
            return None
        last = bool(header[0] & 0x80)
        length = int.from_bytes(header[1:4], "big")
        pos += 4 + length
        if last:
            return min(pos, size)
    return None


def _strip_trailing_tags(fh: BinaryIO, end: int, notes: list[str]) -> int:
    """Entfernt ID3v1, APEv2 und Lyrics3v2 vom Dateiende, in beliebiger Reihenfolge."""
    changed = True
    while changed and end > 0:
        changed = False

        if end >= 128:
            fh.seek(end - 128)
            if fh.read(3) == b"TAG":
                end -= 128
                notes.append("ID3v1 entfernt")
                changed = True
                continue

        if end >= 32:
            fh.seek(end - 32)
            footer = fh.read(32)
            if footer[:8] == b"APETAGEX":
                # Layout: Magic(8) Version(4) Size(4) Items(4) Flags(4) Reserved(8).
                # Size zählt den Footer mit, den Header aber nicht.
                tag_size = int.from_bytes(footer[12:16], "little")
                flags = int.from_bytes(footer[20:24], "little")
                total = tag_size
                if flags & 0x80000000:      # Header zusätzlich vorhanden
                    total += 32
                if 0 < total <= end:
                    end -= total
                    notes.append("APE-Tag entfernt")
                    changed = True
                    continue

        if end >= 15:
            fh.seek(end - 15)
            trailer = fh.read(15)
            if trailer[6:] == b"LYRICS200" and trailer[:6].isdigit():
                total = int(trailer[:6]) + 15
                if 0 < total <= end:
                    end -= total
                    notes.append("Lyrics3v2 entfernt")
                    changed = True
    return end


def audio_bounds(path: str | Path) -> PayloadBounds:
    """Bestimmt den reinen Audiobereich einer Datei."""
    p = Path(path)
    size = p.stat().st_size
    notes: list[str] = []

    with p.open("rb") as fh:
        riff = _riff_data_chunk(fh, size)
        if riff:
            notes.append("WAV-Hülle erkannt")
            return PayloadBounds(riff[0], riff[1], notes)

        mdat = _mp4_mdat(fh, size)
        if mdat:
            notes.append("MP4-Container: mdat-Box verwendet")
            return PayloadBounds(mdat[0], mdat[1], notes)

        start = _id3v2_size(fh)
        if start:
            notes.append(f"ID3v2 übersprungen ({start} Bytes)")
        end = _strip_trailing_tags(fh, size, notes)

        fh.seek(start)
        head = fh.read(4)
        if head[:4] == b"fLaC":
            flac_start = _flac_audio_start(fh, start, end)
            if flac_start is not None:
                notes.append(
                    f"FLAC-Metadatenblöcke übersprungen ({flac_start - start} Bytes)"
                )
                start = flac_start
            else:
                notes.append("FLAC-Metadatenblöcke nicht auswertbar")
        elif head[:2] == b"\x0b\x77":
            pass
        elif len(head) >= 2:
            word = int.from_bytes(head[:2], "big")
            if word & MPEG_SYNC_MASK != MPEG_SYNC_MASK:
                notes.append(
                    "kein MPEG-Sync am Anfang der Audiodaten - "
                    "möglicherweise Müll vor dem ersten Frame"
                )

    return PayloadBounds(start, end, notes)


def audio_crc32(path: str | Path) -> tuple[int, PayloadBounds]:
    """CRC32 nur über die Audiodaten, ohne Tags und ohne WAV-Hülle."""
    bounds = audio_bounds(path)
    return crc32_file(path, bounds.start, bounds.end), bounds


def format_crc(crc: int, uppercase: bool = True) -> str:
    text = f"{crc & 0xFFFFFFFF:08x}"
    return text.upper() if uppercase else text
