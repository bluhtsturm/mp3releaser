# mp3releaser — Linux-Reimplementierung

Neuimplementierung des Windows-Tools *MP3 Releaser 3.9* (Delphi/VCL, 2003) in
Python. Kein Port und keine Dekompilierung: die Funktionalität wird aus der
mitgelieferten Dokumentation (`mp3r_tags.nfo`, `skl_making_guide.nfo`),
den Konfigurationsdateien und beobachtbarem Verhalten rekonstruiert.

Der Funktionsumfang des Originals ist abgedeckt, dazu vier Oberflächen in
drei Auslieferungsformen: Kommandozeile, gebündelte Anwendung (AppImage) und
Weboberfläche im Container.

*English version: [README.en.md](README.en.md)*

## Herunterladen

Das fertige AppImage gibt es unter
[**Releases**](https://github.com/bluhtsturm/mp3releaser/releases/latest) – eine Datei, ohne Installation, ohne Python.
Daneben liegt `SHA256SUMS` mit der Prüfsumme. Am Beispiel von 0.25.1:

```bash
chmod +x mp3releaser-0.25.1-x86_64.AppImage
./mp3releaser-0.25.1-x86_64.AppImage              # grafische Oberfläche
./mp3releaser-0.25.1-x86_64.AppImage --help       # Kommandozeile
sha256sum -c SHA256SUMS                           # Prüfsumme kontrollieren
```

Voraussetzung: Linux x86_64 mit glibc 2.38 oder neuer (Ubuntu 24.04,
Linux Mint 22, Debian 13, Fedora 39 und neuer). Die grafische Oberfläche
nutzt das GTK 4 des Systems; die Kommandozeile läuft auch ohne. Fehlt FUSE,
startet es mit `--appimage-extract-and-run`.

## Schnellstart

```bash
# Kommandozeile
python3 -m releaser release /pfad/zur/release --group GRP     # alles in einem Schritt
python3 -m releaser wizard /pfad/zur/release templates/standard.skl
python3 -m releaser build  /pfad/zur/release vorlage.skl --tag --rename --group GRP
python3 -m releaser verify /pfad/zur/release/xyz.sfv
python3 -m releaser fields /pfad/zur/release vorlage.skl      # Felder prüfen
python3 -m releaser dupe   /pfad/zur/release --against ~/releases

# Oberflächen
python3 -m releaser gui --mounts "eingang:/data/ein"          # GTK 4
RELEASER_MOUNTS=eingang:/data/ein python3 -m releaser web     # Weboberfläche
docker compose up                                             # dieselbe im Container

# Auslieferung und Vergleich
./packaging/build.sh                                          # Bündel + AppImage
python3 -m releaser metrics --compare cli.json appimage.json container.json

python3 -m pytest tests -q          # 860 Tests
```

Abhängigkeit des Kerns: `mutagen`. Der NFO-Teil kommt ohne aus, die
Oberflächen brauchen zusätzlich GTK 4 beziehungsweise FastAPI.

## Architektur

```
releaser/
  model.py        Release / Disc / Track — reine Datenklassen, kein I/O
  text.py         CP437-I/O, Schreibweisen, ASCII-Konvertierung, Formate
  tags.py         Tag-Registry: Name, Scope, Ausrichtung, Resolver
  skl.py          Parser (Feldererkennung) und Renderer (Blöcke, Replikation)
  nfoview.py      .nfo im festen Raster: Block- und Rahmenzeichen als Flächen
  checksums.py    CRC32 über Datei und über reine Audiodaten
  sfv.py          SFV schreiben, lesen, prüfen
  playlist.py     M3U je CD plus Super-M3U
  naming.py       Namensmuster, Regelkette, Umbenennungsplan
  tagwriter.py    Tags schreiben, ebenfalls als Plan
  companions.py   .nfo/.sfv/.m3u und Cover finden, aufräumen
  cue.py          CUE-Sheets lesen
  genres.py       ID3v1-Genreliste und Zuordnung
  lyrics3.py      Lyrics3v2 schreiben und entfernen
  dupecheck.py    Releasenamen gegen bekannte vergleichen
  config.py       TOML-Konfiguration
  checks.py       Vorlagen und fertige Releases pruefen
  provenance.py   woher ein Wert stammt
  undo.py         Umbenennungen zuruecknehmen
  fields.py       Feldkatalog: Verwendung, Breite, Herkunft
  browse.py       Dateiauswahl — lokal oder auf eingehängte Ordner beschränkt
  service.py      Abläufe ohne Ausgabe — gemeinsame Basis aller Oberflächen
  uistate.py      Fensterlogik ohne Fenster — Zustand und Aktionen
  runtime.py      Auslieferungsform erkennen und vermessen
  audio/
    base.py       AudioInfo + Dispatch nach Endung
    bitreader.py  MSB-first-Bitleser
    mp3.py        MP3 über mutagen
    flac.py       FLAC, Kompressionsrate aus STREAMINFO
    vorbis.py     Ogg Vorbis, Opus, Musepack
    mp4.py        MP4-Container: AAC, ALAC, EC-3
    eac3.py       EC-3-Bitstream-Parser + dec3-Box
    scan.py       Verzeichnis → Release
  frontends/
    cli.py        Kommandozeile
    wizard.py     geführter Modus
    gtkui.py      Desktop-Anwendung (GTK 4)
    web/          Weboberfläche (FastAPI) — nur eingehängte Ordner
```

Die Trennung ist bewusst: `skl.py` kennt weder mutagen noch Dateisystem, der
Renderer ist damit ohne Audiodateien vollständig testbar. Ein Test blockiert
den mutagen-Import und erzeugt trotzdem NFO, Namen und M3U.

Neue Tags erfordern **nur** einen Eintrag in `tags.py::_DEFS` — Parser und
Renderer bleiben unberührt.

## Die SKL-Engine

Ein Tag belegt nicht nur seine eigenen Zeichen, sondern auch die Leerzeichen
daneben. Diese Spanne ist das *Feld*. Werte werden auf Feldbreite gekürzt und
aufgefüllt, damit ASCII-Rahmen in ihrer Spalte stehen bleiben.

| Ausrichtung | Schreibweise | Feld | Beispiel |
|---|---|---|---|
| links | `#Artist` | Tag + folgende Leerzeichen | `#Artist    ` → `Nirvana    ` |
| zentriert | `#Release` | wie links, Wert zentriert | `  Nirvana - …  ` |
| rechts | `Size#` | *vorangehende* Leerzeichen + Tag | `      Size# MB` → `   26.5 MB` |

**Longest-Match ist zwingend.** Ohne Sortierung nach Literal-Länge würde
`#Releasenc` als `#Release` + `nc` gelesen, `#10Hz` als Text + `#Hz`.

**Zeilenreplikation.** Eine Zeile mit Track-Tags (`#N`, `#Trk`, `#Ptit`) wird
pro Track wiederholt. Enthält die *Folgezeile* `#Trk` ohne `#N`/`#Ptit`, dient
sie als Fortsetzungszeile für

* umbrochene Tracktitel,
* CD-Kopfzeilen bei Multi-CD-Releases,
* die Leerzeile darunter.

Dasselbe Muster gilt für `#Rnotes` und `#Gnews`. Umbrochen wird mit der
Breite der Fortsetzungszeile, nicht der Hauptzeile — sonst schnitte ein
schmaleres Fortsetzungsfeld den Rest stillschweigend ab.

**Introspektion.** `Template.field_widths()` und `Template.tag_names()` liefern
genau das, was das Original für die GUI brauchte: Feldbreiten zum Dimensionieren
der Eingabefelder, und die Menge der ungenutzten Tags zum Ausgrauen.

### Verifikation gegen das Original-Template

`generic.skl` aus der Originaldistribution parst sauber: 43 Tags erkannt, alle
63 Rahmenzeilen behalten ihre Breite von 83 Zeichen, Multi-CD-Kopfzeilen,
Titelumbruch und rechtsbündige Summenfelder verhalten sich wie dokumentiert.

Das Original-Template selbst gehört nicht ins Repo — die ASCII-Grafik ist
urheberrechtlich geschützt (MorGoTH, 2000). `templates/example.skl` ist ein
eigenes, neutrales Testtemplate.

## Getroffene Annahmen

Die Doku des Originals ist an drei Stellen unscharf. Aktuelles Verhalten:

1. **`#hhh…` vs. `#hhL…`** — `hhh` („filled with spaces") wird als rechtsbündig
   interpretiert, `hhL` als linksbündig. Gegen echte Referenz-NFOs noch nicht
   verifiziert.
2. **„cuts the useless spaces at the left side"** — implementiert als
   Trimmen der Zeilenenden (`trim_trailing=True`). Ein optionales `dedent=True`
   entfernt zusätzlich gemeinsame Einrückung; standardmäßig aus, weil es
   ASCII-Grafik zerstören würde.
3. **Notizblock ohne Fortsetzungszeile** — dann repliziert die Hauptzeile pro
   Notizzeile. Für die Trackliste ist das dokumentiert, für Notizen nicht.

Diese drei Punkte lassen sich durch Diff gegen unter Wine erzeugte
Referenz-NFOs klären — ein sauberer Verifikationsschritt für die Arbeit.

## Audio-Layer

Gemeinsames Interface: jeder Reader liefert ein `AudioInfo`, `scan.py` baut
daraus die `Release`. Eine Datei, die sich nicht lesen lässt — abgeschnitten,
beschädigt, ohne Leserecht —, wird übersprungen und als Hinweis gemeldet,
statt den ganzen Scan abzubrechen (`--strict` bricht bewusst ab).

| Format | Quelle | Besonderheit |
|---|---|---|
| MP3 | mutagen (`ID3`, `MPEGInfo`) | VBR-/ABR-Status, Channel-Mode in Szene-Schreibweise, Encoder aus LAME/Xing |
| FLAC | mutagen (`FLAC`, Vorbis) | Kompressionsrate für `#FlacC` aus STREAMINFO gegen Dateigröße, Encoder aus dem Vendor-String (`FLAC 1.4.3`) |
| Ogg Vorbis | mutagen | Tag-Abbildung mit FLAC geteilt |
| Opus | mutagen | Bitrate aus Dateigröße geschätzt (meldet keine) |
| Musepack | mutagen | APEv2-Tags — **ungetestet**, ffmpeg kann MPC nicht erzeugen |
| AAC (`.m4a`) | mutagen | Profil aus der Codec-Kennung, VBR aus `stsz` |
| ALAC (`.m4a`) | mutagen | verlustfrei, daher nie VBR |
| EAC3 (`.ec3`) | eigener Bitstream-Parser | kein Tag-Container — siehe unten |
| EAC3 (MP4) | mutagen + `dec3`-Box | Tags aus iTunes-Atoms, Technik aus `EC3SpecificBox` |

### AAC im MP4-Container

mutagen liefert `codec` und `codec_description`. Daraus wird das Profil
abgeleitet: `mp4a.40.2` ist AAC-LC, `.5` HE-AAC, `.29` HE-AACv2. Für
`#Format` reicht "AAC", die Profilangabe landet im Encoder-Feld.

**VBR** ist der interessante Teil: MP4 hat kein VBR-Flag. Die `stsz`-Box
enthält aber die Größe jedes einzelnen Samples. Ist das Feld `sample_size`
ungleich null, sind alle Samples gleich groß; sonst folgt eine Tabelle, deren
Streuung sich auswerten lässt. Liegt der Variationskoeffizient über 10 %, gilt
der Stream als variabel.

Das ist ausdrücklich eine **Heuristik** — AAC schwankt wegen des
Bit-Reservoirs auch bei konstanter Zielbitrate leicht, deshalb keine
strengere Schwelle. Reichen die Samples für keine Aussage, bleibt es bei
einer Warnung statt einer Behauptung. Die `stsz`-Box wird über den
Containerpfad `moov/trak/mdia/minf/stbl` gesucht, nicht per Byte-Suche.

### EC-3: warum ein eigener Parser

mutagen deckt Dolby Digital Plus nicht ab. Für rohe Streams gibt es weder
Tags noch einen Header mit der Dauer — alles muss aus den Syncframes kommen:
`strmtyp`, `frmsiz`, `fscod`, `numblkscod`, `acmod`, `lfeon`, `bsid`.

Um an `addbsi` heranzukommen (dort steckt das JOC-Kennzeichen), muss der
gesamte BSI-Header traversiert werden, inklusive der optionalen Mixing- und
Info-Metadaten. Die Bedingungen dort folgen FFmpegs `eac3_parser`, der an zwei
Stellen präziser ist als der Prosatext der Spezifikation (`dmixmod` und
`paninfo` hängen von `acmod`-Schwellen ab, die im Fließtext anders stehen).

Die aufwendige Traversierung läuft nur über die ersten Frames; jeder weitere
Frame wird allein aus seinen ersten Bytes gezählt. Dauer und Bitrate stimmen
damit auch bei langen Dateien.

Schlägt diese Traversierung fehl, bleiben die Kernfelder trotzdem gültig und
`atmos` wird `None` — **unbekannt, nicht nein**. Diese Unterscheidung ist
wichtig: ein falsches „kein Atmos" ist schlimmer als ein ehrliches „weiß nicht".

**Konsequenz fürs Datenmodell:** `AudioInfo.tagless` markiert Formate, die
grundsätzlich keine Tags tragen können. Titel kommen dann aus dem Dateinamen,
und der Scanner schreibt eine Warnung — statt stillschweigend etwas zu raten.

### Verifikation

Der EC-3-Parser wurde gegen echte, mit ffmpeg erzeugte Bitstreams getestet
(Mono, Stereo, 5.1, 44,1 kHz, EC-3 in MP4, Zehn-Minuten-Streams). Samplerate, Kanalzahl, Bitrate und
Dauer stimmen exakt mit `ffprobe` überein, und die BSI-Tiefentraversierung
läuft bei allen bis `addbsi` durch.

Den JOC-Pfad kann ffmpegs EC-3-Encoder nicht erzeugen. Er wird deshalb mit
synthetisch gebauten Syncframes und `dec3`-Boxen getestet (`BitWriter` in
`tests/test_audio.py`). Gegen ein echtes Atmos-Sample ist er **noch nicht**
verifiziert — das bleibt offen.

## SFV und die zwei CRC-Werte

Ein SFV enthält den CRC32 der **kompletten Datei**. Das hat eine unangenehme
Eigenschaft: Umtaggen ändert die Datei und damit die Prüfsumme, obwohl die
Audiodaten unberührt sind. Das SFV meldet dann einen Fehler, der keiner ist.

`checksums.py` berechnet deshalb zusätzlich einen **Audio-CRC** nur über die
Nutzdaten — ohne ID3v2 am Anfang, ohne ID3v1/APEv2/Lyrics3v2 am Ende, ohne
FLAC-Metadatenblöcke und ohne eine eventuelle WAV-Hülle. Das entspricht der
Option „check for stuff in front of the mp3 (WAV envelope, ID3v2 ...)" des
Originals, die dort „mp3-crc" hieß.

Mit `--audio-crc` landen diese Werte als Kommentarzeilen im SFV:

```
; audio-crc 56356AA4 01-artist-track_1.mp3
01-artist-track_1.mp3 44A37193
```

Fremde Prüfprogramme überlesen Kommentarzeilen, `verify` nutzt sie:

```
1 ok, 1 nur umgetaggt, 1 fehlerhaft
  ~ 01-artist-track_1.mp3 (Audiodaten unverändert)
  x 02-artist-track_2.mp3: erwartet 9E1F98FA, gefunden F7FADEB3
```

Ohne mitnotierten Audio-CRC ist diese Unterscheidung nicht möglich — dann gilt
jede Abweichung als Fehler. Das ist bewusst so: raten wäre schlimmer.

**Ein SFV je Verzeichnis.** Bei Mehr-CD-Releases entsteht damit automatisch
eines pro CD, mit nackten Dateinamen. Prüfprogramme erwarten das SFV neben den
Dateien, die es beschreibt. `--sfv-include log pdf` nimmt weitere Endungen auf.

## M3U

Erweitertes Format mit `#EXTINF:<sekunden>,<Artist> - <Titel>`. Je CD eine
Playlist mit nackten Dateinamen, dazu bei Mehr-CD-Releases die **Super-M3U**
im Wurzelverzeichnis mit Pfaden relativ dazu (`CD1/01-....mp3`). Bei einer
einzelnen CD entfällt die Super-M3U, sie wäre nur eine Dopplung.

Normale Schrägstriche sind Voreinstellung — unter Linux findet kein Abspieler
eine Datei hinter `CD1\01-….mp3`. Das Original schrieb Rückwärts-Schrägstriche,
weil es unter Windows lief; `--m3u-windows-paths` (in der Konfiguration
`m3u_windows_paths = true`) stellt das wieder her.

## Testansatz

Prüfsummen werden gegen eine **eigene, bitweise CRC32-Implementierung** im
Test geprüft, nicht gegen `zlib` — sonst würde die Bibliothek gegen sich
selbst antreten. Die Tag-Erkennung wird mit synthetisch gebauten Dateien für
jede Kombination aus ID3v2/ID3v1/APEv2/Lyrics3v2 getestet.

Ein Test macht das Kernverhalten explizit: eine Datei umtaggen, dann prüfen,
dass der Datei-CRC sich geändert hat und der Audio-CRC nicht.

## Naming-Schema

Das Original löste das Umbenennen über rund vierzig Checkboxen. Dahinter
stecken aber nur zwei Konzepte.

**Erstens ein Muster** — in derselben Tag-Sprache wie die SKL-Templates, nur
ohne Spaltenlogik:

```
--dir-pattern  "#Artist-#Album-#Source-#Year-#Grp"
--file-pattern "#N-#Artist-#Trk"
```

Ein Vokabular für NFO *und* Dateinamen statt zweier paralleler Systeme. Fünf
Tags kommen dazu, die nur beim Benennen Sinn ergeben (`#Cd`, `#Cd2`, `#Grp`,
`#Ext`, `#Fmt`); sie stehen in einer eigenen Tabelle, damit `inspect`
weiterhin nur echte SKL-Tags zeigt.

**Zweitens eine Regelkette** — jede Regel eine reine Funktion `str -> str` mit
einem Namen. Die Konfiguration ist eine lesbare Liste statt Boolescher Flags:

```
--pipeline inch transliterate alnum forbidden spaces collapse trim
```

| Regel | Wirkung |
|---|---|
| `inch` | `12" Mix` → `12INCH Mix` |
| `transliterate` | `Die Ärzte` → `Die Aerzte` |
| `strip_diacritics` | Akzente entfernen, ohne `ä`→`ae` |
| `forbidden` | Zeichen raus, die im Dateisystem nicht erlaubt sind |
| `spaces` | Leerzeichen → konfigurierbares Zeichen |
| `collapse` | `a__-_b` → `a_b` |
| `alnum` | nur Buchstaben, Ziffern und Trenner — `Titel, mit Komma` → `titel_mit_komma` |
| `trim` | führende/abschließende Trennzeichen weg |

Der Rest sind Geltungsbereiche: Verzeichnis, Dateiname, Tag und NFO haben je
eine eigene Schreibweise, teilen sich aber die Kette. Das ersetzt die vier
getrennten „Charcase"-Blöcke des Originals.

**Drittens der Name von Hand.** Eine Regelkette trifft nicht jeden Fall:
`collapse` macht aus „Los Marañones I - Nattern Narren" ein
`los_maranones_i-nattern_narren`, obwohl dort `_-_` gemeint war. Im Reiter
„Namen" steht deshalb jeder Dateiname in einem eigenen Eingabefeld —
vorgefüllt mit dem Namen aus dem Muster, überschreibbar. Ein Name von Hand
wird wörtlich übernommen: keine Regelkette, keine Schreibweise. Nur was keinen
gültigen Dateinamen ergäbe, fällt weg (verbotene Zeichen, Punkte am Rand),
Leerzeichen werden zum eingestellten Trennzeichen, und eine mitgetippte
Endung wird nicht verdoppelt. Leer lassen oder `↺` nimmt wieder das Muster;
wer genau den Namen des Musters eintippt, bleibt ebenfalls beim Muster und
folgt damit späteren Änderungen daran. Kollisionen zwischen Namen von Hand
meldet die Vorschau wie jede andere.

**Die Gruppe steht im Verzeichnisnamen, wie sie eingegeben ist.** Aus
„GrP" wird nicht „grp" oder „GRP": Die Schreibweise des Verzeichnisses gilt
für alles vor dem Gruppennamen, nicht für ihn. Nur Zeichen, die kein Ordnername
enthalten darf, fallen weg, Leerzeichen werden zum Trenner. Das gilt nur für
das Verzeichnis — die Dateien darin, Begleitdateien eingeschlossen, folgen
ganz der Schreibweise der Dateien. Ein von Hand gesetzter Verzeichnisname
behält die Gruppe ebenfalls so, wie sie im Feld steht.

**`#Source` hat ein eigenes Feld.** Die Quelle in der NFO („CDDA, WEB,
Vinyl") und die Quelle im Verzeichnisnamen sind zwei Felder: „Quelle" für die
Vorlage und „Quelle (Name)" für Verzeichnis- und Dateinamen. Vorher war es ein
Feld, das in beiden Gruppen des Formulars stand — wer es in der einen änderte,
änderte es in der anderen mit.

### Plan statt Sofortausführung

`plan_rename()` fasst nichts an, sondern liefert eine Liste von Operationen
plus Warnungen und Kollisionen. `rename` zeigt diese Vorschau standardmäßig
an; erst `--apply` führt aus. Das macht die riskanteste Operation des
Programms überprüfbar, bevor sie passiert.

Kollisionen werden in zwei Formen erkannt: zwei Tracks, die auf denselben
Namen abbilden, und Ziele, die bereits auf der Platte liegen. Letztere zählen
nicht als Kollision, wenn sie selbst Quelle im Plan sind — sie weichen ja noch.
Ebenso wenig eine reine Änderung der Schreibweise auf einem Dateisystem, das
Groß und klein nicht unterscheidet (FAT/exFAT, SMB): Dort „existiert"
`track.mp3`, wenn `Track.mp3` umbenannt werden soll — es ist aber dieselbe
Datei.

### Drei Fallstricke, die Tests aufgedeckt haben

**Zyklen.** Tauschen zwei Dateien ihre Namen, würde naives Umbenennen eine
davon überschreiben. Die Ausführung läuft deshalb zweistufig über temporäre
Namen. Beim Nachziehen der Pfade im Modell darf *innerhalb* einer Stufe nur
ein Mapping greifen — sonst dreht der zweite Treffer die Datei wieder auf den
Ausgangsnamen zurück.

**Rollback.** Schlägt eine Umbenennung mittendrin fehl, werden alle bereits
ausgeführten zurückgenommen. Ohne das bliebe ein halb umbenanntes Release
liegen, inklusive temporärer Namen, die den nächsten Versuch blockieren.
Die temporären Namen tragen ein Zufallstoken, damit eine Altlast nicht stört.

**Die „intro"-Regel.** Das Original stellte Dateien namens `intro` den Artist
voran, um Namensdopplungen zu vermeiden. Enthält das Muster ohnehin schon
`#Artist`, wäre das eine Dopplung (`01-artist-artist-intro`) — die Regel
greift dann nicht.

## Tag-Schreiben

Gleiche Bauform wie beim Umbenennen: `plan_tags()` liest die vorhandenen Tags,
berechnet die Sollwerte und liefert eine Liste von Feldänderungen, ohne eine
Datei anzufassen. Erst `apply_tags()` schreibt.

```
  CD1/01-x.m4a
      title        roher titel 11  ->  Roher Titel 11
      album        -               ->  Das Album (WEB)
      tracknumber  -               ->  1/2
```

Die Sollwerte entstehen aus dem `Release`-Modell, nicht aus den Dateien. Das
Schreiben ist damit der Gegenlauf zum Scannen: was der Scanner zusammengeführt
und korrigiert hat, landet zurück in den Dateien.

Ein normalisierter Satz Feldnamen (`title`, `artist`, `album`, `tracknumber`
…) wird pro Format abgebildet — ID3v2-Frames, Vorbis-Comments, iTunes-Atoms.
Vorbis trennt dabei Nummer und Gesamtzahl in eigene Felder, MP4 nutzt Tupel;
das erledigt der jeweilige Writer.

„Vorhandene Tags entfernen" (`--strip-tags`) entfernt sie restlos — ID3v2,
ID3v1, APEv2 und Lyrics3v2 —, auch bei Dateien, die gar keinen Tag hatten.

### Wiederholbarkeit

Zwei Fehler sind mir hier aufgefallen, beide erst beim zweiten Durchlauf:

Der Album-Zusatz (`--album-addition CDDA`) wurde von der Schreibweisenregel
erfasst und zu `(Cdda)` — und weil der zweite Lauf den Zusatz dann nicht mehr
wiedererkannte, hängte er ihn erneut an. Jetzt wird ein vorhandener Zusatz
**vor** der Schreibweisenregel abgetrennt und danach in seiner eigenen
Schreibweise wieder angehängt. Ein zweiter Lauf meldet null Änderungen.

Ein Test hält das Kernversprechen fest: Tag-Schreiben verändert den Audio-CRC
nicht. Damit greift die `verify`-Logik aus dem SFV-Teil auch nach einem
Tag-Lauf.

### Reihenfolge in `build`

`--tag` läuft vor `--rename`, und beide vor der Erzeugung von NFO, SFV und
M3U. Das ist keine Kosmetik: würde das SFV vor dem Tag-Lauf entstehen, wären
sämtliche Prüfsummen sofort falsch. Nach dem Taggen werden die Dateigrößen neu
gelesen, damit `#Size` in der NFO zu den Dateien passt.

## Als Bibliothek

`releaser/__init__.py` exportiert eine flache API. Der Audio-Layer wird per
`__getattr__` erst bei Bedarf geladen, damit der NFO-Teil ohne mutagen läuft:

```python
from releaser import scan_directory, Template, write_release_sfvs

result = scan_directory("/pfad/zur/release")
nfo = Template.from_file("vorlage.skl").render(result.release)
```

Ein Test sichert diese Schichtentrennung ab, indem er den mutagen-Import
blockiert und trotzdem NFO, Namen und M3U erzeugt.

## Abgleich mit dem Original

| Funktion des Originals | Stand |
|---|---|
| Tags lesen: MP3, FLAC, OGG, MPC | ✅ (MPC ungetestet) |
| zusätzlich: AAC, ALAC, EC-3 | ✅ (im Original nicht vorhanden) |
| Tags schreiben: ID3v1, ID3v2, Vorbis | ✅ |
| Tags schreiben: APEv2, Lyrics3v2 | ✅ `--apev2`, `--lyrics3` |
| NFO aus `.skl`-Vorlage | ✅ vollständig, inkl. Multi-CD und Umbruch |
| SFV mit Kommentaren, Zusatzendungen | ✅ plus Audio-CRC und `verify` |
| M3U je CD und Super-M3U | ✅ |
| Umbenennen mit Zeichensatzregeln | ✅ als Plan mit Vorschau |
| Längenwarnungen | ✅ Verzeichnis, Dateiname, Begleitdateien |
| alte NFO/SFV/M3U entfernen | ✅ `--clean` |
| `.cue`-Dateien verarbeiten | ✅ inkl. Laufzeitberechnung |
| Cover/JPG, „00"-Präfixregel | ✅ `--companion-prefix` |
| Konfigurationsdatei (`MP3releaser.ini`) | ✅ als TOML |
| ID3v1-Genreliste und -Mapping | ✅ 192 Genres, mit Aliassen |
| Dupe-Prüfung gegen vorhandene Releases | ✅ `dupe` |
| GUI | ✅ GTK 4 — dazu geführter Modus und Weboberfläche |

Zusätzlich, über das Original hinaus: drei Auslieferungsformen mit
gemeinsamem Kern, Herkunftsverfolgung der Werte, Plan-vor-Ausführung für
jede verändernde Operation und `metrics` zum Vergleich der Formen.

## Was beim zweiten Durchgehen aufgefallen ist

Fünf Fehler, die alle aus dem Zusammenspiel entstanden — jedes Modul für sich
war in Ordnung.

1. **Genre gegen Schreibweise.** `normalise_genre` bringt das Genre auf die
   kanonische Schreibweise, damit ID3v1 seine Nummer findet. Danach griff die
   Schreibweisenregel zu und machte `Drum & Bass` zu `DRUM & BASS` — und
   mutagen vergleicht exakt, also stand in ID3v1 wieder 255 („unbekannt").
   Das Genre ist jetzt von der Regel ausgenommen, sobald es erkannt wurde;
   unbekannte Genres folgen ihr weiterhin.
2. **Lesen ohne Schreiben.** Ogg Vorbis, Opus und Musepack wurden gelesen,
   aber nicht geschrieben — der Tag-Lauf meldete „kann keine Tags tragen",
   obwohl Vorbis-Comments genau dafür da sind. Ein Test vergleicht jetzt die
   Leser- gegen die Schreiberliste; was fehlt, muss ausdrücklich als
   tag-los deklariert sein.
3. **Leerzeichen im SFV-Namen.** Die CD-Kennung kam aus dem Verzeichnisnamen,
   nicht aus der Nummer. Neben einem Ordner `Disc 2` hieß das SFV
   `…-disc 2.sfv` — und die M3U daneben `…-cd2.m3u`. Beide nehmen jetzt die
   Nummer.
4. **Begleitdateien mit zweierlei Maß.** Die `.nfo` folgte dem eingestellten
   Namensmuster, `.sfv` und `.m3u` nicht. Alle drei bekommen denselben
   Rumpf.
5. **Eine Messung, die schreibt.** `metrics` legte eine Probedatei im
   Arbeitsverzeichnis an, um die Schreibbarkeit zu prüfen. Eine Messung darf
   nichts anlegen, auch nichts Kurzlebiges — jetzt wird gefragt statt
   ausprobiert.

Dazu eine Verbesserung: Ein Tippfehler in der Konfiguration blieb wirkungslos
und unbemerkt. Unbekannte Schlüssel werden jetzt gemeldet, mit Vorschlag:

```
Konfiguration: [naming] 'grupp' wird nicht ausgewertet - meintest du 'group'?
```

## Was beim ersten Durchgehen aufgefallen ist

Vier Fehler, die vorher niemand gesehen hätte:

1. **Audio-CRC im MP4-Container.** Für `.m4a` war der „Audio-CRC" schlicht der
   Datei-CRC — die Unterscheidung zwischen beschädigt und nur umgetaggt
   funktionierte für AAC gar nicht. Jetzt wird die `mdat`-Box verwendet.
2. **Sampler.** Der Scanner schrieb bei verschiedenen Artists den Artist in das
   *Titelfeld*. Beim Tag-Schreiben wäre das als Titel in den Dateien gelandet.
   Jetzt hält das Modell beides getrennt; zusammengesetzt wird erst zur
   Anzeige, an genau einer Stelle (`compose_track_title`).
3. **Veraltete Begleitdateien.** Ein zweiter `build`-Lauf nach einer
   Umbenennung ließ das alte SFV liegen, das anschließend lauter fehlende
   Dateien meldete.
4. **Positionale Argumente.** Ein neues Feld in der Mitte von `Track`
   verschob alle positionalen Aufrufe — drei Tests fielen sofort um. Das Feld
   steht jetzt am Ende, mit einem Kommentar dazu.

Außerdem: CLI-Fehler kommen nicht mehr als Traceback, sondern als Meldung mit
Exit-Code 2.

## Konfiguration

Die ~25 Kommandozeilenschalter sind der Punkt, an dem das Original in seine
Checkbox-Flut gekippt ist. Dieselbe Information steht hier in einer TOML-Datei:

```toml
[naming]
group = "GRP"
case = "lower"
companion_prefix = "00-"        # .nfo, Bilder, .sfv und .m3u
prefix_all = true               # false: nur .nfo und Bilder

[tags]
case = "capitalize"
album_addition = "CDDA"
write_apev2 = true

[build]
audio_crc = true
release_date_format = "%d.%m.%Y"  # Voreinstellung "%Y-%m-%d", "" = nicht vorbelegen

[gui]
start = "/home/ich/Musik/Eingang" # Verzeichnis, das die Auswahl beim Start zeigt
```

Rangfolge: ausdrücklich gesetzter Schalter schlägt Datei, Datei schlägt
Voreinstellung. Umgesetzt dadurch, dass die CLI-Voreinstellungen `None` sind —
`None` heißt „nicht angegeben", nicht „aus".

Gesucht wird in `./mp3releaser.toml`, `./.mp3releaser.toml`,
`$XDG_CONFIG_HOME/mp3releaser/config.toml` und
`~/.config/mp3releaser/config.toml`. `config --example` gibt eine
kommentierte Vorlage aus.

Wo die Datei je nach Form liegt:

| Form | Datei |
|---|---|
| AppImage, Desktop | `~/.config/mp3releaser/config.toml` — legt der Speichern-Knopf an ([Als Standard speichern](#als-standard-speichern)) |
| Kommandozeile | dieselbe; eine `mp3releaser.toml` im aktuellen Verzeichnis hat Vorrang |
| Container | `config/mp3releaser/config.toml` neben `docker-compose.yml`, im Container `/config/mp3releaser/config.toml` ([Einstellungen im Container](#einstellungen-im-container)) |

`releaser config` sagt, welche Datei gelesen wird, und zeigt ihren Inhalt —
alle Abschnitte. Gibt es keine, nennt der Befehl die Orte, an denen er
gesucht hat.

Das ist gleichzeitig die Datenbasis aller Oberflächen: Kommandozeile,
Desktop-Anwendung und Weboberfläche lesen dieselbe Datei — `[naming]`,
`[tags]` und `[build]` — und rufen denselben Kern. `[gui]` gilt nur für die
Desktop-Anwendung. Die Profile baut die Dienstschicht an
einer Stelle (`naming_from_config`, `tags_from_config`,
`build_options_from_config`).

## CUE-Sheets

Ein CUE beschreibt die Trackaufteilung einer Audiodatei, die als ein Stück
vorliegt. Laufzeiten ergeben sich aus dem Abstand zum nächsten `INDEX 01`; der
letzte Track reicht bis zum Dateiende, dessen Länge das CUE nicht kennt —
die kommt aus dem Audio-Layer. Gelesen wird UTF-8 (mit oder ohne BOM), mit
Rückfall auf CP1252 und CP437.

**Die Folge ist die eigentliche Arbeit:** alle Tracks zeigen dann auf
dieselbe Datei. Ohne Gegenmaßnahme würde das Umbenennen sie mehrfach
anfassen, die M3U sie mehrfach listen und die Gesamtgröße sich mit jedem
Track vervielfachen. Alle drei Stellen sind entsprechend behandelt, die
Dateigröße wird anteilig nach Laufzeit verteilt.

## Dupe-Prüfung

Vergleicht einen Releasenamen gegen bekannte — eine Textdatei oder ein
Verzeichnis mit Releases. Der Vergleich läuft über eine normalisierte Form
ohne Gruppenkürzel, Quellen- und Formatangaben, sodass

```
Der_Artist-Das_Album-CDDA-2026-GRP
der.artist-das.album-WEB-2026-ANDERE
```

als dasselbe Release erkannt werden. Ein Gruppenkürzel wird erst ab drei
Bestandteilen abgetrennt (`Artist-Album-GRP`); bei `Artist-Album` ist der
letzte Teil das Album. Zusätzlich findet ein unscharfer Vergleich Tippfehler.
Er liefert Kandidaten, keine Urteile.

Beim Bauen der Wortliste war Zurückhaltung nötig: „Album", „Single" und
„Sampler" stehen oft im echten Titel. Sie zu entfernen ließ in einem Test
zwei verschiedene Releases zusammenfallen.

## ID3v1-Genres

ID3v1 kennt Genres nur als Zahl. Wer „electronic" statt „Electronic"
schreibt, bekommt dort 255 („unbekannt") — die Angabe geht beim Schreiben
stillschweigend verloren. Der Name wird deshalb auf die kanonische
Schreibweise gebracht, mit Aliassen für gängige Varianten (`DnB`,
`Hip Hop`, `rock n roll`, `Alternative Rock` → `Alt. Rock`). Unbekannte
Genres bleiben als Freitext stehen und erzeugen eine Warnung, statt verworfen
zu werden.

Die Liste wird in einem Test gegen mutagens abgeglichen, damit beide nicht
auseinanderlaufen, und ein weiterer Test stellt sicher, dass jeder Alias
auflösbar ist.

## Lyrics3v2

Ein Tag-Format von 1998, das mutagen nicht unterstützt. Es sitzt am
Dateiende, vor einem eventuellen ID3v1-Block:

```
[Audiodaten][Lyrics3v2][APEv2][ID3v1]
```

Diese Reihenfolge herzustellen war der knifflige Teil: mutagen hängt ID3v1
immer ganz hinten an, also müssen die Altformate vorher geschrieben und
ID3v1 zuletzt angehängt werden. Im ersten Anlauf stand ID3v1 zwischen
Lyrics3 und APEv2 — mein eigener Leser fand den Block dann nicht mehr.

## Drei Auslieferungsformen

Dasselbe Programm soll in drei Formen erscheinen: als Quelltext für die
Kommandozeile, als gebündelte Anwendung (AppImage) und als Container mit
Weboberfläche. Sie unterscheiden sich nicht darin, **was** sie können,
sondern darin, **was sie voraussetzen**.

Damit das trägt, liegt die gesamte Ablauflogik in `service.py` und schreibt
nichts auf die Konsole. Die Oberflächen sind dünne Schichten darüber. Wer
eine weitere baut, ruft die Dienstschicht auf und schreibt keine eigene
Ablauflogik — sonst driften die Formen auseinander, und dann vergleicht die
Präsentation nicht mehr drei Verpackungen desselben Programms, sondern drei
verschiedene Programme.

Ein Test hält das fest: der geführte Modus erzeugt exakt dieselben Dateien
wie der direkte Aufruf.

### `metrics` — die Unterschiede messen statt behaupten

```
$ python3 -m releaser metrics
  Form                             Quelltext / CLI
  Startzeit                        80 ms
  Arbeitsspeicher                  17.8 MB
  Programmcode                     502.2 KB
  Fremdbibliotheken                1.4 MB
  zusammen                         1.9 MB
  Rechte nötig                     nein
  Daten liegen                     beim Nutzer, im eigenen Dateisystem

  * Setzt eine passende Python-Version voraus - und die Bereitschaft,
    eine Kommandozeile zu benutzen.
```

Die Form wird zur Laufzeit erkannt: `APPIMAGE`/`APPDIR` in der Umgebung,
`/.dockerenv` oder ein Container-Hinweis in `/proc/self/cgroup`, sonst
Quelltext. `--json` gibt dasselbe maschinenlesbar aus, damit sich die drei
Ausgaben nebeneinanderlegen lassen.

Gemessen wird nur, was sich ehrlich bestimmen lässt. Wo das nicht geht, steht
`unbekannt` statt einer plausiblen Zahl.

Die unbequemste Zeile ist „Rechte nötig": ausgerechnet die modernste Form
verlangt am meisten. Wer einen Container starten darf, hat faktisch Root auf
dem Wirt.

## Felder: die Designentscheidung des Originals, neu bewertet

Das Original baute sein Formular aus der geladenen `.skl`: Felder ohne
passenden Tag wurden ausgegraut. Das war 2003 richtig, weil die Vorlage die
einzige Abnehmerin der Eingaben war.

Heute speist dasselbe Modell **drei** Abnehmer: die NFO über die Vorlage, die
Dateinamen über die Namensmuster, die Tags über das Tag-Profil. Ein Feld ohne
Tag in der Vorlage kann trotzdem gebraucht werden — `#Catnr` landet mit
`catalog_in_album` im Album-Tag, `#Source` steckt im voreingestellten
Verzeichnismuster (als eigenes Feld „Quelle (Name)", siehe
[Naming-Schema](#naming-schema)). Ausgrauen würde bedeuten, dass man Werte
nicht eingeben kann, die das Programm gleich darauf benutzt.

`fields.py` behält deshalb die Erkenntnis und lässt die Einschränkung weg:
alle Felder bleiben da, aber die Vorlage bestimmt, wie sie aussehen.

```
$ releaser fields /pfad/zur/release vorlage.skl

in der Vorlage
   Artist              59  'Ein ziemlich langer Artistname'  (aus den Tags)
   Quelle              59  ''
   Format              59  'MP3'  (abgeleitet)

im Verzeichnisnamen
   Artist              59  ...
   Quelle (Name)        -  ''

nicht verwendet
   Subgenre             -  ''
```

Drei Dinge stehen dort, die keine andere Software zeigt:

**Die Feldbreite.** Ein Wert, der breiter ist als sein Platz in der Vorlage,
wird im NFO abgeschnitten — stillschweigend. `overflow_warnings()` meldet es
vorher, mitsamt dem Abschnitt, der übrig bliebe.

**Die Verwendung.** Ein Feld kann in mehreren Gruppen stehen. Was nirgends
gebraucht wird, landet in einer eigenen Gruppe: sichtbar und eingeklappt,
nicht deaktiviert — die Vorlage kann sich ja ändern.

**Die Herkunft.** `provenance.py` merkt sich, woher jeder Wert kommt: aus den
Tags, aus einem Dateinamen, aus einem CUE, aus dem Verzeichnisnamen oder
abgeleitet. Ein Titel aus einem gepflegten Tag verdient anderes Zutrauen als
einer, der aus `03-aus-dem-dateinamen.mp3` geraten wurde.
`origins.uncertain()` listet genau die Felder, bei denen ein Blick lohnt.

Der Scanner wusste das alles schon — er hat es bisher nur weggeworfen.

## Auslieferung als Bündel

```
./packaging/build.sh binary     # eine Datei, gut 20 MB, laeuft ohne Python
./packaging/build.sh appdir     # AppDir, direkt startbar ueber ./AppRun
./packaging/build.sh            # zusaetzlich das AppImage (braucht appimagetool)
PYTHON=python3.12 ./packaging/build.sh   # mit einem bestimmten Interpreter
```

PyInstaller bündelt den Python-Interpreter und mutagen in eine Datei. Geprüft
wird das mit `env -i` und `PATH=/nonexistent`: ohne Python, ohne Bibliotheken,
ohne PATH läuft der komplette Ablauf durch — taggen, umbenennen, NFO, SFV,
M3U, und `verify` meldet anschließend „2 ok".

**GTK wird nicht mitgebündelt.** Die Bibliothek ist zu eng mit dem System
verwoben; zwei GTK-Fassungen im selben Prozess vertragen sich nicht. Die
grafische Oberfläche nutzt deshalb das GTK des Wirts, und `metrics` sagt das
auch — statt einen Anspruch zu erheben, den das Bündel nicht einlöst.

Mitgebündelt wird nur die Python-Seite von PyGObject, einschließlich der
**GTK-Overrides** (`gi.overrides.Gtk`, `gi.overrides.Gdk`). PyInstaller nahm
die nur mit, wenn sein GTK-3-Hook griff; auf einem Rechner mit ausschließlich
GTK 4 fehlten sie, und die Oberfläche brach beim Start ab. Sie stehen jetzt
ausdrücklich im Spec. Umgekehrt bleiben Grafikbibliotheken, die GTK auf dem
Wirt ohnehin mitbringt (X11, xcb, cairo, fontconfig, freetype …), draußen –
dieselben Namen stehen auf der Ausschlussliste der AppImage-Gemeinschaft.
Ebenso der Textsatz (Pango, HarfBuzz, Graphene) und GTK selbst, jeweils mit
ihren Typelibs (`HOST_PROVIDED`, `HOST_TYPELIBS` in `pyinstaller.spec`):
Seit die NFO-Vorschau Pango direkt einbindet, zog PyInstaller sie sonst
herein, und eine ältere Pango aus dem Bündel neben dem neueren GTK des
Wirts brach den Start ab (0.25.0 auf Debian 13). Ein Test startet die
Oberfläche aus dem AppDir unter `xvfb-run`, ein zweiter prüft das gebaute
Bündel darauf, dass keine dieser Bibliotheken darin liegt.

Die Oberfläche kommt nur ins Bündel, wenn der bauende Interpreter PyGObject
und GTK 4 importieren kann; `build.sh` warnt sonst. Das fertige AppImage
braucht glibc 2.38 oder neuer – das legt der Rechner fest, auf dem gebaut
wird.

### Neue Version veröffentlichen

Das AppImage baut GitHub Actions (`.github/workflows/release.yml`), sobald
ein Versions-Tag gepusht wird:

```bash
# Version in pyproject.toml und releaser/__init__.py erhöhen, committen, dann:
git tag v0.22.2
git push origin v0.22.2
```

Der Workflow baut auf Ubuntu 24.04 mit demselben Aufbau wie oben, lässt
vorher die komplette Testsuite laufen (unter `xvfb` mit GTK 4 und WebKitGTK),
danach die Bündeltests samt Start der Oberfläche, startet das AppImage ohne
Python und ohne `PATH`, öffnet die Oberfläche in einem frischen Debian 13
(`packaging/check-start.sh`, mit einem neueren GTK als dem des Bausystems)
— und erst dann legt er das Release mit AppImage und `SHA256SUMS` an.
Passt das Tag nicht zur Version im Code, bricht er ab.
`appimagetool` ist auf eine Fassung mit Prüfsumme festgelegt. Von Hand
gestartet (*Actions → Release → Run workflow*) entsteht nur ein Artefakt zum
Ausprobieren, kein Release.

`AppRun` kommt ohne externe Programme aus: kein `readlink`, kein `dirname`.
Ein Bündel, das eine funktionierende `PATH`-Variable voraussetzt, hätte den
Zweck verfehlt. Ein Test startet es mit `PATH=/nonexistent`.

## Die drei Formen nebeneinander

```
$ releaser metrics --json > cli.json
$ ./build/AppDir/AppRun metrics --json > appimage.json
$ docker compose run --rm releaser metrics --json > container.json
$ releaser metrics --compare cli.json appimage.json container.json

                    Quelltext / CLI   AppImage          Container
------------------  ----------------  ----------------  --------------------
Startzeit           120 ms            140 ms            310 ms
Arbeitsspeicher     37.7 MB           34.7 MB           30.3 MB
Auslieferungsgröße  2 MB              15 MB             210 MB
Rechte nötig        nein              nein              ja
Daten liegen        beim Nutzer       beim Nutzer       im Container
```

Dieselbe Software, dieselben Fähigkeiten, verschiedene Voraussetzungen. Die
Zeile „Rechte nötig" ist die unbequemste: ausgerechnet die modernste Form
verlangt am meisten.

## Weboberfläche

```bash
RELEASER_MOUNTS="eingang:/data/eingang,archiv:/data/archiv:ro" releaser web
docker compose up
```

Wieder eine dünne Schicht über `uistate` — nur liegt zwischen Zustand und
Anzeige diesmal ein Netz. Das hat drei Folgen, die im Code sichtbar sind.

**Der Zustand liegt auf dem Server.** Jede Sitzung hat dort ihren eigenen
`AppState`, mit Cookie adressiert, nach einer Stunde verfallen. Wer den
Dienst betreibt, hat Zugriff darauf. Bei den anderen beiden Formen liegt
derselbe Zustand im Arbeitsspeicher des eigenen Rechners. Ein Test hält fest,
dass zwei Clients ihre Eingaben nicht sehen. Die Sitzungsverwaltung ist
threadsicher, weil FastAPI die Endpunkte in einem Thread-Pool ausführt.

**Die Dateiauswahl ist beschränkt.** Es gibt hier ausschließlich
`MountedSource`. Sichtbar ist, was jemand vorher in die Compose-Datei
geschrieben hat — der Nutzer der Oberfläche entscheidet das nicht. Die Seite
sagt das auch, in einem Banner über der Auswahl:

> Diese Fassung sieht nur die eingehängten Ordner: eingang, archiv (nur
> lesen). Was hier eingegeben wird, liegt auf dem Server, nicht auf diesem
> Rechner.

**Kein Hochladen.** Browser können die Originaldateien nicht umbenennen; es
entstünde eine Kopie im Container und ein ZIP zurück. Voller Funktionsumfang
geht nur über eingehängte Ordner — deshalb gibt es Drag & Drop bewusst nicht.

### Einstellungen im Container

Die Weboberfläche hat keinen Speichern-Knopf; ihre Einstellungen stehen in
`config/mp3releaser/config.toml` neben `docker-compose.yml`. Die
Compose-Datei hängt den Ordner `config/` nur lesend unter `/config` ein, das
Image setzt `XDG_CONFIG_HOME=/config`. Ohne `config.toml` gelten die
Voreinstellungen.

```bash
cp ~/.config/mp3releaser/config.toml config/mp3releaser/config.toml   # die des AppImage
docker compose restart releaser          # gelesen wird beim Start
docker compose logs releaser | grep Konfiguration
```

Eingehängt wird bewusst der Ordner, nicht die Datei: Fehlt eine eingehängte
Datei, legt Docker an ihrer Stelle einen leeren Ordner an — als root, den man
danach nur mit `sudo` wieder loswird. Der Ordner `config/mp3releaser/` liegt
deshalb schon im Repository, die `config.toml` darin schließt `.gitignore`
aus. Im Container wirken `[naming]`, `[tags]` und `[build]`; `[gui]` gilt nur
für die Desktop-Anwendung, und die Vorlage wählt man im Web aus `templates/`.

### In einer echten Browser-Engine geprüft

Die übrigen Web-Tests gehen über die API — das JavaScript läuft dabei nie.
`tools/webcheck.py` lädt die Seite deshalb mit **WebKitGTK** von einem echten
Server und bedient sie: klicken, doppelklicken, tippen, Dialog öffnen. Vierzehn
Prüfungen, unter `xvfb-run`, als regulärer Test eingebunden.

```
  [ok ] Banner nennt Beschränkung und Datenlage
  [ok ] ohne Auswahl sind alle Aktionen gesperrt
  [ok ] Doppelklick öffnet den Ordner
  [ok ] Gruppe „nicht verwendet“ ist eingeklappt
  [ok ] Überlänge wird rot markiert ({'counter': '92/59', 'red': True})
  [ok ] Umbenennungsplan erscheint im Dialog
  14 von 14 Pruefungen bestanden
```

Der Prüfstand hatte selbst zwei Fehler, die erst der Lauf zeigte: Ausnahmen in
GObject-Rückrufen wurden verschluckt, sodass die Kette still abbrach statt zu
melden — und alle Skripte teilten sich den globalen Namensraum, weshalb ein
`const` aus Schritt eins den zweiten Schritt zerlegte. Ein eigener Test prüft
jetzt, dass der Prüfstand Fehler auch meldet.

### Was nach außen geht

Nie ein Pfad des Wirtsystems. Der Browser sieht
`eingang/Artist-Album-2026-GRP`, der Weg zurück läuft ausschließlich über
`MountedSource.resolve()`. Vorlagennamen dürfen keine Pfadtrenner und keine
Null-Bytes enthalten, sonst wären sie ein zweiter Weg nach draußen.

Der Container läuft als eigener Benutzer, ohne Capabilities, mit
`no-new-privileges`, und der Port ist auf `127.0.0.1` gebunden. Ein Test
prüft, dass `RELEASER_MOUNTS` und die `volumes` der Compose-Datei
zusammenpassen — ein Einhängepunkt ohne Volume wäre ein Ordner, der nicht
existiert.

## Desktop-Anwendung (GTK 4)

```
+----------------------------------------------------------+
| Kopfleiste: Einlesen  Vorlage  |  Release erstellen  ⋯   |
+--------------------+-------------------------------------+
| Auswahl            | Felder, nach Verwendung gruppiert     |
| (Baum links)       | mit Breite, Zeichenzaehler, Herkunft  |
+--------------------+-------------------------------------+
| Statuszeile        | Meldungen (aufklappbar)               |
+----------------------------------------------------------+
```

`gtkui.py` ist reine Darstellung — jede Entscheidung steht in `uistate.py`.
Die Eingabefelder sind so breit wie ihr Platz in der Vorlage, daneben steht
ein Zähler `29/9`, der rot wird, bevor etwas abgeschnitten wird.

### Ein Knopf: Release erstellen

„Release erstellen" macht aus dem eingelesenen Ordner das fertige Release:
Tags schreiben, umbenennen, `.nfo`, `.sfv` und `.m3u` erzeugen — in dieser
Reihenfolge, mit einem Klick. Vorher waren das drei Knöpfe mit je eigener
Vorschau. Die Einzelschritte gibt es weiter, im Menü `⋯` daneben.

Ein Zwischendialog fehlt mit Absicht: Was entsteht, zeigen die Reiter
„Namen" und „NFO" schon vorher. Und bevor etwas angefasst wird, prüft
`AppState.produce`, ob alles gehen kann — eine Vorlage ist geladen, der
Ordner ist beschreibbar, beim Umbenennen gibt es keine Kollision. Sonst ändert
sich nichts, und ein Fenster sagt, warum. Danach zeigt ein Fenster, was getan
wurde. Zurückgenommen wird mit `↶`: erst die Umbenennung, dann die Tags.

Dasselbe gibt es im Web (Knopf „Release erstellen", `POST /api/produce`) und
auf der Kommandozeile als eine Eingabe:

```bash
releaser release /pfad/zur/release --group GRP
```

Ohne Vorlage auf der Kommandozeile nimmt `release` die gespeicherte, sonst die
mitgelieferte. Auch hier gilt: Kollidiert das Umbenennen, wird nichts
geschrieben — `build --tag --rename` hatte bis dahin die Tags schon in die
Dateien geschrieben.

Das Modul lässt sich **ohne GTK importieren**. `is_available()` sagt, ob die
Bibliothek da ist, `requirements_hint()` nennt das Paket und einen Weg, der
ohne Grafikstack funktioniert. Sonst ließe sich das Paket auf einem Server
nicht einmal einlesen.

### Als Standard speichern

Der Knopf mit dem Speichern-Symbol in der Kopfleiste merkt sich:

| gespeichert | Schlüssel |
|---|---|
| die geladene `.skl` | `[build] template` |
| den Gruppennamen | `[naming] group` |
| das Verzeichnis, das die Auswahl links gerade zeigt | `[gui] start` |
| Verzeichnis- und Dateimuster | `[naming] dir_pattern`, `file_pattern` |
| die Schreibweise von Ordner und Dateien (`upper`, `lower` …) | `[naming] case_dir`, `case_file` |
| das „00-“ vor den Begleitdateien | `[naming] companion_prefix`, `prefix_all` |

Ein Fenster bestätigt, was wo gespeichert wurde. Beim nächsten Start — auch
per Doppelklick auf das AppImage — ist alles wieder eingestellt, und die
Auswahl steht in dem gespeicherten Verzeichnis. Gibt es das nicht mehr,
beginnt sie an der Wurzel, mit einem Hinweis.

Gespeichert wird in die Datei, aus der die Einstellungen beim Start kamen;
ohne eine solche nach `~/.config/mp3releaser/config.toml`. Von Hand gepflegte
Abschnitte wie `[tags]` bleiben erhalten. Die mitgelieferte Vorlage steht dort
nur mit ihrem Namen (`standard.skl`): Im AppImage liegt sie unter einem Pfad,
der bei jedem Start anders heißt (`/tmp/.mount_…`). Fehlt eine gespeicherte
Vorlage, lädt das Programm die mitgelieferte und sagt es. Eine kaputte
Konfigurationsdatei verhindert den Start nicht: Das Fenster öffnet sich mit
der Voreinstellung und nennt den Fehler.

### Gegen echtes GTK geprüft

Die GTK-Aufrufe fallen sonst erst beim ersten Start auf. Die Tests bauen das
Fenster deshalb wirklich auf — unter `xvfb-run`, in einem Unterprozess, weil
GTK ohne Display abstürzt statt eine Ausnahme zu werfen. Geprüft werden der
Fensteraufbau, die Zeilen der Auswahl, das Durchschreiben einer Eingabe ins
Modell, das Zurückweisen einer ungültigen Eingabe und der Aufbau der
Planfenster.

Dabei kam ein Bedienfehler heraus, den keine Logikprüfung gefunden hätte:
Das Auswählen einer Zeile löste ein Neuzeichnen aus, und das Neuzeichnen warf
die gerade getroffene Auswahl weg — „Einlesen" blieb wirkungslos. Die Liste
wird jetzt nur neu gebaut, wenn sich ihr Inhalt geändert hat, und die
Auswahl ist ein eigener Zustand neben dem geöffneten Verzeichnis.

## Standardvorlage

`templates/standard.skl` enthält jedes Feld, das sich in einer Oberfläche
eintragen lässt, dazu die berechneten Werte — Bitrate, Samplerate, Laufzeiten,
Größe, Trackliste mit Fortsetzungszeile, Notizen und Gruppennachrichten. 78
Spalten breit, Rahmen aus Codepage 437, eigene Gestaltung.

```
╠════════════════════════════════[ RELEASE ]═════════════════════════════════╣
║   Artist          : Die Ärzte                                              ║
║   Full title      : Ein Album (Deluxe)                                     ║
╠═══════════════════════════════[ TRACKLIST ]════════════════════════════════╣
║       CD1                                                                  ║
║   01. Intro                                                      [01:05]   ║
║   02. Ein ziemlich langer Titel, der in die Fortsetzungszeile    [03:35]   ║
║       umbricht                                                             ║
```

Sie wird **von selbst geladen**, in allen drei Formen: im Desktop und auf der
Kommandozeile aus `templates/`, im AppImage aus `usr/share/mp3releaser/`, im
Container aus dem eingehängten Vorlagenordner. Eine ausdrücklich gewählte
oder gespeicherte Vorlage hat Vorrang.

Nicht enthalten sind nur Tags, die einen schon vorhandenen Wert anders
ausgerichtet wiederholen würden (`Tpti#` neben `#Tpti`, `#Releasenc` neben
`#Release` …), die Positionsmarker `#Notesmark` und `#Notesmarkend` und das
im Original unbenutzte `#Bm`. Ein Test hält fest, dass jeder andere Tag
drinsteht — ein vergessener fiele auf.

Erzeugt wird die Datei von `tools/make_standard_skl.py`: Eine `.skl` ist
spaltengenau, und ein Leerzeichen zu viel verschiebt den rechten Rahmen. Der
Generator baut jede Zeile auf dieselbe Breite und prüft das selbst.

## Prüfen

Ein Kommando, zwei Gegenstände — was geprüft wird, entscheidet der Pfad.

**Eine Vorlage**, bevor jemand sie benutzt:

```
$ releaser check eng.skl
eng.skl: 4 Hinweise
  ! #Album fehlt - das Album taucht nirgends auf [#Album]
  ! #Trk fehlt - die Trackliste taucht nirgends auf [#Trk]
  ! weder #Release noch #Artist und #Album - die Kopfzeile bleibt leer
  ! #Artist hat nur 8 Zeichen Platz, empfohlen sind mindestens 24 [#Artist]
```

Geprüft werden zu schmale Felder, fehlende Tags, Tippfehler wie `#Quatsch`,
reine Namens-Tags wie `#Grp` (sie landeten wörtlich in der NFO), eine
fehlende Fortsetzungszeile in der Trackliste und die Gesamtbreite. Das
steckt alles in der `.skl` selbst und fiele sonst erst an einem Release auf,
dessen Werte zufällig lang genug sind. In der Oberfläche gibt es dafür den
Knopf „Vorlage prüfen".

**Ein fertiges Release**, nachdem alles erzeugt wurde:

```
$ releaser check /pfad/zur/release
Der_Artist-Das_Album-FLAC-2026-GRP: 1 Fehler, 1 Anmerkungen
  x Prüfsumme weicht ab: erwartet 2CFAFC5D, gefunden B7C5EC05 [01-….flac]
  - kein Bild im Verzeichnis
```

NFO, SFV und Playlist vorhanden, Prüfsummen stimmen, alle Tracks getaggt,
keine doppelten Tracknummern, Namen nicht zu lang — und mit `--against`
zusätzlich die Dupe-Prüfung. Der Exit-Code ist 1, wenn etwas wirklich kaputt
ist; ein fehlendes Bild ist nur eine Anmerkung.

## Rückgängig machen

Umbenennen ist die einzige Operation, die sich nicht aus den Dateien
zurückrechnen lässt — hinterher weiß niemand mehr, wie es vorher hieß. Jeder
ausgeführte Plan wird deshalb protokolliert, unter
`~/.local/state/mp3releaser/undo.json`.

```
$ releaser undo --list
 1. 2026-09-19 14:27  Der_Artist-Das_Album-FLAC-2026-GRP  (3 Umbenennungen)
$ releaser undo --apply
3 Umbenennung(en) zurueckgenommen.
```

Nicht im Releaseverzeichnis, denn das wird ja selbst umbenannt und beim
nächsten `--clean` womöglich aufgeräumt.

**Tags lassen sich ebenso zurücknehmen.** Vor dem Schreiben werden die alten
Werte der geänderten Felder festgehalten — nur dieser Felder; unveränderte
zurückzuschreiben würde Dateien anfassen, die niemand verändert hat. Beide
Arten stehen im selben Protokoll:

```
$ releaser undo --list
 1. 2026-09-20 14:23  Der_Artist-Das_Album-FLAC-2026-GRP  (3 Umbenennungen)
 2. 2026-09-20 14:22  rel  (2 getaggte Dateien)
```

Das Protokoll wird in `apply_tags` geschrieben, nicht in der Dienstschicht
darüber. Das hat einen Grund: Das `tag`-Kommando schrieb an der Dienstschicht
vorbei und blieb deshalb zunächst unprotokolliert — derselbe Fehler, der
vorher schon beim `rename` aufgefallen war. An der Stelle, durch die jedes
Schreiben muss, kann ihn niemand mehr umgehen. Ein einzelner beschädigter
Eintrag im Protokoll wird übergangen, statt das ganze Protokoll unlesbar zu
machen.

Die Rücknahme läuft in umgekehrter Reihenfolge: erst das Wurzelverzeichnis,
dann die CD-Ordner, zuletzt die Dateien. Das ist auch der Grund für einen
Fallstrick, über den ich zuerst gestolpert bin: Der protokollierte Pfad einer
Datei zeigt auf den *alten* Ordnernamen. Die Vorabprüfung muss deshalb
nachrechnen, wo die Datei heute liegt — naiv geprüft wäre jede Datei „nicht
mehr vorhanden".

## NFO-Vorschau

Ein dritter Reiter zeigt die fertige `.nfo` und ändert sich bei jeder
Eingabe mit — man tippt in ein Feld und sieht, wie sich der ASCII-Rahmen
füllt:

```
+------------------------------------------------------------------+
|                    Der Artist - Das Album                        |
|   Artist      : Der Artist                                       |
|   Album       : Das Album                                        |
|   01.Titel 1                                          [03:35]    |
+------------------------------------------------------------------+
41 Zeilen, breiteste 78 Zeichen · Vorlage: example.skl
```

Steht unter der Vorschau ein Hinweis wie „2 Feld(er) werden abgeschnitten",
passt ein Wert nicht in seinen Platz — das sieht man jetzt, bevor die Datei
entsteht, und nicht erst hinterher darin.

Dasselbe gilt für die Trackliste, dort aber mit einer Bedingung: Hat die
Vorlage eine Fortsetzungszeile, bricht ein langer Titel um und geht nicht
verloren. Fehlt sie, wird er abgeschnitten — und *das* wird gemeldet.

Kein Zeilenumbruch: Die Vorlage ist spaltengenau, ein Umbruch würde den
Rahmen zerreißen. Die Anzeige scrollt stattdessen waagerecht.

**Im festen Raster, nicht als Text.** Zuerst stand die Vorschau in einem
Textfeld. Fehlten der Schrift die Blockzeichen der Codepage 437 (`█ ▄ ▀ ▌ ▐
░ ▒ ▓`), nahm die Textdarstellung sie aus einer Ersatzschrift — mit anderer
Breite. Jede Zeile mit Block-Grafik verrutschte gegenüber den anderen und sah
eingerückt aus; nachgestellt mit „Noto Mono". Und weil der Zeilenabstand
einer Schrift größer ist als ihre Zeichen, blieb zwischen übereinanderliegenden
Blöcken eine Fuge, senkrechte Rahmenlinien waren gestrichelt.

Jetzt hat jedes Zeichen seine Zelle, wie in einem NFO-Betrachter.
`nfoview.py` beschreibt die 48 Grafikzeichen von `0xB0` bis `0xDF` — Blöcke,
Schattierungen, alle einfachen, doppelten und gemischten Rahmenzeichen — als
Rechtecke, die ihre Zelle bis zum Rand füllen; Doppellinien biegen an Ecken
außen um und halten innen an. Der Desktop zeichnet sie über `Gtk.Snapshot`,
die Webseite auf einem Canvas — nach derselben Geometrie, die der Server
mitliefert. Nur gewöhnliche Zeichen kommen noch aus der Schrift, jedes einzeln
an seinem Platz. Ein Test zeichnet dieselbe Grafik mit verschiedenen Schriften
und misst nach, dass Blöcke lückenlos sind; die Prüfung im Browser misst die
Rahmenlinie der Standardvorlage Pixel für Pixel. „Text kopieren" legt die
`.nfo` als Text in die Zwischenablage.

Beide Oberflächen haben sie, aus derselben Quelle. Im Web ist es ein eigener
Endpunkt statt eines Feldes im Zustand — die Datei ist einige Kilobyte groß
und wird nur geladen, wenn der Reiter offen ist.

## Fensterlogik ohne Fenster

`uistate.py` enthält alles, was ein Fenster tut, nur ohne Fenster: welcher
Ordner offen ist, welches Release geladen wurde, welche Felder geändert
wurden, **welche Schaltflächen benutzbar sind** und was beim Klicken passiert.

Die GTK- und die Browser-Schicht darüber bleiben reine Darstellung. Das hat
zwei Gründe. Erstens verhalten sich Desktop und Web dann nicht nur ähnlich,
sondern gleich — ein Test lädt dasselbe Release über `LocalSource` und über
`MountedSource` und vergleicht das Ergebnis Feld für Feld. Zweitens lässt
sich das Verhalten ohne Grafikumgebung prüfen; was danach schiefgeht, ist
Layout.

### `enabled()` statt verstreuter Ereignisbehandler

Welche Schaltfläche wann aktiv ist, steht an einer Stelle:

```python
Action.APPLY_RENAME: bool(plan and plan.changes and plan.is_safe)
```

Daraus folgen Regeln, die die Oberfläche nicht selbst kennen muss:

* „Umbenennen" ist erst nach einer Vorschau benutzbar — und nur, wenn der
  Plan keine Kollisionen hat.
* Ändert jemand ein Feld, verfallen beide Pläne. Sie bezogen sich auf den
  alten Stand, und ein Knopf, der einen veralteten Plan ausführt, ist
  schlimmer als ein grauer Knopf.
* „Dateien erzeugen" braucht eine Vorlage — außer die `.nfo` ist abgewählt.

### Eingaben gehen nicht verloren, aber auch nicht durch

`set_field()` prüft den Typ, bevor es ins Modell schreibt: Buchstaben im
Jahresfeld werden gemeldet, nicht übernommen. Jede Änderung von Hand setzt
die Herkunft des Feldes auf „von Hand" — damit verschwindet die Warnung
„unsicher" genau dann, wenn jemand hingeschaut hat.

Fehler aus der Tiefe werden zu Meldungen statt zu Abstürzen: Ein Pfad, der
aus dem Einhängepunkt herausführt, landet als rote Zeile in der Meldungsliste
und die Auswahl bleibt leer. Dasselbe gilt für scheiternde schreibende
Aktionen — ein fehlendes Schreibrecht etwa erscheint im Web als Meldung statt
als nackter Serverfehler 500. Und hat sich zwischen Vorschau und Ausführung
etwas geändert, sodass der Umbenennungsplan nicht mehr sicher ist, wird nichts
umbenannt, und die Oberfläche sagt das.

## Dateiauswahl

Beide Oberflächen zeigen links einen Baum. Was sie zeigen dürfen, ist
verschieden — und das ist der Punkt:

| | `LocalSource` | `MountedSource` |
|---|---|---|
| Reichweite | das gesamte Dateisystem | nur was eingehängt wurde |
| Pfade nach außen | echte Pfade | virtuell, `einhaengepunkt/unterordner` |
| Wer entscheidet | der Nutzer | wer den Container betreibt |

```
$ releaser browse --start /tmp/mnt /tmp/mnt
Quelle: lokales Dateisystem - Reichweite: das gesamte Dateisystem des Nutzers
  [R] /tmp/mnt/eingang  (2 Audiodateien)
  [ ] /tmp/mnt/geheim

$ releaser browse --mounts "eingang:/tmp/mnt/eingang"
Quelle: eingehängte Verzeichnisse - Reichweite: nur was eingehängt wurde
  eingang: schreibbar
  [R] eingang  (2 Audiodateien)
```

Dasselbe Verzeichnis, zwei Formen — im zweiten Fall existiert `geheim` für
das Programm nicht. Die Weboberfläche bekommt deshalb **keine** Drag-and-drop-
Variante: Browser können die Originaldateien nicht umbenennen, das Ergebnis
wäre eine Kopie im Container und ein ZIP zurück. Volle Funktion gibt es nur
über eingehängte Ordner, und die trägt jemand vorher in die Compose-Datei ein.

Konfiguriert wird wie bei Docker gewohnt:

```
RELEASER_MOUNTS=eingang:/data/eingang,archiv:/data/archiv:ro
```

### Die Beschränkung muss halten

`MountedSource` gibt nie Wirtspfade heraus und prüft jeden Weg zurück nach
innen. Getestet wird nicht nur der Normalfall, sondern vor allem, was
scheitern muss: `..` in jeder Schreibweise, absolute Pfade, unbekannte
Einhängepunkte, Null-Bytes — und **Symlinks**, die aus dem Einhängepunkt
herausführen. Der letzte Fall ist der unauffälligste: Der Pfad sieht bis zum
Auflösen harmlos aus, deshalb wird erst danach geprüft, nicht davor.

## Geführter Modus

`wizard` führt durch die vier Schritte und zeigt vor jeder verändernden
Aktion, was passieren würde. Er hat keine eigene Ablauflogik, nur Rückfragen.

Ohne Terminal bricht er ab, statt die Vorgaben durchzuwinken — eine
Rückfrage, die niemand sieht, darf nicht stillschweigend mit „ja" beantwortet
werden, wenn dahinter Dateien umbenannt werden. Für Vorführungen und Tests
gibt es `--batch` als ausdrückliches Opt-in.

## Stand

Der Funktionsumfang des Originals ist abgedeckt, dazu vier Oberflächen
(Kommandozeile, geführter Modus, GTK 4, Web) in drei Auslieferungsformen.
860 Tests, jede Schicht auf ihrer eigenen Ebene geprüft:

| Ebene | wie geprüft |
|---|---|
| Kern, Dienstschicht | direkt, ohne Oberfläche |
| Fensterlogik | ohne Fenster, mit gescriptetem Ein-/Ausgabeobjekt |
| GTK 4 | Fenster wirklich aufgebaut, unter `xvfb-run` |
| Web-API | über HTTP mit `TestClient` |
| Webseite | in WebKitGTK bedient — Klicks, Eingaben, Dialoge |
| Bündel | mit `env -i` und `PATH=/nonexistent` gestartet; Oberfläche aus dem AppDir gestartet |
| EC-3-Parser | gegen `ffprobe` als unabhängiges Orakel |
| Prüfsummen | gegen eine eigene bitweise CRC32-Implementierung |
| dieses README | gegen Kommandoliste, Modulbaum und Testzahl |

Der letzte Eintrag hat einen Anlass: Der Kopf dieses README stand lange auf
dem Stand des ersten Tages, weil Textersetzungen stillschweigend nicht
griffen — eine Ersetzung ohne Treffer meldet nichts. `tests/test_readme.py`
prüft jetzt für beide Sprachfassungen, dass jedes erwähnte Kommando existiert,
jedes existierende erwähnt ist, der Modulbaum stimmt und die genannte
Testzahl aktuell ist.

Die Korrekturen aus der Fehlerdurchsicht zu 0.22.1 und alle Änderungen
seitdem stehen mit Ursache und Auswirkung in [`CHANGE.md`](CHANGE.md).

### Aus der ersten Erprobung

Drei Rückmeldungen vom ersten echten Start des AppImage:

* **Reiter „Namen".** Verzeichnis- und Dateimuster sind jetzt in der
  Oberfläche änderbar, mit einer Vorschau, die sich beim Tippen mitändert.
  Der Verzeichnisname lässt sich auch **von Hand** setzen: ein Muster ohne
  Tags wird wörtlich übernommen, die Zeichenregeln greifen weiter.
* **Notizen und Gruppennachrichten** sind mehrzeilig geworden. Vorher standen
  sie in einer einzeiligen Eingabe mit Ersatzzeichen — unbrauchbar.
* **Felder waren versteckt.** Ohne geladene Vorlage landet fast alles in der
  Gruppe „nicht verwendet", und die war eingeklappt. Sie bleibt jetzt offen,
  solange keine Vorlage geladen ist, und ein Hinweis sagt, was ohne Vorlage
  fehlt.

**Der Absturz beim Ändern eines Tags.** Bei jeder Wertänderung wurde das
ganze Formular neu gebaut — während das geänderte Eingabefeld noch den Fokus
hatte. GTK zerstörte das Widget, dessen Fokus-Controller daraufhin erneut
auslöste und auf bereits freigegebenen Speicher zugriff. Das Ergebnis war ein
Absturz, keine Ausnahme, und deshalb auch keine Meldung.

Zwei Absicherungen: Eine reine Wertänderung baut das Formular gar nicht mehr
neu — Gruppen und Feldbreiten ändern sich dabei ohnehin nicht, nur die
Herkunftsangabe wird an Ort und Stelle nachgezogen. Und ein Feld, das während
des Abräumens noch „leave" meldet, schreibt nichts mehr. Beide Pfade sind
getestet.

Dazu: Ausnahmen aus Ereignisbehandlern werden abgefangen und erscheinen als
rote Meldung *und* auf der Standardfehlerausgabe. GTK verschluckte sie sonst —
das Fenster blieb stehen, ohne dass jemand erfuhr, warum.

### Aus der zweiten Erprobung

* **Getrennte Schreibweisen.** Verzeichnis und Dateien haben je eine eigene
  Regel — in der Szene ist der Ordner groß und die Dateien klein
  geschrieben. `--case-dir` und `--case-file`, in der Oberfläche zwei
  Auswahlfelder.
* **Präfix für alle Begleitdateien.** `--prefix-all` nimmt `.sfv` und `.m3u`
  mit; ohne die Option bleibt es beim Original-Verhalten (nur `.nfo` und
  Bilder). SFV und M3U bildeten ihren Namen bis dahin selbst und kannten die
  Präfixregel gar nicht.
* **Bilder** im Releaseordner werden erkannt und mit umbenannt, mit demselben
  Rumpf wie die übrigen Begleitdateien. Die Vorschau nennt das gefundene Bild.
* **Standard speichern.** Ein Knopf in der Kopfleiste schreibt Vorlage,
  Muster, Gruppe, Schreibweisen und Präfix nach
  `~/.config/mp3releaser/config.toml`. Beim nächsten Start ist alles gesetzt
  — für eine Vorführung entscheidend. Gespeichert wird in die vorhandene
  Datei hinein; von Hand gepflegte Abschnitte wie `[tags]` bleiben erhalten.
* **Einfachklick öffnete den Ordner.** `GtkListBox` löst `row-activated`
  standardmäßig schon beim einfachen Klick aus. Jetzt wählt ein Klick aus,
  ein Doppelklick öffnet.

### Aus der dritten Erprobung

* **Verzeichnis kapitalisiert, Dateien klein.** Voreinstellung der Oberfläche
  ist jetzt `capitalize` für den Ordner und `lower` für die Dateien:
  `Die_Aerzte-Ein_Album-CDDA-2026-GRP` mit `01-die_aerzte-erster_titel.flac`
  darin.
* **Unterstriche sind Wortgrenzen.** In Python zählt `_` als Wortzeichen —
  ohne Sonderbehandlung wurde aus `der_artist` ein einziges Wort und damit
  `Der_artist`. Nach der Regelkette stehen die Wörter aber genau so da.
* **Akronyme bleiben stehen**, bis vier Zeichen: `CDDA`, `WEB`, `GRP`, `DJ`.
  Längeres wird normalisiert, damit aus `REMIXED` nicht dauerhaft
  Großbuchstaben werden.
* **Begleitdateien folgen der Dateischreibweise**, nicht der des
  Verzeichnisses. Sie sind Dateien — ein Ordner darf kapitalisiert heißen und
  `.nfo`, `.sfv`, `.m3u` und das Bild darin trotzdem durchgehend klein:

```
Der_Artist-Das_Album-2026-GRP/
    00-der_artist-das_album-2026-grp.jpg
    00-der_artist-das_album-2026-grp.m3u
    00-der_artist-das_album-2026-grp.nfo
    00-der_artist-das_album-2026-grp.sfv
    01-der_artist-titel_1.flac
    02-der_artist-titel_2.flac
```

### Aus der vierten Erprobung

* **`00-` ist Voreinstellung**, für alle Begleitdateien. Abschaltbar mit
  `--no-prefix`, auf `.nfo` und Bilder beschränkbar über
  `prefixed_suffixes`.
* **Formatkennung im Ordnernamen.** Der neue Namens-Tag `#Fmt` setzt vor dem
  Jahr eine Kennung ein, abgeleitet aus dem, was der Scanner gefunden hat:

  | erkannt | Kennung | Ordner |
  |---|---|---|
  | MP3 | keine | `der_artist-das_album-cdda-2026-grp` |
  | FLAC | `FLAC` | `der_artist-das_album-cdda-flac-2026-grp` |
  | AAC | `AAC` | `der_artist-das_album-cdda-aac-2026-grp` |
  | EC-3 mit JOC | `ATMOS` | `der_artist-das_album-cdda-atmos-2026-grp` |

  MP3 ist der stillschweigende Normalfall und bekommt keine Kennung — so
  hielt es auch die Szene. Atmos sticht dabei das Containerformat: eine
  EC-3-Datei mit JOC ist für den Hörer ein Atmos-Release, kein EAC3-Release.
  Fehlt die Kennung, bleibt kein doppeltes Trennzeichen stehen; das erledigt
  die `collapse`-Regel.

### Was der fünfte Durchgang ergeben hat

* **Eine Voreinstellung für alle Oberflächen.** Sie lag verstreut: die
  Bibliothek sagte „klein für beides", das Auswahlfeld im Desktop zeigte
  „capitalize" und die Weboberfläche benutzte wieder etwas anderes. Jetzt
  liefert `service.naming_from_config()` sie an einer Stelle, und ein Test
  vergleicht Desktop und Web Feld für Feld.
* **Anzeige und Wirklichkeit.** Die Auswahlfelder für die Schreibweise waren
  fest vorbelegt, statt den Zustand abzulesen — sie zeigten „capitalize",
  während „lower" galt.
* **Tippfehler im Muster.** `#Quatsch` überlebte die Regelkette und landete
  wörtlich im Namen. Unbekannte Tags werden jetzt gemeldet.
* **Leeres Verzeichnismuster.** Es zielte auf das *übergeordnete*
  Verzeichnis. Die Kollisionsprüfung fing es zufällig ab, weil das
  Elternverzeichnis immer existiert. Jetzt wird es ausdrücklich abgewiesen.
* **Namens-Reiter auch im Web.** Muster, Gruppe und Vorschau waren nur im
  Desktop erreichbar, obwohl die Logik gemeinsam ist.

### Was der sechste Durchgang ergeben hat

* **Drei Stellen umgingen die Voreinstellung.** `service.build()`,
  `service.process()` und der geführte Modus fielen ohne Profil auf die
  Bibliotheksvorgabe zurück — sie benannten also anders als jede Oberfläche.
  Ein Test prüft jetzt, dass dort kein `NamingProfile()` mehr steht.
* **Bitratenwarnung bei verlustfreien Formaten.** FLAC hat je Datei eine
  andere Bitrate; die Meldung „unterschiedliche Bitraten" kam bei jedem
  FLAC-Release und war reines Rauschen. Sie gilt jetzt nur noch für
  verlustbehaftete Formate. Mit ABR kodierte MP3 zählen ebenfalls als
  variabel.
* **Überlange Pfade.** Ein Pfadbestandteil jenseits von 255 Zeichen ließ das
  Betriebssystem werfen — in der Weboberfläche ein Serverfehler mit Traceback
  statt einer Meldung. Wird jetzt vorher abgewiesen.
* **Steuerzeichen im NFO.** Ein Nullbyte aus einem defekten Tag überlebte bis
  in die Ausgabe und hätte die Spaltenausrichtung zerstört. Dateinamen waren
  bereits geschützt, die NFO nicht.

Gegengeprüft, ohne Befund: alle sechzehn Kommandos, der Audio-Layer mit
beschädigten Dateien jedes Formats, der SKL-Renderer mit entarteten Vorlagen
(1000 Tracks, Tags ohne Platz, nur Fortsetzungszeilen) und ein zweiter
`build`-Lauf auf demselben Release.

### Aus der siebten Erprobung

Sonderzeichen aus Titeln landeten unverändert in den Dateinamen. Die neue
Regel `alnum` lässt nur Buchstaben, Ziffern und Trennzeichen stehen; alles
andere wird zu einem Trenner. Apostrophe verschwinden ganz, sonst würde aus
`Don't` ein `don_t`.

Sie läuft **nach** `transliterate` — erst wird `ä` zu `ae`, dann wird
aussortiert. In der anderen Reihenfolge wäre der Umlaut spurlos weg.

**Nur für Namen, nicht für Tags.** In den Dateien bleiben Kommas, Klammern
und Umlaute erhalten; sie gehören dorthin. Ein Test hält beides nebeneinander
fest:

```
Ordner   Die_Aerzte-Ein_Album_Deluxe_Teil_2-FLAC-2026-GRP
Datei    02-die_aerzte-rocknroll_live_koeln.flac
Tag      'Die Ärzte' | 'Ein Album (Deluxe), Teil 2' | "Rock'n'Roll (Live @ Köln)"
```

Dabei kam ein Folgefehler heraus: Ein Sonderzeichen direkt vor einem
Muster-Trennstrich verschluckte diesen — aus `…(Mix)-CDDA…` wurde
`…mix_cdda…`. Trifft eine Folge aus Trennzeichen aufeinander, gewinnt jetzt
der Bindestrich, weil er im Muster die Bestandteile trennt.

### Was der achte Durchgang ergeben hat

* **Rückwärts-Schrägstriche in der M3U.** Das Original lief unter Windows und
  schrieb `CD1\01-….flac`. Unter Linux findet das kein Abspieler. Normale
  Schrägstriche sind jetzt Voreinstellung, `--m3u-windows-paths` stellt das
  alte Verhalten her.
* **Musterfeld und Wirklichkeit.** Wer den Verzeichnisnamen von Hand setzt,
  ändert damit das Muster — das Eingabefeld darüber zeigte weiter das alte.
* **Dupe-Prüfung kannte die neuen Formate nicht.** `ATMOS`, `EAC3`, `ALAC`,
  `OPUS` und `MPC` zählten nicht als Formatangabe, deshalb galten eine
  FLAC- und eine Atmos-Fassung desselben Albums als verschiedene Releases.

Gegengeprüft, ohne Befund: der Inhalt aller erzeugten Dateien bei einem
Zwei-CD-Release mit Umlauten (NFO in CP437, SFV mit Audio-CRC, Super-M3U,
`verify` meldet „2 ok" je CD), ein Release mit einer einzigen ungetaggten
Datei, ein Quellordner mit Komma im Namen und ein Lauf über sechzig Dateien.

### Was der neunte Durchgang ergeben hat

* **Abgeschnittene Tracktitel wurden nicht gemeldet.** `overflows()` kennt
  nur die Kopfdaten. Ob ein langer Titel umbricht oder verloren geht, hängt
  daran, ob die Vorlage eine Fortsetzungszeile hat — das steht jetzt unter
  der Vorschau.
* **Zwei kryptische Meldungen.** `metrics --compare` nannte bei kaputtem JSON
  nicht die Datei, und ein `KeyError` brachte seine Anführungszeichen mit:
  `Fehler: 'unbekannte Namensregel: …'`.

Gegengeprüft, ohne Befund: leere Titel, Titel aus reinen Sonderzeichen,
doppelte Tracknummern (Kollision wird erkannt), CD-Ordner mit Leerzeichen im
Namen, die Vorschau bei Samplern und Mehr-CD-Releases, und ob die
Überlauf-Warnung mit dem tatsächlich gerenderten Text übereinstimmt — bei 200
Zeichen langen Werten bleibt die NFO exakt 78 Spalten breit.

### Was der zehnte Durchgang ergeben hat

* **Unbrauchbare Eingaben wurden zu Programmfehlern statt zu Befunden.**
  `check` auf ein Verzeichnis ohne Audiodateien brach mit Exit-Code 2 ab,
  statt einen Bericht mit einem Fehler zu liefern. Jetzt ist es ein Befund
  über das Release, kein Fehler des Programms.
* **Eine Binärdatei galt als Vorlage** — mit vier Hinweisen zu fehlenden
  Tags. Eine Datei ohne einen einzigen Tag ist jetzt ein Fehler, und eine
  ungewöhnliche Endung eine Anmerkung.
* **Parität.** Prüfen und Rückgängig gab es nur auf der Kommandozeile und
  halb im Desktop. Beides liegt jetzt in `uistate` und steht in allen drei
  Oberflächen zur Verfügung — im Desktop als Knöpfe, im Web über `/api/check`
  und `/api/undo`.

Gegengeprüft, ohne Befund: Rücknahme nach dem Löschen einer Datei (wird
erkannt und verweigert, `--force` nimmt zurück, was geht), Rücknahme eines
Mehr-CD-Laufs, zwei gestapelte Läufe im Protokoll und ein fehlgeschlagener
Plan, der nichts protokolliert.

### Was der elfte Durchgang ergeben hat

* **Im Dienst konnte ein Nutzer die Umbenennung eines anderen zurücknehmen.**
  Das Protokoll liegt einmal auf dem Server und gehört allen Sitzungen
  gemeinsam. Bernd sah im Protokoll, was Anna umbenannt hatte — mitsamt
  Releasename — und konnte es mit einem Klick zurückdrehen. Nachgestellt mit
  zwei Clients gegen denselben Dienst.

  Jetzt merkt sich jede Sitzung, welche Einträge sie selbst angelegt hat, und
  im Dienst darf sie nur diese sehen und zurücknehmen. Am eigenen Rechner
  bleibt es beim gemeinsamen Protokoll: Dort soll man auch zurücknehmen
  können, was die Kommandozeile getan hat.

  Für die Präsentation ist das ein handfester Fall: Dieselbe Funktion ist am
  eigenen Rechner harmlos und im geteilten Dienst ein Übergriff. Der
  Unterschied liegt nicht im Code der Funktion, sondern darin, wem der Ort
  gehört, an dem der Zustand liegt.
* **Die Tag-Rücknahme hinterließ Spuren.** Die Werte kehrten zurück, aber
  ein ID3v1-Block, den der Tag-Lauf angelegt hatte, blieb stehen — ebenso
  APEv2 und Lyrics3v2. Das Protokoll hält bei MP3 jetzt fest, welche Blöcke
  vorher da waren, und die Rücknahme entfernt die übrigen.

* **Nur lesend eingehängte Ordner wurden beschrieben.** `:ro` in
  `RELEASER_MOUNTS` stand zwar in der Beschreibung des Einhängepunkts, wurde
  aber vor dem Umbenennen, Taggen und Erzeugen nicht geprüft. Im echten
  Container hätte der Kernel es abgewiesen — mitten im Vorgang, mit einem
  Systemfehler. Jetzt bleiben Vorschauen erlaubt, Ausführen ist gesperrt, und
  die Statuszeile sagt „nur lesend".

Gegengeprüft, ohne Befund: Tag-Rücknahme bei MP3, AAC, Ogg und FLAC — jeweils
exakt der Ausgangsstand, einschließlich der Gesamtzahl `3/12`, und der
Audio-CRC ist nach Schreiben und Rücknahme unverändert.

### Beim Bauen der Standardvorlage

* **Das Build-Skript verwendete ein veraltetes Bündel.** `build.sh appdir`
  baute die Einzeldatei nur, wenn gar keine da war. Eine alte blieb liegen —
  das AppImage kannte dann `check` und `undo` nicht, obwohl der Quelltext sie
  längst hatte. Jetzt wird neu gebaut, sobald eine Quelldatei neuer ist als
  das Bündel, und `releaser --version` sagt, welche Fassung man vor sich hat.
* **Ein übersprungener Test war veraltet.** Der Ende-zu-Ende-Test des
  Bündels lief hier seit Wochen nicht, weil kein Bündel gebaut war. Die
  geänderte Voreinstellung für die Schreibweise hat er deshalb nie gesehen —
  er erwartete noch den klein geschriebenen Ordner. Übersprungene Tests
  verrotten unbemerkt; ein zusätzlicher Test prüft jetzt, dass das Bündel
  jedes Kommando des Quelltexts kennt.

### Die Tests und das Benutzerverzeichnis

Mit dem Tag-Undo schrieb jeder Test, der Tags setzt, einen Eintrag ins
Rückgängig-Protokoll — ins echte, unter `~/.local/state`. Ein Testlauf
hinterließ siebzehn Einträge, und ein anschließendes `releaser undo` hätte
Testdateien statt der eigenen Releases angefasst. Außerdem hingen die Tests
der Oberfläche davon ab, was man zuletzt als Standard gespeichert hatte.

`tests/conftest.py` leitet jetzt für jeden Test `XDG_STATE_HOME` und
`XDG_CONFIG_HOME` in ein Wegwerfverzeichnis um. Ein Test prüft, dass die
Umleitung greift.

### Aus der zwölften Erprobung

* **Dateinamen von Hand.** Aus „Los Marañones I - Nattern Narren" machte die
  Regelkette `los_maranones_i-nattern_narren` — gemeint war `_-_`. Im Reiter
  „Namen" lässt sich jetzt jeder Dateiname einzeln überschreiben, im AppImage
  wie im Web (siehe [Naming-Schema](#naming-schema)).
* **Zwei Quellen statt einer.** „Quelle" stand unter „in der Vorlage" und
  unter „im Verzeichnisnamen" — und war dasselbe Feld: Eine Änderung in der
  einen Gruppe tauchte in der anderen auf. Jetzt sind es zwei eigenständige
  Felder; `#Source` in den Namensmustern liest „Quelle (Name)".

### Aus der dreizehnten Erprobung

* **„Standard speichern" blieb ohne Wirkung.** Gespeichert wurde zwar, aber
  das AppImage, per Doppelklick ohne Argumente gestartet, las die
  Konfiguration gar nicht: `run()` baute dann einen leeren Zustand. Nur
  `releaser gui` lud sie. Dazu landete die Bestätigung in der eingeklappten
  Meldungsliste — beim Klick sah man nichts. Jetzt starten beide Wege gleich,
  und ein Fenster bestätigt das Speichern (siehe
  [Als Standard speichern](#als-standard-speichern)).
* **Das Verzeichnis wird mitgespeichert.** Die Auswahl öffnet beim Start den
  zuletzt gespeicherten Ordner.
* **Releasedatum aus der Systemzeit.** Ein leeres Releasedatum wird beim
  Einlesen mit dem heutigen Datum vorbelegt (`2026-09-28`, Herkunft „aus der
  Systemzeit"). Ein vorhandener Wert bleibt; das Format stellt
  `[build] release_date_format` ein, `""` schaltet es ab. Kommandozeile,
  Desktop und Web tragen dasselbe Datum ein.
* **FLAC-Version.** Bei MP3 kam der Encoder aus dem LAME-Header, bei FLAC
  wurde nur ein `ENCODER`-Tag gelesen — den schreibt der Referenz-Encoder
  nicht. Seine Fassung steht im Vendor-String (`reference libFLAC 1.4.3
  20230623`) und erscheint jetzt als `FLAC 1.4.3`.
* **Wo liegt die Konfiguration?** Für den Container gab es keine Antwort:
  Das Image enthielt keine, `docker-compose.yml` hängte keine ein. Jetzt
  liegt sie in `config/mp3releaser/config.toml`, und der Dienst nennt beim
  Start, welche Datei er liest (siehe
  [Einstellungen im Container](#einstellungen-im-container)).
  `releaser config` zeigte außerdem den Abschnitt `[gui]` nicht an und
  sagte ohne Datei nicht, wo er gesucht hatte.

### Aus der vierzehnten Erprobung

* **Gruppe wörtlich.** Die Schreibweise des Verzeichnisses machte aus der
  Gruppe „GRP" ein „grp". Jetzt steht sie im Verzeichnisnamen so, wie sie
  eingegeben ist; die Dateien darin bleiben bei ihrer Schreibweise (siehe
  [Naming-Schema](#naming-schema)).
* **Ein Knopf für das fertige Release** statt „Tags", „Umbenennen" und
  „Dateien erzeugen" — im Desktop, im Web und auf der Kommandozeile als
  `releaser release` (siehe [Ein Knopf](#ein-knopf-release-erstellen)).
* **NFO-Vorschau mit Block-Grafik.** Fehlten der Schrift die Blockzeichen,
  verrutschten die Zeilen; zwischen den Zeilen blieben Fugen. Die Vorschau
  zeichnet jetzt im festen Raster (siehe [NFO-Vorschau](#nfo-vorschau)).
* **0.25.0 startete auf Debian 13 nicht.** Mit der neuen NFO-Vorschau nahm
  PyInstaller Pango, HarfBuzz und Graphene vom Bausystem (Ubuntu 24.04) ins
  Bündel. Auf Debian 13 lud das GTK des Systems dann die alte Pango aus dem
  Bündel, und der Start brach mit `undefined symbol:
  pango_font_description_set_features` ab. 0.25.1 lässt den Textsatz von
  GTK samt Typelibs draußen; der Release-Workflow startet das AppImage
  jetzt zusätzlich in einem frischen Debian 13 (siehe
  [Auslieferung als Bündel](#auslieferung-als-bündel)).

### Was offen ist

* **Musepack** wird gelesen und geschrieben, ist aber ungetestet — ffmpeg
  kann kein MPC erzeugen.
* **Atmos (JOC)** ist nur gegen synthetische Syncframes geprüft; ffmpegs
  EC-3-Encoder erzeugt kein JOC.
* **Drei Annahmen zur SKL-Engine** (siehe „Getroffene Annahmen") sind gegen
  echte Referenz-NFOs noch nicht verifiziert.
* **Die Container-Messung** in der Vergleichstabelle ist geschätzt, bis
  `docker compose` einmal gelaufen ist.
