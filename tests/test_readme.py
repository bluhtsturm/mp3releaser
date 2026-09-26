"""Hält das README am Code fest.

Anlass ist ein eigener Fehler: Der Kopf des README stand monatelang auf dem
Stand des ersten Tages („Dieser Stand enthält Kern + SKL-Renderer"), weil
Textersetzungen stillschweigend nicht griffen - eine Ersetzung ohne Treffer
meldet nichts. Dokumentation, die nichts erzwingt, driftet.

Geprüft wird deshalb, was sich prüfen lässt: erwähnte Kommandos, der
Modulbaum und die genannte Testzahl.
"""

import io
import re
import subprocess
import sys
from contextlib import redirect_stdout, suppress
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

#: Woerter, die im Fliesstext hinter "releaser" stehen, aber keine
#: Unterkommandos sind.
NOT_COMMANDS = {"import", "web", "metrics"}


@pytest.fixture(scope="module")
def text() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def commands() -> set[str]:
    from releaser.frontends.cli import main

    buffer = io.StringIO()
    with redirect_stdout(buffer), suppress(SystemExit):
        main(["--help"])
    return set(re.findall(r"^\s{4}(\w+)\s", buffer.getvalue(), re.M))


def test_readme_exists_and_is_substantial(text):
    assert len(text) > 5000


def test_every_mentioned_command_exists(text, commands):
    mentioned = set(re.findall(r"releaser\s+(\w+)", text)) - NOT_COMMANDS
    unknown = mentioned - commands
    assert not unknown, f"im README erwähnt, aber kein Kommando: {sorted(unknown)}"


def test_every_command_is_mentioned(text, commands):
    """Ein Kommando, das nirgends steht, findet niemand."""
    missing = {c for c in commands if c not in text}
    assert not missing, f"nicht im README erwähnt: {sorted(missing)}"


def test_module_tree_matches_reality(text):
    listed = set(re.findall(r"^\s{2,4}(\w+\.py)\s", text, re.M))
    actual = {p.name for p in (ROOT / "releaser").rglob("*.py")
              if p.name not in ("__init__.py", "__main__.py")}
    # app.py liegt unter web/ und wird dort als Verzeichnis genannt
    actual -= {"app.py"}

    assert not (listed - actual), \
        f"im README, aber nicht vorhanden: {sorted(listed - actual)}"
    assert not (actual - listed), \
        f"vorhanden, aber nicht im README: {sorted(actual - listed)}"


def test_claimed_test_count_is_current(text):
    claimed = {int(n) for n in re.findall(r"(\d+) Tests", text)}
    assert claimed, "das README nennt keine Testzahl"

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", str(ROOT / "tests"), "-q",
         "--collect-only", "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=180, cwd=ROOT)
    found = re.search(r"(\d+) tests collected", collected.stdout)
    assert found, collected.stdout[-800:]
    actual = int(found.group(1))

    assert claimed == {actual}, (
        f"README nennt {sorted(claimed)}, tatsächlich sind es {actual}")


def test_no_stale_planning_language(text):
    """Was fertig ist, darf nicht mehr als geplant beschrieben sein."""
    for phrase in ("Der Audio-/Tag-Layer folgt",
                   "Es fehlt die GUI",
                   "geplant: CLI, Binary/AppImage"):
        assert phrase not in text, f"veraltete Aussage im README: {phrase!r}"


def test_comparison_table_has_no_open_items_for_shipped_features(text):
    """Im Abgleich mit dem Original darf nichts mehr offen stehen."""
    section = text.split("## Abgleich mit dem Original", 1)[1]
    section = section.split("\n## ", 1)[0]
    open_rows = [line for line in section.splitlines() if "❌" in line]
    assert not open_rows, "offene Punkte im Abgleich:\n" + "\n".join(open_rows)
