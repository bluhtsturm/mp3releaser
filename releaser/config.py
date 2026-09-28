"""Konfigurationsdatei.

Das Original hielt seine Einstellungen in ``MP3releaser.ini`` und bot sie über
rund vierzig Schaltflächen an. Hier steht dieselbe Information in einer
TOML-Datei - lesbar, versionierbar und für alle Oberflächen dieselbe Quelle::

    [naming]
    dir_pattern = "#Artist-#Album-#Source-#Fmt-#Year-#Grp"
    group = "GRP"
    case = "lower"
    companion_prefix = "00-"

    [tags]
    case = "capitalize"
    album_addition = "CDDA"
    write_apev2 = true

    [build]
    audio_crc = true
    sfv_include = ["log", "pdf"]

    [gui]
    start = "/home/ich/Musik/Eingang"

Rangfolge: ausdrücklich gesetzter Kommandozeilenschalter schlägt
Konfigurationsdatei, diese schlägt die eingebaute Voreinstellung.

Gesucht wird, wenn kein Pfad angegeben ist, in dieser Reihenfolge:
``./mp3releaser.toml``, ``./.mp3releaser.toml``,
``$XDG_CONFIG_HOME/mp3releaser/config.toml``,
``~/.config/mp3releaser/config.toml``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:                                   # Python 3.11+
    import tomllib
except ModuleNotFoundError:            # pragma: no cover
    tomllib = None                     # type: ignore[assignment]

CONFIG_NAME = "mp3releaser.toml"
SECTIONS = ("naming", "tags", "build", "gui")

#: Erlaubte Schluessel je Abschnitt. Ein Tippfehler bliebe sonst wirkungslos
#: und unbemerkt - das ist schlimmer als eine Meldung.
KNOWN_KEYS: dict[str, frozenset[str]] = {
    "naming": frozenset({
        "dir_pattern", "file_pattern", "group", "case", "space", "pipeline",
        "companion_prefix", "companion_pattern", "prefix_all",
        "case_dir", "case_file",
    }),
    "tags": frozenset({
        "case", "comment", "label_in_comment", "catalog_in_album",
        "album_addition", "write_totals", "write_id3v1", "id3v2",
        "strip_existing", "write_apev2", "write_lyrics3", "normalise_genre",
        "write_disc_for_single",
    }),
    "build": frozenset({
        "audio_crc", "sfv_include", "sfv_comment", "clean", "catalog_no",
        "template", "m3u_windows_paths", "release_date_format",
    }),
    # Nur die Desktop-Anwendung: wo die Auswahl beim Start steht
    "gui": frozenset({"start"}),
}


def _suggest(key: str, candidates: frozenset[str]) -> str:
    from difflib import get_close_matches

    near = get_close_matches(key, sorted(candidates), n=1, cutoff=0.7)
    return f" - meintest du {near[0]!r}?" if near else ""


class ConfigError(Exception):
    pass


@dataclass
class Config:
    naming: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, Any] = field(default_factory=dict)
    build: dict[str, Any] = field(default_factory=dict)
    gui: dict[str, Any] = field(default_factory=dict)
    source: Optional[Path] = None
    #: unbekannte Schluessel, die wirkungslos bleiben
    warnings: list[str] = field(default_factory=list)

    def section(self, name: str) -> dict[str, Any]:
        return getattr(self, name, {})

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.section(section).get(key, default)


def candidate_paths() -> list[Path]:
    paths = [Path.cwd() / CONFIG_NAME, Path.cwd() / f".{CONFIG_NAME}"]
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        paths.append(Path(xdg) / "mp3releaser" / "config.toml")
    paths.append(Path.home() / ".config" / "mp3releaser" / "config.toml")
    return paths


def find_config() -> Optional[Path]:
    for path in candidate_paths():
        if path.is_file():
            return path
    return None


def parse(text: str, source: Optional[Path] = None) -> Config:
    if tomllib is None:                # pragma: no cover
        raise ConfigError("TOML-Unterstützung fehlt (Python 3.11 oder neuer nötig)")
    try:
        data = tomllib.loads(text)
    except Exception as exc:           # tomllib.TOMLDecodeError
        raise ConfigError(f"Konfiguration nicht lesbar: {exc}") from exc

    unknown = set(data) - set(SECTIONS)
    if unknown:
        raise ConfigError(
            f"unbekannte Abschnitte: {sorted(unknown)} - erlaubt sind {list(SECTIONS)}")

    config = Config(source=source)
    for name in SECTIONS:
        value = data.get(name, {})
        if not isinstance(value, dict):
            raise ConfigError(f"Abschnitt [{name}] muss eine Tabelle sein")
        known = KNOWN_KEYS[name]
        for key in value:
            if key not in known:
                config.warnings.append(
                    f"[{name}] {key!r} wird nicht ausgewertet"
                    + _suggest(key, known))
        setattr(config, name, value)
    return config


def _read(path: Path) -> Config:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"{path} ist kein gültiges UTF-8: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path} nicht lesbar: {exc}") from exc
    return parse(text, source=path)


def load(path: Optional[str | Path] = None, required: bool = False) -> Config:
    """Lädt die Konfiguration. Ohne Pfad wird an den üblichen Orten gesucht."""
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise ConfigError(f"Konfiguration nicht gefunden: {p}")
        return _read(p)

    found = find_config()
    if found is None:
        if required:
            raise ConfigError(
                "keine Konfiguration gefunden, gesucht in: "
                + ", ".join(str(p) for p in candidate_paths()))
        return Config()
    return _read(found)


def resolve(config: Config, section: str, key: str,
            cli_value: Any, default: Any) -> Any:
    """Rangfolge: Kommandozeile, dann Konfiguration, dann Voreinstellung.

    ``cli_value is None`` bedeutet "nicht angegeben" - deshalb setzt die CLI
    ihre Voreinstellungen auf ``None`` statt auf den echten Wert.
    """
    if cli_value is not None:
        return cli_value
    value = config.get(section, key)
    return default if value is None else value


EXAMPLE = '''# mp3releaser - Beispielkonfiguration
# Ablage: ./mp3releaser.toml oder ~/.config/mp3releaser/config.toml

[naming]
dir_pattern = "#Artist-#Album-#Source-#Fmt-#Year-#Grp"
file_pattern = "#N-#Artist-#Trk"
group = "GRP"
case_dir = "capitalize"        # unchanged | lower | upper | capitalize
case_file = "lower"
space = "_"
pipeline = ["inch", "transliterate", "alnum", "forbidden", "spaces", "collapse", "trim"]
companion_prefix = "00-"       # Standard; "" schaltet es ab
prefix_all = true              # auch .sfv und .m3u

[tags]
case = "capitalize"
comment = ""
album_addition = ""            # z. B. "CDDA"
catalog_in_album = false
label_in_comment = false
write_totals = true
write_id3v1 = true
id3v2 = 4                      # 3 oder 4
write_apev2 = false
write_lyrics3 = false
normalise_genre = true

[build]
audio_crc = true
sfv_include = ["log"]
clean = false
catalog_no = false
release_date_format = "%Y-%m-%d"   # leeres Releasedatum = heute; "" schaltet es ab

[gui]
start = "~/Musik/Eingang"      # Verzeichnis, das die Auswahl beim Start zeigt
'''


#: Sprechender Name für den Export aus dem Paket.
load_config = load


def dump(config: "Config") -> str:
    """Schreibt die Konfiguration als TOML.

    Bewusst von Hand statt mit einer weiteren Abhaengigkeit: gebraucht werden
    nur Zeichenketten, Wahrheitswerte, Zahlen und Listen von Zeichenketten.
    """
    def value(item) -> str:
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, (int, float)):
            return str(item)
        if isinstance(item, (list, tuple)):
            return "[" + ", ".join(value(entry) for entry in item) + "]"
        return '"' + _escape(str(item)) + '"'

    lines = ["# mp3releaser - gespeicherte Einstellungen"]
    for section in SECTIONS:
        entries = config.section(section)
        if not entries:
            continue
        lines.append(f"\n[{section}]")
        for key in sorted(entries):
            lines.append(f"{key} = {value(entries[key])}")
    return "\n".join(lines) + "\n"


#: TOML-Escapes fuer Zeichen, die in einer einfachen Zeichenkette nicht
#: woertlich stehen duerfen.
_ESCAPES = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t",
            "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def _escape(text: str) -> str:
    """Macht eine Zeichenkette TOML-tauglich.

    Ein Zeilenumbruch oder Tabulator in einem Wert (etwa einem Kommentar)
    ergab frueher eine Datei, die ``tomllib`` beim naechsten Start nicht
    mehr lesen konnte.
    """
    out: list[str] = []
    for char in text:
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append(f"\\u{ord(char):04X}")
        else:
            out.append(char)
    return "".join(out)


def user_config_path() -> Path:
    """Wohin ``save`` ohne Pfad schreibt: die Benutzerkonfiguration.

    Ein gesetztes, aber leeres ``$XDG_CONFIG_HOME`` zaehlt wie ein fehlendes
    (so will es die XDG-Spezifikation). Frueher entstand dann ein relativer
    Pfad ``mp3releaser/config.toml`` im aktuellen Verzeichnis - dort, wo die
    Suche beim naechsten Start nicht nachsieht.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "mp3releaser" / "config.toml"


def save(config: "Config", path: Optional[str | Path] = None) -> Path:
    """Speichert die Konfiguration. Ohne Pfad ins Benutzerverzeichnis."""
    target = Path(path) if path else user_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dump(config), encoding="utf-8")
    return target
