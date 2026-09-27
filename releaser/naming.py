"""Naming-Schema.

Das Original löste das Umbenennen über rund vierzig Checkboxen. Dahinter
stecken aber nur zwei Konzepte:

1. **Ein Muster** — wie sich der Name zusammensetzt. Hier dieselbe Tag-Sprache
   wie in den SKL-Templates, nur ohne Spaltenlogik::

       "#Artist-#Album-#Source-#Year-#Grp"   ->  Artist-Album-CDDA-2026-GRP
       "#N-#Artist-#Trk"                     ->  01-artist-titel

   Ein Vokabular für NFO *und* Dateinamen statt zweier paralleler Systeme.

2. **Eine Regelkette** — was danach mit dem Text passiert. Jede Regel ist eine
   reine Funktion ``str -> str`` mit einem Namen. Die Konfiguration ist eine
   lesbare Liste statt eines Dutzends Boolescher Flags::

       pipeline = ("inch", "transliterate", "forbidden", "spaces", "collapse")

Der Rest sind Geltungsbereiche: Verzeichnis, Dateiname, Tag und NFO haben je
eine eigene Schreibweise, teilen sich aber die Kette.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace as dc_replace
from functools import lru_cache
from uuid import uuid4
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Sequence

from .model import Disc, Release, Track
from .tags import LITERALS, LITERAL_ORDER, Context, Settings
from .text import CharCase, to_ascii


class Scope(Enum):
    DIRECTORY = "directory"
    FILENAME = "filename"
    TAG = "tag"
    NFO = "nfo"


# ================================================================= Musterteil

#: Zusätzliche Tags, die nur beim Benennen sinnvoll sind. Sie landen bewusst
#: nicht in der globalen Registry, damit ``inspect`` weiter nur SKL-Tags zeigt.
#: Formatkennung im Verzeichnisnamen. MP3 ist der stillschweigende Normalfall
#: und bekommt keine - so hielt es auch die Szene. Alles, was hier nicht steht,
#: bleibt ebenfalls unbenannt.
FORMAT_MARKERS: dict[str, str] = {
    "FLAC": "FLAC",
    "AAC": "AAC",
}


def format_marker(release: Release) -> str:
    """Kennung wie ``FLAC`` oder ``ATMOS``, sonst leer.

    Atmos sticht das Containerformat: eine EC-3-Datei mit JOC ist fuer den
    Hoerer ein Atmos-Release, nicht ein EAC3-Release.
    """
    if "atmos" in (release.released_with or "").lower():
        return "ATMOS"
    return FORMAT_MARKERS.get((release.audio_format or "").upper(), "")


EXTRA_RESOLVERS: dict[str, Callable[["NameContext"], str]] = {
    "#Cd": lambda c: str(c.disc.number) if c.disc else "",
    "#Cd2": lambda c: f"{c.disc.number:02d}" if c.disc else "",
    "#Grp": lambda c: c.group,
    "#Ext": lambda c: c.extension.lstrip("."),
    "#Fmt": lambda c: format_marker(c.release),
    # In Namen gilt die eigene Quelle des Verzeichnisnamens, nicht die der
    # .nfo - siehe ``Release.dir_source``. Sonst fuellte das eine Feld das
    # andere aus.
    "#Source": lambda c: c.release.dir_source,
}


@dataclass
class NameContext:
    """Auswertungskontext eines Musters."""

    release: Release
    settings: Settings = field(default_factory=Settings)
    track: Optional[Track] = None
    disc: Optional[Disc] = None
    group: str = ""
    extension: str = ""

    def as_tag_context(self) -> Context:
        return Context(release=self.release, settings=self.settings,
                       track=self.track, disc=self.disc)


@lru_cache(maxsize=64)
def compile_pattern(source: str) -> "Pattern":
    """Muster werden pro Track ausgewertet - einmal zerlegen reicht."""
    return Pattern(source)


class Pattern:
    """Ein Namensmuster. Substituiert Tags ohne Spaltenausrichtung."""

    def __init__(self, source: str):
        self.source = source
        self._parts = self._split(source)

    @staticmethod
    def _split(source: str) -> list[tuple[bool, str]]:
        """Zerlegt in (ist_tag, text). Longest-Match wie im SKL-Parser."""
        order = sorted(set(LITERAL_ORDER) | set(EXTRA_RESOLVERS), key=len, reverse=True)
        parts: list[tuple[bool, str]] = []
        buffer = ""
        i = 0
        while i < len(source):
            for lit in order:
                if source.startswith(lit, i):
                    if buffer:
                        parts.append((False, buffer))
                        buffer = ""
                    parts.append((True, lit))
                    i += len(lit)
                    break
            else:
                buffer += source[i]
                i += 1
        if buffer:
            parts.append((False, buffer))
        return parts

    def tags(self) -> list[str]:
        return [text for is_tag, text in self._parts if is_tag]

    def render(self, ctx: NameContext) -> str:
        out: list[str] = []
        tag_ctx = ctx.as_tag_context()
        for is_tag, text in self._parts:
            if not is_tag:
                out.append(text)
            elif text in EXTRA_RESOLVERS:
                out.append(EXTRA_RESOLVERS[text](ctx) or "")
            else:
                out.append(LITERALS[text].resolve(tag_ctx) or "")
        return "".join(out)


# ================================================================ Regelkette

#: Zeichen, die auf gängigen Dateisystemen nicht in Namen dürfen.
FORBIDDEN = set('<>:"/\\|?*') | {chr(c) for c in range(32)}

_INCH = re.compile(r'(?<=\d)\s*"')
_MULTI_SEP = re.compile(r"([_\-.])\1+")
_SEP_RUN = re.compile(r"[_\-.\s]{2,}")


def rule_inch(value: str) -> str:
    """``12"`` wird zu ``12INCH`` - Anführungszeichen sind im Dateinamen tabu."""
    value = _INCH.sub("INCH", value)
    return value.replace('"', "")


