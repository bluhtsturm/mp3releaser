#!/bin/sh
# Startet die Oberflaeche eines AppImage ohne Bildschirm und prueft, dass sie
# laeuft: nach einigen Sekunden noch offen und ohne Ladefehler.
#
#   packaging/check-start.sh build/mp3releaser-x86_64.AppImage [sekunden]
#
# Braucht Xvfb und das GTK 4 des Systems. Der Release-Workflow ruft das in
# frischen Systemen mit neuerem GTK als dem des Bausystems auf: Was das
# Buendel selbst mitbringt, muss dazu passen. 0.25.0 brachte Pango mit und
# brach auf Debian 13 ab, 0.25.1 brachte GLib mit und brach auf Debian
# testing ab - auf Ubuntu 24.04, wo gebaut wird, fiel beides nicht auf.
#
# Xvfb wird direkt gestartet, nicht ueber xvfb-run: Das scheiterte
# gelegentlich beim Aufraeumen seines Ordners und meldete dann einen Fehler,
# obwohl die Oberflaeche lief.
set -u
app=${1:?Pfad zum AppImage angeben}
seconds=${2:-15}
export APPIMAGE_EXTRACT_AND_RUN=1
log=$(mktemp)
display=$(mktemp)

"$app" --version || exit 1

# Xvfb waehlt selbst eine freie Nummer und schreibt sie, sobald es bereit ist
Xvfb -displayfd 3 -screen 0 1280x800x24 -nolisten tcp 3>"$display" \
    >/dev/null 2>&1 &
xvfb=$!
tries=0
while [ ! -s "$display" ] && [ "$tries" -lt 100 ]; do
    sleep 0.1
    tries=$((tries + 1))
done
if [ ! -s "$display" ]; then
    echo "FEHLER: Xvfb startet nicht" >&2
    kill "$xvfb" 2>/dev/null
    exit 1
fi

status=0
DISPLAY=:$(cat "$display") timeout "$seconds" "$app" >"$log" 2>&1 || status=$?
kill "$xvfb" 2>/dev/null
cat "$log"

if [ "$status" -ne 124 ]; then
    echo "FEHLER: Oberflaeche nach weniger als $seconds s beendet (Status $status)" >&2
    exit 1
fi
if grep -q -e "Traceback" -e "undefined symbol" \
        -e "Failed to load shared library" -e "nicht zur Verfügung" "$log"; then
    echo "FEHLER: Oberflaeche meldet einen Ladefehler" >&2
    exit 1
fi
echo "Oberflaeche laeuft"
