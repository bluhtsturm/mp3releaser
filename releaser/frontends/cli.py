"""Kommandozeile fuer den SKL-Renderer.

    python -m releaser scan /pfad/zur/release -o release.json
    python -m releaser render templates/example.skl release.json -o out.nfo
    python -m releaser nfo /pfad/zur/release templates/example.skl -o out.nfo
    python -m releaser rename /pfad/zur/release --group GRP          # Vorschau
    python -m releaser rename /pfad/zur/release --group GRP --apply
    python -m releaser tag /pfad/zur/release --case capitalize          # Vorschau
    python -m releaser tag /pfad/zur/release --case capitalize --apply
    python -m releaser build /pfad/zur/release templates/example.skl
    python -m releaser verify /pfad/zur/release/xyz.sfv
    python -m releaser inspect templates/example.skl

``inspect`` zeigt, welche Tags ein Template nutzt und wie breit die Felder
sind - genau die Information, mit der die spaetere GUI ihre Eingabefelder
dimensioniert und nicht benutzte Felder ausgraut.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path

from ..model import Disc, Release, Track
from ..skl import Template
from ..tags import REGISTRY, Settings
from ..text import CharCase, write_nfo


def _check_fields(cls, data: dict, what: str) -> None:
    """Unbekannte Schluessel melden, statt mit einem TypeError abzubrechen.

    Fuer die Release selbst gab es das schon; ein Tippfehler in einem Track
    oder in den Einstellungen endete dagegen in einem Traceback.
    """
    unknown = set(data) - set(cls.__dataclass_fields__)
    if unknown:
        raise SystemExit(f"unbekannte Felder in {what}: {sorted(unknown)}")


def release_from_dict(data: dict) -> Release:
    discs_data = data.pop("discs", [])
    tracks_data = data.pop("tracks", [])
    _check_fields(Release, data, "der Releasebeschreibung")

    def track(values: dict) -> Track:
        _check_fields(Track, values, "einem Track")
        return Track(**values)

    discs: list[Disc] = []
    if discs_data:
        for d in discs_data:
            tracks = [track(t) for t in d.pop("tracks", [])]
            _check_fields(Disc, d, "einer CD")
            discs.append(Disc(tracks=tracks, **d))
    elif tracks_data:
        discs = [Disc(1, tracks=[track(t) for t in tracks_data])]

    return Release(discs=discs, **data)


def settings_from_dict(data: dict) -> Settings:
    _check_fields(Settings, data, "den Einstellungen")
    if "nfo_charcase" in data:
        data["nfo_charcase"] = CharCase(data["nfo_charcase"])
    return Settings(**data)


def release_to_dict(release: Release) -> dict:
    """Serialisiert eine Release so, dass ``render`` sie wieder einlesen kann."""
    def drop(value) -> bool:
        return value is None or value == "" or value == []

    def clean(obj):
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items() if not drop(v)}
        if isinstance(obj, list):
            return [clean(v) for v in obj]
        if isinstance(obj, float):
            return round(obj, 3)
        return obj

    return clean(dataclasses.asdict(release))


def _print_warnings(warnings: list[str]) -> None:
    for w in warnings:
        print(f"  ! {w}", file=sys.stderr)


def _release_date_format(args: argparse.Namespace) -> str:
    """Format des vorbelegten Releasedatums aus ``[build]`` - leer heisst aus.

    Alle Kommandos lesen dasselbe, damit ``nfo``, ``build`` und die
    Oberflaechen dieselbe .nfo erzeugen.
    """
    from ..service import RELEASE_DATE_FORMAT

    config = getattr(args, "_config", None)
    if config is None:
        return RELEASE_DATE_FORMAT
    return str(config.get("build", "release_date_format", RELEASE_DATE_FORMAT))


def cmd_scan(args: argparse.Namespace) -> int:
    from ..audio import scan_directory
    from ..service import fill_release_date

    result = scan_directory(args.directory, strict=args.strict)
    fill_release_date(result.release, result.origins, _release_date_format(args))
    if result.warnings:
        print(f"{len(result.warnings)} Hinweis(e):", file=sys.stderr)
        _print_warnings(result.warnings)

    payload = release_to_dict(result.release)
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"geschrieben: {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text + "\n")
    return 0


def cmd_nfo(args: argparse.Namespace) -> int:
    from ..audio import scan_directory
    from ..service import fill_release_date

    result = scan_directory(args.directory, strict=args.strict)
    fill_release_date(result.release, result.origins, _release_date_format(args))
    if result.warnings:
        _print_warnings(result.warnings)

    tpl = Template.from_file(args.template, codepage=args.codepage)
    text = tpl.render(result.release, Settings())
    if args.out:
        write_nfo(args.out, text, codepage=args.codepage)
        print(f"geschrieben: {args.out} ({args.codepage})", file=sys.stderr)
    else:
        sys.stdout.write(text + "\n")
    return 0


def _tag_profile_from_args(args: argparse.Namespace):
    from ..config import resolve
    from ..tagwriter import FIELDS, TagProfile

    from ..text import CharCase

    cfg = args._config
    pick = lambda key, value, default: resolve(cfg, "tags", key, value, default)

    return TagProfile(
        charcase=CharCase(pick("case", args.tag_case, "unchanged")),
        fields=frozenset(args.fields) if args.fields else frozenset(FIELDS),
        comment=pick("comment", args.comment, ""),
        label_in_comment=pick("label_in_comment", args.label_in_comment or None,
                              False),
        catalog_in_album=pick("catalog_in_album", args.catalog_in_album or None,
                              False),
        album_addition=pick("album_addition", args.album_addition, ""),
        write_totals=not pick("no_totals", args.no_totals or None,
                              not pick("write_totals", None, True)),
        write_id3v1=not pick("no_id3v1", args.no_id3v1 or None,
                             not pick("write_id3v1", None, True)),
        id3v2_version=pick("id3v2", args.id3v2, 4),
        write_disc_for_single=pick("write_disc_for_single", None, False),
        strip_existing=pick("strip_existing", args.strip_tags or None, False),
        write_apev2=pick("write_apev2", args.apev2 or None, False),
        write_lyrics3=pick("write_lyrics3", args.lyrics3 or None, False),
        normalise_genre=pick("normalise_genre", None, True),
    )


def _add_tag_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tag-case", default=None,
                        choices=["unchanged", "lower", "upper", "capitalize"])
    parser.add_argument("--fields", nargs="*", metavar="FELD",
                        help="nur diese Felder schreiben")
    parser.add_argument("--comment", help="fester Kommentartext")
    parser.add_argument("--label-in-comment", action="store_true",
                        help="Company statt Kommentartext schreiben")
    parser.add_argument("--catalog-in-album", action="store_true",
                        help="Katalognummer ans Album anhaengen")
    parser.add_argument("--album-addition", metavar="TEXT",
                        help="Zusatz hinter dem Albumnamen, z. B. CDDA")
    parser.add_argument("--no-totals", action="store_true",
                        help="'3' statt '3/12' schreiben")
    parser.add_argument("--no-id3v1", action="store_true")
    parser.add_argument("--id3v2", type=int, default=None, choices=[3, 4])
    parser.add_argument("--strip-tags", action="store_true",
                        help="vorhandene Tags vorher restlos entfernen")
    parser.add_argument("--apev2", action="store_true",
                        help="zusaetzlich APEv2 schreiben (MP3)")
    parser.add_argument("--lyrics3", action="store_true",
                        help="zusaetzlich Lyrics3v2 schreiben (MP3)")


def cmd_tag(args: argparse.Namespace) -> int:
    from ..audio import scan_directory
    from ..tagwriter import apply_tags, format_plan, plan_tags

    root = Path(args.directory)
    result = scan_directory(root, strict=args.strict)
    if result.warnings:
        _print_warnings(result.warnings)

    profile = _tag_profile_from_args(args)
    plan = plan_tags(result.release, profile)
    print(format_plan(plan, root))

    if not args.apply:
        print(f"\n{len(plan.changes)} Aenderung(en) in {len(plan.files)} Datei(en) - "
              f"Vorschau. Mit --apply ausfuehren.", file=sys.stderr)
        return 0

    written = apply_tags(plan, profile)
    print(f"\n{len(written)} Datei(en) geschrieben.", file=sys.stderr)
    return 0


def _profile_from_args(args: argparse.Namespace):
    from ..config import resolve
    from ..naming import DEFAULT_PIPELINE, NamingProfile, Scope
    from ..text import CharCase

    cfg = args._config
    pick = lambda key, value, default: resolve(cfg, "naming", key, value, default)

    from ..service import PRESET_CASE

    case = args.case or cfg.get("naming", "case")
    default_dir = case or PRESET_CASE["directory"]
    default_file = case or PRESET_CASE["file"]
    case_dir = CharCase(pick("case_dir", args.case_dir, default_dir))
    case_file = CharCase(pick("case_file", args.case_file, default_file))
    pipeline = pick("pipeline", args.pipeline, list(DEFAULT_PIPELINE))
    # --no-prefix ist ein ausdruecklicher Schalter und schlaegt deshalb auch
    # ein companion_prefix aus der Datei. Frueher gewann die Datei.
    prefix = ("" if args.no_prefix
              else pick("companion_prefix", args.companion_prefix, "00-"))
    return NamingProfile(
        dir_pattern=pick("dir_pattern", args.dir_pattern,
                         NamingProfile.dir_pattern),
        file_pattern=pick("file_pattern", args.file_pattern, "#N-#Artist-#Trk"),
        group=pick("group", args.group, ""),
        space_char=pick("space", args.space, "_"),
        pipeline=tuple([pipeline] if isinstance(pipeline, str) else pipeline),
        companion_prefix=prefix,
        companion_pattern=pick("companion_pattern", None,
                               NamingProfile.companion_pattern),
        charcase={Scope.DIRECTORY: case_dir, Scope.FILENAME: case_file,
                  Scope.TAG: CharCase.UNCHANGED, Scope.NFO: CharCase.UNCHANGED},
        prefixed_suffixes=frozenset(
            {".nfo", ".jpg", ".jpeg", ".png", ".pdf", ".sfv", ".m3u", ".m3u8"}
            if pick("prefix_all", args.prefix_all or None, True)
            else {".nfo", ".jpg", ".jpeg", ".png", ".pdf"}),
    )


def _add_naming_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dir-pattern", default=None)
    parser.add_argument("--file-pattern", default=None)
    parser.add_argument("--group", help="Gruppenkuerzel fuer #Grp")
    parser.add_argument("--space", default=None, metavar="CHAR",
                        help="Ersatzzeichen fuer Leerzeichen (Standard: _)")
    parser.add_argument("--companion-prefix", default=None, metavar="TEXT",
                        help="Praefix fuer .nfo und Bilder, z. B. '00-'")
    parser.add_argument("--case", default=None,
                        choices=["unchanged", "lower", "upper", "capitalize"])
    parser.add_argument("--case-dir", default=None,
                        choices=["unchanged", "lower", "upper", "capitalize"],
                        help="Schreibweise nur fuer das Verzeichnis")
    parser.add_argument("--case-file", default=None,
                        choices=["unchanged", "lower", "upper", "capitalize"],
                        help="Schreibweise nur fuer die Dateien")
    parser.add_argument("--prefix-all", action="store_true",
                        help="Praefix auch fuer .sfv und .m3u (Standard)")
    parser.add_argument("--no-prefix", action="store_true",
                        help="kein '00-' vor den Begleitdateien")
    from ..naming import DEFAULT_PIPELINE

    parser.add_argument("--pipeline", nargs="*", metavar="REGEL",
                        help="Regelkette, Standard: " + " ".join(DEFAULT_PIPELINE))


def cmd_rename(args: argparse.Namespace) -> int:
    from ..naming import format_plan
    from ..service import perform_rename, preview_rename, scan

    # Ueber die Dienstschicht, nicht an ihr vorbei: dort wird auch das
    # Rueckgaengig-Protokoll geschrieben.
    scanned = scan(args.directory, strict=args.strict,
                   release_date_format=_release_date_format(args))
    _print_warnings(scanned.warnings)

    profile = _profile_from_args(args)
    plan = preview_rename(scanned.release, scanned.root, profile)

    print(format_plan(plan, scanned.root))
    if not args.apply:
        print(f"\n{len(plan.changes)} Aenderung(en) - Vorschau. "
              f"Mit --apply ausfuehren.", file=sys.stderr)
        return 0 if plan.is_safe else 1
    if not plan.is_safe:
        print("\nAbbruch: Kollisionen im Plan.", file=sys.stderr)
        return 1

    executed, _root = perform_rename(scanned.release, scanned.root, profile)
    print(f"\n{len(executed.changes)} Aenderung(en) ausgefuehrt. "
          "Zuruecknehmen mit: releaser undo --apply", file=sys.stderr)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Der komplette Ablauf. Die Arbeit macht die Dienstschicht."""
    from ..config import resolve
    from ..service import BuildOptions, _as_list, process

    cfg = args._config
    pick = lambda key, value, default: resolve(cfg, "build", key, value, default)
    build_pick_bool = lambda key, value: bool(pick(key, value or None, False))

    options = BuildOptions(
        template=Path(args.template),
        nfo=not args.no_nfo,
        sfv=not args.no_sfv,
        m3u=not args.no_m3u,
        clean=pick("clean", args.clean or None, False),
        audio_crc=pick("audio_crc", args.audio_crc or None, False),
        sfv_comment=pick("sfv_comment", args.sfv_comment, ""),
        sfv_include=tuple(_as_list(pick("sfv_include", args.sfv_include or None,
                                        []))),
        use_catalog_no=pick("catalog_no", args.catalog_no or None, False),
        codepage=args.codepage,
        m3u_windows_paths=build_pick_bool("m3u_windows_paths",
                                          args.m3u_windows_paths),
        release_date_format=_release_date_format(args),
    )

    outcome = process(
        args.directory, options,
        naming=_profile_from_args(args),
        tags=_tag_profile_from_args(args),
        do_tag=args.tag, do_rename=args.rename, strict=args.strict,
    )

    for path in outcome.removed:
        print(f"  - {path.name} entfernt", file=sys.stderr)
    _print_warnings(outcome.warnings)
    for collision in outcome.collisions:
        print(f"  x {collision}", file=sys.stderr)
    if not outcome.ok:
        return 1

    root = outcome.root
    for path in outcome.created:
        print(path.relative_to(root) if path.is_relative_to(root) else path)
    return 0


