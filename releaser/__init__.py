"""mp3releaser - Linux-Reimplementierung von MP3 Releaser 3.9.

Die Bibliothek ist in Schichten aufgebaut, die einzeln nutzbar sind::

    from releaser import scan_directory, Template, write_release_sfvs

    result = scan_directory("/pfad/zur/release")
    nfo = Template.from_file("vorlage.skl").render(result.release)

Der Renderer (``Template``, ``Settings``) haengt nicht vom Audio-Layer ab und
laeuft ohne mutagen. Umgekehrt kennt der Audio-Layer keine Templates.
"""

from .model import Disc, Release, Track
from .skl import Template, parse_line, render_line
from .tags import REGISTRY, Context, Settings
from .text import CharCase, format_size_mb, format_time, read_template, write_nfo

from .checksums import audio_crc32, crc32_file, format_crc
from .sfv import (
    SfvEntry,
    SfvFile,
    build_sfv,
    parse_sfv,
    read_sfv,
    verify_sfv,
    write_release_sfvs,
    write_sfv,
)
from .playlist import build_entries, render_m3u, write_m3u, write_release_m3us
from .companions import (
    COMPANION_SUFFIXES,
    COVER_SUFFIXES,
    find_companions,
    find_covers,
    remove_companions,
)

from .naming import (
    NamingProfile,
    companion_name,
    companion_stem,
    future_companion_stem,
    Pattern,
    RenamePlan,
    apply_plan,
    plan_rename,
    release_dirname,
    track_stem,
)
from .tagwriter import TagPlan, TagProfile, apply_tags, desired_tags, plan_tags

from . import browse, checks, cue, dupecheck, fields, genres, lyrics3
from . import provenance, undo
from . import runtime, service, uistate
from .uistate import Action, AppState, Level, Message
from .fields import Consumer, FieldSpec, FieldView, build_views, group_views
from .provenance import Origin, OriginMap
from .browse import AccessError, LocalSource, Mount, MountedSource, Source
from .runtime import Variant, collect_metrics, detect_variant
from .service import BuildOptions, BuildOutcome, ScanOutcome
from .config import Config, ConfigError, load_config

__version__ = "0.24.0"

__all__ = [
    "__version__",
    # Modell
    "Release", "Disc", "Track",
    # NFO
    "Template", "Settings", "Context", "REGISTRY", "parse_line", "render_line",
    "read_template", "write_nfo", "CharCase", "format_time", "format_size_mb",
    # Pruefsummen und Begleitdateien
    "crc32_file", "audio_crc32", "format_crc",
    "SfvFile", "SfvEntry", "build_sfv", "parse_sfv", "read_sfv", "write_sfv",
    "verify_sfv", "write_release_sfvs",
    "build_entries", "render_m3u", "write_m3u", "write_release_m3us",
    "COMPANION_SUFFIXES", "COVER_SUFFIXES", "find_companions", "find_covers",
    "remove_companions",
    # Benennen und Taggen
    "NamingProfile", "Pattern", "RenamePlan", "plan_rename", "apply_plan",
    "release_dirname", "track_stem", "companion_name", "companion_stem", "future_companion_stem",
    "TagProfile", "TagPlan", "plan_tags", "apply_tags", "desired_tags",
    # Ergaenzungen aus dem Original
    "browse", "checks", "cue", "dupecheck", "fields", "genres", "lyrics3",
    "provenance", "undo",
    "runtime", "service", "uistate",
    "AppState", "Action", "Level", "Message",
    "Origin", "OriginMap",
    "Consumer", "FieldSpec", "FieldView", "build_views", "group_views",
    "Source", "LocalSource", "MountedSource", "Mount", "AccessError",
    "Variant", "detect_variant", "collect_metrics",
    "BuildOptions", "BuildOutcome", "ScanOutcome",
    "Config", "ConfigError", "load_config",
]


def __getattr__(name: str):
    """Audio-Layer erst bei Bedarf laden - er braucht mutagen."""
    if name in ("scan_directory", "read_file", "AudioInfo", "AudioError",
                "ScanResult"):
        from . import audio

        return getattr(audio, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
