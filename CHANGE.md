# Änderungen – 0.24.1: Konfiguration finden, auch im Container

Stand: 28.09.2026 · Version 0.24.0 → **0.24.1**

Anlass war die Frage, wo die Konfigurationsdatei von AppImage und Container
liegt. Beim Nachsehen fielen zwei Lücken auf. Von den 6 neuen Tests schlagen
5 gegen 0.24.0 fehl; einer hält den beschriebenen Pfad im Container fest, den
die Suche schon vorher kannte.

| | vorher | nachher |
|---|---|---|
| Tests | 806 | 812 |
| Ergebnis mit GTK 4, WebKitGTK und gebautem Bündel (Python 3.12) | alle grün | alle 812 grün, nichts übersprungen |
| `pyflakes` | sauber | sauber |

## 1. Wo die Konfiguration liegt

| Form | Datei |
|---|---|
| AppImage, Desktop | `~/.config/mp3releaser/config.toml` – legt der Speichern-Knopf an |
| Kommandozeile | dieselbe; eine `mp3releaser.toml` im aktuellen Verzeichnis hat Vorrang |
| Container | `config/mp3releaser/config.toml` neben `docker-compose.yml` (neu) |

## 2. Container: Konfiguration eingebunden

**Vorher** gab es für den Container keine: Das Image enthielt keine
Konfigurationsdatei, `docker-compose.yml` hängte keine ein, und die
Weboberfläche hat keinen Speichern-Knopf. Der Dienst lief immer mit den
Voreinstellungen.

**Jetzt:**
* `Dockerfile` setzt `XDG_CONFIG_HOME=/config`; der Container liest
  `/config/mp3releaser/config.toml`.
* `docker-compose.yml` hängt `./config` nur lesend unter `/config` ein, für
  den Dienst `releaser` und für `cli`.
* Eingehängt wird bewusst der **Ordner**, nicht die Datei: Fehlt eine
  eingehängte Datei, legt Docker an ihrer Stelle einen leeren Ordner an –
  als root, den man danach nur mit `sudo` wieder loswird. Der Ordner
  `config/mp3releaser/` liegt deshalb schon im Repository, mit einer kurzen
  Beschreibung (`README.md`). Ohne `config.toml` darin gelten die
  Voreinstellungen, genau wie vorher.
* `.gitignore` schließt alles in `config/mp3releaser/` außer der
  Beschreibung aus; `.dockerignore` hält `config/` und `mp3releaser.toml` aus
  dem Build-Kontext – private Einstellungen gelangen nicht ins Image.
* Beim Start nennt der Dienst die Datei: `Konfiguration:
  /config/mp3releaser/config.toml` oder `Konfiguration: keine gefunden - es
  gelten die Voreinstellungen` – zu sehen mit `docker compose logs releaser`.

Im echten Container geprüft: ohne `config.toml` die Voreinstellungen; mit
Datei nach `docker compose restart releaser` Gruppe, Schreibweise und
Datumsformat aus der Datei; `[gui]` und `[build] template` aus einer
kopierten AppImage-Konfiguration stören nicht; `docker compose run --rm -T cli
config --example > config/mp3releaser/config.toml` ergibt eine gültige
Vorlage.

## 3. `releaser config`

* Zeigt alle Abschnitte. `[gui]` fehlte seit 0.24.0 in der Anzeige, obwohl
  der Abschnitt in der Datei stand und wirkte.
* Ohne Datei nennt der Befehl die Orte, an denen er gesucht hat, und wohin
  die Desktop-Anwendung beim ersten Speichern schreibt. Vorher stand dort nur
  „keine Konfiguration gefunden“.
* `config --example` nennt im Kopf die drei Ablageorte.

## 4. Dokumentation

* `README.md`, `README.en.md`: Tabelle „wo die Datei je nach Form liegt“ im
  Abschnitt Konfiguration, neuer Abschnitt „Einstellungen im Container“ bzw.
  „Settings in the container“, Eintrag unter „Aus der dreizehnten
  Erprobung“, Testzahl.
* `EINRICHTUNG.md`: Container-Schritt mit optionaler Konfiguration, Ablageorte.
* `GITHUB.md`: was mit hochgeht und was nicht.

## Neue Tests

* `tests/test_extras.py`: `config` zeigt alle Abschnitte, ohne Datei die
  Suchorte; der Start der Weboberfläche nennt die Konfiguration, mit und ohne
  Datei.
