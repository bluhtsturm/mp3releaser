"""Tests für die Paketierung.

Der eigentliche Bau dauert zu lange für jeden Testlauf. Geprüft wird deshalb
zweierlei: dass die Bauanleitung in sich stimmig ist (Dateien vorhanden,
Desktop-Eintrag gültig, AppRun ausführbar), und - falls schon gebaut wurde -
dass die gebündelte Fassung wirklich eigenständig läuft.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.runtime import Variant, compare, format_comparison

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
APPIMAGE = PACKAGING / "appimage"
BUNDLE = ROOT / "build" / "dist" / "mp3releaser"
APPRUN = ROOT / "build" / "AppDir" / "AppRun"

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_bundle = pytest.mark.skipif(
    not BUNDLE.is_file(), reason="Bündel nicht gebaut (packaging/build.sh binary)")
needs_appdir = pytest.mark.skipif(
    not APPRUN.is_file(), reason="AppDir nicht gebaut (packaging/build.sh appdir)")


def run_isolated(*args: str) -> subprocess.CompletedProcess:
    """Startet das Bündel ohne jede Python-Umgebung."""
    return subprocess.run(list(args), capture_output=True, text=True,
                          timeout=120, env={"HOME": "/tmp", "PATH": "/nonexistent"})


# ============================================================ Bauanleitung


def test_packaging_files_exist():
    for name in ("build.sh", "pyinstaller.spec", "entrypoint.py"):
        assert (PACKAGING / name).is_file(), name
    for name in ("AppRun", "mp3releaser.desktop", "mp3releaser.svg"):
        assert (APPIMAGE / name).is_file(), name


def test_apprun_is_executable():
    assert os.access(APPIMAGE / "AppRun", os.X_OK)


def test_build_script_is_executable():
    assert os.access(PACKAGING / "build.sh", os.X_OK)


def test_desktop_entry_has_the_required_keys():
    text = (APPIMAGE / "mp3releaser.desktop").read_text(encoding="utf-8")
    assert text.startswith("[Desktop Entry]")
    values = dict(line.split("=", 1) for line in text.splitlines()
                  if "=" in line and not line.startswith("["))
    assert values["Type"] == "Application"
    assert values["Exec"] == "mp3releaser"
    assert values["Icon"] == "mp3releaser"
    assert values["Categories"].endswith(";")


def test_icon_is_valid_svg():
    text = (APPIMAGE / "mp3releaser.svg").read_text(encoding="utf-8")
    assert text.lstrip().startswith("<?xml")
    assert "<svg" in text and "</svg>" in text


def test_apprun_sets_appdir_so_the_variant_is_detected():
    """Ohne APPDIR wüsste das Programm nicht, in welcher Form es läuft."""
    text = (APPIMAGE / "AppRun").read_text(encoding="utf-8")
    assert "APPDIR" in text
    assert "usr/bin/mp3releaser" in text
    # GTK darf nicht aus dem Bündel kommen - zwei Fassungen vertragen sich nicht
    assert "LD_LIBRARY_PATH" not in text


def test_pyproject_entry_points_point_at_real_functions():
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"] | data["project"]["gui-scripts"]
    for target in scripts.values():
        module, _, attribute = target.partition(":")
        imported = __import__(module, fromlist=[attribute])
        assert callable(getattr(imported, attribute)), target


def test_pyproject_lists_every_package():
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    listed = set(data["tool"]["setuptools"]["packages"])
    found = {"releaser"} | {
        f"releaser.{p.name}" for p in (ROOT / "releaser").iterdir()
        if p.is_dir() and (p / "__init__.py").exists()}
    assert found <= listed, found - listed


# ======================================================== gebündelte Fassung


@needs_bundle
def test_bundle_runs_without_python():
    result = run_isolated(str(BUNDLE), "--help")
    assert result.returncode == 0
    assert "wizard" in result.stdout


@needs_bundle
def test_bundle_reports_itself_as_bundled():
    result = run_isolated(str(BUNDLE), "metrics", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["variant"] in (Variant.FROZEN.value, Variant.APPIMAGE.value)
    assert payload["bundled"] is True
    # Im Bündel sind die Bibliotheken nicht getrennt messbar
    assert payload["dependency_bytes"] is None
    assert payload["total_bytes"] > 1_000_000


@needs_appdir
def test_apprun_reports_appimage():
    result = run_isolated(str(APPRUN), "metrics", "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["variant"] == Variant.APPIMAGE.value
    assert payload["needs_privileges"] is False
    assert any("GTK" in note for note in payload["notes"])


@needs_appdir
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")
def test_bundle_does_the_whole_job(tmp_path):
    """Die gebündelte Fassung muss fachlich dasselbe können wie der Quelltext."""
    release = tmp_path / "release"
    release.mkdir()
    for no in (1, 2):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"sine=frequency={400 + no * 50}:duration=1",
             "-c:a", "libmp3lame",
             "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
             "-metadata", "album=Das Album", "-metadata", f"track={no}/2",
             "-metadata", "date=2026",
             str(release / f"0{no}-x.mp3"), "-y"], check=True)
    template = tmp_path / "vorlage.skl"
    shutil.copy(ROOT / "templates" / "example.skl", template)

    built = run_isolated(str(APPRUN), "build", str(release), str(template),
                         "--tag", "--rename", "--group", "GRP", "--audio-crc")
    assert built.returncode == 0, built.stderr

    # Voreinstellung: Ordner kapitalisiert, Begleitdateien klein mit "00-"
    target = tmp_path / "Der_Artist-Das_Album-2026-GRP"
    assert target.is_dir(), sorted(p.name for p in tmp_path.iterdir())
    assert sorted(p.suffix for p in target.iterdir()) == [
        ".m3u", ".mp3", ".mp3", ".nfo", ".sfv"]

    checked = run_isolated(str(APPRUN), "verify",
                           str(target / "00-der_artist-das_album-2026-grp.sfv"))
    assert checked.returncode == 0
    assert "2 ok" in checked.stdout


# ============================================================== Vergleich


def payload(variant: str, **changes) -> dict:
    base = {
        "variant": variant, "python": "3.12.3", "platform": "Linux x86_64",
        "startup_seconds": 0.1, "resident_kb": 20000,
        "package_bytes": 1000, "dependency_bytes": 2000, "total_bytes": 3000,
        "euid": 1000, "writable_cwd": True, "needs_privileges": False,
        "data_location": "beim Nutzer", "notes": [], "bundled": False,
    }
    base.update(changes)
    return base


def test_compare_builds_one_column_per_form():
    rows = compare([payload("source"), payload("appimage"),
                    payload("container")])
    assert rows[0] == ["", "Quelltext / CLI", "AppImage", "Container"]
    assert len(rows) == 7                       # Kopf plus sechs Zeilen


def test_compare_formats_units():
    rows = dict((row[0], row[1:]) for row in compare([
        payload("source", startup_seconds=0.12, resident_kb=38000,
                total_bytes=2 * 1024 * 1024)]))
    assert rows["Startzeit"] == ["120 ms"]
    assert rows["Arbeitsspeicher"] == ["37.1 MB"]
    assert rows["Auslieferungsgröße"] == ["2 MB"]


def test_compare_marks_the_privileged_form():
    rows = dict((row[0], row[1:]) for row in compare([
        payload("source"), payload("container", needs_privileges=True)]))
    assert rows["Rechte nötig"] == ["nein", "ja"]


def test_compare_handles_missing_values():
    rows = dict((row[0], row[1:]) for row in compare([
        payload("source", startup_seconds=None, resident_kb=None)]))
    assert rows["Startzeit"] == ["unbekannt"]
    assert rows["Arbeitsspeicher"] == ["unbekannt"]


def test_comparison_text_lists_notes_once():
    text = format_comparison([
        payload("source", notes=["gleicher Hinweis"]),
        payload("appimage", notes=["gleicher Hinweis", "eigener Hinweis"]),
    ])
    assert text.count("gleicher Hinweis") == 2      # je Form einmal
    assert "eigener Hinweis" in text
    assert "Auslieferungsgröße" in text


def test_cli_metrics_compare(tmp_path, capsys):
    from releaser import cli

    files = []
    for variant in ("source", "container"):
        path = tmp_path / f"{variant}.json"
        path.write_text(json.dumps(payload(
            variant, needs_privileges=variant == "container")))
        files.append(str(path))

    assert cli.main(["metrics", "--compare", *files]) == 0
    out = capsys.readouterr().out
    assert "Quelltext / CLI" in out and "Container" in out
    assert "Rechte nötig" in out


# ============================================================== Container


DOCKERFILE = ROOT / "Dockerfile"
COMPOSE = ROOT / "docker-compose.yml"


def test_container_files_exist():
    assert DOCKERFILE.is_file()
    assert COMPOSE.is_file()
    assert (ROOT / ".dockerignore").is_file()


def test_container_does_not_run_as_root():
    """Der Dienst braucht keine erhoehten Rechte - nur wer ihn startet."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "useradd" in text
    lines = [l.strip() for l in text.splitlines()]
    user_lines = [l for l in lines if l.startswith("USER ")]
    assert user_lines and user_lines[-1] == "USER releaser"
    # USER muss vor dem Startbefehl stehen
    assert lines.index(user_lines[-1]) < max(
        i for i, l in enumerate(lines) if l.startswith(("CMD", "ENTRYPOINT")))


