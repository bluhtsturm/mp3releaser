"""Ogg Vorbis, Opus und Musepack.

Das Original unterstützte neben MP3 und FLAC auch Ogg Vorbis und Musepack.
Beide bringt mutagen mit; die Tag-Abbildung teilen sie sich mit FLAC
(Vorbis-Comments) beziehungsweise mit allem APEv2-basierten.
"""

from __future__ import annotations

from pathlib import Path

from .base import (
    AudioError,
    AudioInfo,
    apply_ape_tags,
    apply_vorbis_tags,
    register,
)

CHANNEL_NAMES = {1: "Mono", 2: "Stereo", 6: "5.1", 8: "7.1"}


def _channel_mode(channels: int | None) -> str:
    if not channels:
        return ""
    return CHANNEL_NAMES.get(channels, f"{channels}ch")


@register(".ogg", ".oga")
def read_ogg(path: Path) -> AudioInfo:
    from mutagen.oggvorbis import OggVorbis, OggVorbisHeaderError

    try:
        audio = OggVorbis(path)
    except OggVorbisHeaderError as exc:
        raise AudioError(f"kein Ogg-Vorbis-Header in {path.name}: {exc}") from exc

    si = audio.info
    info = AudioInfo(
        path=path,
        codec="OGG",
        size_bytes=path.stat().st_size,
        duration=float(si.length or 0.0),
        bitrate=int(round((si.bitrate or 0) / 1000)) or None,
        samplerate=si.sample_rate or None,
        channels=si.channels or None,
        channel_mode=_channel_mode(si.channels),
        #: Vorbis ist praktisch immer variabel
        vbr=True,
    )
    apply_vorbis_tags(audio, info)
    return info


@register(".opus")
def read_opus(path: Path) -> AudioInfo:
    from mutagen.oggopus import OggOpus, OggOpusHeaderError

    try:
        audio = OggOpus(path)
    except OggOpusHeaderError as exc:
        raise AudioError(f"kein Opus-Header in {path.name}: {exc}") from exc

    si = audio.info
    size = path.stat().st_size
    duration = float(si.length or 0.0)
    info = AudioInfo(
        path=path,
        codec="OPUS",
        size_bytes=size,
        duration=duration,
        #: Opus meldet keine Bitrate - aus Dateigröße und Dauer schätzen
        bitrate=int(round(size * 8 / duration / 1000)) if duration else None,
        samplerate=48000,          # Opus dekodiert immer auf 48 kHz
        channels=si.channels or None,
        channel_mode=_channel_mode(si.channels),
        vbr=True,
    )
    apply_vorbis_tags(audio, info)
    info.warnings.append("Opus: Bitrate aus Dateigröße geschätzt")
    return info


@register(".mpc", ".mp+")
def read_musepack(path: Path) -> AudioInfo:
    from mutagen.musepack import Musepack, MusepackHeaderError

    try:
        audio = Musepack(path)
    except MusepackHeaderError as exc:
        raise AudioError(f"kein Musepack-Header in {path.name}: {exc}") from exc

    si = audio.info
    info = AudioInfo(
        path=path,
        codec="MPC",
        size_bytes=path.stat().st_size,
        duration=float(si.length or 0.0),
        bitrate=int(round((si.bitrate or 0) / 1000)) or None,
        samplerate=si.sample_rate or None,
        channels=si.channels or None,
        channel_mode=_channel_mode(getattr(si, "channels", None)),
        vbr=True,
    )
    apply_ape_tags(audio.tags, info)
    return info
