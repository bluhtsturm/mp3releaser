"""Tests für das gemeinsame Fundament der drei Oberflächen."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser import runtime, service
from releaser.model import Release
from releaser.naming import NamingProfile
from releaser.tagwriter import TagProfile

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


def encode(target: Path, *args: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    *args, str(target), "-y"], check=True)
    return target


def make_release(tmp_path: Path, count: int = 2) -> Path:
    root = tmp_path / "Artist-Album-2026-GRP"
    for no in range(1, count + 1):
        encode(root / f"0{no}-x.mp3", "-c:a", "libmp3lame",
               "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
               "-metadata", "album=Das Album", "-metadata", f"track={no}/{count}",
               "-metadata", "date=2026")
    return root


def make_template(tmp_path: Path) -> Path:
    template = tmp_path / "t.skl"
    template.write_bytes("#Release            \n#N #Trk             \n".encode("cp437"))
    return template


# ============================================================= Dienstschicht


@needs_ffmpeg
def test_scan_returns_release_and_warnings(tmp_path):
    root = make_release(tmp_path)
    outcome = service.scan(root)
    assert outcome.release.total_tracks == 2
    assert outcome.root == root
    assert isinstance(outcome.warnings, list)


@needs_ffmpeg
def test_build_creates_all_three_companion_files(tmp_path):
    root = make_release(tmp_path)
    release = service.scan(root).release
    options = service.BuildOptions(template=make_template(tmp_path))

    outcome = service.build(release, root, options)
    suffixes = sorted(p.suffix for p in outcome.created)
    assert suffixes == [".m3u", ".nfo", ".sfv"]
    assert outcome.ok


@needs_ffmpeg
def test_build_can_skip_parts(tmp_path):
    root = make_release(tmp_path)
    release = service.scan(root).release
    options = service.BuildOptions(nfo=False, m3u=False)

    outcome = service.build(release, root, options)
    assert [p.suffix for p in outcome.created] == [".sfv"]


def test_build_without_template_is_rejected(tmp_path):
    release = Release(artist="A", album="B")
    with pytest.raises(ValueError):
        service.build(release, tmp_path, service.BuildOptions(template=None))


@needs_ffmpeg
def test_build_clean_removes_stale_files(tmp_path):
    root = make_release(tmp_path)
    (root / "veraltet.sfv").write_bytes(b"; alt\r\n")
    release = service.scan(root).release
    options = service.BuildOptions(template=make_template(tmp_path), clean=True)

    outcome = service.build(release, root, options)
    assert [p.name for p in outcome.removed] == ["veraltet.sfv"]
    assert not (root / "veraltet.sfv").exists()


@needs_ffmpeg
def test_preview_rename_touches_nothing(tmp_path):
    root = make_release(tmp_path)
    release = service.scan(root).release
    before = sorted(p.name for p in root.iterdir())

    plan = service.preview_rename(release, root, NamingProfile(group="GRP"))
    assert plan.changes
    assert sorted(p.name for p in root.iterdir()) == before


@needs_ffmpeg
def test_perform_rename_reports_the_new_root(tmp_path):
    root = make_release(tmp_path)
    release = service.scan(root).release

    plan, new_root = service.perform_rename(release, root,
                                            NamingProfile(group="GRP"))
    assert plan.is_safe
    assert new_root.name == "der_artist-das_album-2026-GRP"
    assert new_root.is_dir()
    assert not root.exists()


@needs_ffmpeg
def test_perform_rename_leaves_everything_alone_on_collision(tmp_path):
    root = make_release(tmp_path)
    release = service.scan(root).release
    for track in release.tracks:
        track.title = "Gleicher Titel"

    plan, new_root = service.perform_rename(
        release, root, NamingProfile(file_pattern="#Trk"))
    assert not plan.is_safe
    assert new_root == root
    assert root.is_dir()


@needs_ffmpeg
def test_process_runs_tag_rename_and_build_in_order(tmp_path):
    """Das SFV muss nach dem Taggen und Umbenennen entstehen."""
    from releaser.sfv import verify_sfv

    root = make_release(tmp_path)
    options = service.BuildOptions(template=make_template(tmp_path),
                                   audio_crc=True)
    outcome = service.process(
        root, options,
        naming=NamingProfile(group="GRP"),
        tags=TagProfile(comment="ein kommentar"),
        do_tag=True, do_rename=True,
    )

    assert outcome.ok
    assert outcome.root.name == "der_artist-das_album-2026-GRP"
    sfv = next(p for p in outcome.created if p.suffix == ".sfv")
    assert verify_sfv(sfv).success          # Pruefsummen passen zum Endzustand


@needs_ffmpeg
def test_process_stops_before_building_on_collision(tmp_path):
    root = make_release(tmp_path)
    options = service.BuildOptions(template=make_template(tmp_path))
    outcome = service.process(
        root, options,
        naming=NamingProfile(file_pattern="#Album"),   # beide Tracks gleich
        do_rename=True,
    )
    assert not outcome.ok
    assert outcome.collisions
    assert outcome.created == []


@needs_ffmpeg
def test_companion_names_preview(tmp_path):
    root = make_release(tmp_path)
    release = service.scan(root).release
    names = service.companion_names(release, NamingProfile())
    assert all(name.startswith("00-") for name in names.values())


def test_dupe_check_via_service(tmp_path):
    (tmp_path / "Der_Artist-Das_Album-CDDA-2026-GRP").mkdir()
    index, key, matches = service.check_dupe(
        "der.artist-das.album-WEB-2026-ANDERE", tmp_path)
    assert len(index) == 1
    assert key == "der-artist-das-album"
    assert matches and matches[0].exact


# ============================================================ Laufzeitmessung


def test_variant_detection_defaults_to_source(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("APPDIR", raising=False)
    monkeypatch.delenv("container", raising=False)
    monkeypatch.setattr(runtime, "_in_container", lambda: False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert runtime.detect_variant() is runtime.Variant.SOURCE


def test_variant_detection_appimage(monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/tmp/mp3releaser.AppImage")
    assert runtime.detect_variant() is runtime.Variant.APPIMAGE


def test_variant_detection_container(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("APPDIR", raising=False)
    monkeypatch.setenv("container", "docker")
    assert runtime.detect_variant() is runtime.Variant.CONTAINER


def test_every_variant_has_a_label():
    for variant in runtime.Variant:
        assert variant.label


def test_collect_returns_plausible_numbers():
    metrics = runtime.collect()
    assert metrics.package_bytes > 10_000          # der Quelltext ist da
    assert metrics.total_bytes >= metrics.package_bytes
    assert metrics.python.count(".") == 2
    if metrics.resident_kb is not None:
        assert metrics.resident_kb > 0
    if metrics.startup_seconds is not None:
        assert 0 <= metrics.startup_seconds < 3600


def test_container_variant_is_marked_as_privileged(monkeypatch):
    monkeypatch.setattr(runtime, "detect_variant",
                        lambda: runtime.Variant.CONTAINER)
    metrics = runtime.collect()
    assert metrics.needs_privileges is True
    assert "Container" in metrics.data_location
    assert any("Docker-Socket" in n for n in metrics.notes)


def test_source_variant_is_not_privileged(monkeypatch):
    monkeypatch.setattr(runtime, "detect_variant", lambda: runtime.Variant.SOURCE)
    metrics = runtime.collect()
    assert metrics.needs_privileges is False


def test_human_bytes():
    assert runtime.human_bytes(None) == "unbekannt"
    assert runtime.human_bytes(512) == "512 B"
    assert runtime.human_bytes(1536) == "1.5 KB"
    assert runtime.human_bytes(5 * 1024 * 1024) == "5 MB"


def test_format_metrics_contains_every_row():
    metrics = runtime.collect()
    text = runtime.format_metrics(metrics)
    for label, _ in runtime.as_rows(metrics):
        assert label in text


def test_as_dict_is_json_serialisable():
    payload = runtime.as_dict(runtime.collect())
    restored = json.loads(json.dumps(payload))
    assert restored["variant"] in {v.value for v in runtime.Variant}
    assert "notes" in restored


def test_cli_metrics_json(capsys):
    from releaser import cli

    assert cli.main(["metrics", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "total_bytes" in payload


def test_cli_metrics_table(capsys):
    from releaser import cli

    assert cli.main(["metrics"]) == 0
    out = capsys.readouterr().out
    assert "Form" in out and "Daten liegen" in out


# ============================================================ Oberflaechen


def test_cli_entry_point_still_works():
    """Der alte Einstiegspunkt muss nach dem Umzug weiter funktionieren."""
    from releaser import cli
    from releaser.frontends import cli as frontend_cli

    assert cli.main is frontend_cli.main


def test_frontends_package_exposes_cli():
    from releaser import frontends

    assert hasattr(frontends, "cli")


# ============================================================ Gefuehrter Modus


class ScriptedConsole:
    """Beantwortet Rückfragen aus einer Liste und merkt sich die Ausgabe."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.lines: list[str] = []
        self.interactive = True

    # dieselbe Schnittstelle wie releaser.frontends.wizard.Console
    def say(self, text=""):
        self.lines.append(text)

    def ask(self, question, default=True):
        self.say(question)
        if not self.answers:
            return default
        answer = self.answers.pop(0)
        return default if answer == "" else answer in ("j", "ja", "y")

    def ask_text(self, question, default=""):
        self.say(question)
        return self.answers.pop(0) if self.answers else default

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@needs_ffmpeg
def test_wizard_walks_all_four_steps(tmp_path):
    from releaser.frontends import wizard

    root = make_release(tmp_path)
    console = ScriptedConsole(["j", "j", "GRP", "j", "j", "j"])
    code = wizard.run(root, template=make_template(tmp_path), console=console)

    assert code == 0
    for step in ("Schritt 1 von 4", "Schritt 2 von 4",
                 "Schritt 3 von 4", "Schritt 4 von 4"):
        assert step in console.text
    assert "Fertig" in console.text


