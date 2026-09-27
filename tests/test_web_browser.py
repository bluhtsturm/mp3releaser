"""Prüft die Seite in einer echten Browser-Engine.

Die übrigen Web-Tests gehen über die API - das JavaScript läuft dabei nie.
Hier lädt WebKitGTK die Seite von einem echten Server und bedient sie: klicken,
tippen, Dialog öffnen. Damit ist die einzige Schicht abgedeckt, die sonst erst
im Browser des Nutzers auffiele.

Läuft in einem Unterprozess unter ``xvfb-run``, weil GTK ohne Display
abstürzt statt eine Ausnahme zu werfen - ein Absturz würde die ganze
Testsitzung mitnehmen.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "tools" / "webcheck.py"


def _webkit_available() -> bool:
    try:
        import gi

        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit

        return WebKit is not None
    except Exception:                       # noqa: BLE001
        return False


needs_browser = pytest.mark.skipif(
    not (_webkit_available() and shutil.which("xvfb-run")
         and shutil.which("ffmpeg")),
    reason="WebKitGTK, xvfb-run oder ffmpeg nicht vorhanden")


@pytest.fixture
def served_tree(tmp_path: Path) -> Path:
    release = tmp_path / "eingang" / "Artist-Album-2026-GRP"
    release.mkdir(parents=True)
    for no in (1, 2):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"sine=frequency={400 + no * 50}:duration=1",
             "-c:a", "libmp3lame",
             "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
             "-metadata", "album=Das Album", "-metadata", f"track={no}/2",
             "-metadata", "date=2026", "-metadata", "genre=Electronic",
             str(release / f"0{no}-x.mp3"), "-y"], check=True)
    return tmp_path


#: Wird aus der Umgebung durchgereicht, falls gesetzt. Auf Ubuntu 24.04 darf
#: ein normaler Benutzer keine Namespaces anlegen; WebKits Sandbox (bwrap)
#: scheitert dann, und der Webprozess stuerzt ab. Der Release-Workflow setzt
#: die Variable - geladen wird nur die eigene Seite vom eigenen Testserver.
PASS_THROUGH = ("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS",)


def _browser_env(home: Path) -> dict:
    """Bewusst schmale Umgebung - nur, was der Pruefstand wirklich braucht."""
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "NO_AT_BRIDGE": "1"}
    env.update({key: os.environ[key] for key in PASS_THROUGH if key in os.environ})
    return env


@needs_browser
def test_page_works_in_a_real_browser_engine(served_tree):
    result = subprocess.run(
        ["xvfb-run", "-a", sys.executable, str(CHECKER),
         str(served_tree / "eingang"), str(ROOT / "templates")],
        capture_output=True, text=True, timeout=180,
        env=_browser_env(served_tree),
    )
    output = result.stdout

    # Jede einzelne Pruefung soll bestanden sein - und die Meldung soll
    # aussagen, welche nicht, falls doch.
    failed = [line for line in output.splitlines() if "[FEHLER]" in line]
    assert not failed, "\n".join(failed) + "\n" + result.stderr[-2000:]
    assert "15 von 15 Pruefungen bestanden" in output, output[-2000:]

    # Stichproben aus der Ausgabe, damit der Test nicht nur eine Zahl prueft
    for expected in (
        "Banner nennt Beschränkung und Datenlage",
        "ohne Auswahl sind alle Aktionen gesperrt",
        "Gruppe „nicht verwendet“ ist eingeklappt",
        "Überlänge wird rot markiert",
        "Umbenennungsplan erscheint im Dialog",
        "NFO-Vorschau gefüllt",
    ):
        assert expected in output, expected


@needs_browser
def test_checker_reports_its_own_failures(served_tree, tmp_path):
    """Der Prüfstand muss Fehler melden, nicht still enden."""
    broken = tmp_path / "leer"
    broken.mkdir()
    result = subprocess.run(
        ["xvfb-run", "-a", sys.executable, str(CHECKER),
         str(broken), str(ROOT / "templates")],
        capture_output=True, text=True, timeout=180,
        env=_browser_env(tmp_path),
    )
    assert result.returncode != 0
    assert "[FEHLER]" in result.stdout or "fehlgeschlagen" in result.stdout