def cmd_wizard(args: argparse.Namespace) -> int:
    from .wizard import run

    return run(
        args.directory,
        template=Path(args.template) if args.template else None,
        naming=_profile_from_args(args),
        tags=_tag_profile_from_args(args),
        strict=args.strict,
        batch=args.batch,
        release_date_format=_release_date_format(args),
    )


def cmd_web(args: argparse.Namespace) -> int:
    from ..browse import from_environment
    from .web import is_available, requirements_hint, run

    if not is_available():
        print(requirements_hint(), file=sys.stderr)
        return 3
    source = from_environment(args.mounts) if args.mounts else from_environment()
    if not source.mounts:
        print("Keine eingehaengten Verzeichnisse. Die Weboberflaeche zeigt "
              "ausschliesslich, was eingehaengt wurde:\n"
              "    RELEASER_MOUNTS=eingang:/data/eingang releaser web\n"
              "    oder: releaser web --mounts eingang:/data/eingang",
              file=sys.stderr)
        return 2
    print(f"Sichtbar: {', '.join(source.names)}", file=sys.stderr)
    from ..service import build_options_from_config

    templates = args.templates or os.environ.get("RELEASER_TEMPLATES") or None
    return run(host=args.host, port=args.port, source=source,
               naming=_profile_from_args(args),
               tags=_tag_profile_from_args(args),
               templates_dir=Path(templates) if templates else None,
               build_options=build_options_from_config(args._config))


