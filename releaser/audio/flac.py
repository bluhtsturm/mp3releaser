"""FLAC ueber mutagen.

Der Tag ``#FlacC`` des Originals verlangt eine Kompressionsrate. Die steht
nirgends in der Datei, sondern ergibt sich aus dem Verhaeltnis von Dateigroesse
zur unkomprimierten PCM-Groesse, die aus STREAMINFO berechenbar ist:

    total_samples * channels * bits_per_sample / 8

Die Encoder-Fassung steht im Vendor-String des Kommentarblocks - dort, wo
der Referenz-Encoder ``reference libFLAC 1.4.3 20230623`` hinschreibt.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import AudioError, AudioInfo, apply_vorbis_tags, register

#: So nennt sich der Referenz-Encoder im Vendor-String
_LIBFLAC = re.compile(r"libFLAC\s+(\S+)", re.IGNORECASE)


def encoder_from_vendor(vendor: str) -> str:
    """Die Encoder-Angabe aus dem Vendor-String eines FLAC-Kommentarblocks.

    Bei MP3 steht die Encoder-Fassung im LAME-Header, bei FLAC im
    Vendor-String - den las das Programm bisher nicht, das Feld blieb bei
    FLAC leer. Der Referenz-Encoder wird zu ``FLAC 1.4.3``, so wie MP3
    ``LAME 3.100`` zeigt. Andere Encoder bleiben, wie sie sich nennen (ffmpeg
    etwa ``Lavf60.16.100``). ``Mutagen …`` ist kein Encoder, sondern das
    Tag-Programm, das einen fehlenden Kommentarblock angelegt hat.
    """
    vendor = (vendor or "").strip()
    if not vendor or vendor.lower().startswith("mutagen"):
        return ""
    match = _LIBFLAC.search(vendor)
    return f"FLAC {match.group(1)}" if match else vendor


@register(".flac")
def read_flac(path: Path) -> AudioInfo:
    from mutagen.flac import FLAC, FLACNoHeaderError

    try:
        audio = FLAC(path)
    except FLACNoHeaderError as exc:
        raise AudioError(f"kein FLAC-Header in {path.name}: {exc}") from exc

    si = audio.info
    size = path.stat().st_size
    info = AudioInfo(
        path=path,
        codec="FLAC",
        size_bytes=size,
        duration=float(si.length or 0.0),
        bitrate=int(round((si.bitrate or 0) / 1000)) or None,
        samplerate=si.sample_rate or None,
        channels=si.channels or None,
        bits_per_sample=si.bits_per_sample or None,
        channel_mode={1: "Mono", 2: "Stereo"}.get(si.channels, f"{si.channels}ch"),
    )

    raw = (si.total_samples or 0) * (si.channels or 0) * (si.bits_per_sample or 0) / 8
    if raw > 0:
        info.compression_ratio = size / raw

    apply_vorbis_tags(audio, info)
    # Wie bei MP3 der LAME-Header geht der Vendor-String einem ENCODER-Tag
    # vor: Er stammt vom Encoder selbst, das Tag von irgendeinem Programm.
    # Ein Kommentarblock ohne Eintraege ist "leer", aber nicht None - der
    # Referenz-Encoder schreibt genau so einen.
    if audio.tags is not None:
        encoder = encoder_from_vendor(getattr(audio.tags, "vendor", ""))
        if encoder:
            info.encoder = encoder
    return info
