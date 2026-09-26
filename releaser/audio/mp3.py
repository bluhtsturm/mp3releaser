"""MP3 ueber mutagen.

Neben den Tags interessieren drei Dinge, die das Original explizit anzeigte:
VBR-Status, Channel-Mode in der Schreibweise der Szene ("Joint-Stereo"),
und der Encoder aus dem LAME/Xing-Header.
"""

from __future__ import annotations

from pathlib import Path

from .base import AudioError, AudioInfo, register

#: mutagen liefert den Mode als Zahl; das Original schrieb diese Namen.
MPEG_MODES = {
    0: "Full Stereo",
    1: "Joint-Stereo",
    2: "Dual-Channel",
    3: "Single-Channel",
}


@register(".mp3")
def read_mp3(path: Path) -> AudioInfo:
    from mutagen.id3 import ID3, ID3NoHeaderError
    from mutagen.mp3 import MP3, HeaderNotFoundError

    try:
        audio = MP3(path)
    except HeaderNotFoundError as exc:
        raise AudioError(f"kein MPEG-Header in {path.name}: {exc}") from exc

    mi = audio.info
    info = AudioInfo(
        path=path,
        codec="MP3",
        size_bytes=path.stat().st_size,
        duration=float(mi.length or 0.0),
        bitrate=int(round((mi.bitrate or 0) / 1000)) or None,
        samplerate=mi.sample_rate or None,
        channels=1 if mi.mode == 3 else 2,
        channel_mode=MPEG_MODES.get(mi.mode, ""),
        vbr=_is_variable(getattr(mi, "bitrate_mode", None)),
        encoder=(getattr(mi, "encoder_info", "") or "").strip(),
    )

    try:
        _apply_id3(ID3(path), info)
    except ID3NoHeaderError:
        info.warnings.append("keine ID3-Tags vorhanden")
        info.title = path.stem
    return info


def _is_variable(mode) -> bool:
    """VBR und ABR gelten beide als variabel.

    Bei ABR schwankt die Bitrate von Frame zu Frame genauso, nur um einen
    Zielwert herum - jede Datei hat dadurch eine etwas andere mittlere
    Bitrate. Als "konstant" behandelt, meldete der Scanner bei jedem
    ABR-Release faelschlich "unterschiedliche Bitraten".
    """
    if mode is None:
        return False
    return str(mode).rsplit(".", 1)[-1] in ("VBR", "ABR")


def _apply_id3(tags, info: AudioInfo) -> None:
    def text(frame_id: str) -> str:
        frame = tags.get(frame_id)
        if frame is None:
            return ""
        values = getattr(frame, "text", None)
        return str(values[0]).strip() if values else ""

    info.title = text("TIT2")
    info.artist = text("TPE1")
    info.album_artist = text("TPE2")
    info.album = text("TALB")
    info.genre = text("TCON")
    if not info.encoder:
        info.encoder = text("TENC") or text("TSSE")

    for frame in tags.getall("COMM"):
        if frame.text:
            info.comment = str(frame.text[0]).strip()
            break

    year = text("TDRC") or text("TYER") or text("TDRL")
    if year[:4].isdigit():
        info.year = int(year[:4])

    info.track_no, info.total_tracks = _split_pair(text("TRCK"))
    info.disc_no, info.total_discs = _split_pair(text("TPOS"))


def _split_pair(value: str) -> tuple[int | None, int | None]:
    """'3/12' -> (3, 12); '3' -> (3, None)."""
    if not value:
        return None, None
    head, _, tail = value.partition("/")
    num = int(head) if head.strip().isdigit() else None
    total = int(tail) if tail.strip().isdigit() else None
    return num, total
