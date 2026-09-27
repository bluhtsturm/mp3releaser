# Änderungen – Fehlerdurchsicht 0.22.1

Stand: 26.09.2026 · Version 0.22.0 → **0.22.1**

Der gesamte Code (Kern, Audio-Layer, alle vier Oberflächen, Web-JavaScript,
Build-Skript, Tests) wurde Zeile für Zeile durchgesehen. Jeder unten
aufgeführte Fehler wurde vor der Korrektur **nachgestellt** und ist jetzt
durch einen Regressionstest abgesichert. Die neuen Tests wurden zusätzlich
gegen den alten Code laufen gelassen: jeder Test zu einem behobenen Fehler
schlägt dort fehl und läuft mit den Korrekturen durch. Einige wenige
zusätzliche Tests sichern Nachbarfälle ab, die schon vorher funktionierten
(etwa, dass eine fremde Datei am Ziel weiterhin als Kollision gilt).

| | vorher | nachher |
|---|---|---|
| Tests | 672 | 734 |
| Ergebnis ohne GTK (Python 3.11) | 2 rot (Build-Skript), Rest grün | alle grün; übersprungen wird nur, wofür GTK, WebKitGTK oder ein gebautes Bündel fehlt |
| Ergebnis mit GTK 4, WebKitGTK und gebautem Bündel (Python 3.12) | – | alle 734 grün, nichts übersprungen |
| `pyflakes` | sauber | sauber |

Die Funktionalität ist unverändert; es wurden nur Fehler behoben und
Lücken geschlossen, an denen dieselbe Einstellung in verschiedenen
Oberflächen verschieden wirkte.

---

## 1. Audio-Layer

### 1.1 EC-3: Dauer und Bitrate langer Dateien falsch *(schwer)*
`releaser/audio/eac3.py` – `analyse_stream()` hörte nach der
Strukturanalyse (`max_frames × 8` Frames) auf zu **zählen**, obwohl die
Dokumentation „aus allen Frames hochgerechnet“ versprach. Jede Datei über
etwa 4–9 Minuten wurde zu kurz gemeldet, die Bitrate entsprechend zu hoch.

Nachgestellt mit einer 10-Minuten-Datei: **557 s / 482 kbps** statt
**600 s / 448 kbps**. Betroffen waren `#Tpti`, `#Ptit`, `#Cpti`, `#Br`
und die M3U-Laufzeiten jeder längeren Dolby-Digital-Plus-/Atmos-Datei.

Korrektur: Nach der Strukturanalyse werden die restlichen Frames über einen
schlanken Kopf-Leser (`_frame_header`) weitergezählt – ohne die aufwendige
BSI-Traversierung. Ergebnis jetzt 600,0 s / 448 kbps (ffprobe: 600,2 s /
448 kbps), Laufzeit 0,3 s für 10 Minuten.

### 1.2 EC-3: Center-Mischpegel bei 3/0 und 3/1 nicht übersprungen
`_parse_bsi_tail()` prüfte `acmod > 5` statt `acmod > 2` (ETSI TS 102 366,
FFmpeg `eac3_parser`). Bei den Kanalbelegungen 3/0 und 3/1 wurde der BSI ab
dem Mischpegel um 6 Bit verschoben gelesen – die JOC-/Atmos-Erkennung und die
Objektanzahl konnten falsch oder „unbekannt“ werden.

### 1.3 Eine beschädigte Datei brach den ganzen Scan ab
`releaser/audio/base.py` – die Reader fingen nur die „kein Header“-Fehler
ihres Formats. Eine abgeschnittene FLAC-Datei meldet mutagen aber als
allgemeines `mutagen.flac.error`, eine Datei ohne Leserecht als
`PermissionError`. Beides beendete `scan`, `build`, `wizard` und das Einlesen
in den Oberflächen mit einem Traceback. Jetzt wird die Datei übersprungen und
als Hinweis gemeldet (bzw. mit `--strict` sauber abgebrochen).

### 1.4 MP3 mit ABR galt als konstante Bitrate
`releaser/audio/mp3.py` – nur `VBR` wurde als variabel erkannt, `ABR` nicht.
Bei ABR hat jede Datei eine leicht andere mittlere Bitrate; der Scanner
meldete deshalb bei jedem ABR-Release fälschlich „unterschiedliche
Bitraten“, und `#Br` zeigte eine einzelne kbps-Zahl.

### 1.5 CUE-Übernahme ohne Herkunftstabelle stürzte ab
`releaser/audio/scan.py` – `_apply_cue_sheets()` erlaubt `origins=None`,
griff aber ungeprüft darauf zu (`AttributeError`).