def rule_transliterate(value: str) -> str:
    """Umlaute und Akzente nach ASCII."""
    return to_ascii(value)


#: Zeichen, die spurlos verschwinden statt zu einem Trenner zu werden.
#: "Don't" soll "dont" ergeben, nicht "don_t".
_DROPPED = "'’ʼ`´"
_NOT_ALLOWED = re.compile(r"[^0-9A-Za-z\s_-]")


def rule_alnum(value: str) -> str:
    """Laesst nur Buchstaben, Ziffern und Trennzeichen stehen.

    Alles andere wird zu einem Leerzeichen - die nachfolgenden Regeln machen
    daraus das eingestellte Trennzeichen. Nur Apostrophe verschwinden ganz,
    weil "Don't" sonst zu "don_t" wuerde.

    Die Regel gilt ausschliesslich fuer Datei- und Verzeichnisnamen. Was in
    die Tags oder ins NFO geschrieben wird, bleibt unveraendert - dort sind
    Kommas und Klammern erwuenscht.

    Laeuft nach ``transliterate``, damit aus "ä" erst "ae" wird und nicht
    nichts.
    """
    for char in _DROPPED:
        value = value.replace(char, "")
    return _NOT_ALLOWED.sub(" ", value)


def rule_forbidden(value: str) -> str:
    """Entfernt Zeichen, die im Dateisystem nicht erlaubt sind."""
    return "".join(c for c in value if c not in FORBIDDEN)


def rule_spaces(value: str, space_char: str = "_") -> str:
    return re.sub(r"\s+", space_char, value.strip())