@needs_ffmpeg
def test_wizard_stops_when_the_data_is_wrong(tmp_path):
    from releaser.frontends import wizard

    root = make_release(tmp_path)
    console = ScriptedConsole(["n"])
    assert wizard.run(root, console=console) == 1
    assert "Schritt 2" not in console.text


@needs_ffmpeg
def test_wizard_skips_steps_that_are_declined(tmp_path):
    from releaser.frontends import wizard

    root = make_release(tmp_path)
    before = sorted(p.name for p in root.iterdir())
    console = ScriptedConsole(["j", "n", "GRP", "n", "n", "n"])

    assert wizard.run(root, console=console) == 0
    assert sorted(p.name for p in root.iterdir()) == before   # nichts passiert
    assert console.text.count("uebersprungen") == 2


@needs_ffmpeg
def test_wizard_refuses_to_answer_itself_without_a_terminal(tmp_path):
    from releaser.frontends.wizard import Console, run

    root = make_release(tmp_path)
    before = sorted(p.name for p in root.iterdir())
    console = Console(interactive=False, write=lambda text: None)

    assert run(root, console=console) == 1
    assert sorted(p.name for p in root.iterdir()) == before


@needs_ffmpeg
def test_wizard_reports_collisions_instead_of_renaming(tmp_path):
    from releaser.frontends import wizard
    from releaser.naming import NamingProfile

    root = make_release(tmp_path)
    console = ScriptedConsole(["j", "n", "j", "n", "n"])
    code = wizard.run(root, console=console,
                      naming=NamingProfile(group="GRP", file_pattern="#Album"))

    assert code == 0
    assert "Kollisionen" in console.text
    assert root.is_dir()