* `tests/test_packaging.py`: `Dockerfile` und `docker-compose.yml` zeigen auf
  denselben Ort, für beide Dienste; der Ordner liegt im Repository, die Datei
  ist von Git und Docker ausgeschlossen; der beschriebene Pfad wird gesucht.

---

# Änderungen – 0.24.0: Standard speichern, Releasedatum, FLAC-Version

Stand: 28.09.2026 · Version 0.23.0 → **0.24.0**

Rückmeldungen aus dem Test des AppImage 0.23.0. Jeder Fehler wurde vor der
Korrektur nachgestellt. Von den 37 neuen Tests schlagen 36 gegen 0.23.0 fehl
und laufen jetzt durch; einer sichert einen Nachbarfall ab, der schon vorher
funktionierte (ein `ENCODER`-Tag bei FLAC ohne brauchbaren Vendor-String).

| | vorher | nachher |
|---|---|---|
| Tests | 769 | 806 |
| Ergebnis mit GTK 4, WebKitGTK und gebautem Bündel (Python 3.12) | alle grün | alle 806 grün, nichts übersprungen |
| `pyflakes` | sauber | sauber |

## 1. „Als Standard speichern“ blieb ohne Wirkung *(schwer)*

**Nachgestellt.** Vorlage laden, Gruppe und Schreibweisen einstellen, auf
das Speichern-Symbol klicken, das AppImage neu starten: nichts davon war
eingestellt.

**Ursachen – drei, die sich gegenseitig verdeckten:**

1. **Das AppImage las die Konfiguration nicht.** Ohne Argumente gestartet
   (Doppelklick) ruft `packaging/entrypoint.py` die Oberfläche über `run()`
   auf. `run()` baute dann einen leeren Zustand
   (`AppState(source=LocalSource())`) – ohne Konfiguration, ohne gespeicherte
   Vorlage, ohne Gruppe, ohne Schreibweisen, sogar ohne die mitgelieferte
   Standardvorlage. Gespeichert wurde also, aber nie wieder geladen. Nur
   `releaser gui` ging über `build_state()` und lud alles.
   *Jetzt:* `run()` ohne Zustand nimmt `build_state()` – beide Wege starten
   gleich.
2. **Die Bestätigung war unsichtbar.** „Standard gespeichert“ stand nur in
   der Meldungsliste, und die ist eingeklappt. Beim Klick passierte sichtbar
   nichts. *Jetzt:* Ein Fenster zeigt, was wohin gespeichert wurde.
3. **Die mitgelieferte Vorlage wurde mit ihrem AppImage-Pfad gespeichert.**
   Das AppImage hängt sich bei jedem Start unter einem neuen Namen ein
   (`/tmp/.mount_XXXXXX`). Ein gespeicherter Pfad dorthin zeigte beim
   nächsten Start ins Leere, und die Oberfläche lud dann **gar keine**
   Vorlage. *Jetzt:* Mitgelieferte Vorlagen stehen nur mit ihrem Namen in der
   Konfiguration (`template = "standard.skl"`) und werden darüber wieder
   gefunden. Fehlt eine gespeicherte Vorlage, lädt das Programm die
   mitgelieferte und meldet es.

**Außerdem:**
* Gespeichert wird in die Datei, aus der die Einstellungen beim Start kamen.
  Lag eine `mp3releaser.toml` im Arbeitsverzeichnis, gewann die beim Start –
  das Speichern ging aber nach `~/.config` und war beim nächsten Start
  wieder verdeckt.
* Eine eigene Vorlage wird mit absolutem Pfad gespeichert; ein relativer
  hinge vom Startverzeichnis ab.
* Eine kaputte Konfigurationsdatei (oder ein unbrauchbarer Wert wie
  `case_dir = "schraeg"`) verhindert den Start nicht mehr: Das Fenster
  öffnet sich mit der Voreinstellung und nennt den Fehler. Per Doppelklick
  gestartet gäbe es sonst keinerlei Rückmeldung. Überschrieben wird eine
  kaputte Datei beim Speichern weiterhin nicht.
* `releaser --config DATEI gui` reicht die angegebene Datei jetzt an die
  Oberfläche weiter; die las vorher selbst nach und übersah `--config`.

## 2. Das ausgewählte Verzeichnis wird mitgespeichert

