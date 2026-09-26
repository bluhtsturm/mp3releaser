"""Textwerkzeuge: Codepage-I/O, Schreibweisen, Zeit- und Groessenformate.

Der Renderer arbeitet intern durchgaengig mit ``str`` (Unicode). CP437 kommt
nur an den Raendern ins Spiel: beim Lesen des Templates und beim Schreiben der
fertigen .nfo. Genau so vermeidet man die Klasse von Bugs, an der das Original
laut Changelog wiederholt gelitten hat.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from pathlib import Path

NFO_CODEPAGE = "cp437"

#: Ersetzungen, die *vor* der generischen Unicode-Zerlegung greifen muessen,
#: weil NFKD aus "Ä" sonst "A" statt "Ae" macht.
_ASCII_MAP = {
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ä": "ae", "ö": "oe", "ü": "ue",
    "ß": "ss", "æ": "ae", "Æ": "Ae", "ø": "oe", "Ø": "Oe",
    "å": "aa", "Å": "Aa", "đ": "d", "Đ": "D", "þ": "th", "Þ": "Th",
    "—": "-", "–": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
}


class CharCase(Enum):
    """Schreibweisen-Regel. Im Original getrennt fuer Dir / Tags / NFO."""

    UNCHANGED = "unchanged"
    LOWER = "lower"
    UPPER = "upper"
    CAPITALIZE = "capitalize"

    def apply(self, value: str) -> str:
        if not value or self is CharCase.UNCHANGED:
            return value
        if self is CharCase.LOWER:
            return value.lower()
        if self is CharCase.UPPER:
            return value.upper()
        return capitalize_words(value)


#: Trenner sind alle Nicht-Wortzeichen *und* der Unterstrich. Ohne ihn waere
#: "der_artist" ein einziges Wort - in Python zaehlt "_" als Wortzeichen, und
#: genau diese Form entsteht, nachdem die Regelkette Leerzeichen ersetzt hat.
_WORD_SPLIT = re.compile(r"([\W_]+)", re.UNICODE)

#: Woerter, die in der Mitte eines Titels klein bleiben.
_MINOR_WORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into",
    "nor", "of", "on", "or", "the", "to", "vs", "with",
}


#: Bis zu dieser Laenge bleiben durchgehend grossgeschriebene Woerter, wie
#: sie sind: Akronyme ("DJ", "UK"), Quellenangaben ("CDDA", "WEB") und
#: Gruppenkuerzel ("GRP"). Laengere werden normalisiert, damit aus "REMIX"
#: nicht dauerhaft Grossbuchstaben werden.
ACRONYM_LENGTH = 4


def capitalize_words(value: str, keep_minor: bool = True) -> str:
    """Title-Case mit Ruecksicht auf Fuellwoerter und bereits gesetzte Caps."""
    parts = _WORD_SPLIT.split(value)
    out: list[str] = []
    word_index = 0
    last_word_index = max(
        (i for i, p in enumerate(parts) if p and not _WORD_SPLIT.fullmatch(p)),
        default=-1,
    )
    for i, part in enumerate(parts):
        if not part or _WORD_SPLIT.fullmatch(part):
            out.append(part)
            continue
        lowered = part.lower()
        is_edge = word_index == 0 or i == last_word_index
        if keep_minor and not is_edge and lowered in _MINOR_WORDS:
            out.append(lowered)
        elif part.isupper() and len(part) <= ACRONYM_LENGTH:
            out.append(part)
        else:
            out.append(lowered[:1].upper() + lowered[1:])
        word_index += 1
    return "".join(out)


def to_ascii(value: str) -> str:
    """Konvertiert nach 7-Bit-ASCII (Option 'ascii conversion for .nfo')."""
    for src, dst in _ASCII_MAP.items():
        value = value.replace(src, dst)
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if ord(c) < 128)


def to_codepage(value: str, codepage: str = NFO_CODEPAGE) -> bytes:
    """Kodiert nach CP437 und faellt fuer nicht abbildbare Zeichen auf ASCII zurueck."""
    try:
        return value.encode(codepage)
    except UnicodeEncodeError:
        return to_ascii(value).encode(codepage, errors="replace")


def read_template(path: str | Path, codepage: str = NFO_CODEPAGE) -> str:
    raw = Path(path).read_bytes()
    text = raw.decode(codepage, errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_nfo(
    path: str | Path,
    text: str,
    codepage: str = NFO_CODEPAGE,
    crlf: bool = True,
) -> None:
    body = text.replace("\r\n", "\n")
    if crlf:
        body = body.replace("\n", "\r\n")
    Path(path).write_bytes(to_codepage(body, codepage))


# --------------------------------------------------------------------- Formate


def format_time(seconds: float, strip_leading_zero: bool = False) -> str:
    """mm:ss - bei mehr als 59 Minuten waechst das Minutenfeld mit."""
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    out = f"{minutes:02d}:{secs:02d}"
    if strip_leading_zero:
        out = out.lstrip("0") or "0"
        if out.startswith(":"):
            out = "0" + out
    return out


def format_size_mb(size_bytes: int, decimal_comma: bool = False) -> str:
    """Groesse in MB mit einer Nachkommastelle."""
    out = f"{size_bytes / (1024 * 1024):.1f}"
    return out.replace(".", ",") if decimal_comma else out


def wrap_value(value: str, width: int, max_lines: int | None = None) -> list[str]:
    """Weicher Umbruch an Wortgrenzen, harter Schnitt bei Ueberlaenge."""
    if width <= 0:
        return [""]
    lines: list[str] = []
    for paragraph in value.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            while len(word) > width:
                if current:
                    lines.append(current)
                    current = ""
                lines.append(word[:width])
                word = word[width:]
            candidate = f"{current} {word}".strip()
            if len(candidate) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    if max_lines is not None:
        lines = lines[:max_lines]
    return lines or [""]