## 2. CUE-Sheets (`releaser/cue.py`)

### 2.1 UTF-8-BOM verschluckte die erste Zeile
Beim Dekodieren als `utf-8` bleibt ein BOM als Zeichen U+FEFF stehen; die
erste Zeile – typischerweise `PERFORMER` oder `REM GENRE` – wurde nicht
erkannt und ging stillschweigend verloren. Der BOM wird jetzt entfernt.

### 2.2 `FILE` ohne Anführungszeichen: falscher Dateityp
Aus `FILE mix.mp3 MP3` wurde der Typ `mix.mp3 MP3`. Jetzt wird mit und ohne
Anführungszeichen korrekt getrennt.

## 3. Tags schreiben (`releaser/tagwriter.py`)

### 3.1 „Vorhandene Tags entfernen“ stürzte bei MP3 ohne Tag ab
`strip_existing` rief `delete()` auf einem leeren `ID3()`-Objekt auf, das
keinen Dateinamen kennt → `TypeError`. Gelöscht wird jetzt über die Datei.
Außerdem entfernt die Option – wie beschrieben „restlos“ – nun auch APEv2 und
Lyrics3v2, nicht nur ID3.

## 4. NFO-Erzeugung

### 4.1 Umbrochener Text wurde in der Fortsetzungszeile abgeschnitten
`releaser/skl.py`, `releaser/text.py` – Tracktitel, Notizen und
Gruppennachrichten wurden komplett mit der Breite der **Hauptzeile**
umbrochen. Ist das Feld der Fortsetzungszeile schmaler (z. B. eingerückt),
wurde der Rest jeder Zeile stillschweigend abgeschnitten – Text fehlte in der
.nfo. `wrap_value()` kennt jetzt eine eigene Breite für die erste Zeile; die
Folgezeilen werden mit der Breite der Fortsetzungszeile umbrochen.

### 4.2 `space_before_kbps` setzte das Leerzeichen an die falsche Stelle
`releaser/tags.py` – statt `320 kbps` entstand ` 320kbps`, was das Feld um
eine Spalte verschob.

### 4.3 `#Size` zeigte nach dem Taggen die alte Größe
`releaser/service.py` (`refresh_sizes`), `uistate.py`, `wizard.py` – Tags
ändern die Dateigröße (neuer ID3v2-Block, ID3v1, APEv2). Das Modell behielt
die Größen vom Einlesen, und die anschließend erzeugte .nfo stimmte nicht mit
den Dateien überein. Nach jedem Tag-Lauf (CLI `build --tag`, Wizard, Desktop,
Web) werden die Größen jetzt neu gelesen; CUE-Tracks, die sich eine Datei
teilen, im alten Verhältnis.

## 5. SFV (`releaser/sfv.py`)

### 5.1 SFV-Kommentar nur im ersten CD-Verzeichnis
Wurde der Kommentar als Generator übergeben, war er nach dem ersten SFV
erschöpft; die SFVs der übrigen CDs blieben ohne Kommentar.

## 6. Benennen (`releaser/naming.py`)

### 6.1 Falschmeldungen „kein bekannter Tag“
`unknown_tags()` fügte alle Textteile eines Musters zusammen, bevor es
suchte. Aus `x##Albumfoo` wurden so `x#` + `foo` = „`#foo`“ – ein Tag, den
niemand geschrieben hatte. Jetzt wird jeder Textteil einzeln geprüft.

### 6.2 Reine Schreibweisenänderung galt als Kollision
Auf Dateisystemen ohne Unterscheidung von Groß-/Kleinschreibung (FAT/exFAT,
SMB) „existiert“ `track.mp3` bereits, wenn `Track.mp3` umbenannt werden soll.
Der Plan meldete „Ziel existiert bereits“ und verweigerte die Umbenennung,
obwohl `apply_plan` genau diesen Fall über Zwischennamen beherrscht. Jetzt
wird geprüft, ob Ziel und Quelle dieselbe Datei sind.

## 7. Genres und Dupe-Prüfung

### 7.1 Genre-Alias „Alternative Rock“ lief ins Leere
`releaser/genres.py` – der Alias zeigte auf „Alternative Rock“, die
ID3v1-Liste führt Nummer 40 aber als „Alt. Rock“. Das Genre überlebte dadurch
nur in ID3v2. Ein neuer Test prüft, dass jeder Alias auflösbar ist.