def rule_collapse(value: str) -> str:
    """Fasst wiederholte Trennzeichen zusammen.

    Das Original nannte das "cuts all the letters that is dupe in the
    filenames". Was genau gemeint war, geht aus der Doku nicht hervor; hier
    ist es als Zusammenfassen aufeinanderfolgender Trennzeichen umgesetzt
    (``a__-_b`` -> ``a_b``).
    """
    value = _MULTI_SEP.sub(r"\1", value)

    def merge(match: re.Match) -> str:
        # Enthaelt die Folge einen Bindestrich, gewinnt er: er trennt im
        # Muster die Bestandteile. Sonst frisst ein Sonderzeichen direkt
        # davor den Strich - aus "…mix)-cdda…" wuerde "…mix_cdda…".
        return "-" if "-" in match.group(0) else "_"

    return _SEP_RUN.sub(merge, value)


def rule_trim(value: str) -> str:
    return value.strip(" ._-")


def rule_strip_diacritics(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


#: Name -> Funktion. Die Konfiguration referenziert nur Namen.
RULES: dict[str, Callable[..., str]] = {
    "inch": rule_inch,
    "transliterate": rule_transliterate,
    "alnum": rule_alnum,
    "strip_diacritics": rule_strip_diacritics,
    "forbidden": rule_forbidden,
    "spaces": rule_spaces,
    "collapse": rule_collapse,
    "trim": rule_trim,
}

DEFAULT_PIPELINE: tuple[str, ...] = (
    "inch", "transliterate", "alnum", "forbidden", "spaces", "collapse", "trim",
)


# ================================================================== Profil


@dataclass
class NamingProfile:
    """Vollständige Benennungsregeln eines Releases."""

    dir_pattern: str = "#Artist-#Album-#Source-#Fmt-#Year-#Grp"
    disc_dir_pattern: str = "CD#Cd"
    file_pattern: str = "#N-#Artist-#Trk"
    group: str = ""

    pipeline: tuple[str, ...] = DEFAULT_PIPELINE
    space_char: str = "_"

    charcase: dict[Scope, CharCase] = field(default_factory=lambda: {
        Scope.DIRECTORY: CharCase.LOWER,
        Scope.FILENAME: CharCase.LOWER,
        Scope.TAG: CharCase.UNCHANGED,
        Scope.NFO: CharCase.UNCHANGED,
    })

    #: Längengrenzen. Das Original warnte, statt abzuschneiden.
    max_dir_length: int = 100
    max_file_length: int = 120

    #: Präfix für Dateien, die vorn einsortieren sollen. Voreingestellt gilt
    #: es für alle Begleitdateien einschließlich .sfv und .m3u; wer es wie
    #: das Original nur für .nfo und Bilder will, nimmt die beiden aus
    #: ``prefixed_suffixes`` heraus (Konfiguration: ``prefix_all = false``).
    companion_prefix: str = "00-"
    prefixed_suffixes: frozenset[str] = frozenset({
        ".nfo", ".sfv", ".m3u", ".m3u8", ".jpg", ".jpeg", ".png", ".pdf"})
    #: Muster für den Namen der Begleitdateien. ``#Fullrelease`` heißt: so
    #: heißen wie das Verzeichnis. Leer bedeutet: ``dir_pattern`` verwenden.
    companion_pattern: str = "#Fullrelease"

    #: "intro" bekommt den Artist vorangestellt, um Namensdopplungen zu
    #: vermeiden (Option ``RenameIntroFiles`` des Originals).
    rename_intro: bool = True
    intro_names: frozenset[str] = frozenset({"intro", "outro"})

    def sanitize(self, value: str, scope: Scope,
                 charcase: Optional[CharCase] = None) -> str:
        """Regelkette anwenden, danach die Schreibweise des Geltungsbereichs.

        ``charcase`` überschreibt die Schreibweise - gebraucht für Namen, die
        ihre Schreibweise schon mitbringen und nicht ein zweites Mal umgestellt
        werden dürfen.
        """
        for name in self.pipeline:
            fn = RULES.get(name)
            if fn is None:
                raise KeyError(f"unbekannte Namensregel: {name}")
            value = fn(value, self.space_char) if name == "spaces" else fn(value)
        if charcase is None:
            charcase = self.charcase.get(scope, CharCase.UNCHANGED)
        return charcase.apply(value)


# ================================================================ Planung


@dataclass
class RenameOp:
    src: Path
    dst: Path
    kind: str                      # "file" | "disc" | "root"

    @property
    def changed(self) -> bool:
        return self.src != self.dst


@dataclass
class RenamePlan:
    ops: list[RenameOp] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)
    #: der Rueckgaengig-Eintrag, nachdem der Plan ausgefuehrt wurde
    journal: Optional[object] = None

    @property
    def changes(self) -> list[RenameOp]:
        return [op for op in self.ops if op.changed]

    @property
    def is_safe(self) -> bool:
        return not self.collisions