def test_container_declares_the_mount_variable():
    assert "RELEASER_MOUNTS" in DOCKERFILE.read_text(encoding="utf-8")


def test_compose_binds_the_port_locally_only():
    text = COMPOSE.read_text(encoding="utf-8")
    assert '"127.0.0.1:8000:8000"' in text


def test_compose_mounts_match_the_volumes():
    """Was in RELEASER_MOUNTS steht, muss auch eingehaengt sein."""
    import re

    text = COMPOSE.read_text(encoding="utf-8")
    declared = re.search(r'RELEASER_MOUNTS:\s*"([^"]*)"', text).group(1)
    volumes = set(re.findall(r"^\s+- \./[^:]+:([^:\s]+)", text, re.MULTILINE))
    for entry in declared.split(","):
        path = entry.split(":")[1]
        assert path in volumes, f"{path} ist nicht eingehaengt"


def test_compose_drops_capabilities():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "no-new-privileges:true" in text
    assert "cap_drop" in text


def test_build_script_checks_for_the_obsolete_pathlib_package():
    """Das PyPI-Paket 'pathlib' macht PyInstaller unbrauchbar.

    Die Meldung von PyInstaller ist verstaendlich, kommt aber erst mitten im
    Bau. Das Skript prueft vorher und sagt, was zu tun ist.
    """
    text = (PACKAGING / "build.sh").read_text(encoding="utf-8")
    assert "preflight" in text
    assert "pathlib" in text
    assert "pip uninstall pathlib" in text