### 7.2 Alle Alben eines Artists galten als „identisch“
`releaser/dupecheck.py` – `split_group()` hielt bei `Artist-Album` das Album
für das Gruppenkürzel und schnitt es ab. Jedes Album eines Artists wurde so
zum exakten Dupe-Treffer. Ein Gruppenkürzel wird jetzt erst ab drei
Bestandteilen abgetrennt.

## 8. Konfiguration (`releaser/config.py`, `releaser/service.py`)

### 8.1 Schlüssel, die stillschweigend nichts bewirkten
Die Datei akzeptierte Schlüssel ohne Warnung, die in manchen oder allen
Oberflächen ignoriert wurden – genau das, was die Konfiguration laut eigener
Doku verhindern soll:

| Schlüssel | vorher ignoriert in | jetzt |
|---|---|---|
| `[naming] companion_pattern` | überall | überall wirksam |
| `[naming] case`, `pipeline` | Desktop | überall wirksam |
| `[tags]` (komplett) | Desktop | überall wirksam |
| `[tags] write_disc_for_single` | Kommandozeile, Web | überall wirksam |
| `[build]` (komplett) | Desktop, Web | überall wirksam |
| `[build] sfv_comment` | Kommandozeile | überall wirksam |

Dafür gibt es jetzt in der Dienstschicht `tags_from_config()` und
`build_options_from_config()` neben `naming_from_config()` – eine Stelle für
alle Oberflächen.

### 8.2 Weitere Konfigurationsfehler
* **Einzelwert statt Liste:** `sfv_include = "log"` ergab die Endungen
  `l`, `o`, `g`; ebenso bei `pipeline`. Ein einzelner Wert ist jetzt ein
  Eintrag.
* **Ungültige Werte** (`case = "gross"`, `id3v2 = 2`) werden beim Laden als
  Konfigurationsfehler gemeldet statt erst mitten im Schreiben.
* **Speicherort:** Ein gesetztes, aber leeres `$XDG_CONFIG_HOME` führte zu
  einem relativen Pfad im aktuellen Verzeichnis – dort sucht der nächste
  Start nicht. Leer zählt jetzt wie nicht gesetzt (XDG-Spezifikation).
* **Speichern:** Zeilenumbrüche, Tabulatoren und andere Steuerzeichen in
  Werten wurden nicht maskiert; die gespeicherte Datei war danach für
  `tomllib` unlesbar.
* **Laden:** Eine Datei mit ungültigem UTF-8 endete in einem Traceback statt
  in einer Meldung.
* **Beispielkonfiguration** (`config --example`): Die Regelkette ließ `alnum`
  weg und wich damit von der eingebauten Voreinstellung ab.

## 9. Kommandozeile (`releaser/frontends/cli.py`)

* **`--no-prefix` wurde überstimmt**, wenn die Konfigurationsdatei
  `companion_prefix` setzte – entgegen der dokumentierten Rangfolge
  „Schalter schlägt Datei“.
* **Hilfetext zu `--pipeline`** nannte einen veralteten Standard (ohne
  `alnum`); er wird jetzt aus der tatsächlichen Voreinstellung erzeugt.
* **`render`:** Ein Tippfehler in einem Track, einer CD oder den
  Einstellungen der JSON-Datei endete in einem Traceback; jetzt kommt – wie
  schon bei Releasefeldern – eine Meldung mit dem unbekannten Feld.
* **`web`:** Die im Dockerfile gesetzte Variable `RELEASER_TEMPLATES` wurde
  nie ausgewertet. Sie dient jetzt als Rückfall für `--templates`, und die
  `[build]`-Einstellungen gelangen in die Weboberfläche.

## 10. Oberflächen-Logik (`releaser/uistate.py`)

* **Umbenennen meldete Erfolg, ohne etwas zu tun.** Änderte sich zwischen
  Vorschau und Ausführung etwas (Ziel inzwischen belegt), legte
  `perform_rename` den Plan still beiseite – die Oberfläche meldete trotzdem
  „N Umbenennung(en) ausgeführt“ und zeigte auf einen Ordner, der nicht
  existierte. Jetzt: Fehlermeldung mit den Kollisionen, nichts wird
  vorgetäuscht.
* **Fehler bei schreibenden Aktionen** (Tags schreiben, Umbenennen, Dateien
  erzeugen, Zurücknehmen) – etwa fehlendes Schreibrecht – kamen in der
  Weboberfläche als nackter „Internal Server Error“ an. Sie erscheinen jetzt
  als Meldung; nach einem teilweise fehlgeschlagenen Tag-Lauf werden
  Protokoll und Größen trotzdem nachgezogen.