def track_stem(release: Release, track: Track, disc: Disc,
               profile: NamingProfile) -> str:
    """Dateiname ohne Endung für einen Track.

    Ein von Hand gesetzter Name (``Track.manual_stem``) hat Vorrang vor dem
    Muster - siehe :func:`clean_manual_stem`.
    """
    if track.manual_stem:
        suffix = Path(track.path).suffix if track.path else ""
        manual = clean_manual_stem(track.manual_stem, profile, suffix)
        if manual:
            return manual
    return pattern_stem(release, track, disc, profile)


def clean_manual_stem(value: str, profile: NamingProfile,
                      suffix: str = "") -> str:
    """Ein von Hand eingegebener Dateiname - wörtlich, bis auf das Unmögliche.

    Weder Regelkette noch Schreibweise greifen: genau die haben den Namen ja
    verändert, den jemand von Hand richtigstellt (``collapse`` machte etwa
    aus "Titel I - Teil 2" ein "titel_i-teil_2"). Übrig bleiben nur Regeln,
    ohne die kein gültiger Dateiname entsteht: verbotene Zeichen fallen weg,
    Leerzeichen werden zum eingestellten Trennzeichen, Punkte am Rand
    verschwinden (ein führender Punkt versteckte die Datei), und eine
    mitgetippte Endung wird abgeschnitten statt verdoppelt.
    """
    value = value.strip()
    if suffix and value.lower().endswith(suffix.lower()):
        value = value[:-len(suffix)]
    value = rule_spaces(rule_forbidden(value), profile.space_char)
    return value.strip(". ")


def pattern_stem(release: Release, track: Track, disc: Disc,
                 profile: NamingProfile) -> str:
    """Dateiname ohne Endung, wie ihn das Dateimuster ergibt.

    Der "intro"-Sonderfall des Originals stellt den Artist voran, damit nicht
    mehrere Releases im selben Verzeichnis eine Datei ``intro.mp3`` haben.
    Enthält das Muster ohnehin schon ``#Artist``, wäre das eine Dopplung - dann
    greift die Regel nicht.
    """
    pattern = compile_pattern(profile.file_pattern)
    patched = track
    if (profile.rename_intro
            and track.title.strip().lower() in profile.intro_names
            and release.artist
            and "#Artist" not in pattern.tags()):
        patched = dc_replace(track, title=f"{release.artist}-{track.title}")
    ctx = NameContext(release=release, track=patched, disc=disc,
                      group=profile.group)
    return profile.sanitize(pattern.render(ctx), Scope.FILENAME)


_UNKNOWN_TAG = re.compile(r"#\w+")


def unknown_tags(pattern: str) -> list[str]:
    """Tag-artige Reste, die kein bekannter Tag sind.

    Ein Tippfehler wie ``#Quatsch`` waere sonst unsichtbar: er ueberlebt die
    Regelkette und landet woertlich im Dateinamen.
    """
    # Jeden Textteil fuer sich pruefen. Zusammengefuegt entstanden Tags, die
    # es nicht gibt: bei "x##Albumfoo" wurden "x#" und "foo" zu "#foo".
    return [tag
            for is_tag, text in compile_pattern(pattern)._parts if not is_tag
            for tag in _UNKNOWN_TAG.findall(text)]


