"""Feldkatalog für Oberflächen.

Das Original baute sein Formular aus der geladenen ``.skl``: Felder ohne
passenden Tag wurden ausgegraut. Das war 2003 richtig, weil die Vorlage die
einzige Abnehmerin der Eingaben war.

Heute speist dasselbe Modell **drei** Abnehmer: die NFO über die Vorlage, die
Dateinamen über die Namensmuster und die Tags über das Tag-Profil. Ein Feld,
das in keiner Vorlage steht, kann trotzdem gebraucht werden - ``#Catnr`` etwa
landet mit ``catalog_in_album`` im Album-Tag, und ``#Source`` steckt im
voreingestellten Verzeichnismuster.

Deshalb wird hier nicht ausgegraut, sondern **eingeordnet**: Welches Feld geht
wohin, und wie viel Platz hat es dort. Was nirgends gebraucht wird, landet in
einer eigenen Gruppe - sichtbar, aber nicht im Weg.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .naming import NamingProfile, compile_pattern
from .provenance import Origin
from .skl import Template
from .tagwriter import TagProfile


class Consumer(Enum):
    """Wer ein Feld verwendet."""

    NFO = "nfo"
    DIRNAME = "dirname"
    FILENAME = "filename"
    TAGS = "tags"

    @property
    def label(self) -> str:
        return {
            Consumer.NFO: "in der Vorlage",
            Consumer.DIRNAME: "im Verzeichnisnamen",
            Consumer.FILENAME: "im Dateinamen",
            Consumer.TAGS: "in den Tags",
        }[self]


@dataclass(frozen=True)
class FieldSpec:
    #: Attribut im Release-Modell
    name: str
    label: str
    #: zugehöriger SKL-Tag ohne führendes ``#``
    tag: Optional[str] = None
    kind: str = "text"          # text | number | lines
    hint: str = ""
    #: Tag in den Namensmustern, falls er vom SKL-Tag abweicht
    pattern_tag: Optional[str] = None
    #: False: das Feld speist keine Namensmuster, auch wenn sein SKL-Tag
    #: dort vorkommt - dafür gibt es dann ein eigenes Feld
    in_patterns: bool = True

    @property
    def name_tag(self) -> Optional[str]:
        """Der Tag, unter dem das Feld in Namensmustern steht, oder None."""
        if not self.in_patterns:
            return None
        return self.pattern_tag or self.tag


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("artist", "Artist", "Artist"),
    FieldSpec("album", "Album", "Album"),
    FieldSpec("album_addition", "Albumzusatz", "Albwthadd"),
    FieldSpec("year", "Jahr", "Year", kind="number"),
    FieldSpec("genre", "Genre", "Genre",
              hint="wird auf die ID3v1-Schreibweise gebracht"),
    FieldSpec("subgenre", "Subgenre", "Subgenre"),
    FieldSpec("style", "Stil", "Style"),
    FieldSpec("release_type", "Art", "Typ", hint="Album, Single, Maxi, EP"),
    # Zwei eigenständige Felder: die Quelle in der .nfo und die im
    # Verzeichnis-/Dateinamen. Sie füllen sich nicht gegenseitig aus.
    FieldSpec("source", "Quelle", "Source", hint="CDDA, WEB, Vinyl",
              in_patterns=False),
    FieldSpec("dir_source", "Quelle (Name)", None, pattern_tag="Source",
              hint="für Verzeichnis- und Dateinamen, z. B. CDDA, WEB"),
    FieldSpec("audio_format", "Format", "Format"),
    FieldSpec("language", "Sprache", "Language"),
    FieldSpec("country", "Land", "Country"),
    FieldSpec("company", "Label", "Company"),
    FieldSpec("catalog_no", "Katalognummer", "Catnr"),
    FieldSpec("ripper", "Ripper", "Rip"),
    FieldSpec("supplier", "Supplier", "Sup"),
    FieldSpec("grabber", "Grabber", "Grab"),
    FieldSpec("encoder", "Encoder", "Enc"),
    FieldSpec("release_date", "Releasedatum", "Rdate"),
    FieldSpec("store_date", "Verkaufsstart", "Sdate"),
    FieldSpec("liveset_date", "Aufnahmedatum", "Ldate"),
    FieldSpec("url", "URL", "Url"),
    FieldSpec("url2", "Zweite URL", "2ndUrl"),
    FieldSpec("release_counter", "Zähler", "Rc"),
    FieldSpec("released_with", "Erschienen mit", "RelWith"),
    FieldSpec("dirname", "Verzeichnisname", "Fullrelease"),
    FieldSpec("notes", "Notizen", "Rnotes", kind="lines"),
    FieldSpec("group_news", "Gruppennachrichten", "Gnews", kind="lines"),
)

BY_NAME: dict[str, FieldSpec] = {f.name: f for f in FIELDS}

#: Felder, die der Tag-Schreiber unabhängig von jeder Vorlage braucht.
TAG_FIELDS: frozenset[str] = frozenset({"artist", "album", "year", "genre"})


#: Namens-Tags ohne eigenes Feld, die von einem Feld gespeist werden.
PATTERN_ALIASES = {"Fmt": "Format"}


def _pattern_tags(pattern: str) -> set[str]:
    tags = {tag.lstrip("#").rstrip("#") for tag in compile_pattern(pattern).tags()}
    return {PATTERN_ALIASES.get(tag, tag) for tag in tags}


def usage(template: Optional[Template] = None,
          naming: Optional[NamingProfile] = None,
          tags: Optional[TagProfile] = None) -> dict[str, set[Consumer]]:
    """Welche Abnehmer jedes Feld verwenden."""
    in_template = template.tag_names() if template is not None else set()
    in_dir = _pattern_tags(naming.dir_pattern) if naming else set()
    in_file = _pattern_tags(naming.file_pattern) if naming else set()

    tag_fields = set(TAG_FIELDS)
    if tags is not None:
        if tags.catalog_in_album:
            tag_fields.add("catalog_no")
        if tags.label_in_comment:
            tag_fields.add("company")
        # tags.album_addition ist ein fester Text im Profil, nicht das
        # Releasefeld gleichen Namens - letzteres geht nur in die .nfo.

    out: dict[str, set[Consumer]] = {}
    for spec in FIELDS:
        used: set[Consumer] = set()
        if spec.tag and spec.tag in in_template:
            used.add(Consumer.NFO)
        if spec.name_tag and spec.name_tag in in_dir:
            used.add(Consumer.DIRNAME)
        if spec.name_tag and spec.name_tag in in_file:
            used.add(Consumer.FILENAME)
        if spec.name in tag_fields:
            used.add(Consumer.TAGS)
        out[spec.name] = used
    return out


def widths(template: Optional[Template]) -> dict[str, int]:
    """Verfügbare Zeichenbreite je Feld, aus der Vorlage.

    Das ist die eigentliche Leistung des Originals: Ein Wert, der breiter ist
    als sein Feld, wird im NFO abgeschnitten - und zwar stillschweigend. Wer
    die Breite sieht, merkt es vorher.
    """
    if template is None:
        return {}
    by_tag = template.field_widths()
    return {spec.name: by_tag[spec.tag]
            for spec in FIELDS if spec.tag and spec.tag in by_tag}


@dataclass
class FieldView:
    """Ein Feld, wie die Oberfläche es anzeigt."""

    spec: FieldSpec
    value: str
    used_by: set[Consumer]
    width: Optional[int] = None
    origin_label: str = ""

    @property
    def overflows(self) -> bool:
        return self.width is not None and len(self.value) > self.width

    @property
    def truncated(self) -> str:
        """Wie der Wert im NFO ankäme."""
        return self.value if self.width is None else self.value[:self.width]

    @property
    def unused(self) -> bool:
        return not self.used_by


def build_views(release, template=None, naming=None, tags=None,
                origins=None) -> list[FieldView]:
    """Baut die Feldliste für eine Oberfläche."""
    used = usage(template, naming, tags)
    sizes = widths(template)

    views: list[FieldView] = []
    for spec in FIELDS:
        raw = getattr(release, spec.name, "")
        if isinstance(raw, list):
            value = "\n".join(str(item) for item in raw)
        else:
            value = "" if raw is None else str(raw)
        origin = origins.get(spec.name) if origins is not None else None
        # "unbekannt" an einem leeren Feld ist keine Information, sondern
        # Rauschen - dann lieber gar nichts anzeigen.
        label = (origin.label if origin is not None
                 and origin is not Origin.UNKNOWN else "")
        views.append(FieldView(
            spec=spec,
            value=value,
            used_by=used.get(spec.name, set()),
            width=sizes.get(spec.name),
            origin_label=label,
        ))
    return views


def group_views(views: list[FieldView]) -> list[tuple[str, list[FieldView]]]:
    """Gruppiert nach Abnehmer; Mehrfachnennung ist möglich.

    Die Gruppe "nicht verwendet" steht zuletzt - sie wird eingeklappt
    angezeigt, nicht deaktiviert. Ein Feld darin kann jederzeit gebraucht
    werden, sobald jemand die Vorlage oder das Namensmuster ändert.
    """
    groups: list[tuple[str, list[FieldView]]] = []
    for consumer in Consumer:
        members = [v for v in views if consumer in v.used_by]
        if members:
            groups.append((consumer.label, members))
    unused = [v for v in views if v.unused]
    if unused:
        groups.append(("nicht verwendet", unused))
    return groups


def overflow_warnings(views: list[FieldView]) -> list[str]:
    """Felder, deren Inhalt im NFO abgeschnitten würde."""
    return [
        f"{v.spec.label}: {len(v.value)} Zeichen, Platz für {v.width} "
        f"- abgeschnitten zu {v.truncated!r}"
        for v in views if v.overflows
    ]