def cmd_gui(args: argparse.Namespace) -> int:
    from .gtkui import build_state, is_available, requirements_hint, run

    if not is_available():
        print(requirements_hint(), file=sys.stderr)
        return 3
    # Dieselbe Konfiguration, die main() schon gelesen hat - auch die mit
    # --config angegebene. Vorher las die Oberflaeche selbst nach und
    # uebersah --config.
    state = build_state(start=args.start, mounts=args.mounts,
                        template=args.template, group=args.group,
                        config=args._config)
    return run(state)


def cmd_fields(args: argparse.Namespace) -> int:
    """Zeigt, welches Feld wohin geht - und wo der Platz knapp wird."""
    from ..fields import build_views, group_views, overflow_warnings
    from ..service import scan

    scanned = scan(args.directory, strict=args.strict,
                   release_date_format=_release_date_format(args))
    template = (Template.from_file(args.template, codepage=args.codepage)
                if args.template else None)

    views = build_views(scanned.release, template=template,
                        naming=_profile_from_args(args),
                        tags=_tag_profile_from_args(args),
                        origins=scanned.origins)

    for title, members in group_views(views):
        print(f"\n{title}")
        for view in members:
            width = f"{view.width:>3}" if view.width is not None else "  -"
            mark = "!" if view.overflows else " "
            origin = f"  ({view.origin_label})" if view.origin_label else ""
            print(f" {mark} {view.spec.label:<18} {width}  "
                  f"{view.value[:40]!r}{origin}")

    warnings = overflow_warnings(views)
    if warnings:
        print("\nWird im NFO abgeschnitten:")
        for warning in warnings:
            print(f"  ! {warning}")
    return 0