Gespeichert wird jetzt auch das Verzeichnis, das die Auswahl links zeigt
(`[gui] start`). Beim Start öffnet die Auswahl genau diesen Ordner – bisher
begann sie immer an der Wurzel. Ist ein Release eingelesen, zählt der Ordner,
in dem es liegt, nicht das Release selbst: Beim nächsten Start sieht man so
den Eingangsordner mit dem nächsten Release darin. Gibt es das Verzeichnis
nicht mehr, beginnt die Auswahl an der Wurzel, mit einem Hinweis. Wer an der
Wurzel speichert, startet auch wieder dort. `--start` hat Vorrang und öffnet
das angegebene Verzeichnis jetzt ebenfalls direkt.

Was „Als Standard speichern“ insgesamt festhält:

| | Schlüssel |
|---|---|
| die geladene `.skl` | `[build] template` |
| Gruppenname | `[naming] group` |
| Verzeichnis der Auswahl | `[gui] start` (neu) |
| Verzeichnis- und Dateimuster | `[naming] dir_pattern`, `file_pattern` |
| Schreibweise Ordner / Dateien | `[naming] case_dir`, `case_file` |
| „00-“ vor den Begleitdateien | `[naming] companion_prefix`, `prefix_all` |

## 3. Releasedatum aus der Systemzeit

Ein leeres Releasedatum (`#Rdate`) wird beim Einlesen mit dem heutigen Datum
vorbelegt, als `2026-09-28`. Am Feld steht die Herkunft „aus der
Systemzeit“. Ein vorhandener Wert bleibt unangetastet, von Hand
überschreiben geht wie bei jedem Feld.

Das Format ist einstellbar, ein leerer Wert schaltet das Vorbelegen ab:

```toml
[build]
release_date_format = "%d.%m.%Y"    # 28.09.2026
```

Es gilt überall gleich: Desktop, Web, geführter Modus und die Kommandos
`nfo`, `build`, `scan`, `rename`, `check` und `fields`
(`service.fill_release_date`).

## 4. FLAC: Encoder-Fassung erkannt

Bei MP3 kommt der Encoder aus dem LAME-Header (`LAME 3.100`). Bei FLAC las
das Programm nur ein `ENCODER`-Tag – das schreibt der Referenz-Encoder aber
nicht, das Feld blieb leer. Seine Fassung steht im Vendor-String des
Kommentarblocks: `reference libFLAC 1.4.3 20230623`. Daraus wird jetzt
`FLAC 1.4.3`.

* Wie der LAME-Header bei MP3 geht der Vendor-String einem `ENCODER`-Tag
  vor: Er stammt vom Encoder selbst.
* Andere Encoder bleiben, wie sie sich nennen (ffmpeg: `Lavf60.16.100`).
* `Mutagen …` im Vendor-String ist kein Encoder, sondern das Tag-Programm,
  das einen fehlenden Kommentarblock angelegt hat – dann gilt das
  `ENCODER`-Tag.
* Der Referenz-Encoder schreibt einen Kommentarblock ohne Einträge. mutagen
  meldet ihn als leer, aber nicht als fehlend – die Prüfung unterscheidet
  beides.

## 5. Dokumentation

* `README.md`, `README.en.md`: neuer Abschnitt „Als Standard speichern“ bzw.
  „Save as default“, `[gui]` und `release_date_format` im
  Konfigurationsbeispiel, FLAC in der Formattabelle, Abschnitt „Aus der
  dreizehnten Erprobung“, Testzahl.
* `EINRICHTUNG.md`: Speichern in der Desktop-Anwendung, Testzahl.
* `releaser config --example` nennt `release_date_format` und `[gui] start`.

## Neue Tests

* `tests/test_gtkui.py`: Start ohne Argumente im echten GTK-Fenster (wie
  beim Doppelklick auf das AppImage) mit gespeicherter Gruppe, Vorlage und
  Verzeichnis; kompletter Rundlauf speichern → neu starten; Verzeichnis
  öffnen, fehlendes Verzeichnis, `--start` vor dem Gespeicherten, Speichern
  an der Wurzel; eingelesenes Release speichert seinen Ordner; mitgelieferte
  Vorlage über zwei verschiedene AppImage-Einhängepunkte; kaputte und
  unbrauchbare Konfiguration; Speichern in die gelesene Datei; `--config`
  bei `gui`; Bestätigungsfenster und Zusammenfassung.