@needs_ffmpeg
def test_wizard_uses_the_same_service_layer(tmp_path):
    """Der gefuehrte Modus darf keine eigene Ablauflogik haben."""
    from releaser.frontends import wizard

    root = make_release(tmp_path)
    console = ScriptedConsole(["j", "j", "GRP", "j", "j", "j"])
    wizard.run(root, template=make_template(tmp_path), console=console)

    # Voreinstellung: Ordner kapitalisiert, Begleitdateien klein
    new_root = tmp_path / "Der_Artist-Das_Album-2026-GRP"
    created = sorted(p.suffix for p in new_root.iterdir() if p.suffix != ".mp3")
    assert created == [".m3u", ".nfo", ".sfv"]


# ============================================ Präfix der Begleitdateien


@needs_ffmpeg
def test_prefix_applies_to_every_generated_file(tmp_path):
    root = make_release(tmp_path)
    naming = NamingProfile(
        group="GRP", companion_prefix="00-",
        prefixed_suffixes=frozenset({".nfo", ".sfv", ".m3u", ".jpg"}))
    release = service.scan(root).release
    options = service.BuildOptions(template=make_template(tmp_path))

    created = service.build(release, root, options, naming).created
    assert all(p.name.startswith("00-") for p in created), \
        [p.name for p in created]