def cmd_browse(args: argparse.Namespace) -> int:
    """Zeigt, was die jeweilige Dateiauswahl sichtbar macht."""
    from ..browse import AccessError, LocalSource, Kind, describe, from_environment

    source = (from_environment(args.mounts) if args.mounts is not None
              else LocalSource(args.start))
    info = describe(source)
    print(f"Quelle: {info['description']} - Reichweite: {info['scope']}")
    for mount in info.get("mounts", []):
        state = "" if mount["exists"] else "  (nicht vorhanden)"
        rights = "schreibbar" if mount["writable"] else "nur lesen"
        print(f"  {mount['name']}: {rights}{state}")

    try:
        entries = source.list(args.path) if args.path else source.roots()
    except AccessError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    print()
    for entry in entries:
        marker = {Kind.RELEASE: "R", Kind.AUDIO: "a", Kind.COMPANION: "c",
                  Kind.COVER: "j", Kind.CUE: "q"}.get(entry.kind, " ")
        extra = f"  ({entry.audio_files} Audiodateien)" if entry.audio_files else ""
        print(f"  [{marker}] {entry.path}{extra}")
    return 0


def cmd_undo(args: argparse.Namespace) -> int:
    """Nimmt die letzte Umbenennung zurueck."""
    from ..undo import UndoError, check, journal_path, load, undo

    entries = load()
    if args.list:
        if not entries:
            print(f"Kein Protokoll in {journal_path()}")
            return 0
        for index, entry in enumerate(reversed(entries), start=1):
            print(f"{index:2}. {entry.describe()}")
        return 0

    if not entries:
        print("Nichts rueckgaengig zu machen.", file=sys.stderr)
        return 1

    entry = entries[-1]
    print(entry.describe())
    problems = check(entry)
    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)

    if not args.apply:
        print(f"\n{entry.count} {entry.kind.label} wuerden zurueckgenommen. "
              "Mit --apply ausfuehren.", file=sys.stderr)
        return 0 if not problems else 1

    try:
        done = undo(entry, force=args.force)
    except UndoError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    print(f"{len(done)} {entry.kind.label} zurueckgenommen.", file=sys.stderr)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Prueft eine Vorlage oder ein fertiges Release.

    Welches von beidem, entscheidet der Pfad - eine ``.skl`` ist eine
    Vorlage, ein Verzeichnis ein Release.
    """
    from ..checks import check_release, check_template_file
    from ..service import scan

    from ..audio import AudioError
    from ..checks import Level, Report

    target = Path(args.path)
    if target.is_dir():
        try:
            scanned = scan(target, strict=args.strict,
                           release_date_format=_release_date_format(args))
        except AudioError as exc:
            # Ein unlesbares Verzeichnis ist ein Befund ueber das Release,
            # kein Fehler des Programms.
            report = Report(checked=target.name)
            report.add(Level.ERROR, str(exc))
            print(report.render())
            return 1
        _print_warnings(scanned.warnings)
        known = None
        if args.against:
            from ..dupecheck import load

            known = [name for names in load(args.against).entries.values()
                     for name in names]
        report = check_release(scanned.release, scanned.root,
                               naming=_profile_from_args(args),
                               known_releases=known)
    elif target.is_file():
        report = check_template_file(target, codepage=args.codepage)
    else:
        print(f"Fehler: nicht gefunden: {target}", file=sys.stderr)
        return 2

    print(report.render())
    return 0 if report.ok else 1


def cmd_metrics(args: argparse.Namespace) -> int:
    """Was diese Auslieferungsform voraussetzt - gemessen, nicht behauptet."""
    from ..runtime import as_dict, collect, format_comparison, format_metrics

    if args.compare:
        payloads = []
        for name in args.compare:
            try:
                payloads.append(json.loads(Path(name).read_text(encoding="utf-8")))
            except json.JSONDecodeError as exc:
                # Ohne den Dateinamen sucht man bei mehreren Dateien lange
                raise ValueError(f"{name} ist kein gueltiges JSON: {exc}") from exc
        print(format_comparison(payloads))
        return 0

    metrics = collect()
    if args.json:
        print(json.dumps(as_dict(metrics), indent=2, ensure_ascii=False))
    else:
        print(format_metrics(metrics))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from ..sfv import verify_sfv

    result = verify_sfv(args.sfv)
    print(f"{len(result.ok)} ok", end="")
    if result.retagged:
        print(f", {len(result.retagged)} nur umgetaggt", end="")
    if result.failed:
        print(f", {len(result.failed)} fehlerhaft", end="")
    if result.missing:
        print(f", {len(result.missing)} fehlend", end="")
    print()

    for name in result.retagged:
        print(f"  ~ {name} (Audiodaten unverändert)", file=sys.stderr)
    for name, expected, actual in result.failed:
        print(f"  x {name}: erwartet {expected:08X}, gefunden {actual:08X}",
              file=sys.stderr)
    for name in result.missing:
        print(f"  ? {name} fehlt", file=sys.stderr)
    return 0 if result.success else 1


def cmd_dupe(args: argparse.Namespace) -> int:
    from ..dupecheck import load, normalise

    index = load(args.against)
    target = Path(args.name)
    name = target.name if target.exists() else args.name

    matches = index.check(name, threshold=args.threshold)
    print(f"{name}\n  Vergleichsform: {normalise(name)}\n"
          f"  geprueft gegen {len(index)} Eintraege")
    if not matches:
        print("  kein Treffer")
        return 0
    for match in matches:
        kind = "identisch" if match.exact else f"aehnlich {match.percent}%"
        print(f"  [{kind}] {match.name}")
    return 1


def cmd_config(args: argparse.Namespace) -> int:
    from ..config import EXAMPLE, find_config, load

    if args.example:
        sys.stdout.write(EXAMPLE)
        return 0
    found = args.path or find_config()
    if found is None:
        print("keine Konfiguration gefunden", file=sys.stderr)
        return 1
    config = load(found)
    print(f"gelesen: {config.source}")
    for warning in config.warnings:
        print(f"  ! {warning}", file=sys.stderr)
    for section in ("naming", "tags", "build"):
        values = config.section(section)
        if values:
            print(f"[{section}]")
            for key, value in sorted(values.items()):
                print(f"  {key} = {value!r}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.release).read_text(encoding="utf-8"))
    settings = settings_from_dict(payload.pop("settings", {}))
    release = release_from_dict(payload)

    tpl = Template.from_file(args.template, codepage=args.codepage)
    text = tpl.render(release, settings, trim_trailing=not args.keep_trailing)

    if args.out:
        write_nfo(args.out, text, codepage=args.codepage)
        print(f"geschrieben: {args.out} ({args.codepage})", file=sys.stderr)
    else:
        sys.stdout.write(text + "\n")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    tpl = Template.from_file(args.template, codepage=args.codepage)
    widths = tpl.field_widths()
    used = tpl.tag_names()
    print(f"{len(used)} Tags im Template, {len(REGISTRY) - len(used)} ungenutzt\n")
    for name in sorted(widths):
        desc = REGISTRY[name].description or REGISTRY[name].scope.value
        print(f"  #{name:<14} Breite {widths[name]:>3}   {desc}")
    missing = sorted(set(REGISTRY) - used)
    if missing:
        print("\nnicht im Template (Eingabefelder waeren deaktiviert):")
        print("  " + ", ".join(missing))
    return 0


def main(argv: list[str] | None = None) -> int:
    from .. import __version__

    ap = argparse.ArgumentParser(prog="releaser", description=__doc__)
    # Beantwortet "welche Fassung habe ich eigentlich gebaut?" - ein
    # veraltetes Buendel kannte sonst Kommandos nicht, ohne dass man es sah.
    ap.add_argument("--version", action="version",
                    version=f"mp3releaser {__version__}")
    ap.add_argument("--config", metavar="PFAD",
                    help="Konfigurationsdatei (Standard: automatisch suchen)")
    ap.add_argument("--codepage", default="cp437",
                    help="Codepage von Template und Ausgabe (Standard: cp437)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="Template mit Releasedaten fuellen")
    r.add_argument("template")
    r.add_argument("release", help="JSON-Datei mit den Releasedaten")
    r.add_argument("-o", "--out", help="Ziel-.nfo (Standard: stdout)")
    r.add_argument("--keep-trailing", action="store_true",
                   help="Leerzeichen am Zeilenende nicht entfernen")
    r.set_defaults(func=cmd_render)

    s_ = sub.add_parser("scan", help="Verzeichnis einlesen und als JSON ausgeben")
    s_.add_argument("directory")
    s_.add_argument("-o", "--out", help="Ziel-JSON (Standard: stdout)")
    s_.add_argument("--strict", action="store_true",
                    help="bei nicht lesbaren Dateien abbrechen")
    s_.set_defaults(func=cmd_scan)

    n = sub.add_parser("nfo", help="Verzeichnis scannen und direkt .nfo erzeugen")
    n.add_argument("directory")
    n.add_argument("template")
    n.add_argument("-o", "--out")
    n.add_argument("--strict", action="store_true")
    n.set_defaults(func=cmd_nfo)

    b = sub.add_parser("build", help=".nfo, .sfv und .m3u fuer ein Release erzeugen")
    b.add_argument("directory")
    b.add_argument("template")
    b.add_argument("--strict", action="store_true")
    b.add_argument("--no-nfo", action="store_true")
    b.add_argument("--no-sfv", action="store_true")
    b.add_argument("--no-m3u", action="store_true")
    b.add_argument("--sfv-comment", help="Kommentarzeile im SFV")
    b.add_argument("--sfv-include", nargs="*", default=[],
                   metavar="EXT", help="zusaetzliche Endungen ins SFV, z. B. log pdf")
    b.add_argument("--audio-crc", action="store_true",
                   help="tagfreien Audio-CRC als Kommentar mitschreiben")
    b.add_argument("--catalog-no", action="store_true",
                   help="Katalognummer statt Releasename als Dateiname")
    b.add_argument("--rename", action="store_true",
                   help="vorher nach Schema umbenennen")
    b.add_argument("--tag", action="store_true",
                   help="vorher Tags schreiben (laeuft vor dem Umbenennen)")
    b.add_argument("--clean", action="store_true",
                   help="vorhandene .nfo/.sfv/.m3u vorher entfernen")
    b.add_argument("--m3u-windows-paths", action="store_true",
                   help="Rueckwaerts-Schraegstriche in der M3U wie im Original")
    _add_naming_args(b)
    _add_tag_args(b)
    b.set_defaults(func=cmd_build)

    tg = sub.add_parser("tag", help="Tags aus dem Modell in die Dateien schreiben")
    tg.add_argument("directory")
    tg.add_argument("--apply", action="store_true",
                    help="Aenderungen wirklich schreiben (Standard: Vorschau)")
    tg.add_argument("--strict", action="store_true")
    _add_tag_args(tg)
    tg.set_defaults(func=cmd_tag)

    rn = sub.add_parser("rename", help="Dateien und Ordner nach Schema umbenennen")
    rn.add_argument("directory")
    rn.add_argument("--apply", action="store_true",
                    help="Aenderungen wirklich ausfuehren (Standard: Vorschau)")
    rn.add_argument("--strict", action="store_true")
    _add_naming_args(rn)
    rn.set_defaults(func=cmd_rename)

    v = sub.add_parser("verify", help="ein SFV gegen die Dateien daneben pruefen")
    v.add_argument("sfv")
    v.set_defaults(func=cmd_verify)

    d = sub.add_parser("dupe", help="Releasenamen gegen bekannte Namen pruefen")
    d.add_argument("name", help="Releasename oder Pfad zum Verzeichnis")
    d.add_argument("--against", required=True,
                   help="Textdatei mit Namen oder Verzeichnis mit Releases")
    d.add_argument("--threshold", type=float, default=0.88,
                   help="Aehnlichkeitsschwelle (Standard: 0.88)")
    d.set_defaults(func=cmd_dupe)

    c = sub.add_parser("config", help="Konfiguration anzeigen oder Beispiel ausgeben")
    c.add_argument("path", nargs="?", help="Konfigurationsdatei")
    c.add_argument("--example", action="store_true",
                   help="Beispielkonfiguration ausgeben")
    c.set_defaults(func=cmd_config)

    w = sub.add_parser("wizard", help="gefuehrt durch den kompletten Ablauf")
    w.add_argument("directory")
    w.add_argument("template", nargs="?", help="SKL-Vorlage fuer die .nfo")
    w.add_argument("--strict", action="store_true")
    w.add_argument("--batch", action="store_true",
                   help="Antworten von der Standardeingabe lesen, auch ohne Terminal")
    _add_naming_args(w)
    _add_tag_args(w)
    w.set_defaults(func=cmd_wizard)

    wb = sub.add_parser("web", help="Weboberflaeche starten (FastAPI)")
    wb.add_argument("--host", default="0.0.0.0")
    wb.add_argument("--port", type=int, default=8000)
    wb.add_argument("--mounts", help="eingehaengte Verzeichnisse; sonst aus "
                                     "RELEASER_MOUNTS")
    wb.add_argument("--templates", help="Verzeichnis mit .skl-Vorlagen "
                                         "(sonst aus RELEASER_TEMPLATES)")
    _add_naming_args(wb)
    _add_tag_args(wb)
    wb.set_defaults(func=cmd_web)

    g = sub.add_parser("gui", help="grafische Oberflaeche starten (GTK 4)")
    g.add_argument("--start", help="Startverzeichnis der Auswahl")
    g.add_argument("--mounts", help="eingehaengte Verzeichnisse statt des "
                                    "ganzen Dateisystems")
    g.add_argument("--template", help="SKL-Vorlage gleich laden")
    g.add_argument("--group", help="Gruppenkuerzel")
    g.set_defaults(func=cmd_gui)

    fl = sub.add_parser("fields",
                        help="Felder, ihre Verwendung, Breite und Herkunft")
    fl.add_argument("directory")
    fl.add_argument("template", nargs="?", help="SKL-Vorlage")
    fl.add_argument("--strict", action="store_true")
    _add_naming_args(fl)
    _add_tag_args(fl)
    fl.set_defaults(func=cmd_fields)

    br = sub.add_parser("browse", help="Dateiauswahl anzeigen")
    br.add_argument("path", nargs="?", help="virtueller Pfad (leer = Wurzeln)")
    br.add_argument("--mounts", metavar="SPEC",
                    help="eingehaengte Verzeichnisse wie im Container, z. B. "
                         "'eingang:/data/ein,archiv:/data/arch:ro'")
    br.add_argument("--start", help="Startverzeichnis der lokalen Auswahl")
    br.set_defaults(func=cmd_browse)

    ud = sub.add_parser("undo", help="die letzte Umbenennung zuruecknehmen")
    ud.add_argument("--apply", action="store_true",
                    help="wirklich zuruecknehmen (Standard: Vorschau)")
    ud.add_argument("--list", action="store_true", help="Protokoll anzeigen")
    ud.add_argument("--force", action="store_true",
                    help="auch bei Hindernissen so weit wie moeglich")
    ud.set_defaults(func=cmd_undo)

    ck = sub.add_parser("check",
                        help="eine .skl-Vorlage oder ein fertiges Release pruefen")
    ck.add_argument("path", help="Vorlage oder Releaseverzeichnis")
    ck.add_argument("--against", help="Liste bekannter Releases fuer die "
                                      "Dupe-Pruefung")
    ck.add_argument("--strict", action="store_true")
    _add_naming_args(ck)
    _add_tag_args(ck)
    ck.set_defaults(func=cmd_check)

    m = sub.add_parser("metrics",
                       help="Voraussetzungen dieser Auslieferungsform messen")
    m.add_argument("--json", action="store_true", help="maschinenlesbar ausgeben")
    m.add_argument("--compare", nargs="+", metavar="DATEI",
                   help="mehrere --json-Ausgaben gegenueberstellen")
    m.set_defaults(func=cmd_metrics)

    i = sub.add_parser("inspect", help="Tags und Feldbreiten eines Templates zeigen")
    i.add_argument("template")
    i.set_defaults(func=cmd_inspect)

    args = ap.parse_args(argv)

    from ..config import ConfigError, load as load_config

    try:
        args._config = load_config(args.config)
        for warning in args._config.warnings:
            print(f"Konfiguration: {warning}", file=sys.stderr)
    except ConfigError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("abgebrochen", file=sys.stderr)
        return 130
    except FileNotFoundError as exc:
        print(f"Fehler: Datei nicht gefunden: {exc.filename}", file=sys.stderr)
        return 2
    except ConfigError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    except KeyError as exc:
        # str(KeyError) setzt Anfuehrungszeichen um die Meldung
        print(f"Fehler: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:                      # noqa: BLE001
        from ..audio.base import AudioError

        if isinstance(exc, AudioError):
            print(f"Fehler: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
