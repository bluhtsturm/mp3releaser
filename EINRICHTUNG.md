# Einrichten und ausprobieren

Kurzanleitung für den ersten Start. Ausführlich steht alles im `README.md`.

## 1. Kern und Kommandozeile

Gebraucht wird Python 3.11 oder neuer.

```bash
cd mp3releaser
python3 -m venv .venv && . .venv/bin/activate
pip install -e .                 # installiert mutagen mit
```

Erster Lauf auf einer Kopie eines Releases — **nie auf dem Original**, das
Programm benennt um und schreibt Tags:

```bash
cp -r /pfad/zu/einem/release /tmp/probe
releaser scan /tmp/probe                       # was erkannt wurde
releaser fields /tmp/probe templates/standard.skl
releaser rename /tmp/probe --group GRP         # nur Vorschau
releaser wizard /tmp/probe templates/standard.skl
```

`rename`, `tag` und der geführte Modus zeigen immer erst einen Plan. Erst
`--apply` beziehungsweise die Rückfrage führt etwas aus.

Alles auf einmal:

```bash
releaser build /tmp/probe templates/standard.skl \
    --tag --rename --group GRP --audio-crc
releaser verify /tmp/probe/*.sfv
```

## 2. Tests

```bash
pip install pytest
python3 -m pytest tests -q
```

Erwartet: **734 bestanden**. Tests, deren Werkzeug fehlt, werden übersprungen
statt zu scheitern. Für den vollen Umfang:

```bash
sudo apt install ffmpeg xvfb python3-gi gir1.2-gtk-4.0 gir1.2-webkit-6.0
pip install fastapi uvicorn httpx pyinstaller
```

* **ffmpeg** — erzeugt die Audiodateien für die Tests
* **xvfb** — virtuelles Display für GTK und WebKit
* **gir1.2-gtk-4.0** — Desktop-Oberfläche
* **gir1.2-webkit-6.0** — prüft die Webseite in einer echten Browser-Engine
* **fastapi, uvicorn, httpx** — Weboberfläche
* **pyinstaller** — gebündelte Fassung

## 3. Desktop-Oberfläche

```bash
releaser gui                                   # ganzes Dateisystem
releaser gui --mounts "eingang:/tmp/probe"     # beschränkt, wie im Container
releaser gui --group GRP --template templates/standard.skl
```

Links auswählen, „Einlesen", rechts die Felder. Die Eingabefelder sind so
breit wie ihr Platz in der geladenen Vorlage; der Zähler daneben wird rot,
bevor etwas abgeschnitten wird.

## 4. Weboberfläche

```bash
pip install fastapi uvicorn
RELEASER_MOUNTS="eingang:/tmp/probe" \
  releaser web --templates templates
# http://127.0.0.1:8000
```

Oder im Container — dann zuerst die Ordner in `docker-compose.yml` anpassen:

```bash
mkdir -p data/eingang data/archiv
cp -r /pfad/zu/einem/release data/eingang/
docker compose up --build
```

Sichtbar ist ausschließlich, was unter `volumes` steht.

## 5. Gebündelte Fassung und AppImage

```bash
pip install pyinstaller
./packaging/build.sh binary      # eine Datei, ~21 MB, läuft ohne Python
./packaging/build.sh appdir      # startbar über ./build/AppDir/AppRun
```

Die grafische Oberfläche kommt nur ins Bündel, wenn der bauende Interpreter
PyGObject und GTK 4 importieren kann – `build.sh` warnt, wenn nicht. Unter
Ubuntu/Debian ist das meist das System-Python; ein anderes wählt man so:

```bash
PYTHON=python3.12 ./packaging/build.sh
```

Für die fertige Einzeldatei zusätzlich `appimagetool` in den Suchpfad legen,
dann baut `./packaging/build.sh` ohne Argument alles bis zum AppImage:

```bash
wget -O ~/.local/bin/appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x ~/.local/bin/appimagetool
./packaging/build.sh             # -> build/mp3releaser-x86_64.AppImage
```

Das fertige AppImage braucht auf dem Zielrechner glibc 2.38 oder neuer
(Ubuntu 24.04, Linux Mint 22, Debian 13, Fedora 39 und neuer) und für die
grafische Oberfläche GTK 4 des Systems. Die Kommandozeile läuft ohne GTK.

## 6. Die drei Formen vergleichen

```bash
releaser metrics --json > cli.json
./build/AppDir/AppRun metrics --json > appimage.json
docker compose run --rm cli metrics --json > container.json

releaser metrics --compare cli.json appimage.json container.json
```

## 7. Konfiguration statt Schalter

```bash
releaser config --example > mp3releaser.toml
```

Die Datei wird in `./mp3releaser.toml` und `~/.config/mp3releaser/config.toml`
gesucht. Kommandozeilenschalter haben Vorrang. Unbekannte Schlüssel werden
gemeldet, mit Vorschlag.

## Falls etwas klemmt

| Meldung | Ursache |
|---|---|
| `GTK 4 nicht verfügbar` | `apt install python3-gi gir1.2-gtk-4.0` |
| `Die Weboberfläche braucht FastAPI` | `pip install fastapi uvicorn` |
| `Keine eingehaengten Verzeichnisse` | `RELEASER_MOUNTS` setzen oder `--mounts` |
| `Ziel existiert bereits` | ein früherer Lauf liegt noch da |
| `Plan hat Kollisionen` | zwei Tracks bilden auf denselben Namen ab |
| `The 'pathlib' package is an obsolete backport` | `pip uninstall pathlib` — siehe unten |

### Das PyPI-Paket `pathlib`

Bricht `build.sh` mit dieser Meldung ab, liegt eine Rückportierung aus
Python-2-Zeiten im Pfad, die das gleichnamige Standardmodul überschreibt:

```bash
python3 -m pip uninstall pathlib
```

Gefahrlos — das `pathlib` der Standardbibliothek ist ein anderes und bleibt
unberührt. `build.sh` prüft das inzwischen vorab und sagt es deutlicher.

Fehler erscheinen als Meldung mit Exit-Code 2, nicht als Traceback. Kommt
doch einer, ist das ein Fehler im Programm.