* `tests/test_service.py`: Releasedatum vorbelegen, vorhandenes behalten,
  Format und Abschalten, `[build] release_date_format`, über `scan`, `nfo`
  (mit `--config`), `build` und `scan -o`.
* `tests/test_web.py`: Releasedatum samt Herkunft im Webformular.
* `tests/test_audio.py`: Vendor-String → Encoder (Referenz-Encoder, ffmpeg,
  mutagen, leer), Vorrang vor dem `ENCODER`-Tag, Rückfall auf das Tag, eine
  echte Datei aus dem `flac`-Programm ohne jedes Tag.
* Geändert: `test_missing_saved_template_is_reported` erwartet jetzt die
  mitgelieferte Vorlage statt gar keiner.

---

# Änderungen – 0.23.0: Dateinamen von Hand, zwei Quellen

Stand: 27.09.2026 · Version 0.22.1 → **0.23.0**

Zwei Rückmeldungen aus der Erprobung des AppImage.

| | vorher | nachher |
|---|---|---|
| Tests | 736 | 769 |
| Ergebnis mit GTK 4, WebKitGTK und gebautem Bündel (Python 3.12) | alle grün | alle 769 grün, nichts übersprungen |
| Prüfungen im echten Browser (`tools/webcheck.py`) | 15 | 16 |
| `pyflakes` | sauber | sauber |

## 1. Dateinamen im Reiter „Namen“ von Hand bearbeiten

**Anlass.** Aus dem Titel „Los Marañones I - Nattern Narren“ machte die
Regelkette `los_maranones_i-nattern_narren`. Gemeint war `_-_`. Ursache ist
die Regel `collapse`, die Folgen von Trennzeichen wie `_-_` zu einem `-`
zusammenzieht – für die meisten Titel gewollt, für diesen nicht. Die
Dateinamen ließen sich nur über das Muster beeinflussen, nicht einzeln.

**Jetzt.** Im Reiter „Namen“ steht jede Datei in einer eigenen Zeile:
bisheriger Name, ein Eingabefeld mit dem neuen Namen (ohne Endung), die
Endung, und `↺`. Das gilt für die Desktop-Anwendung (AppImage) wie für die
Weboberfläche.

* Das Feld ist mit dem Namen aus dem Dateimuster vorgefüllt. Überschreiben
  und Eingabetaste (bzw. Feld verlassen) übernimmt den Namen; die Zeile ist
  dann als „von Hand“ markiert.
* Ein Name von Hand wird **wörtlich** übernommen: keine Regelkette, keine
  Schreibweise. Nur was keinen gültigen Dateinamen ergäbe, fällt weg –
  verbotene Zeichen (`/ \ : * ? " < > |`), Punkte am Rand (ein führender
  Punkt versteckte die Datei). Leerzeichen werden zum eingestellten
  Trennzeichen, eine mitgetippte Endung (`.mp3`) wird nicht verdoppelt.
* Leer lassen oder `↺` nimmt wieder den Namen aus dem Muster. Wer genau den
  Namen des Musters eintippt, bleibt ebenfalls beim Muster – die Datei folgt
  dann weiter späteren Änderungen am Muster.
* Ein Name von Hand bleibt bestehen, wenn das Muster geändert wird. „Neu
  laden“ verwirft ihn, wie ungespeicherte Feldänderungen auch.
* Zwei gleiche Namen im selben Ordner werden als Kollision markiert (Zeile
  rot, Hinweis darunter), der Umbenennungsplan ist dann nicht ausführbar.
* Eine Änderung verwirft eine bereits erstellte Umbenennungsvorschau – der
  Plan bezog sich auf die alten Namen.
* Im Web sind alle Dateien bearbeitbar, auch bei großen Releases; die
  Vorschau war vorher auf die ersten Dateien begrenzt.

**Umsetzung.**
* `releaser/model.py`: `Track.manual_stem` (am Ende der Felder, damit
  positionale Aufrufe gültig bleiben).
* `releaser/naming.py`: `track_stem()` nimmt den Namen von Hand, sonst
  `pattern_stem()` (die bisherige Logik). `clean_manual_stem()` bereinigt
  die Eingabe. Umbenennungsplan und Vorschau gehen beide über
  `track_stem()` und zeigen damit dasselbe.
