#!/bin/sh
# Baut die gebuendelte Fassung und daraus ein AppImage.
#
#   ./packaging/build.sh            beides, soweit moeglich
#   ./packaging/build.sh binary     nur die Einzeldatei
#   ./packaging/build.sh appdir     nur das AppDir (ohne appimagetool)
#
# Voraussetzungen: Python 3.11+, PyInstaller. Fuer das fertige AppImage
# zusaetzlich appimagetool; fehlt es, entsteht trotzdem ein lauffaehiges
# AppDir, das sich mit ./AppDir/AppRun direkt starten laesst.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
DIST="$BUILD/dist"
APPDIR="$BUILD/AppDir"
TARGET="${1:-all}"

log() { printf '==> %s\n' "$*"; }

preflight() {
    python3 - <<'CHECK' || exit 1
import sys

if sys.version_info < (3, 11):
    sys.exit(f"Python 3.11 oder neuer noetig, gefunden: "
             f"{sys.version_info.major}.{sys.version_info.minor}")

try:
    import PyInstaller  # noqa: F401
except ImportError:
    sys.exit("PyInstaller fehlt:\n    pip install pyinstaller")

# Das PyPI-Paket "pathlib" ist eine Rueckportierung aus Python-2-Zeiten und
# ueberschreibt das gleichnamige Standardmodul. PyInstaller bricht deshalb ab.
try:
    from importlib.metadata import distribution

    location = distribution("pathlib").locate_file("")
except Exception:
    pass
else:
    sys.exit(
        "Das veraltete PyPI-Paket 'pathlib' ist installiert und macht\n"
        f"PyInstaller unbrauchbar. Gefunden in: {location}\n\n"
        "Entfernen (gefahrlos - das pathlib der Standardbibliothek ist ein\n"
        "anderes und bleibt unberuehrt):\n"
        f"    {sys.executable} -m pip uninstall pathlib"
    )
CHECK
}

build_binary() {
    preflight
    log "Einzeldatei bauen"
    python3 -m PyInstaller "$ROOT/packaging/pyinstaller.spec" \
        --distpath "$DIST" --workpath "$BUILD/work" --noconfirm >/dev/null
    log "fertig: $DIST/mp3releaser ($(du -h "$DIST/mp3releaser" | cut -f1))"
}

binary_is_stale() {
    # Kein Bündel, oder eine Quelldatei ist neuer als das Bündel. Ohne diese
    # Pruefung wurde eine alte Einzeldatei wiederverwendet - das AppImage
    # kannte dann Kommandos nicht, die es im Quelltext laengst gab.
    [ -x "$DIST/mp3releaser" ] || return 0
    [ -n "$(find "$ROOT/releaser" "$ROOT/packaging" -newer "$DIST/mp3releaser" \
              -type f \( -name '*.py' -o -name '*.spec' -o -name '*.html' \) \
              -print -quit)" ]
}

build_appdir() {
    if binary_is_stale; then
        build_binary
    else
        log "Einzeldatei ist aktuell - wird wiederverwendet"
    fi

    log "AppDir zusammenstellen"
    rm -rf "$APPDIR"
    mkdir -p "$APPDIR/usr/bin" \
             "$APPDIR/usr/share/applications" \
             "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
             "$APPDIR/usr/share/mp3releaser"

    cp "$DIST/mp3releaser" "$APPDIR/usr/bin/mp3releaser"
    cp "$ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"
    chmod +x "$APPDIR/AppRun" "$APPDIR/usr/bin/mp3releaser"

    cp "$ROOT/packaging/appimage/mp3releaser.desktop" "$APPDIR/"
    cp "$ROOT/packaging/appimage/mp3releaser.desktop" \
       "$APPDIR/usr/share/applications/"
    cp "$ROOT/packaging/appimage/mp3releaser.svg" "$APPDIR/"
    cp "$ROOT/packaging/appimage/mp3releaser.svg" \
       "$APPDIR/usr/share/icons/hicolor/scalable/apps/"

    # Beispielvorlage und Beispielkonfiguration mitgeben - ohne Vorlage
    # kann das Programm keine .nfo erzeugen.
    cp "$ROOT/templates/standard.skl" "$APPDIR/usr/share/mp3releaser/" 2>/dev/null || true
    cp "$ROOT/templates/example.skl" "$APPDIR/usr/share/mp3releaser/" 2>/dev/null || true
    "$DIST/mp3releaser" config --example \
        > "$APPDIR/usr/share/mp3releaser/mp3releaser.toml" 2>/dev/null || true

    log "fertig: $APPDIR ($(du -sh "$APPDIR" | cut -f1))"
}

build_appimage() {
    build_appdir
    if ! command -v appimagetool >/dev/null 2>&1; then
        cat <<'HINT'
==> appimagetool nicht gefunden - das AppDir ist trotzdem lauffaehig:
        ./build/AppDir/AppRun metrics
    Fuer die fertige Einzeldatei:
        wget -O appimagetool https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
        chmod +x appimagetool
        ./appimagetool build/AppDir build/mp3releaser-x86_64.AppImage
HINT
        return 0
    fi
    log "AppImage bauen"
    appimagetool "$APPDIR" "$BUILD/mp3releaser-x86_64.AppImage"
    log "fertig: $BUILD/mp3releaser-x86_64.AppImage"
}

case "$TARGET" in
    binary)   build_binary ;;
    appdir)   build_appdir ;;
    appimage) build_appimage ;;
    all)      build_appimage ;;
    *) echo "unbekanntes Ziel: $TARGET" >&2; exit 2 ;;
esac