def _pyinstaller_available() -> bool:
    """Ob das ``python3`` im Suchpfad PyInstaller importieren kann - genau
    das Programm, das build.sh aufruft."""
    try:
        return subprocess.run(["python3", "-c", "import PyInstaller"],
                              capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _pyinstaller_available(),
                    reason="PyInstaller nicht installiert")
def test_preflight_passes_in_a_sane_environment():
    result = subprocess.run(
        ["bash", "-c",
         f'source <(sed -n "/^preflight()/,/^}}/p" {PACKAGING / "build.sh"}); '
         "preflight"],
        capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert result.returncode == 0, result.stderr


def test_preflight_detects_the_obsolete_package(tmp_path):
    """Vorgetaeuschte Altlast - die Pruefung muss anschlagen."""
    fake = tmp_path / "site" / "pathlib-1.0.1.dist-info"
    fake.mkdir(parents=True)
    (fake / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: pathlib\nVersion: 1.0.1\n")

    result = subprocess.run(
        ["bash", "-c",
         f'source <(sed -n "/^preflight()/,/^}}/p" {PACKAGING / "build.sh"}); '
         "preflight"],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path),
             "PYTHONPATH": str(tmp_path / "site")})
    assert result.returncode == 1
    assert "pip uninstall pathlib" in result.stderr


def test_compare_names_the_broken_file(tmp_path, capsys):
    from releaser import cli

    good = tmp_path / "gut.json"
    good.write_text(json.dumps(payload("source")))
    bad = tmp_path / "kaputt.json"
    bad.write_text("kein json")

    assert cli.main(["metrics", "--compare", str(good), str(bad)]) == 2
    err = capsys.readouterr().err
    assert "kaputt.json" in err
    assert "JSON" in err