@needs_ffmpeg
def test_prefix_can_be_limited_to_the_nfo(tmp_path):
    root = make_release(tmp_path)
    naming = NamingProfile(
        group="GRP", companion_prefix="00-",
        prefixed_suffixes=frozenset({".nfo", ".jpg", ".jpeg", ".png", ".pdf"}))
    release = service.scan(root).release
    options = service.BuildOptions(template=make_template(tmp_path))

    created = {p.suffix: p.name for p in
               service.build(release, root, options, naming).created}
    assert created[".nfo"].startswith("00-")
    assert not created[".sfv"].startswith("00-")
    assert not created[".m3u"].startswith("00-")


@needs_ffmpeg
def test_generated_names_share_one_stem(tmp_path):
    root = make_release(tmp_path)
    naming = NamingProfile(group="GRP", companion_prefix="00-",
                           prefixed_suffixes=frozenset({".nfo", ".sfv", ".m3u"}))
    release = service.scan(root).release
    options = service.BuildOptions(template=make_template(tmp_path))

    stems = {Path(p.name).stem for p in
             service.build(release, root, options, naming).created}
    assert len(stems) == 1, stems


# ================================ Eine Voreinstellung für alle Oberflächen


def test_preset_is_capitalized_directory_and_lowercase_files():
    from releaser.naming import Scope

    profile = service.naming_from_config()
    assert profile.charcase[Scope.DIRECTORY].value == "capitalize"
    assert profile.charcase[Scope.FILENAME].value == "lower"
    assert profile.companion_prefix == "00-"
    assert ".sfv" in profile.prefixed_suffixes


def test_config_overrides_the_preset():
    from releaser.config import parse
    from releaser.naming import Scope

    config = parse('[naming]\ncase_dir = "lower"\nprefix_all = false\n'
                   'group = "AUSDATEI"\n')
    profile = service.naming_from_config(config)
    assert profile.charcase[Scope.DIRECTORY].value == "lower"
    assert profile.group == "AUSDATEI"
    assert ".sfv" not in profile.prefixed_suffixes


def test_explicit_group_beats_the_config():
    from releaser.config import parse

    config = parse('[naming]\ngroup = "AUSDATEI"\n')
    assert service.naming_from_config(config, group="VONHAND").group == "VONHAND"