* `releaser/uistate.py`: `preview_names()` liefert zusätzlich `rows` – je
  Datei Index, alter Name, Unterordner, neuer Name, Name aus dem Muster,
  Markierung „von Hand“ und Kollision. `set_file_name(index, text)` setzt
  oder löscht den Namen von Hand und meldet ungültige Eingaben.
* Web: neuer Endpunkt `POST /api/filename` (`index`, `value`); die Seite
  zeigt eine Tabelle mit Eingabefeldern statt der Textliste. Escape stellt
  den vorigen Namen wieder her. Wird die Tabelle neu gezeichnet, während
  schon im nächsten Feld getippt wird, bleibt das Getippte stehen.
* GTK: Die Zeilen werden nur neu aufgebaut, wenn sich die Dateien selbst
  ändern (Laden, Umbenennen); sonst werden nur Texte nachgezogen. Ein
  Neuaufbau zerstörte sonst das Feld mit dem Fokus – derselbe Absturzweg,
  der früher im Formular aufgetreten war (siehe unten, 0.22.1).

## 2. „Quelle“ in der Vorlage und im Verzeichnisnamen getrennt

**Anlass.** „Quelle“ stand im Formular unter „in der Vorlage“ und unter „im
Verzeichnisnamen“ – war aber dasselbe Feld (`#Source`). Eine Eingabe in der
einen Gruppe erschien in der anderen, und die Quelle für die NFO („Vinyl
(180 g)“) landete zwangsläufig auch im Ordnernamen.

**Jetzt.** Zwei eigenständige Felder:

| Feld | Gruppe | wirkt auf |
|---|---|---|
| Quelle | in der Vorlage | `#Source` in der `.nfo` |
| Quelle (Name) | im Verzeichnisnamen / im Dateinamen | `#Source` in den Namensmustern |

Keins füllt das andere aus. **Wer die Quelle bisher im Ordnernamen hatte,
trägt sie jetzt in „Quelle (Name)“ ein** – ohne Eintrag fällt `#Source` im
Namen weg (samt Trennzeichen, wie jeder leere Tag).

**Umsetzung.** `Release.dir_source` in `releaser/model.py`; in
`releaser/naming.py` löst `#Source` in Mustern auf `dir_source` auf. In
`releaser/fields.py` kennt `FieldSpec` jetzt `pattern_tag` (Tag in den
Namensmustern, falls er vom SKL-Tag abweicht) und `in_patterns`; danach
richtet sich die Gruppierung im Formular.

## 3. Dokumentation

* `README.md`, `README.en.md`: Namen von Hand und die zwei Quellen im
  Abschnitt „Naming-Schema“, Beispielausgabe von `releaser fields`, neuer
  Abschnitt „Aus der zwölften Erprobung“, Testzahl.
* `README.md`: Die Beispiel-Regelkette nannte die Voreinstellung ohne
  `alnum` – sie lautet `inch transliterate alnum forbidden spaces collapse
  trim`.
* `EINRICHTUNG.md`: Testzahl.

## Neue Tests

* `tests/test_naming.py`: Bereinigung von Hand-Namen (Endung, verbotene
  Zeichen, Punkte am Rand, Trennzeichen, keine Schreibweise), Vorrang vor
  dem Muster, Rückfall bei leerem Ergebnis, Plan und Ausführung mit
  Hand-Namen, Kollision zweier Hand-Namen.
* `tests/test_uistate.py`: Zeilen der Vorschau, Setzen, Zurücksetzen, Name
  gleich Muster, Muster ändern, Kollision, ungültige Position, nur verbotene
  Zeichen, ohne Release, Neu laden.
* `tests/test_web.py`: `rows` im Zustand, `/api/filename` bis zur
  ausgeführten Umbenennung, Zurücksetzen, ungültige Position.
* `tests/test_gtkui.py`: Namen von Hand im echten GTK-Fenster (Eingabe,
  Markierung, `↺`, Feld bleibt dasselbe Widget); der bestehende
  Namens-Test liest die neuen Widgets.
* `tests/test_fields.py`: beide Quellen unabhängig, jede in ihrer Gruppe.
* `tools/webcheck.py`: neuer Schritt im echten Browser – Dateiname
  überschreiben, bereinigter Name und Markierung erscheinen.