* **Namensvorschau:** meldete bei Mehr-CD-Releases Kollisionen zwischen
  `CD1/01-intro.mp3` und `CD2/01-intro.mp3`, obwohl sie in verschiedenen
  Ordnern liegen (der eigentliche Plan wusste das), und listete CUE-Tracks
  einer Datei mehrfach.

## 11. Weboberfläche (`releaser/frontends/web/`)

* **„Ausführen“ verschwand dauerhaft:** Der Prüfen-Dialog blendete den Knopf
  aus, der Plan-Dialog blendete ihn nie wieder ein. Nach einem Klick auf
  „Prüfen“ ließ sich bis zum Neuladen der Seite kein Tag- oder
  Umbenennungsplan mehr ausführen.
* **JavaScript-Fehler** bei einer fehlgeschlagenen Anfrage im Plan- und im
  Erzeugen-Dialog (`payload` war `null`).
* **Zurücknehmen-Dialog** sprach immer von „Umbenennungen“, auch bei einem
  Tag-Lauf; die API liefert jetzt Art und Beschriftung des Eintrags.
* **Sitzungsverwaltung nicht threadsicher:** FastAPI führt die Endpunkte in
  einem Thread-Pool aus; gleichzeitige Anfragen konnten das
  Sitzungsverzeichnis während des Aufräumens verändern. Jetzt mit Sperre.
* **Geteilte Erzeugungsoptionen:** Jede Sitzung bekommt eine eigene Kopie –
  das Laden einer Vorlage verändert die Optionen, geteilt hätte eine Sitzung
  der anderen die Vorlage untergeschoben.
* **Vorlagenname mit NUL-Byte** führte zu einem Serverfehler 500 statt zu
  einer Ablehnung (400).

## 12. Desktop-Anwendung (`releaser/frontends/gtkui.py`)

* **„Als Standard speichern“ vernichtete Einstellungen:** Die
  Konfigurationsdatei wurde jedes Mal komplett neu geschrieben – ein von Hand
  gepflegter Abschnitt `[tags]` oder Schlüssel wie `audio_crc` und
  `sfv_include` waren danach weg. Jetzt wird die vorhandene Datei ergänzt
  (neue Funktion `save_defaults`, ohne GTK testbar); eine unlesbare Datei
  wird nicht überschrieben, sondern gemeldet.
* **`[tags]` und `[build]`** aus der Konfiguration gelten jetzt auch hier
  (siehe 8.1).
* Der Zurücknehmen-Dialog zeigte das interne Pseudofeld `#containers` als
  Tagnamen; der Tooltip nennt jetzt auch Tag-Läufe.

## 13. Prüfungen, Rückgängig, Dateiauswahl

* **Vorlagenprüfung** (`releaser/checks.py`): `#Grp`, `#Cd`, `#Cd2`, `#Ext`
  und `#Fmt` gibt es nur in Namensmustern. In einer .skl landen sie wörtlich
  in der NFO – die Prüfung meldete das nicht, weil sie das Vokabular der
  Namensmuster benutzte. Sie prüft jetzt gegen die SKL-Tags.
* **Rückgängig-Protokoll** (`releaser/undo.py`): Ein einzelner beschädigter
  Eintrag machte das ganze Protokoll unlesbar – auch alles andere darin ließ
  sich nicht mehr zurücknehmen. Beschädigte Einträge werden jetzt übergangen.
* **Dateiauswahl** (`releaser/browse.py`): Andere Ein-/Ausgabefehler als
  „keine Berechtigung“ (etwa auf Netzlaufwerken) kamen als unbehandelter
  Systemfehler statt als Meldung.

## 14. Build-Skript (`packaging/build.sh`)

Die Vorabprüfung importierte zuerst PyInstaller und suchte erst danach das
veraltete PyPI-Paket `pathlib`. PyInstaller scheitert aber gerade an diesem
Paket, und fehlt PyInstaller ganz, kam der eigentliche Hinweis nie zum Zug.
Die Reihenfolge ist umgedreht. Damit laufen auch die beiden zuvor roten Tests
in `tests/test_packaging.py`; der Test für eine „saubere Umgebung“ wird ohne
installiertes PyInstaller übersprungen statt fehlzuschlagen.

## 15. Dokumentation