def companion_stem(release: Release, profile: NamingProfile) -> str:
    """Namensrumpf für .nfo, .sfv, .m3u und Cover.

    Begleitdateien sind Dateien - sie folgen deshalb der Schreibweise der
    Dateien, nicht der des Verzeichnisses. Ein Ordner darf
    ``Der_Artist-Das_Album-2026-GRP`` heißen und die Dateien darin trotzdem
    durchgehend klein.
    """
    pattern = profile.companion_pattern or profile.dir_pattern
    ctx = NameContext(release=release, group=profile.group)
    return profile.sanitize(compile_pattern(pattern).render(ctx), Scope.FILENAME)


def companion_name(release: Release, suffix: str, profile: NamingProfile,
                   stem: Optional[str] = None) -> str:
    """Vollständiger Dateiname einer Begleitdatei, inklusive Präfixregel."""
    if not suffix.startswith("."):
        suffix = "." + suffix
    base = stem if stem is not None else companion_stem(release, profile)
    prefix = (profile.companion_prefix
              if suffix.lower() in profile.prefixed_suffixes else "")
    return f"{prefix}{base}{suffix.lower()}"


def future_companion_stem(release: Release, profile: NamingProfile) -> str:
    """Namensrumpf der Begleitdateien *nach* einer Umbenennung.

    ``companion_stem`` geht vom aktuellen Verzeichnisnamen aus. Beim Planen
    ist aber noch nichts umbenannt - dann wird der kuenftige gebraucht, und
    zwar in der Schreibweise der Dateien, nicht der des Verzeichnisses.
    """
    pattern = profile.companion_pattern or profile.dir_pattern
    if pattern == "#Fullrelease":
        pattern = profile.dir_pattern
    ctx = NameContext(release=release, group=profile.group)
    return profile.sanitize(compile_pattern(pattern).render(ctx), Scope.FILENAME)


def release_dirname(release: Release, profile: NamingProfile) -> str:
    ctx = NameContext(release=release, group=profile.group)
    return profile.sanitize(compile_pattern(profile.dir_pattern).render(ctx),
                            Scope.DIRECTORY)


def disc_dirname(release: Release, disc: Disc, profile: NamingProfile) -> str:
    ctx = NameContext(release=release, disc=disc, group=profile.group)
    return profile.sanitize(compile_pattern(profile.disc_dir_pattern).render(ctx),
                            Scope.DIRECTORY)