def test_version_flag(capsys):
    from releaser import __version__, cli

    with pytest.raises(SystemExit) as done:
        cli.main(["--version"])
    assert done.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_build_script_rebuilds_a_stale_binary():
    """Eine alte Einzeldatei wurde wiederverwendet - das AppImage war veraltet."""
    text = (PACKAGING / "build.sh").read_text(encoding="utf-8")
    assert "binary_is_stale" in text
    assert "-newer" in text


@needs_bundle
def test_bundle_knows_every_current_command():
    """Das Bündel muss dieselben Kommandos kennen wie der Quelltext."""
    from releaser.frontends.cli import main
    import io
    from contextlib import redirect_stdout, suppress

    buffer = io.StringIO()
    with redirect_stdout(buffer), suppress(SystemExit):
        main(["--help"])
    import re
    commands = set(re.findall(r"^\s{4}(\w+)\s", buffer.getvalue(), re.M))

    bundled = run_isolated(str(BUNDLE), "--help").stdout
    missing = {c for c in commands if c not in bundled}
    assert not missing, f"im Bündel fehlen: {sorted(missing)} - veraltet?"


# ================================================ Oberfläche im Bündel


def test_spec_bundles_the_gtk_overrides():
    """Ohne ``gi.overrides.Gtk`` brach die Oberfläche im Bündel beim Start ab
    ("set_text() takes exactly 3 arguments"). PyInstaller nimmt die Overrides
    nur mit, wenn sein GTK-3-Hook greift - auf einem Rechner mit nur GTK 4
    fehlten sie, ohne dass der Bau etwas meldete."""
    text = (PACKAGING / "pyinstaller.spec").read_text(encoding="utf-8")
    for module in ("gi.overrides.Gtk", "gi.overrides.Gdk"):
        assert f'"{module}"' in text, module


def test_spec_leaves_host_graphics_libraries_out():
    """GTK kommt vom Wirt - seine Grafikbibliotheken dürfen nicht in einer
    zweiten Fassung aus dem Bündel daneben geladen werden."""
    text = (PACKAGING / "pyinstaller.spec").read_text(encoding="utf-8")
    assert "HOST_PROVIDED" in text
    for name in ("libX11.", "libxcb", "libcairo", "libfontconfig."):
        assert f'"{name}"' in text, name


def _gui_can_start() -> bool:
    from releaser.frontends import gtkui

    return gtkui.is_available() and shutil.which("xvfb-run") is not None


@needs_appdir
@pytest.mark.skipif(not _gui_can_start(), reason="GTK 4 oder xvfb-run nicht vorhanden")
def test_bundled_gui_starts_without_errors(tmp_path):
    """Startet die Oberfläche aus dem AppDir und lässt sie einige Sekunden laufen.

    Endet der Prozess von selbst, ist sie abgestürzt oder hat nur den Hinweis
    auf fehlendes GTK ausgegeben; ein Traceback heißt, dass im Bündel etwas
    fehlt.
    """
    try:
        result = subprocess.run(
            ["xvfb-run", "-a", "timeout", "8", str(APPRUN)],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HOME": str(tmp_path)})
    except subprocess.TimeoutExpired:
        pytest.fail("xvfb-run hing")
    output = result.stdout + result.stderr
    assert "Traceback" not in output, output[-2000:]
    assert "nicht zur Verfügung" not in output, output[-2000:]
    assert result.returncode == 124, output[-2000:]      # von timeout beendet


# ==================================================== Release-Workflow


WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def test_release_workflow_builds_and_checks_before_publishing():
    """Der Workflow muss prüfen, bevor er veröffentlicht - und das AppImage
    so bauen, wie es lokal geprüft wurde."""
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML liest den Schlüssel "on" als Wahrheitswert
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["push"]["tags"] == ["v*"]

    build = workflow["jobs"]["appimage"]
    runs = "\n".join(step.get("run", "") for step in build["steps"])
    assert "PYTHON=.venv/bin/python ./packaging/build.sh" in runs
    assert "--system-site-packages" in runs          # PyGObject aus dem System
    assert "pytest tests" in runs
    assert "tests/test_packaging.py" in runs          # nach dem Bau erneut
    assert "GITHUB_REF_NAME" in runs                  # Tag passt zur Version

    digest = build["env"]["APPIMAGETOOL_SHA256"]
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)

    release = workflow["jobs"]["release"]
    assert release["needs"] == "appimage"
    assert release["permissions"] == {"contents": "write"}
    assert workflow["permissions"] == {"contents": "read"}
