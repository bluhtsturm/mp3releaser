"""FLAC ueber mutagen.

Der Tag ``#FlacC`` des Originals verlangt eine Kompressionsrate. Die steht
nirgends in der Datei, sondern ergibt sich aus dem Verhaeltnis von Dateigroesse
zur unkomprimierten PCM-Groesse, die aus STREAMINFO berechenbar ist:

    total_samples * channels * bits_per_sample / 8
"""

from __future__ import annotations

from pathlib import Path

from .base import AudioError, AudioInfo, apply_vorbis_tags, register


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
    return info