def plan_rename(release: Release, root: str | Path,
                profile: NamingProfile) -> RenamePlan:
    """Berechnet alle Umbenennungen, ohne etwas anzufassen.

    Drei Stufen, jeweils in sich abgeschlossen: erst Dateien innerhalb ihres
    Verzeichnisses, dann CD-Verzeichnisse, zuletzt das Wurzelverzeichnis.
    Dadurch bleiben die Pfade jeder Stufe während der Planung gültig.
    """
    root = Path(root)
    plan = RenamePlan()

    # --- Stufe 1: Dateien --------------------------------------------------
    per_directory: dict[Path, set[str]] = {}
    for disc in release.discs:
        for track in disc.tracks:
            if not track.path:
                plan.warnings.append(
                    f"Track {disc.number}-{track.no} hat keinen Dateipfad, übersprungen")
                continue
            src = Path(track.path)
            stem = track_stem(release, track, disc, profile)
            name = f"{stem}{src.suffix.lower()}"

            if len(name) > profile.max_file_length:
                plan.warnings.append(
                    f"{name} ist {len(name)} Zeichen lang "
                    f"(Grenze {profile.max_file_length})")

            if any(op.src == src for op in plan.ops):
                # Mehrere Tracks aus einem CUE zeigen auf dieselbe Datei.
                continue
            taken = per_directory.setdefault(src.parent, set())
            if name.lower() in taken:
                plan.collisions.append(f"Namenskollision in {src.parent.name}: {name}")
            taken.add(name.lower())
            plan.ops.append(RenameOp(src, src.parent / name, "file"))

    # --- Stufe 1b: Cover --------------------------------------------------
    from .companions import find_covers

    covers = find_covers(root)
    # Der Zielname der Cover folgt dem *neuen* Verzeichnisnamen - aber in der
    # Schreibweise der Dateien, denn ein Cover ist eine Begleitdatei.
    cover_stem = future_companion_stem(release, profile)
    for index, cover in enumerate(covers):
        stem = cover_stem
        if len(covers) > 1:
            stem = f"{stem}-{index + 1:02d}"
        name = companion_name(release, cover.suffix, profile, stem=stem)
        plan.ops.append(RenameOp(cover, cover.parent / name, "file"))

    # --- Stufe 2: CD-Verzeichnisse ----------------------------------------
    if release.multi_disc:
        seen: set[str] = set()
        for disc in release.discs:
            directory = disc.directory(root)
            if directory == root:
                continue
            name = disc_dirname(release, disc, profile)
            if name.lower() in seen:
                plan.collisions.append(f"CD-Verzeichnisse kollidieren: {name}")
            seen.add(name.lower())
            plan.ops.append(RenameOp(directory, directory.parent / name, "disc"))

    # --- Stufe 3: Wurzelverzeichnis ---------------------------------------
    dirname = release_dirname(release, profile)
    if not dirname:
        plan.collisions.append(
            "Der Verzeichnisname waere leer - das Muster liefert nichts")
        _check_existing_targets(plan)
        return plan
    if len(dirname) > profile.max_dir_length:
        plan.warnings.append(
            f"Releasename ist {len(dirname)} Zeichen lang "
            f"(Grenze {profile.max_dir_length})")
    plan.ops.append(RenameOp(root, root.parent / dirname, "root"))

    _check_existing_targets(plan)
    return plan


def _check_existing_targets(plan: RenamePlan) -> None:
    """Meldet Ziele, die bereits auf der Platte liegen.

    Quellen des Plans zaehlen nicht: die weichen im Lauf der Ausfuehrung
    ohnehin. Alles andere waere ein Ueberschreiben fremder Daten.
    """
    sources = {op.src for op in plan.ops}
    for op in plan.ops:
        if not op.changed or op.dst in sources:
            continue
        if op.dst.exists() and not _same_entry(op.src, op.dst):
            plan.collisions.append(f"Ziel existiert bereits: {op.dst}")


def _same_entry(src: Path, dst: Path) -> bool:
    """Ist ``dst`` nur ein anderer Name fuer ``src``?

    Auf Dateisystemen ohne Unterscheidung von Gross- und Kleinschreibung
    (FAT/exFAT-Sticks, SMB-Freigaben) "existiert" ``track.mp3`` bereits,
    wenn ``Track.mp3`` umbenannt werden soll - es ist aber dieselbe Datei.
    Das ist keine Kollision; ``apply_plan`` benennt ueber einen
    Zwischennamen um und kommt damit zurecht.
    """
    try:
        return src.exists() and src.samefile(dst)
    except OSError:
        return False


# =============================================================== Ausführung


