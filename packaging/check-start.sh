#!/bin/sh
# Startet die Oberflaeche eines AppImage ohne Bildschirm und prueft, dass sie
# laeuft: nach einigen Sekunden noch offen und ohne Ladefehler.
#
#   packaging/check-start.sh build/mp3releaser-x86_64.AppImage [sekunden]
#
# Braucht xvfb-run und das GTK 4 des Systems. Der Release-Workflow ruft das
# in einem frischen Debian 13 auf: Dort ist GTK neuer als auf dem Bausystem,
# und was das Buendel selbst mitbringt, muss dazu passen. 0.25.0 brachte
# Pango mit und brach auf Debian 13 beim Start ab - auf Ubuntu 24.04, wo
# gebaut wird, fiel das nicht auf.
set -u
app=${1:?Pfad zum AppImage angeben}
seconds=${2:-15}
export APPIMAGE_EXTRACT_AND_RUN=1
log=$(mktemp)

"$app" --version || exit 1
status=0
xvfb-run -a timeout "$seconds" "$app" >"$log" 2>&1 || status=$?
cat "$log"

if [ "$status" -ne 124 ]; then
    echo "FEHLER: Oberflaeche nach weniger als $seconds s beendet (Status $status)" >&2
    exit 1
fi
if grep -q -e "Traceback" -e "undefined symbol" \
        -e "Failed to load shared library" "$log"; then
    echo "FEHLER: Oberflaeche meldet einen Ladefehler" >&2
    exit 1
fi
echo "Oberflaeche laeuft"