def test_all_frontends_share_one_preset(tmp_path, monkeypatch):
    """Sonst zeigt eine Fassung andere Namen an als die andere."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from releaser.browse import Mount, MountedSource
    from releaser.frontends.gtkui import build_state
    from releaser.frontends.web.app import create_app
    from releaser.naming import Scope

    desktop = build_state().naming
    web = create_app(MountedSource([Mount("m", tmp_path)])).state.store.naming

    for scope in (Scope.DIRECTORY, Scope.FILENAME):
        assert desktop.charcase[scope] == web.charcase[scope]
    assert desktop.dir_pattern == web.dir_pattern
    assert desktop.companion_prefix == web.companion_prefix


def test_service_without_a_profile_uses_the_preset():
    """Ein Aufruf ohne Profil darf nicht anders benennen als die Oberflächen."""
    from releaser.naming import Scope

    default = service.naming_from_config()
    assert default.charcase[Scope.DIRECTORY].value == "capitalize"

    # build() und process() greifen auf dieselbe Voreinstellung zurueck
    import inspect

    source = inspect.getsource(service.build) + inspect.getsource(service.process)
    assert "NamingProfile()" not in source
    assert "naming_from_config()" in source


def test_wizard_without_a_profile_uses_the_preset():
    import inspect

    from releaser.frontends import wizard

    source = inspect.getsource(wizard.run)
    assert "NamingProfile()" not in source
    assert "naming_from_config()" in source


@needs_ffmpeg
def test_m3u_uses_forward_slashes_by_default(tmp_path):
    """Unter Linux findet kein Abspieler eine Datei hinter CD1\\01-….flac."""
    root = tmp_path / "Artist-Album-2026-GRP"
    for disc in (1, 2):
        folder = root / f"CD{disc}"
        encode(folder / "01-x.mp3", "-c:a", "libmp3lame",
               "-metadata", f"title=Titel {disc}", "-metadata", "artist=A",
               "-metadata", "album=B", "-metadata", f"disc={disc}/2")

    release = service.scan(root).release
    created = service.build(release, root,
                            service.BuildOptions(nfo=False, sfv=False)).created
    super_m3u = next(p for p in created if p.parent == root)
    text = super_m3u.read_bytes().decode("cp437")

    assert "/" in text and chr(92) not in text


@needs_ffmpeg
def test_windows_paths_can_be_requested(tmp_path):
    root = tmp_path / "Artist-Album-2026-GRP"
    for disc in (1, 2):
        encode(root / f"CD{disc}" / "01-x.mp3", "-c:a", "libmp3lame",
               "-metadata", "artist=A", "-metadata", "album=B",
               "-metadata", f"disc={disc}/2")

    release = service.scan(root).release
    options = service.BuildOptions(nfo=False, sfv=False, m3u_windows_paths=True)
    created = service.build(release, root, options).created
    super_m3u = next(p for p in created if p.parent == root)
    assert chr(92) in super_m3u.read_bytes().decode("cp437")


# ------------------------------------------------ Korrekturen (Fehlerdurchsicht)


def test_naming_config_is_read_completely():
    """case, pipeline und companion_pattern galten nur auf der Kommandozeile."""
    from releaser.config import parse
    from releaser.naming import Scope

    config = parse('[naming]\ncase = "upper"\npipeline = ["spaces", "trim"]\n'
                   'companion_pattern = "#Catnr"\n')
    profile = service.naming_from_config(config)
    assert profile.charcase[Scope.DIRECTORY].value == "upper"
    assert profile.charcase[Scope.FILENAME].value == "upper"
    assert profile.pipeline == ("spaces", "trim")
    assert profile.companion_pattern == "#Catnr"


def test_case_dir_beats_the_general_case():
    from releaser.config import parse
    from releaser.naming import Scope

    config = parse('[naming]\ncase = "upper"\ncase_dir = "lower"\n')
    profile = service.naming_from_config(config)
    assert profile.charcase[Scope.DIRECTORY].value == "lower"
    assert profile.charcase[Scope.FILENAME].value == "upper"


def test_tags_config_reaches_the_profile():
    from releaser.config import parse

    config = parse('[tags]\ncase = "capitalize"\nwrite_id3v1 = false\n'
                   'id3v2 = 3\nwrite_disc_for_single = true\n'
                   'comment = "hallo"\n')
    profile = service.tags_from_config(config)
    assert profile.charcase.value == "capitalize"
    assert profile.write_id3v1 is False
    assert profile.id3v2_version == 3
    assert profile.write_disc_for_single is True
    assert profile.comment == "hallo"
    assert service.tags_from_config() == TagProfile()


def test_invalid_tag_settings_are_config_errors():
    from releaser.config import ConfigError, parse

    with pytest.raises(ConfigError, match="id3v2"):
        service.tags_from_config(parse("[tags]\nid3v2 = 2\n"))
    with pytest.raises(ConfigError, match="Schreibweise"):
        service.tags_from_config(parse('[tags]\ncase = "gross"\n'))


def test_build_config_reaches_the_options():
    from releaser.config import parse

    config = parse('[build]\naudio_crc = true\nsfv_include = "log"\n'
                   'sfv_comment = "gruss"\nclean = true\ncatalog_no = true\n'
                   'm3u_windows_paths = true\n')
    options = service.build_options_from_config(config)
    assert options.audio_crc and options.clean and options.use_catalog_no
    assert options.m3u_windows_paths
    # ein einzelner Wert ist ein Eintrag, nicht eine Folge von Buchstaben
    assert options.sfv_include == ("log",)
    assert options.sfv_comment == "gruss"
    assert options.template is None


def test_refresh_sizes_reads_the_current_file_sizes(tmp_path):
    from releaser.model import Disc, Track

    single = tmp_path / "a.mp3"
    single.write_bytes(b"x" * 100)
    shared = tmp_path / "mix.flac"
    shared.write_bytes(b"y" * 600)
    release = Release(discs=[Disc(1, tracks=[
        Track(1, "a", 10.0, path=str(single), size_bytes=50),
        Track(2, "b", 10.0, path=str(shared), size_bytes=100),
        Track(3, "c", 20.0, path=str(shared), size_bytes=200),
    ])])
    service.refresh_sizes(release)
    assert [t.size_bytes for t in release.tracks] == [100, 200, 400]


@needs_ffmpeg
def test_sizes_in_the_model_follow_the_tag_writing(tmp_path):
    """Die .nfo nach einem Tag-Lauf zeigte die Groesse von vorher."""
    root = make_release(tmp_path)
    scanned = service.scan(root)
    before = scanned.release.size_bytes

    service.write_tags(scanned.release, TagProfile(comment="ein kommentar"))
    actual = sum(Path(t.path).stat().st_size for t in scanned.release.tracks)
    assert actual != before
    assert scanned.release.size_bytes == actual


def test_overrides_beat_the_config_for_every_key():
    from releaser.config import parse

    config = parse('[naming]\npipeline = ["spaces"]\n')
    profile = service.naming_from_config(config, pipeline=("trim",),
                                         companion_pattern="#Artist")
    assert profile.pipeline == ("trim",)
    assert profile.companion_pattern == "#Artist"


# ================================================ Releasedatum vorbelegen


def test_empty_release_date_becomes_today():
    from datetime import date

    from releaser.model import Release
    from releaser.provenance import Origin, OriginMap

    release, origins = Release(), OriginMap()
    assert service.fill_release_date(release, origins,
                                     today=date(2026, 9, 28)) is True
    assert release.release_date == "2026-09-28"
    assert origins.get("release_date") is Origin.SYSTEM
    assert Origin.SYSTEM.label == "aus der Systemzeit"


def test_existing_release_date_is_kept():
    from datetime import date

    from releaser.model import Release

    release = Release(release_date="01.01.2020")
    assert service.fill_release_date(release, today=date(2026, 9, 28)) is False
    assert release.release_date == "01.01.2020"


def test_release_date_format_is_configurable_and_can_be_switched_off():
    from datetime import date

    from releaser.model import Release

    german = Release()
    service.fill_release_date(german, fmt="%d.%m.%Y", today=date(2026, 9, 28))
    assert german.release_date == "28.09.2026"

    off = Release()
    assert service.fill_release_date(off, fmt="") is False
    assert off.release_date == ""


def test_release_date_format_comes_from_the_build_section():
    from releaser.config import parse

    assert (service.build_options_from_config(None).release_date_format
            == "%Y-%m-%d")
    config = parse('[build]\nrelease_date_format = "%d.%m.%Y"\n')
    assert (service.build_options_from_config(config).release_date_format
            == "%d.%m.%Y")
    off = parse('[build]\nrelease_date_format = ""\n')
    assert service.build_options_from_config(off).release_date_format == ""
    assert off.warnings == []                       # bekannter Schluessel


@needs_ffmpeg
def test_scan_fills_the_release_date_with_today(tmp_path):
    from datetime import date

    from releaser.provenance import Origin

    outcome = service.scan(make_release(tmp_path))
    assert outcome.release.release_date == date.today().strftime("%Y-%m-%d")
    assert outcome.origins.get("release_date") is Origin.SYSTEM
    assert "release_date" not in outcome.origins.uncertain()


@needs_ffmpeg
def test_scan_without_release_date_format_leaves_it_empty(tmp_path):
    outcome = service.scan(make_release(tmp_path), release_date_format="")
    assert outcome.release.release_date == ""


@needs_ffmpeg
def test_nfo_carries_the_release_date(tmp_path):
    """Die .nfo bekommt das Datum - über die Kommandozeile wie im Fenster."""
    from datetime import date

    from releaser import cli

    def read_nfo(path):
        return path.read_bytes().decode("cp437")

    root = make_release(tmp_path)
    template = tmp_path / "d.skl"
    template.write_bytes("Datum: #Rdate              \n".encode("cp437"))
    today = date.today()

    assert cli.main(["nfo", str(root), str(template),
                     "-o", str(tmp_path / "a.nfo")]) == 0
    assert today.strftime("%Y-%m-%d") in read_nfo(tmp_path / "a.nfo")

    config = tmp_path / "eigen.toml"
    config.write_text('[build]\nrelease_date_format = "%d.%m.%Y"\n',
                      encoding="utf-8")
    assert cli.main(["--config", str(config), "nfo", str(root), str(template),
                     "-o", str(tmp_path / "b.nfo")]) == 0
    assert today.strftime("%d.%m.%Y") in read_nfo(tmp_path / "b.nfo")


@needs_ffmpeg
def test_build_uses_the_configured_release_date_format(tmp_path):
    from datetime import date

    root = make_release(tmp_path)
    template = tmp_path / "d.skl"
    template.write_bytes("Datum: #Rdate              \n".encode("cp437"))
    options = service.BuildOptions(template=template, sfv=False, m3u=False,
                                   release_date_format="%d.%m.%Y")

    outcome = service.process(root, options)
    nfo = next(p for p in outcome.created if p.suffix == ".nfo")
    assert date.today().strftime("%d.%m.%Y") in nfo.read_bytes().decode("cp437")


@needs_ffmpeg
def test_scan_json_carries_the_release_date(tmp_path):
    """scan -o und render ergeben dieselbe .nfo wie nfo und build."""
    import json
    from datetime import date

    from releaser import cli

    out = tmp_path / "r.json"
    assert cli.main(["scan", str(make_release(tmp_path)), "-o", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["release_date"] == date.today().strftime("%Y-%m-%d")


# ================================================ alles in einem Schritt


@needs_ffmpeg
def test_process_writes_no_tags_when_the_rename_would_collide(tmp_path):
    """Erst pruefen, dann anfassen. Vorher standen die Tags schon in den
    Dateien, wenn das Umbenennen danach an einer Kollision scheiterte."""
    from mutagen.id3 import ID3

    root = make_release(tmp_path)
    track = sorted(root.glob("*.mp3"))[0]
    before = track.read_bytes()
    outcome = service.process(
        root, service.BuildOptions(template=make_template(tmp_path)),
        naming=NamingProfile(file_pattern="#Album"),
        tags=service.TagProfile(comment="geaendert"),
        do_tag=True, do_rename=True)
    assert outcome.collisions and not outcome.ok
    assert track.read_bytes() == before                # Datei unveraendert
    assert not [frame for frame in ID3(track).values()
                if "geaendert" in str(frame)]


@needs_ffmpeg
def test_cli_release_does_everything_with_the_saved_template(tmp_path,
                                                             monkeypatch,
                                                             capsys):
    """Eine Eingabe fuer das fertige Release - ohne Vorlage auf der
    Kommandozeile nimmt sie die gespeicherte bzw. mitgelieferte."""
    from releaser import cli

    root = make_release(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["release", str(root), "--group", "GrP"]) == 0
    err = capsys.readouterr().err
    assert "standard.skl" in err and "Release erstellt" in err

    target = tmp_path / "Der_Artist-Das_Album-2026-GrP"
    assert f"Ordner: {target}" in err
    assert target.is_dir(), sorted(p.name for p in tmp_path.iterdir())
    names = sorted(p.name for p in target.iterdir())
    assert "00-der_artist-das_album-2026-grp.nfo" in names
    assert "00-der_artist-das_album-2026-grp.sfv" in names
    assert "01-der_artist-titel_1.mp3" in names


@needs_ffmpeg
def test_cli_release_without_any_template_is_an_error(tmp_path, monkeypatch,
                                                      capsys):
    from releaser import cli

    monkeypatch.setattr(service, "bundled_template", lambda: None)
    root = make_release(tmp_path)
    assert cli.main(["release", str(root)]) == 2
    assert "keine Vorlage" in capsys.readouterr().err
    assert root.is_dir()
