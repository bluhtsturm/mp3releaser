"""Dienstschicht.

Hier liegen die Abläufe, die alle Oberflächen brauchen: scannen, taggen,
umbenennen, Begleitdateien erzeugen, prüfen. Die Funktionen geben
Ergebnisobjekte zurück und schreiben **nichts** auf die Konsole - Ausgabe ist
Sache der jeweiligen Oberfläche.

Das ist die Voraussetzung dafür, dass CLI, Desktop-Anwendung und
Weboberfläche wirklich dasselbe Programm sind und nicht drei Nachbauten mit
je eigenen Abweichungen. Was hier nicht steht, kann in einer Oberfläche
anders funktionieren als in der anderen - und genau das soll nicht passieren.

Alles, was Daten verändert, läuft weiterhin zweistufig: erst ein Plan, den
man ansehen kann, dann die Ausführung.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .model import Release
from .provenance import OriginMap
from .naming import (
    NamingProfile,
    RenamePlan,
    apply_plan,
    check_filename_lengths,
    companion_name,
    companion_stem,
    plan_rename,
)
from .playlist import write_release_m3us
from .sfv import VerifyResult, verify_sfv, write_release_sfvs
from .skl import Template
from .tags import Settings
from .tagwriter import TagPlan, TagProfile, apply_tags, plan_tags
from .text import write_nfo


#: Voreinstellung der Anwendungen: Ordner kapitalisiert, Dateien klein - die
#: in der Szene uebliche Schreibweise. Die Bibliothek selbst bleibt bei
#: "klein fuer beides", damit eingebettete Aufrufe sich nicht unbemerkt
#: aendern; wer die Anwendung startet, bekommt diese Voreinstellung.
PRESET_CASE: dict[str, str] = {"directory": "capitalize", "file": "lower"}


def naming_from_config(config=None, group: Optional[str] = None,
                       **overrides) -> NamingProfile:
    """Baut das Namensprofil aus der Konfiguration.

    Eine Stelle fuer alle Oberflaechen - sonst zeigt die eine Fassung andere
    Namen an als die andere, obwohl beide denselben Kern benutzen.
    """
    from dataclasses import replace

    from .naming import Scope
    from .text import CharCase

    section = config.section("naming") if config is not None else {}
    base = NamingProfile()
    profile = replace(
        base,
        dir_pattern=section.get("dir_pattern", base.dir_pattern),
        file_pattern=section.get("file_pattern", base.file_pattern),
        group=group if group is not None else section.get("group", ""),
        space_char=section.get("space", base.space_char),
        companion_prefix=section.get("companion_prefix", base.companion_prefix),
        charcase={
            Scope.DIRECTORY: CharCase(
                section.get("case_dir", PRESET_CASE["directory"])),
            Scope.FILENAME: CharCase(
                section.get("case_file", PRESET_CASE["file"])),
            Scope.TAG: CharCase.UNCHANGED,
            Scope.NFO: CharCase.UNCHANGED,
        },
        **overrides,
    )
    if not section.get("prefix_all", True):
        profile = replace(profile, prefixed_suffixes=frozenset(
            {".nfo", ".jpg", ".jpeg", ".png", ".pdf"}))
    return profile


#: Name der mitgelieferten Standardvorlage
STANDARD_TEMPLATE = "standard.skl"


def bundled_template() -> Optional[Path]:
    """Die mitgelieferte Standardvorlage, sofern auffindbar.

    Gesucht wird dort, wo die drei Auslieferungsformen sie ablegen: im
    AppImage unter ``$APPDIR/usr/share/mp3releaser``, im Container und im
    Quelltext unter ``templates/``. Ohne Fund gibt es keine Voreinstellung -
    dann muss eine Vorlage gewaehlt werden, wie vorher auch.
    """
    import os

    candidates = []
    appdir = os.environ.get("APPDIR")
    if appdir:
        candidates.append(Path(appdir) / "usr" / "share" / "mp3releaser"
                          / STANDARD_TEMPLATE)
    candidates.append(Path(__file__).resolve().parents[1] / "templates"
                      / STANDARD_TEMPLATE)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@dataclass
class BuildOptions:
    """Was beim Erzeugen der Begleitdateien entsteht und wie."""

    template: Optional[Path] = None
    nfo: bool = True
    sfv: bool = True
    m3u: bool = True
    clean: bool = False
    audio_crc: bool = False
    sfv_comment: str = ""
    sfv_include: tuple[str, ...] = ()
    use_catalog_no: bool = False
    codepage: str = "cp437"
    #: Rueckwaerts-Schraegstriche in der M3U wie beim Original
    m3u_windows_paths: bool = False


@dataclass
class ScanOutcome:
    release: Release
    root: Path
    warnings: list[str] = field(default_factory=list)
    #: Herkunft der einzelnen Werte - Oberflächen zeigen sie am Feld an
    origins: OriginMap = field(default_factory=OriginMap)


@dataclass
class BuildOutcome:
    root: Path
    created: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Kollisionen aus einem vorgeschalteten Umbenennen
    collisions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.collisions


# ---------------------------------------------------------------- Einlesen


def scan(directory: str | Path, strict: bool = False) -> ScanOutcome:
    """Verzeichnis einlesen. Der Audio-Layer wird erst hier geladen."""
    from .audio import scan_directory

    root = Path(directory)
    result = scan_directory(root, strict=strict)
    return ScanOutcome(release=result.release, root=root,
                       warnings=list(result.warnings), origins=result.origins)


# ------------------------------------------------------------------ Tags


def preview_tags(release: Release, profile: TagProfile) -> TagPlan:
    return plan_tags(release, profile)


def write_tags(release: Release, profile: TagProfile) -> list[Path]:
    """Schreibt die Tags. Das Rueckgaengig-Protokoll fuehrt ``apply_tags``."""
    return apply_tags(plan_tags(release, profile), profile)


# ------------------------------------------------------------ Umbenennen


def preview_rename(release: Release, root: str | Path,
                   profile: NamingProfile) -> RenamePlan:
    return plan_rename(release, Path(root), profile)


def perform_rename(release: Release, root: str | Path,
                   profile: NamingProfile) -> tuple[RenamePlan, Path]:
    """Führt die Umbenennung aus und gibt den neuen Wurzelpfad zurück.

    Bei Kollisionen wird nichts angefasst; das erkennt der Aufrufer an
    ``plan.is_safe``.
    """
    root = Path(root)
    plan = plan_rename(release, root, profile)
    if not plan.is_safe:
        return plan, root

    done = apply_plan(plan, release)
    # Umbenennen laesst sich nicht aus den Dateien zurueckrechnen - hinterher
    # weiss niemand mehr, wie es vorher hiess. Deshalb ein Protokoll.
    from . import undo as undo_journal

    plan.journal = undo_journal.record(((op.src, op.dst) for op in done),
                                       release.dirname)
    return plan, current_root(release, root)


def current_root(release: Release, fallback: Path) -> Path:
    """Wurzelverzeichnis des Releases nach einer Umbenennung."""
    if not release.tracks or not release.tracks[0].path:
        return fallback
    path = Path(release.tracks[0].path).parent
    while path.name != release.dirname and path != path.parent:
        path = path.parent
    return path if path != path.parent else fallback


# -------------------------------------------------------- Begleitdateien


def build(release: Release, root: str | Path, options: BuildOptions,
          naming: Optional[NamingProfile] = None) -> BuildOutcome:
    """Erzeugt .nfo, .sfv und .m3u für ein bereits eingelesenes Release."""
    root = Path(root)
    # Ohne ausdrueckliches Profil die gemeinsame Voreinstellung nehmen, nicht
    # die Bibliotheksvorgabe - sonst benennt ein Aufruf ohne Profil anders als
    # jede Oberflaeche.
    naming = naming or naming_from_config()
    outcome = BuildOutcome(root=root)

    if options.clean:
        from .companions import remove_companions

        outcome.removed = remove_companions(root)

    if options.nfo:
        if options.template is None:
            raise ValueError("für die .nfo wird eine Vorlage gebraucht")
        template = Template.from_file(options.template, codepage=options.codepage)
        target = root / companion_name(release, ".nfo", naming)
        write_nfo(target, template.render(release, Settings()),
                  codepage=options.codepage)
        outcome.created.append(target)

    # Ein Rumpf fuer alle Begleitdateien - sonst folgt die .nfo dem
    # eingestellten Muster und .sfv/.m3u heissen anders. Das Praefix haengt
    # an der Endung, deshalb je Endung einmal fragen: .sfv und .m3u bilden
    # ihren Namen selbst und kennen die Praefixregel nicht.
    stem = companion_stem(release, naming)

    def stem_for(suffix: str) -> str:
        return companion_name(release, suffix, naming,
                              stem=stem)[:-len(suffix)]

    if options.sfv:
        outcome.created += write_release_sfvs(
            release, root,
            comments=[options.sfv_comment] if options.sfv_comment else [],
            extra_extensions=options.sfv_include,
            use_catalog_no=options.use_catalog_no,
            with_audio_crc=options.audio_crc,
            stem=stem_for(".sfv"),
        )

    if options.m3u:
        outcome.created += write_release_m3us(
            release, root, use_catalog_no=options.use_catalog_no,
            stem=stem_for(".m3u"), windows_paths=options.m3u_windows_paths)

    outcome.warnings += check_filename_lengths(outcome.created)
    return outcome


def process(directory: str | Path, options: BuildOptions,
            naming: Optional[NamingProfile] = None,
            tags: Optional[TagProfile] = None,
            do_tag: bool = False, do_rename: bool = False,
            strict: bool = False) -> BuildOutcome:
    """Der komplette Ablauf in einem Aufruf.

    Die Reihenfolge ist nicht beliebig: erst taggen, dann umbenennen, dann
    die Begleitdateien. Entstünde das SFV vor dem Tag-Lauf, wären sämtliche
    Prüfsummen sofort falsch.
    """
    scanned = scan(directory, strict=strict)
    release, root = scanned.release, scanned.root
    outcome = BuildOutcome(root=root, warnings=list(scanned.warnings))

    if do_tag:
        profile = tags or TagProfile()
        plan = plan_tags(release, profile)
        outcome.warnings += plan.warnings
        apply_tags(plan, profile)

    if do_rename:
        plan, root = perform_rename(release, root,
                                    naming or naming_from_config())
        outcome.warnings += plan.warnings
        if not plan.is_safe:
            outcome.collisions = list(plan.collisions)
            return outcome

    built = build(release, root, options, naming)
    outcome.root = built.root
    outcome.created = built.created
    outcome.removed = built.removed
    outcome.warnings += built.warnings
    return outcome


# ---------------------------------------------------------------- Prüfen


def verify(sfv_path: str | Path,
           directory: Optional[str | Path] = None) -> VerifyResult:
    return verify_sfv(sfv_path, Path(directory) if directory else None)


def check_dupe(name: str, against: str | Path, threshold: float = 0.88):
    from .dupecheck import load, normalise

    index = load(against)
    return index, normalise(name), index.check(name, threshold=threshold)


def companion_names(release: Release, naming: NamingProfile,
                    suffixes: Iterable[str] = (".nfo", ".sfv", ".m3u")) -> dict[str, str]:
    """Wie die Begleitdateien heißen würden - für Vorschauen in Oberflächen."""
    return {suffix: companion_name(release, suffix, naming) for suffix in suffixes}
