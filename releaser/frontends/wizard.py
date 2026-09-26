"""Geführter Modus.

Führt Schritt für Schritt durch den Ablauf und zeigt vor jeder verändernden
Aktion, was passieren würde. Gedacht für Vorführungen und für alle, die sich
die Schalter nicht merken wollen.

Der geführte Modus ist bewusst *keine* zweite Ablauflogik: er ruft dieselbe
Dienstschicht wie alles andere. Was er kann, kann auch der direkte Aufruf -
er fragt nur vorher.

Ohne Terminal (Pipe, CI) beantwortet er nichts selbst, sondern bricht ab. Eine
Rückfrage, die niemand sieht, darf nicht stillschweigend mit "ja" durchgehen,
wenn dahinter Dateien umbenannt werden.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from ..model import Release
from ..naming import NamingProfile, format_plan as format_rename_plan
from ..service import (BuildOptions, build, perform_rename, preview_rename,
                       refresh_sizes, scan)
from ..tagwriter import TagProfile, apply_tags
from ..tagwriter import format_plan as format_tag_plan
from ..tagwriter import plan_tags


class Aborted(Exception):
    """Der Benutzer hat abgebrochen."""


@dataclass
class Console:
    """Ein- und Ausgabe, damit der Ablauf testbar bleibt."""

    read: Callable[[str], str] = input
    write: Callable[[str], None] = lambda text: print(text)
    interactive: bool = True

    def say(self, text: str = "") -> None:
        self.write(text)

    def ask(self, question: str, default: bool = True) -> bool:
        if not self.interactive:
            raise Aborted("kein Terminal - der gefuehrte Modus braucht Rueckfragen")
        suffix = "[J/n]" if default else "[j/N]"
        while True:
            answer = self.read(f"{question} {suffix} ").strip().lower()
            if not answer:
                return default
            if answer in ("j", "ja", "y", "yes"):
                return True
            if answer in ("n", "nein", "no"):
                return False
            self.say("  Bitte j oder n.")

    def ask_text(self, question: str, default: str = "") -> str:
        if not self.interactive:
            raise Aborted("kein Terminal - der gefuehrte Modus braucht Rueckfragen")
        shown = f" [{default}]" if default else ""
        answer = self.read(f"{question}{shown} ").strip()
        return answer or default


def _summary(release: Release, root: Path) -> list[str]:
    lines = [
        f"  Verzeichnis  {root.name}",
        f"  Artist       {release.artist or '-'}",
        f"  Album        {release.album or '-'}",
        f"  Jahr         {release.year or '-'}",
        f"  Format       {release.audio_format or '-'}"
        + (f" / {release.bitrate}kbps" if release.bitrate else ""),
        f"  Tracks       {release.total_tracks}"
        + (f" auf {len(release.discs)} CDs" if release.multi_disc else ""),
        f"  Laufzeit     {int(release.seconds // 60)}:{int(release.seconds % 60):02d}",
        f"  Groesse      {release.size_mb:.1f} MB",
    ]
    return lines


def _show_warnings(console: Console, warnings: Sequence[str], limit: int = 8) -> None:
    if not warnings:
        return
    console.say(f"\n  {len(warnings)} Hinweis(e):")
    for warning in warnings[:limit]:
        console.say(f"    ! {warning}")
    if len(warnings) > limit:
        console.say(f"    ... und {len(warnings) - limit} weitere")


def run(directory: str | Path,
        template: Optional[Path] = None,
        naming: Optional[NamingProfile] = None,
        tags: Optional[TagProfile] = None,
        console: Optional[Console] = None,
        strict: bool = False,
        batch: bool = False) -> int:
    """Führt durch den Ablauf. Rückgabe ist der Exit-Code.

    ``batch`` liest die Antworten auch dann von der Standardeingabe, wenn kein
    Terminal daran hängt - für Vorführungen und Tests. Das muss ausdrücklich
    verlangt werden: von selbst beantwortet der Modus keine Rückfrage.
    """
    from ..service import naming_from_config

    console = console or Console(interactive=batch or sys.stdin.isatty())
    # Dieselbe Voreinstellung wie in den Oberflaechen - der gefuehrte Modus
    # soll nicht anders benennen als der Rest.
    naming = naming or naming_from_config()
    tags = tags or TagProfile()

    try:
        return _run(directory, template, naming, tags, console, strict)
    except Aborted as exc:
        console.say(f"\nAbgebrochen: {exc}" if str(exc) else "\nAbgebrochen.")
        return 1
    except KeyboardInterrupt:
        console.say("\nAbgebrochen.")
        return 130


def _run(directory, template, naming, tags, console, strict) -> int:
    console.say("Schritt 1 von 4: einlesen")
    scanned = scan(directory, strict=strict)
    release, root = scanned.release, scanned.root
    console.say()
    for line in _summary(release, root):
        console.say(line)
    _show_warnings(console, scanned.warnings)

    if not console.ask("\nStimmen diese Angaben?"):
        console.say("\nDann zuerst die Tags in Ordnung bringen - "
                    "oder die Werte mit 'scan -o' als JSON bearbeiten.")
        return 1

    # ---- Schritt 2: Tags ---------------------------------------------------
    console.say("\nSchritt 2 von 4: Tags")
    plan = plan_tags(release, tags)
    if not plan.changes:
        console.say("  Die Tags sind bereits so, wie sie sein sollen.")
    else:
        console.say(format_tag_plan(plan, root))
        if console.ask(f"\n{len(plan.changes)} Aenderung(en) schreiben?",
                       default=False):
            apply_tags(plan, tags)
            # Die .nfo aus Schritt 4 soll die Groesse nach dem Taggen zeigen
            refresh_sizes(release)
            console.say(f"  {len(plan.files)} Datei(en) geschrieben.")
        else:
            console.say("  uebersprungen.")

    # ---- Schritt 3: Umbenennen --------------------------------------------
    console.say("\nSchritt 3 von 4: Umbenennen")
    if not naming.group:
        naming = _with_group(naming, console.ask_text("  Gruppenkuerzel?", ""))

    rename_plan = preview_rename(release, root, naming)
    if not rename_plan.changes:
        console.say("  Die Namen passen bereits.")
    else:
        console.say(format_rename_plan(rename_plan, root))
        if not rename_plan.is_safe:
            console.say("\n  Der Plan hat Kollisionen und wird nicht ausgefuehrt.")
        elif console.ask(f"\n{len(rename_plan.changes)} Umbenennung(en) ausfuehren?",
                         default=False):
            _, root = perform_rename(release, root, naming)
            console.say(f"  Neuer Ordner: {root.name}")
        else:
            console.say("  uebersprungen.")

    # ---- Schritt 4: Begleitdateien ----------------------------------------
    console.say("\nSchritt 4 von 4: Begleitdateien")
    options = BuildOptions(
        template=template,
        nfo=template is not None,
        audio_crc=console.ask("  Tagfreien Audio-CRC ins SFV schreiben?"),
    )
    if template is None:
        console.say("  Keine Vorlage angegeben - es entstehen nur .sfv und .m3u.")

    if not console.ask("  Jetzt erzeugen?"):
        console.say("\nNichts erzeugt.")
        return 0

    outcome = build(release, root, options, naming)
    _show_warnings(console, outcome.warnings)
    console.say("")
    for path in outcome.created:
        console.say(f"  {path.relative_to(root)}")
    console.say(f"\nFertig. {len(outcome.created)} Datei(en) erzeugt in {root.name}")
    return 0


def _with_group(profile: NamingProfile, group: str) -> NamingProfile:
    from dataclasses import replace

    return replace(profile, group=group) if group else profile