def apply_plan(plan: RenamePlan, release: Optional[Release] = None,
               force: bool = False) -> list[RenameOp]:
    """Führt den Plan aus und aktualisiert optional die Pfade im Release.

    Umbenennungen laufen zweistufig über temporäre Namen. Das ist nötig, weil
    Zielnamen mit noch vorhandenen Quellnamen kollidieren können - etwa beim
    Tausch zweier Tracknummern oder bei einer reinen Schreibweisenänderung auf
    einem Dateisystem, das Groß- und Kleinschreibung nicht unterscheidet.
    """
    if plan.collisions and not force:
        raise ValueError("Plan hat Kollisionen: " + "; ".join(plan.collisions))

    done: list[RenameOp] = []
    stages: list[dict[Path, Path]] = []
    new_root: Optional[Path] = None
    token = uuid4().hex[:8]
    #: [aktueller Pfad, Ursprungspfad] je verschobenem Eintrag - fuer das Rollback
    moves: list[list[Path]] = []

    try:
        for kind in ("file", "disc", "root"):
            stage = [op for op in plan.ops if op.kind == kind and op.changed]
            if not stage:
                continue
            stage = [RenameOp(_remap(op.src, stages), _remap(op.dst, stages), op.kind)
                     for op in stage]
            stage = [op for op in stage if op.changed]
            if not stage:
                continue

            for index, op in enumerate(stage):
                tmp = op.src.parent / f".mp3releaser-{token}-{index}"
                op.src.rename(tmp)
                moves.append([tmp, op.src])
            for entry, op in zip(moves[-len(stage):], stage):
                op.dst.parent.mkdir(parents=True, exist_ok=True)
                entry[0].rename(op.dst)
                entry[0] = op.dst

            mapping: dict[Path, Path] = {}
            for op in stage:
                mapping[op.src] = op.dst
                done.append(op)
                if op.kind == "root":
                    new_root = op.dst
            stages.append(mapping)
    except OSError:
        _rollback(moves)
        raise

    if release is not None:
        _update_release_paths(release, stages, new_root)
    return done


def _rollback(moves: list[list[Path]]) -> None:
    """Macht alle bereits ausgefuehrten Umbenennungen rueckgaengig.

    Ohne das bliebe bei einem Fehler ein halb umbenanntes Release zurueck -
    inklusive temporaerer Namen, die den naechsten Versuch blockieren.
    """
    for current, original in reversed(moves):
        if current != original and current.exists():
            try:
                original.parent.mkdir(parents=True, exist_ok=True)
                current.rename(original)
            except OSError:
                pass


def _remap(path: Path, stages: Sequence[dict[Path, Path]]) -> Path:
    """Zieht ausgeführte Umbenennungen nach.

    Die Stufen wirken nacheinander - eine Datei wird erst selbst umbenannt,
    dann ihr CD-Verzeichnis, zuletzt das Wurzelverzeichnis. *Innerhalb* einer
    Stufe darf dagegen nur ein Treffer greifen: bei einem Zyklus (zwei Dateien
    tauschen ihre Namen) würde ein zweiter Treffer die Datei wieder auf den
    Ausgangsnamen zurückdrehen.
    """
    for mapping in stages:
        for src, dst in mapping.items():
            if path == src:
                path = dst
                break
            if path.is_relative_to(src):
                path = dst / path.relative_to(src)
                break
    return path


def _update_release_paths(release: Release, stages: Sequence[dict[Path, Path]],
                          new_root: Optional[Path]) -> None:
    for track in release.tracks:
        if track.path:
            track.path = str(_remap(Path(track.path), stages))
    if new_root is not None:
        release.dirname = new_root.name


#: Das Original warnte, wenn .nfo/.m3u/.sfv zu lang wurden - lange Namen
#: ueberleben manche Uebertragungswege nicht.
MAX_COMPANION_NAME = 64


def check_filename_lengths(paths: Sequence[Path],
                           limit: int = MAX_COMPANION_NAME) -> list[str]:
    """Meldet erzeugte Dateinamen, die eine Laengengrenze reissen."""
    return [f"{p.name} ist {len(p.name)} Zeichen lang (Grenze {limit})"
            for p in paths if len(p.name) > limit]


def format_plan(plan: RenamePlan, root: Path) -> str:
    """Menschenlesbare Vorschau."""
    lines: list[str] = []
    for op in plan.changes:
        try:
            src = op.src.relative_to(root.parent)
            dst = op.dst.relative_to(root.parent)
        except ValueError:
            src, dst = op.src, op.dst
        lines.append(f"  {src}  ->  {dst}")
    if not lines:
        lines.append("  (nichts zu tun)")
    for warning in plan.warnings:
        lines.append(f"  ! {warning}")
    for collision in plan.collisions:
        lines.append(f"  x {collision}")
    return "\n".join(lines)