---

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
| Tests | 672 | 736 |
| Ergebnis ohne GTK (Python 3.11) | 2 rot (Build-Skript), Rest grün | alle grün; übersprungen wird nur, wofür GTK, WebKitGTK oder ein gebautes Bündel fehlt |
| Ergebnis mit GTK 4, WebKitGTK und gebautem Bündel (Python 3.12) | – | alle 736 grün, nichts übersprungen |
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
* **AppImage veröffentlicht** – zunächst als Datei unter `releases/`, seit
  dem Release-Workflow (Abschnitt 17) als GitHub-Release mit `SHA256SUMS`.
  Download-Hinweise in beiden README-Fassungen.

Das AppImage wurde selbst geprüft: ohne Python und ohne `PATH`
(`env -i`) läuft der komplette Ablauf durch (taggen, umbenennen, NFO, SFV,
M3U; `verify` meldet „3 ok“), und die Oberfläche startet unter Xvfb ohne
Fehler. Es braucht glibc 2.38 oder neuer (Ubuntu 24.04, Linux Mint 22,
Debian 13, Fedora 39 und neuer) und für die Oberfläche GTK 4 des Systems.

## 17. Release-Workflow

`.github/workflows/release.yml` baut das AppImage bei jedem Versions-Tag
(`v*`) auf GitHub Actions und veröffentlicht es als Release – statt es als
Datei ins Repository zu legen, wo jede Version die Historie um gut 20 MB
vergrößert.

Ablauf: Systempakete (GTK 4, WebKitGTK, xvfb, ffmpeg) → Python-Umgebung mit
PyGObject aus dem System → Abgleich von Tag, `__version__` und
`pyproject.toml` → pyflakes und komplette Testsuite → `appimagetool` 1.9.1
mit geprüfter SHA-256 → Bau → Bündeltests einschließlich Start der
Oberfläche → AppImage ohne Python und ohne `PATH` gestartet → Umbenennen,
Prüfsumme → Release mit AppImage und `SHA256SUMS` und zweisprachigen
Hinweisen. Veröffentlicht wird nur, wenn alle Schritte davor bestanden haben;
nur dieser letzte Schritt hat Schreibrecht. Ein erneuter Lauf für dasselbe
Tag ersetzt die Dateien, statt zu scheitern.

Geprüft mit `actionlint` (samt `shellcheck`) und durch einen vollständigen
Nachbau des Build-Jobs in einer frischen Kopie des Repositorys. Ein Test in
`tests/test_packaging.py` hält die wesentlichen Eigenschaften fest.

Der erste Lauf auf GitHub zeigte eine Lücke, die lokal nicht auffallen
konnte: Auf dem Runner (normaler Benutzer, Ubuntu 24.04) darf WebKits Sandbox
keine Namespaces anlegen, und der Webprozess stürzte ab. Der Workflow setzt
dafür `WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS` – der Browser-Test startete
seinen Prüfstand aber mit einer leeren Umgebung, die Variable kam nie an. Er
reicht sie jetzt durch, wenn sie gesetzt ist.

Seit das erste Release steht, liegt das AppImage nicht mehr im Repository
(`releases/` entfernt); die Download-Hinweise zeigen auf die Release-Seite.
Jede Version im Repository hätte die Historie um gut 20 MB vergrößert – die
bereits eingecheckte Datei bleibt in der Historie, weil ein Umschreiben der
Historie jeden vorhandenen Klon ungültig machen würde.

Außerdem: `upload-artifact`/`download-artifact` auf die ersten Fassungen mit
Node 24 (v6/v7), und ein Test prüft am *gebauten* Bündel, dass keine der
ausgeschlossenen Grafikbibliotheken darin steckt – welche Bibliotheken
PyInstaller hereinzieht, hängt vom Rechner ab, auf dem gebaut wird.

## Neue Tests

64 Tests, verteilt auf die jeweils zuständige Testdatei und dort
unter der Überschrift „Korrekturen (Fehlerdurchsicht)“ bzw. „Oberfläche im
Bündel“ zu finden:
`test_audio.py`, `test_extras.py`, `test_skl.py`, `test_tagwriter.py`,
`test_sfv_m3u.py`, `test_naming.py`, `test_checks.py`, `test_undo.py`,
`test_service.py`, `test_api.py`, `test_uistate.py`, `test_web.py`,
`test_gtkui.py`, `test_packaging.py`, dazu die auf beide Sprachfassungen
erweiterten Prüfungen in `test_readme.py`.
