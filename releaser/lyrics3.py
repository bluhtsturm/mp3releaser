"""Lyrics3v2.

Ein Tag-Format von 1998, das das Original noch schrieb und das mutagen nicht
unterstützt. Es sitzt am Dateiende, **vor** einem eventuellen ID3v1-Block:

    [Audiodaten][Lyrics3v2][APEv2][ID3v1]

Aufbau::

    LYRICSBEGIN
    IND00002<daten>          3 Zeichen Feldkennung, 5 Ziffern Länge, Daten
    ETT00012Ein Titel
    000037LYRICS200          6 Ziffern Gesamtlänge, dann die Endmarke

Die Gesamtlänge zählt von ``LYRICSBEGIN`` bis zum letzten Feld - die sechs
Ziffern und ``LYRICS200`` selbst gehören nicht dazu. Genau diese Stelle wird
in Fremdimplementierungen gern falsch gemacht.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

BEGIN = b"LYRICSBEGIN"
END = b"LYRICS200"
#: Feldkennungen, die hier geschrieben werden.
FIELDS: dict[str, str] = {
    "indications": "IND",
    "lyrics": "LYR",
    "comment": "INF",
    "title": "ETT",
    "artist": "EAR",
    "album": "EAL",
}
#: Reihenfolge laut Spezifikation: IND zuerst.
ORDER: tuple[str, ...] = ("indications", "lyrics", "comment",
                          "title", "artist", "album")

MAX_FIELD = 99999


class Lyrics3Error(Exception):
    pass


def build(values: dict[str, str], encoding: str = "cp437") -> bytes:
    """Baut einen Lyrics3v2-Block aus den übergebenen Feldern."""
    body = bytearray(BEGIN)
    has_lyrics = bool(values.get("lyrics"))

    for name in ORDER:
        if name == "indications":
            # Feld 1: Lyrics vorhanden, Feld 2: Zeitmarken (hier nie)
            data = f"{int(has_lyrics)}0".encode(encoding)
        else:
            text = values.get(name, "")
            if not text:
                continue
            data = text.encode(encoding, errors="replace")
        if len(data) > MAX_FIELD:
            raise Lyrics3Error(f"Feld {name} ist zu lang ({len(data)} Bytes)")
        body += FIELDS[name].encode("ascii")
        body += f"{len(data):05d}".encode("ascii")
        body += data

    return bytes(body) + f"{len(body):06d}".encode("ascii") + END


def find(data: bytes, end: Optional[int] = None) -> Optional[tuple[int, int]]:
    """Position eines Lyrics3v2-Blocks, der bei ``end`` endet."""
    end = len(data) if end is None else end
    if end < 15 or data[end - 9:end] != END:
        return None
    digits = data[end - 15:end - 9]
    if not digits.isdigit():
        return None
    size = int(digits)
    start = end - 15 - size
    if start < 0 or data[start:start + len(BEGIN)] != BEGIN:
        return None
    return start, end


def _ape_start(data: bytes, end: int) -> Optional[int]:
    """Anfang eines APEv2-Blocks, der bei ``end`` endet."""
    if end < 32 or data[end - 32:end - 24] != b"APETAGEX":
        return None
    size = int.from_bytes(data[end - 20:end - 16], "little")
    flags = int.from_bytes(data[end - 12:end - 8], "little")
    total = size + (32 if flags & 0x80000000 else 0)
    start = end - total
    return start if 0 <= start < end else None


def remove(path: str | Path) -> bool:
    """Entfernt einen vorhandenen Block. Gibt zurück, ob etwas entfernt wurde."""
    p = Path(path)
    data = p.read_bytes()
    cut = _block_end(data)
    found = find(data, cut)
    if not found:
        return False
    start, stop = found
    p.write_bytes(data[:start] + data[stop:])
    return True


def _block_end(data: bytes) -> int:
    """Position, an der der Lyrics3-Block enden müsste.

    Hinter ihm dürfen nur noch APEv2 und ID3v1 stehen - in beliebiger
    Reihenfolge, denn nicht jedes Programm hält sich an die übliche. Deshalb
    wird geschlungen, bis nichts Bekanntes mehr am Ende steht.
    """
    end = len(data)
    while True:
        if end >= 128 and data[end - 128:end - 125] == b"TAG":
            end -= 128
            continue
        ape = _ape_start(data, end)
        if ape is not None:
            end = ape
            continue
        return end


def write(path: str | Path, values: dict[str, str],
          encoding: str = "cp437") -> None:
    """Schreibt einen Lyrics3v2-Block an die richtige Stelle.

    Ein vorhandener Block wird ersetzt. APEv2 und ID3v1 bleiben unangetastet
    und behalten ihre Position am Dateiende.
    """
    p = Path(path)
    data = p.read_bytes()
    cut = _block_end(data)

    found = find(data, cut)
    if found:
        start, stop = found
        data = data[:start] + data[stop:]
        cut -= stop - start

    block = build(values, encoding)
    p.write_bytes(data[:cut] + block + data[cut:])


def read(path: str | Path, encoding: str = "cp437") -> dict[str, str]:
    """Liest einen vorhandenen Block. Leeres Dict, wenn keiner da ist."""
    data = Path(path).read_bytes()
    found = find(data, _block_end(data))
    if not found:
        return {}
    start, stop = found
    body = data[start + len(BEGIN):stop - 15]

    reverse = {code: name for name, code in FIELDS.items()}
    out: dict[str, str] = {}
    pos = 0
    while pos + 8 <= len(body):
        code = body[pos:pos + 3].decode("ascii", errors="replace")
        digits = body[pos + 3:pos + 8]
        if not digits.isdigit():
            break
        size = int(digits)
        payload = body[pos + 8:pos + 8 + size]
        name = reverse.get(code)
        if name:
            out[name] = payload.decode(encoding, errors="replace")
        pos += 8 + size
    return out
