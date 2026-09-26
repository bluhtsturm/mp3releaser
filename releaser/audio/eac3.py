"""Enhanced AC-3 (Dolby Digital Plus).

Der Teil, den mutagen nicht abdeckt. Zwei Faelle:

* **Roher ``.ec3``/``.eac3``-Stream** - kein Tag-Container, kein Header mit
  Dauer. Alles muss aus dem Bitstream selbst kommen: Syncframes zaehlen,
  BSI-Header parsen, Substreams zuordnen.
* **EC-3 im MP4-Container** - hier liegen nur ``parse_dec3`` und ``find_dec3``;
  das Lesen des Containers erledigt ``mp4.py`` (ETSI TS 102 366, Annex F).

Referenz: ETSI TS 102 366 (AC-3/E-AC-3), Annex E fuer die BSI-Syntax,
Annex F fuer ``EC3SpecificBox``. Die Traversierung der optionalen
Mixing-/Info-Metadaten folgt der Implementierung in FFmpegs ``eac3_parser``,
die gegenueber dem Prosatext der Spezifikation an zwei Stellen praeziser ist
(Bedingungen auf ``acmod`` bei ``dmixmod`` und ``paninfo``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .base import ACMOD_NAMES, AudioError, AudioInfo, register
from .bitreader import BitReader, BitReaderError

SYNCWORD = b"\x0b\x77"

#: fscod -> Samplerate. 3 bedeutet: fscod2 auswerten (halbierte Raten).
FSCOD = {0: 48000, 1: 44100, 2: 32000}
FSCOD2 = {0: 24000, 1: 22050, 2: 16000}

#: numblkscod -> Anzahl Audioblocks je Frame (je 256 Samples).
NUMBLKS = {0: 1, 1: 2, 2: 3, 3: 6}

STRMTYP_INDEPENDENT = 0
STRMTYP_DEPENDENT = 1
STRMTYP_AC3 = 2

#: chanmap-Bits des abhaengigen Substreams (MSB zuerst) und ihre Kanalzahl.
CHANMAP_BITS = [
    ("L", 1), ("C", 1), ("R", 1), ("Ls", 1), ("Rs", 1),
    ("Lc/Rc", 2), ("Lrs/Rrs", 2), ("Cs", 1), ("Ts", 1), ("Lsd/Rsd", 2),
    ("Lw/Rw", 2), ("Vhl/Vhr", 2), ("Vhc", 1), ("Lts/Rts", 2),
    ("LFE2", 1), ("LFE", 1),
]


@dataclass
class Substream:
    strmtyp: int
    substreamid: int
    frame_bytes: int
    samplerate: int
    numblks: int
    acmod: int
    lfeon: int
    bsid: int
    chanmap: Optional[int] = None
    #: aus ``addbsi``: Dolby-Erweiterung Typ A (JOC)
    ext_type_a: Optional[bool] = None
    complexity_index: Optional[int] = None
    #: True, wenn die BSI-Traversierung bis ``addbsi`` durchlief
    fully_parsed: bool = False

    @property
    def channels(self) -> int:
        base = ACMOD_NAMES.get(self.acmod, ("", 0))[1]
        return base + (1 if self.lfeon else 0)

    @property
    def chanmap_channels(self) -> int:
        if self.chanmap is None:
            return 0
        total = 0
        for i, (_name, count) in enumerate(CHANMAP_BITS):
            if self.chanmap & (1 << (15 - i)):
                total += count
        return total


# --------------------------------------------------------------- BSI-Parsing


def parse_syncframe(data: bytes, offset: int) -> Substream:
    """Liest den BSI-Header eines Syncframes ab ``offset`` (zeigt auf 0x0B77)."""
    if data[offset:offset + 2] != SYNCWORD:
        raise AudioError(f"kein Syncword an Position {offset}")

    br = BitReader(data, (offset + 2) * 8)
    strmtyp = br.read(2)
    substreamid = br.read(3)
    frmsiz = br.read(11)
    frame_bytes = (frmsiz + 1) * 2

    fscod = br.read(2)
    if fscod == 3:
        fscod2 = br.read(2)
        if fscod2 not in FSCOD2:
            raise AudioError(f"reserviertes fscod2={fscod2} bei Byte {offset}")
        samplerate = FSCOD2[fscod2]
        numblks = 6
    else:
        samplerate = FSCOD[fscod]
        numblks = NUMBLKS[br.read(2)]

    acmod = br.read(3)
    lfeon = br.read(1)
    bsid = br.read(5)

    sub = Substream(strmtyp, substreamid, frame_bytes, samplerate,
                    numblks, acmod, lfeon, bsid)

    # Ab hier wird es optional und fehleranfaellig. Die Werte oben sind
    # bereits vollstaendig - schlaegt die Tiefentraversierung fehl, bleibt
    # nur die JOC-Information unbekannt.
    try:
        _parse_bsi_tail(br, sub, fscod)
        sub.fully_parsed = True
    except BitReaderError:
        pass

    return sub


def _parse_bsi_tail(br: BitReader, sub: Substream, fscod: int) -> None:
    acmod, lfeon, strmtyp = sub.acmod, sub.lfeon, sub.strmtyp

    br.skip(5)                                   # dialnorm
    if br.flag():                                # compre
        br.skip(8)
    if acmod == 0:                               # 1+1: zweiter Kanal
        br.skip(5)
        if br.flag():
            br.skip(8)

    if strmtyp == STRMTYP_DEPENDENT:
        if br.flag():                            # chanmape
            sub.chanmap = br.read(16)

    if br.flag():                                # mixmdate
        if acmod > 2:
            br.skip(2)                           # dmixmod
        if (acmod & 1) and acmod > 5:
            br.skip(6)                           # ltrtcmixlev / lorocmixlev
        if acmod & 4:
            br.skip(6)                           # ltrtsurmixlev / lorosurmixlev
        if lfeon and br.flag():
            br.skip(5)                           # lfemixlevcod
        if strmtyp == STRMTYP_INDEPENDENT:
            for _ in range(1 if acmod else 2):
                if br.flag():                    # pgmscle
                    br.skip(6)
            if br.flag():                        # extpgmscle
                br.skip(6)
            mixdef = br.read(2)
            if mixdef == 1:
                br.skip(5)
            elif mixdef == 2:
                br.skip(12)
            elif mixdef == 3:
                mixdeflen = br.read(5)
                br.skip(8 * (mixdeflen + 2))
            if acmod < 2:
                for _ in range(1 if acmod else 2):
                    if br.flag():                # paninfoe
                        br.skip(8 + 6)
            if br.flag():                        # frmmixcfginfoe
                if sub.numblks == 1:
                    br.skip(5)
                else:
                    for _ in range(sub.numblks):
                        if br.flag():
                            br.skip(5)

    if br.flag():                                # infomdate
        br.skip(3)                               # bsmod
        br.skip(2)                               # copyrightb, origbs
        if acmod == 2:
            br.skip(4)                           # dsurmod, dheadphonmod
        elif acmod >= 6:
            br.skip(2)                           # dsurexmod
        if br.flag():                            # audprodie
            br.skip(8)                           # mixlevel, roomtyp, adconvtyp
        if acmod == 0 and br.flag():             # audprodi2e
            br.skip(8)
        if fscod < 3:
            br.skip(1)                           # sourcefscod

    if strmtyp == STRMTYP_INDEPENDENT and sub.numblks != 6:
        br.skip(1)                               # convsync
    if strmtyp == STRMTYP_AC3:
        blkid = 1 if sub.numblks == 6 else br.read(1)
        if blkid:
            br.skip(6)                           # frmsizecod

    if br.flag():                                # addbsie
        addbsil = br.read(6)
        nbytes = addbsil + 1
        addbsi = bytes(br.read(8) for _ in range(nbytes))
        _parse_addbsi(addbsi, sub)


def _parse_addbsi(addbsi: bytes, sub: Substream) -> None:
    """Dolby-Erweiterung Typ A: JOC-Kennzeichen und Objektanzahl.

    Layout laut ETSI TS 103 420: sieben reservierte Bits, dann
    ``flag_ec3_extension_type_a``; ist es gesetzt, folgt
    ``complexity_index_type_a`` (= Anzahl der JOC-Objekte).
    """
    if not addbsi:
        return
    sub.ext_type_a = bool(addbsi[0] & 0x01)
    if sub.ext_type_a and len(addbsi) >= 2:
        sub.complexity_index = addbsi[1]


# ------------------------------------------------------------ Stream-Analyse


@dataclass
class StreamSummary:
    substreams: list[Substream] = field(default_factory=list)
    frame_count: int = 0            # nur unabhaengige Frames (= Audioframes)
    total_bytes: int = 0
    samples: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def independent(self) -> list[Substream]:
        return [s for s in self.substreams if s.strmtyp != STRMTYP_DEPENDENT]

    @property
    def dependent(self) -> list[Substream]:
        return [s for s in self.substreams if s.strmtyp == STRMTYP_DEPENDENT]


def analyse_stream(data: bytes, max_frames: int = 2000) -> StreamSummary:
    """Laeuft ueber die Syncframes und fasst die Substream-Struktur zusammen.

    ``max_frames`` begrenzt nur die Strukturanalyse; Dauer und Bitrate werden
    aus allen Frames hochgerechnet.
    """
    summary = StreamSummary()
    seen: dict[tuple[int, int], Substream] = {}

    offset = data.find(SYNCWORD)
    if offset < 0:
        raise AudioError("kein EC-3-Syncword gefunden")
    if offset > 0:
        summary.warnings.append(f"{offset} Bytes Vorlauf vor dem ersten Syncframe")

    frames = 0
    while offset + 5 <= len(data):
        if data[offset:offset + 2] != SYNCWORD:
            resync = data.find(SYNCWORD, offset)
            if resync < 0:
                break
            summary.warnings.append(f"Resync bei Byte {resync}")
            offset = resync
            continue
        try:
            sub = parse_syncframe(data, offset)
        except (AudioError, BitReaderError, KeyError, IndexError):
            break
        if sub.frame_bytes <= 0:
            break

        key = (sub.strmtyp, sub.substreamid)
        if key not in seen:
            seen[key] = sub
            summary.substreams.append(sub)
        elif sub.chanmap is not None and seen[key].chanmap is None:
            seen[key] = sub

        if sub.strmtyp != STRMTYP_DEPENDENT and sub.substreamid == 0:
            summary.frame_count += 1
            summary.samples += sub.numblks * 256

        offset += sub.frame_bytes
        frames += 1
        if frames > max_frames * 8:
            break

    summary.total_bytes = len(data)
    return summary


def summarise_channels(summary: StreamSummary) -> tuple[int, str]:
    """Gesamtkanalzahl und Beschriftung aus unabhaengigem + abhaengigem Stream."""
    ind = summary.independent
    if not ind:
        return 0, ""
    main = ind[0]
    channels = main.channels
    for dep in summary.dependent:
        channels = max(channels, dep.chanmap_channels + (1 if main.lfeon else 0))
    label = ACMOD_NAMES.get(main.acmod, ("?", 0))[0]
    if main.lfeon:
        label += " + LFE"
    speaker = f"{channels - 1}.1" if main.lfeon else f"{channels}.0"
    return channels, f"{label} ({speaker})"


def detect_joc(summary: StreamSummary) -> tuple[Optional[bool], Optional[int]]:
    """JOC/Atmos-Kennzeichen aus den abhaengigen Substreams.

    Rueckgabe ``(None, None)``, wenn keiner der Substreams vollstaendig
    geparst werden konnte - dann ist *unbekannt* die ehrliche Antwort,
    nicht *nein*.
    """
    deps = summary.dependent
    if not deps:
        # Ohne abhaengigen Substream kann kein JOC vorliegen, sofern wenigstens
        # ein Frame vollstaendig gelesen wurde.
        if any(s.fully_parsed for s in summary.substreams):
            return False, None
        return None, None
    if not any(s.fully_parsed for s in deps):
        return None, None
    for dep in deps:
        if dep.ext_type_a:
            return True, dep.complexity_index
    return False, None


# ------------------------------------------------------------------- Reader


@register(".ec3", ".eac3")
def read_raw_ec3(path: Path) -> AudioInfo:
    data = path.read_bytes()
    summary = analyse_stream(data)
    ind = summary.independent
    if not ind:
        raise AudioError(f"kein unabhaengiger Substream in {path.name}")
    main = ind[0]

    duration = summary.samples / main.samplerate if main.samplerate else 0.0
    bitrate = int(round(len(data) * 8 / duration / 1000)) if duration else None
    channels, mode = summarise_channels(summary)
    atmos, objects = detect_joc(summary)

    info = AudioInfo(
        path=path,
        codec="EAC3",
        size_bytes=path.stat().st_size,
        duration=duration,
        bitrate=bitrate,
        samplerate=main.samplerate,
        channels=channels,
        channel_mode=mode,
        atmos=atmos,
        object_count=objects,
        tagless=True,
        warnings=list(summary.warnings),
    )
    info.title = path.stem
    info.warnings.append(
        "roher EC-3-Stream: keine Tags im Format - Titel stammt aus dem Dateinamen"
    )
    if atmos is None:
        info.warnings.append("JOC-Status unbestimmbar (BSI-Traversierung abgebrochen)")
    return info


# ------------------------------------------ EC3SpecificBox (von mp4.py genutzt)


@dataclass
class Dec3Box:
    data_rate: int
    substreams: list[dict]
    ext_type_a: Optional[bool] = None
    complexity_index: Optional[int] = None


def parse_dec3(payload: bytes) -> Dec3Box:
    """``EC3SpecificBox`` nach ETSI TS 102 366, Annex F.6."""
    br = BitReader(payload)
    data_rate = br.read(13)
    num_ind_sub = br.read(3) + 1

    subs: list[dict] = []
    for _ in range(num_ind_sub):
        fscod = br.read(2)
        bsid = br.read(5)
        br.skip(1)                       # reserved
        br.skip(1)                       # asvc
        bsmod = br.read(3)
        acmod = br.read(3)
        lfeon = br.read(1)
        br.skip(3)                       # reserved
        num_dep_sub = br.read(4)
        chan_loc = br.read(9) if num_dep_sub else None
        if not num_dep_sub:
            br.skip(1)                   # reserved
        subs.append(dict(fscod=fscod, bsid=bsid, bsmod=bsmod, acmod=acmod,
                         lfeon=lfeon, num_dep_sub=num_dep_sub, chan_loc=chan_loc))

    box = Dec3Box(data_rate=data_rate, substreams=subs)
    # Optionaler Dolby-Anhang: 7 reservierte Bits + flag_ec3_extension_type_a,
    # danach complexity_index_type_a.
    if br.remaining >= 8:
        br.skip(7)
        box.ext_type_a = bool(br.read(1))
        if box.ext_type_a and br.remaining >= 8:
            box.complexity_index = br.read(8)
    return box


def find_dec3(data: bytes) -> Optional[bytes]:
    """Sucht die ``dec3``-Box und gibt ihren Inhalt zurueck."""
    idx = data.find(b"dec3")
    while idx > 4:
        size = int.from_bytes(data[idx - 4:idx], "big")
        if 8 < size < 4096 and idx - 4 + size <= len(data):
            return data[idx + 4:idx - 4 + size]
        idx = data.find(b"dec3", idx + 4)
    return None
