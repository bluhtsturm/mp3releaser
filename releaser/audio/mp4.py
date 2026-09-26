"""MP4/M4A-Container: AAC, ALAC und EC-3.

mutagen liest den Container und die iTunes-Atoms. Was es nicht liefert, wird
hier aus den Boxen nachgeholt:

* **Codec-Kennung** — ``mp4a.40.2`` ist AAC-LC, ``.5`` HE-AAC, ``.29``
  HE-AACv2. Für das NFO-Feld ``#Format`` reicht "AAC", die Profilangabe
  landet in ``encoder``.
* **VBR** — MP4 hat kein VBR-Flag. Die ``stsz``-Box enthält aber die Größe
  jedes einzelnen Samples; schwanken die, ist der Stream variabel. Das ist
  eine Heuristik, siehe ``looks_variable``.
* **EC-3** — technische Werte aus der ``dec3``-Box, siehe ``eac3.py``.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Optional

from .base import ACMOD_NAMES, AudioError, AudioInfo, register
from .eac3 import find_dec3, parse_dec3

#: Objekttyp-Kennung aus ``mp4a.40.<N>`` -> Profilname.
AAC_PROFILES = {
    "2": "AAC-LC",
    "5": "HE-AAC",
    "29": "HE-AACv2",
    "23": "AAC-LD",
    "39": "AAC-ELD",
}

CHANNEL_NAMES = {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}

#: Ab diesem Variationskoeffizienten der Sample-Größen gilt ein Stream als
#: variabel. AAC schwankt auch bei konstanter Zielbitrate leicht (Bit-Reservoir),
#: deshalb keine strengere Schwelle.
VBR_THRESHOLD = 0.10


def _iter_boxes(data: bytes, start: int, end: int):
    """Läuft über die MP4-Boxen eines Bereichs."""
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos:pos + 4], "big")
        name = data[pos + 4:pos + 8]
        if size == 1:                       # 64-Bit-Größe
            size = int.from_bytes(data[pos + 8:pos + 16], "big")
            payload = pos + 16
        elif size == 0:                     # bis zum Ende
            size = end - pos
            payload = pos + 8
        else:
            payload = pos + 8
        if size < 8 or pos + size > end:
            return
        yield name, payload, pos + size
        pos += size


def find_stsz(data: bytes) -> Optional[bytes]:
    """Sucht die ``stsz``-Box über den Containerpfad statt per Byte-Suche."""
    def descend(start: int, end: int, path: tuple[bytes, ...]) -> Optional[bytes]:
        for name, payload, stop in _iter_boxes(data, start, end):
            if name == b"stsz":
                return data[payload:stop]
            if name in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                found = descend(payload, stop, path + (name,))
                if found:
                    return found
        return None

    return descend(0, len(data), ())


def sample_sizes(stsz: bytes, limit: int = 5000) -> list[int]:
    """Liest die Sample-Größen aus einer ``stsz``-Box.

    Ist das Feld ``sample_size`` ungleich null, haben alle Samples dieselbe
    Größe und es folgt keine Tabelle.
    """
    if len(stsz) < 12:
        return []
    uniform = int.from_bytes(stsz[4:8], "big")
    count = int.from_bytes(stsz[8:12], "big")
    if uniform:
        return [uniform] * min(count, limit)
    sizes: list[int] = []
    for i in range(min(count, limit)):
        offset = 12 + i * 4
        if offset + 4 > len(stsz):
            break
        sizes.append(int.from_bytes(stsz[offset:offset + 4], "big"))
    return sizes


def looks_variable(sizes: list[int]) -> Optional[bool]:
    """Heuristik: schwanken die Sample-Größen deutlich, ist der Stream variabel.

    ``None``, wenn zu wenige Samples für eine Aussage vorliegen.
    """
    usable = [s for s in sizes if s > 0]
    if len(usable) < 20:
        return None
    mean = statistics.fmean(usable)
    if mean <= 0:
        return None
    return statistics.pstdev(usable) / mean > VBR_THRESHOLD


def describe_codec(codec: str, description: str) -> tuple[str, str]:
    """(Format für #Format, Profilzusatz für den Encoder-Eintrag)."""
    codec = (codec or "").lower()
    if codec.startswith("mp4a.40."):
        profile = AAC_PROFILES.get(codec.rsplit(".", 1)[1], description or "AAC")
        return "AAC", profile
    if codec.startswith("mp4a"):
        return "AAC", description or "AAC"
    if codec == "alac":
        return "ALAC", ""
    if codec in ("ec-3", "ec+3"):
        return "EAC3", ""
    if codec.startswith("ac-3"):
        return "AC3", ""
    return (description or codec or "MP4").upper(), ""


@register(".m4a", ".mp4", ".m4b")
def read_mp4(path: Path) -> AudioInfo:
    from mutagen.mp4 import MP4, MP4StreamInfoError

    info = AudioInfo(path=path, size_bytes=path.stat().st_size)
    try:
        mp4 = MP4(path)
    except MP4StreamInfoError as exc:
        raise AudioError(f"MP4 nicht lesbar: {exc}") from exc

    mi = mp4.info
    if mi is not None:
        info.duration = float(mi.length or 0.0)
        info.samplerate = getattr(mi, "sample_rate", None)
        info.channels = getattr(mi, "channels", None)
        info.bits_per_sample = getattr(mi, "bits_per_sample", None) or None
        bitrate = getattr(mi, "bitrate", 0)
        info.bitrate = int(round(bitrate / 1000)) if bitrate else None
        codec, profile = describe_codec(getattr(mi, "codec", ""),
                                        getattr(mi, "codec_description", ""))
        info.codec = codec
        if profile:
            info.encoder = profile
        info.channel_mode = CHANNEL_NAMES.get(info.channels or 0,
                                              f"{info.channels}ch"
                                              if info.channels else "")

    _apply_mp4_tags(mp4, info)

    raw = path.read_bytes()
    if info.codec == "EAC3":
        _apply_dec3(raw, info)
    elif info.codec == "ALAC":
        info.vbr = False
    else:
        stsz = find_stsz(raw)
        variable = looks_variable(sample_sizes(stsz)) if stsz else None
        if variable is None:
            info.warnings.append("VBR-Status nicht bestimmbar (stsz unauswertbar)")
        else:
            info.vbr = variable
    return info


def _apply_dec3(raw: bytes, info: AudioInfo) -> None:
    payload = find_dec3(raw)
    if not payload:
        info.warnings.append("EC-3 ohne dec3-Box - technische Werte unvollständig")
        return
    box = parse_dec3(payload)
    if box.data_rate:
        info.bitrate = box.data_rate
    if box.substreams:
        main = box.substreams[0]
        label = ACMOD_NAMES.get(main["acmod"], ("?", 0))[0]
        if main["lfeon"]:
            label += " + LFE"
        info.channel_mode = label
    info.atmos = box.ext_type_a
    info.object_count = box.complexity_index


def _apply_mp4_tags(mp4, info: AudioInfo) -> None:
    tags = mp4.tags or {}

    def first(key: str) -> str:
        value = tags.get(key)
        if isinstance(value, list) and value:
            return str(value[0])
        return ""

    info.title = first("\xa9nam")
    info.artist = first("\xa9ART")
    info.album_artist = first("aART")
    info.album = first("\xa9alb")
    info.genre = first("\xa9gen")
    info.comment = first("\xa9cmt")
    encoder = first("\xa9too")
    if encoder:
        info.encoder = f"{info.encoder} ({encoder})" if info.encoder else encoder

    date = first("\xa9day")[:4]
    if date.isdigit():
        info.year = int(date)

    for key, num_attr, total_attr in (("trkn", "track_no", "total_tracks"),
                                      ("disk", "disc_no", "total_discs")):
        value = tags.get(key)
        if isinstance(value, list) and value and isinstance(value[0], tuple):
            num, total = (list(value[0]) + [0, 0])[:2]
            setattr(info, num_attr, num or None)
            setattr(info, total_attr, total or None)