* README: Kommentar zu `companion_prefix` widersprach dem Verhalten (das
  Präfix gilt standardmäßig auch für .sfv/.m3u; `prefix_all = false` schaltet
  das ab); „drei“ Namens-Tags waren tatsächlich fünf (`#Fmt` fehlte);
  Testzahl aktualisiert; Verweis auf diese Datei.
* Veraltete Kommentare in `naming.py` (Präfixregel) und
  `frontends/__init__.py` („geplant: Desktop und Web“ – beides existiert).
* Version auf **0.22.1** (`pyproject.toml`, `releaser/__init__.py`).

## 16. Nachkontrolle, AppImage und englische README

Beim zweiten Durchgang und beim Bau des AppImage kamen noch diese Punkte
hinzu:

* **Die Oberfläche im AppImage stürzte beim Start ab** (*schwer*).
  PyInstaller bündelte PyGObjects GTK-Overrides (`gi.overrides.Gtk`,
  `gi.overrides.Gdk`) nur, wenn sein GTK-3-Hook griff. Auf einem Rechner mit
  ausschließlich GTK 4 fehlten sie; die Oberfläche brach mit
  „`Gtk.TextBuffer.set_text() takes exactly 3 arguments`“ ab. Sie stehen jetzt
  ausdrücklich in `packaging/pyinstaller.spec`.
* **Grafikbibliotheken des Wirts im Bündel.** Über die Gdk-/cairo-Typelibs
  kamen X11, xcb, cairo, fontconfig, freetype und Verwandte ins Bündel – und
  wären neben dem GTK des Wirts in einer zweiten Fassung geladen worden. Sie
  bleiben jetzt draußen (dieselben Namen stehen auf der Ausschlussliste der
  AppImage-Gemeinschaft); das Bündel wurde dadurch 3 MB kleiner.
* **`build.sh`:** warnt, wenn der bauende Interpreter GTK 4 nicht importieren
  kann (sonst entstand still ein AppImage ohne Oberfläche); der Interpreter
  ist über `PYTHON=` wählbar; `appimagetool` läuft ohne FUSE, also auch in
  Containern und CI; der Download-Hinweis nennt die aktuelle Adresse
  (`AppImage/appimagetool` statt des eingestellten `AppImageKit`).
* **Unsichtbares Zeichen im Quelltext:** Die BOM-Korrektur aus 2.1 stand als
  wörtliches U+FEFF in `cue.py` (und im Test) – funktionsfähig, aber
  unsichtbar und von manchem Editor stillschweigend entfernt. Jetzt als
  Escape-Sequenz `"\ufeff"`.
* **Dokumentation:** Die README beschrieb die M3U noch mit
  Rückwärts-Schrägstrichen als Voreinstellung und nannte
  `$XDG_CONFIG_HOME` nicht als Suchort; `EINRICHTUNG.md` nannte eine veraltete
  Testzahl; eine Zeile der Tabelle in 8.1 war ungenau (die Weboberfläche las
  `case` und `pipeline` schon vorher über die Kommandozeile).
* **Englische README** (`README.en.md`): vollständige Übersetzung, beide
  Fassungen verweisen aufeinander. `tests/test_readme.py` prüft jetzt beide
  gleichermaßen (Kommandos, Modulbaum, Testzahl) und dazu die Testzahl in
  `EINRICHTUNG.md`.
* **AppImage veröffentlicht** unter `releases/` mit `SHA256SUMS` –
  Download-Hinweise in beiden README-Fassungen.

Das AppImage wurde selbst geprüft: ohne Python und ohne `PATH`
(`env -i`) läuft der komplette Ablauf durch (taggen, umbenennen, NFO, SFV,
M3U; `verify` meldet „3 ok“), und die Oberfläche startet unter Xvfb ohne
Fehler. Es braucht glibc 2.38 oder neuer (Ubuntu 24.04, Linux Mint 22,
Debian 13, Fedora 39 und neuer) und für die Oberfläche GTK 4 des Systems.

## Neue Tests

62 Tests, verteilt auf die jeweils zuständige Testdatei und dort
unter der Überschrift „Korrekturen (Fehlerdurchsicht)“ bzw. „Oberfläche im
Bündel“ zu finden:
`test_audio.py`, `test_extras.py`, `test_skl.py`, `test_tagwriter.py`,
`test_sfv_m3u.py`, `test_naming.py`, `test_checks.py`, `test_undo.py`,
`test_service.py`, `test_api.py`, `test_uistate.py`, `test_web.py`,
`test_gtkui.py`, `test_packaging.py`, dazu die auf beide Sprachfassungen
erweiterten Prüfungen in `test_readme.py`.
