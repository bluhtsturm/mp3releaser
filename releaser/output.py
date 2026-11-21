"""Das fertige Release in einen Ausgabeordner schieben.

Letzter Schritt von "Release erstellen", sofern ein Ausgabeordner eingestellt
ist: Eingang und Ausgang getrennt zu halten heisst, dass im Eingang nur liegt,
was noch zu tun ist.

**Ueber Dateisystemgrenzen.** Im Container sind Eingang und Ausgang meist
zwei Volumes - fuer den Kernel zwei Dateisysteme, und ``rename`` scheitert
dort mit ``EXDEV``. Dann wird kopiert und erst *nach* vollstaendiger Kopie das
Original geloescht. Scheitert die Kopie, wird der angefangene Rest im Ziel
entfernt; das Original bleibt, wie es war.

**Rueckgaengig.** Das Verschieben landet im selben Protokoll wie Umbenennen
und Taggen (:mod:`releaser.undo`), als eigener Eintrag - die Ruecknahme holt
das Release zurueck an seinen alten Platz.
"""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path
from typing import Optional

from .model import Release


def move_path(src: Path, dst: Path) -> None:
    """Verschiebt eine Datei oder einen Ordner, notfalls per Kopie.

    ``dst`` darf noch nicht existieren - geprueft wird das vom Aufrufer, hier
    nur noch einmal als letzte Sicherung, damit nie etwas ueberschrieben wird.
    """
    src, dst = Path(src), Path(dst)
    if dst.exists():
        raise FileExistsError(errno.EEXIST, "Ziel existiert bereits", str(dst))
    try:
        src.rename(dst)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    try:
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst)
    except BaseException:
        # Eine halbe Kopie ist schlimmer als keine: sie blockierte den
        # naechsten Versuch und saehe aus wie ein fertiges Release.
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst, ignore_errors=True)
        elif dst.exists() or dst.is_symlink():
            dst.unlink(missing_ok=True)
        raise
    if src.is_dir() and not src.is_symlink():
        shutil.rmtree(src)
    else:
        src.unlink()


def writable_dir(path: Path) -> bool:
    """Darf dieser Prozess im Ordner anlegen, umbenennen und loeschen?

    Der Schalter ``:ro`` eines Einhaengepunkts sagt das nicht vollstaendig:
    Ein mit ``sudo`` angelegter Ordner gehoert root, und der Dienst im
    Container (Benutzer 1000) darf trotzdem nicht hinein.
    """
    return os.access(path, os.W_OK | os.X_OK)


def target_for(root: Path, output_dir: Path, name: Optional[str] = None) -> Path:
    """Wo das Release nach dem Verschieben liegt."""
    return Path(output_dir) / (name or Path(root).name)


def check_move(root: Path, output_dir: Path,
               name: Optional[str] = None) -> list[str]:
    """Was dem Verschieben im Weg steht - leer heisst: es kann laufen.

    ``name`` ist der Ordnername *nach* dem Umbenennen. Geprueft wird vorher,
    damit "Release erstellen" gar nicht erst anfaengt, wenn es am Ende nicht
    abschliessen koennte.
    """
    root, output_dir = Path(root), Path(output_dir)
    if not output_dir.is_dir():
        return [f"Ausgabeordner gibt es nicht: {output_dir}"]
    try:
        out = output_dir.resolve()
        here = root.resolve()
    except OSError as exc:
        return [f"Ausgabeordner nicht auflösbar: {exc}"]
    if out == here or here in out.parents:
        return [f"Ausgabeordner liegt im Release selbst: {output_dir}"]
    if out == here.parent:
        return []                       # liegt schon dort - nichts zu tun
    target = target_for(root, output_dir, name)
    if target.exists() or target.is_symlink():
        return [f"Im Ausgabeordner gibt es schon {target.name}"]
    # Die Rechte erst jetzt - aber vor jedem Schritt von "Release erstellen":
    # Frueher fiel ein fehlendes Schreibrecht erst beim Verschieben auf, mit
    # Tags und Umbenennung schon erledigt - ein halb fertiges Release.
    if not writable_dir(output_dir):
        return [f"Ausgabeordner ist nicht beschreibbar: {output_dir}"]
    if not writable_dir(here.parent):
        return [f"Das Release kann nicht aus {here.parent} heraus verschoben "
                "werden - dort fehlt das Schreibrecht"]
    return []


def move_release(release: Release, root: Path,
                 output_dir: Path) -> tuple[Path, Optional[object]]:
    """Schiebt das Release nach ``output_dir``.

    Rueckgabe: der neue Wurzelpfad und der Protokolleintrag (``None``, wenn
    das Release schon dort lag). Die Pfade im Modell werden nachgefuehrt, so
    dass nichts neu eingelesen werden muss.
    """
    root = Path(root)
    problems = check_move(root, output_dir)
    if problems:
        raise ValueError("; ".join(problems))
    target = target_for(root, output_dir)
    if target.resolve() == root.resolve():
        return root, None
    move_path(root, target)

    for track in release.tracks:
        if not track.path:
            continue
        path = Path(track.path)
        if path == root or root in path.parents:
            track.path = str(target / path.relative_to(root))

    from . import undo as undo_journal

    entry = undo_journal.record_move(root, target, release.dirname or root.name)
    return target, entry
