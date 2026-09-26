"""Audio-Layer: Dateien lesen und in Release-Strukturen ueberfuehren."""

from .base import AUDIO_EXTENSIONS, AudioError, AudioInfo, read_file
from . import eac3, flac, mp3, mp4, vorbis  # registrieren ihre Reader
from .scan import ScanResult, find_audio_files, parse_filename, scan_directory

__all__ = [
    "AUDIO_EXTENSIONS", "AudioError", "AudioInfo", "read_file",
    "ScanResult", "find_audio_files", "parse_filename", "scan_directory",
    "eac3", "flac", "mp3", "mp4", "vorbis",
]
