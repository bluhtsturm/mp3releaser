# mp3releaser — a Linux reimplementation

A reimplementation of the Windows tool *MP3 Releaser 3.9* (Delphi/VCL, 2003)
in Python. It is neither a port nor a decompilation: the functionality has
been reconstructed from the bundled documentation (`mp3r_tags.nfo`,
`skl_making_guide.nfo`), the configuration files and observable behaviour.

The feature set of the original is covered, plus four user interfaces in
three delivery forms: command line, bundled application (AppImage) and a web
interface in a container.

*Deutsche Fassung: [README.md](README.md)*

> **Language note.** The program itself speaks German — messages, window
> labels and report texts. Command names, options and configuration keys are
> English-like and are shown unchanged below. Where this README quotes program
> output, it is quoted verbatim (in German), with an explanation next to it.

## Download

The ready-made AppImage lives in the repository under
[`releases/`](releases/) — a single file, no installation, no Python:

```bash
chmod +x mp3releaser-0.22.1-x86_64.AppImage
./mp3releaser-0.22.1-x86_64.AppImage              # graphical interface
./mp3releaser-0.22.1-x86_64.AppImage --help       # command line
sha256sum -c SHA256SUMS                           # verify the checksum
```

Requirements: Linux x86_64 with glibc 2.38 or newer (Ubuntu 24.04,
Linux Mint 22, Debian 13, Fedora 39 and later). The graphical interface uses
the system's GTK 4; the command line works without it. Without FUSE, start it
with `--appimage-extract-and-run`.

## Quick start

```bash
# command line
python3 -m releaser wizard /path/to/release templates/standard.skl
python3 -m releaser build  /path/to/release template.skl --tag --rename --group GRP
python3 -m releaser verify /path/to/release/xyz.sfv
python3 -m releaser fields /path/to/release template.skl      # inspect fields
python3 -m releaser dupe   /path/to/release --against ~/releases

# user interfaces
python3 -m releaser gui --mounts "incoming:/data/in"          # GTK 4
RELEASER_MOUNTS=incoming:/data/in python3 -m releaser web     # web interface
docker compose up                                             # the same, in a container

# delivery and comparison
./packaging/build.sh                                          # bundle + AppImage
python3 -m releaser metrics --compare cli.json appimage.json container.json

python3 -m pytest tests -q          # 735 tests
```

The core depends on `mutagen` only. The NFO part works without it; the user
interfaces additionally need GTK 4 or FastAPI respectively.

## Architecture

```
releaser/
  model.py        Release / Disc / Track — plain data classes, no I/O
  text.py         CP437 I/O, letter case, ASCII conversion, formats
  tags.py         tag registry: name, scope, alignment, resolver
  skl.py          parser (field detection) and renderer (blocks, replication)
  checksums.py    CRC32 over the whole file and over the audio data only
  sfv.py          write, read and verify SFV
  playlist.py     one M3U per disc plus the super M3U
  naming.py       name patterns, rule chain, rename plan
  tagwriter.py    write tags, likewise as a plan
  companions.py   find and clean up .nfo/.sfv/.m3u and cover images
  cue.py          read CUE sheets
  genres.py       ID3v1 genre list and mapping
  lyrics3.py      write and remove Lyrics3v2
  dupecheck.py    compare release names with known ones
  config.py       TOML configuration
  checks.py       check templates and finished releases
  provenance.py   where a value came from
  undo.py         undo renames and tag runs
  fields.py       field catalogue: usage, width, origin
  browse.py       file browser — local, or restricted to mounted folders
  service.py      workflows without output — shared basis of all interfaces
  uistate.py      window logic without a window — state and actions
  runtime.py      detect and measure the delivery form
  audio/
    base.py       AudioInfo + dispatch by file extension
    bitreader.py  MSB-first bit reader
    mp3.py        MP3 via mutagen
    flac.py       FLAC, compression ratio from STREAMINFO
    vorbis.py     Ogg Vorbis, Opus, Musepack
    mp4.py        MP4 container: AAC, ALAC, EC-3
    eac3.py       EC-3 bitstream parser + dec3 box
    scan.py       directory → Release
  frontends/
    cli.py        command line
    wizard.py     guided mode
    gtkui.py      desktop application (GTK 4)
    web/          web interface (FastAPI) — mounted folders only
```

The separation is deliberate: `skl.py` knows neither mutagen nor the file
system, so the renderer can be tested completely without audio files. One test
blocks the mutagen import and still produces an NFO, names and an M3U.

New tags **only** need an entry in `tags.py::_DEFS` — parser and renderer stay
untouched.

## The SKL engine

A tag occupies not only its own characters but also the spaces next to it.
That span is the *field*. Values are truncated and padded to the field width so
that ASCII frames stay in their column.

| Alignment | Notation | Field | Example |
|---|---|---|---|
| left | `#Artist` | tag + following spaces | `#Artist    ` → `Nirvana    ` |
| centred | `#Release` | like left, value centred | `  Nirvana - …  ` |
| right | `Size#` | *preceding* spaces + tag | `      Size# MB` → `   26.5 MB` |

**Longest match is mandatory.** Without sorting by literal length,
`#Releasenc` would be read as `#Release` + `nc`, and `#10Hz` as text + `#Hz`.

**Line replication.** A line with track tags (`#N`, `#Trk`, `#Ptit`) is
repeated for every track. If the *following* line contains `#Trk` without
`#N`/`#Ptit`, it serves as a continuation line for

* wrapped track titles,
* disc header lines in multi-disc releases,
* the blank line below them.

The same pattern applies to `#Rnotes` and `#Gnews`. Text that wraps is broken
at the width of the continuation line, not the main line — otherwise a
narrower continuation field would silently cut off the rest.

**Introspection.** `Template.field_widths()` and `Template.tag_names()` return
exactly what the original needed for its GUI: field widths to size the input
fields, and the set of unused tags to grey them out.

### Verification against the original template

`generic.skl` from the original distribution parses cleanly: 43 tags
detected, all 63 frame lines keep their width of 83 characters, multi-disc
headers, title wrapping and right-aligned total fields behave as documented.

The original template itself does not belong in the repository — its ASCII
art is protected by copyright (MorGoTH, 2000). `templates/example.skl` is a
separate, neutral test template.

## Assumptions made

The original's documentation is vague in three places. Current behaviour:

1. **`#hhh…` vs. `#hhL…`** — `hhh` ("filled with spaces") is interpreted as
   right-aligned, `hhL` as left-aligned. Not yet verified against real
   reference NFOs.
2. **"cuts the useless spaces at the left side"** — implemented as trimming
   line ends (`trim_trailing=True`). An optional `dedent=True` additionally
   removes common indentation; it is off by default because it would destroy
   ASCII art.
3. **Notes block without a continuation line** — the main line is then
   repeated for every note line. This is documented for the track list, but
   not for notes.

These three points can be settled by diffing against reference NFOs produced
under Wine — a clean verification step for future work.

## Audio layer

Common interface: every reader returns an `AudioInfo`, and `scan.py` builds
the `Release` from them. A file that cannot be read — truncated, damaged, no
permission — is skipped and reported as a warning instead of aborting the
whole scan (`--strict` aborts on purpose).

| Format | Source | Particularity |
|---|---|---|
| MP3 | mutagen (`ID3`, `MPEGInfo`) | VBR/ABR status, channel mode in scene spelling, encoder from LAME/Xing |
| FLAC | mutagen (`FLAC`, Vorbis) | compression ratio for `#FlacC` from STREAMINFO vs. file size |
| Ogg Vorbis | mutagen | tag mapping shared with FLAC |
| Opus | mutagen | bitrate estimated from file size (Opus reports none) |
| Musepack | mutagen | APEv2 tags — **untested**, ffmpeg cannot create MPC |
| AAC (`.m4a`) | mutagen | profile from the codec identifier, VBR from `stsz` |
| ALAC (`.m4a`) | mutagen | lossless, therefore never VBR |
| EAC3 (`.ec3`) | own bitstream parser | no tag container — see below |
| EAC3 (MP4) | mutagen + `dec3` box | tags from iTunes atoms, technical data from `EC3SpecificBox` |

### AAC in the MP4 container

mutagen provides `codec` and `codec_description`. The profile is derived from
them: `mp4a.40.2` is AAC-LC, `.5` HE-AAC, `.29` HE-AACv2. "AAC" is enough for
`#Format`; the profile goes into the encoder field.

**VBR** is the interesting part: MP4 has no VBR flag. The `stsz` box, however,
contains the size of every single sample. If the `sample_size` field is
non-zero, all samples have the same size; otherwise a table follows whose
spread can be evaluated. If the coefficient of variation exceeds 10 %, the
stream is considered variable.

This is explicitly a **heuristic** — because of the bit reservoir, AAC
fluctuates slightly even at a constant target bitrate, hence no stricter
threshold. If there are too few samples to tell, the result is a warning
rather than a claim. The `stsz` box is located via the container path
`moov/trak/mdia/minf/stbl`, not by searching for bytes.

### EC-3: why a parser of its own

mutagen does not cover Dolby Digital Plus. Raw streams have neither tags nor a
header containing the duration — everything has to come from the sync frames:
`strmtyp`, `frmsiz`, `fscod`, `numblkscod`, `acmod`, `lfeon`, `bsid`.

To get to `addbsi` (where the JOC flag lives), the entire BSI header has to be
traversed, including the optional mixing and info metadata. The conditions
there follow FFmpeg's `eac3_parser`, which is more precise than the prose of
the specification in two places (`dmixmod` and `paninfo` depend on `acmod`
thresholds that read differently in the running text).

The expensive traversal only covers the first frames; every further frame is
counted from its first bytes alone. Duration and bitrate therefore stay
correct for long files as well.

If this traversal fails, the core fields remain valid and `atmos` becomes
`None` — **unknown, not no**. The distinction matters: a false "no Atmos" is
worse than an honest "don't know".

**Consequence for the data model:** `AudioInfo.tagless` marks formats that
cannot carry tags at all. Titles then come from the file name, and the scanner
emits a warning — instead of silently guessing.

### Verification

The EC-3 parser was tested against real bitstreams created with ffmpeg (mono,
stereo, 5.1, 44.1 kHz, EC-3 in MP4, ten-minute streams). Sample rate, channel
count, bitrate and duration match `ffprobe` exactly, and the deep BSI
traversal runs through to `addbsi` for all of them.

ffmpeg's EC-3 encoder cannot produce the JOC path. It is therefore tested with
synthetically built sync frames and `dec3` boxes (`BitWriter` in
`tests/test_audio.py`). It has **not yet** been verified against a real Atmos
sample — that remains open.

## SFV and the two CRC values

An SFV contains the CRC32 of the **complete file**. That has an unpleasant
property: retagging changes the file and thus the checksum, although the
audio data is untouched. The SFV then reports an error that isn't one.

`checksums.py` therefore also computes an **audio CRC** over the payload only
— without ID3v2 at the start, without ID3v1/APEv2/Lyrics3v2 at the end,
without FLAC metadata blocks and without a WAV envelope, if there is one. This
corresponds to the original's option "check for stuff in front of the mp3
(WAV envelope, ID3v2 ...)", which it called "mp3-crc".

With `--audio-crc` these values end up in the SFV as comment lines:

```
; audio-crc 56356AA4 01-artist-track_1.mp3
01-artist-track_1.mp3 44A37193
```

Other checkers skip comment lines; `verify` uses them. Its output (German)
reads "1 ok, 1 only retagged, 1 broken" and names the files:

```
1 ok, 1 nur umgetaggt, 1 fehlerhaft
  ~ 01-artist-track_1.mp3 (Audiodaten unverändert)
  x 02-artist-track_2.mp3: erwartet 9E1F98FA, gefunden F7FADEB3
```

Without a recorded audio CRC this distinction is impossible — every deviation
then counts as an error. That is deliberate: guessing would be worse.

**One SFV per directory.** For multi-disc releases this automatically yields
one per disc, with bare file names. Checkers expect the SFV next to the files
it describes. `--sfv-include log pdf` adds further extensions.

## M3U

Extended format with `#EXTINF:<seconds>,<artist> - <title>`. One playlist per
disc with bare file names, plus — for multi-disc releases — the **super M3U**
in the root directory with paths relative to it (`CD1/01-....mp3`). For a
single disc the super M3U is omitted; it would just be a duplicate.

Forward slashes are the default — on Linux no player finds a file behind
`CD1\01-….mp3`. The original wrote backslashes because it ran on Windows;
`--m3u-windows-paths` (in the configuration: `m3u_windows_paths = true`)
restores that.

## Testing approach

Checksums are tested against a **separate, bit-by-bit CRC32 implementation**
in the test, not against `zlib` — otherwise the library would be competing
against itself. Tag detection is tested with synthetically built files for
every combination of ID3v2/ID3v1/APEv2/Lyrics3v2.

One test makes the core behaviour explicit: retag a file, then check that the
file CRC has changed and the audio CRC has not.

## Naming scheme

The original handled renaming through some forty check boxes. Behind them,
however, there are only two concepts.

**First, a pattern** — in the same tag language as the SKL templates, only
without the column logic:

```
--dir-pattern  "#Artist-#Album-#Source-#Year-#Grp"
--file-pattern "#N-#Artist-#Trk"
```

One vocabulary for NFO *and* file names instead of two parallel systems. Five
tags are added that only make sense for naming (`#Cd`, `#Cd2`, `#Grp`,
`#Ext`, `#Fmt`); they live in a separate table so that `inspect` keeps
showing real SKL tags only.

**Second, a rule chain** — every rule is a pure function `str -> str` with a
name. The configuration is a readable list instead of Boolean flags:

```
--pipeline inch transliterate alnum forbidden spaces collapse trim
```

| Rule | Effect |
|---|---|
| `inch` | `12" Mix` → `12INCH Mix` |
| `transliterate` | `Die Ärzte` → `Die Aerzte` |
| `strip_diacritics` | remove accents, without `ä`→`ae` |
| `forbidden` | drop characters not allowed in the file system |
| `spaces` | spaces → configurable character |
| `collapse` | `a__-_b` → `a_b` |
| `alnum` | letters, digits and separators only — `Title, with comma` → `title_with_comma` |
| `trim` | drop leading/trailing separators |

The rest are scopes: directory, file name, tag and NFO each have their own
letter case but share the chain. This replaces the original's four separate
"charcase" blocks.

### Plan instead of immediate execution

`plan_rename()` touches nothing; it returns a list of operations plus warnings
and collisions. `rename` shows this preview by default; only `--apply`
executes it. That makes the riskiest operation of the program checkable before
it happens.

Collisions are detected in two forms: two tracks that map to the same name,
and targets that already exist on disk. The latter do not count as a
collision if they are themselves a source in the plan — they are about to
move out of the way. Nor does a pure change of letter case on a file system
that does not distinguish case (FAT/exFAT, SMB): there, `track.mp3` "exists"
when `Track.mp3` is being renamed, but it is the same file.

### Three pitfalls uncovered by tests

**Cycles.** If two files swap names, naive renaming would overwrite one of
them. Execution therefore runs in two stages via temporary names. When the
paths in the model are updated, only one mapping may apply *within* a stage
— otherwise the second match turns the file back to its original name.

**Rollback.** If a rename fails half-way, all renames already performed are
reverted. Without that, a half-renamed release would be left behind, including
temporary names that block the next attempt. The temporary names carry a
random token so that leftovers do not interfere.

**The "intro" rule.** The original prefixed files named `intro` with the
artist to avoid duplicate names. If the pattern already contains `#Artist`,
that would be a duplication (`01-artist-artist-intro`) — the rule then does
not apply.

## Writing tags

Same design as renaming: `plan_tags()` reads the existing tags, computes the
target values and returns a list of field changes without touching a file.
Only `apply_tags()` writes.

```
  CD1/01-x.m4a
      title        roher titel 11  ->  Roher Titel 11
      album        -               ->  Das Album (WEB)
      tracknumber  -               ->  1/2
```

The target values come from the `Release` model, not from the files. Writing
is thus the reverse of scanning: whatever the scanner merged and corrected
goes back into the files.

A normalised set of field names (`title`, `artist`, `album`, `tracknumber`
…) is mapped per format — ID3v2 frames, Vorbis comments, iTunes atoms. Vorbis
separates number and total into fields of their own, MP4 uses tuples; the
respective writer takes care of that.

"Remove existing tags" (`--strip-tags`) removes them completely — ID3v2,
ID3v1, APEv2 and Lyrics3v2 — also on files that had no tag at all.

### Repeatability

Two bugs showed up here, both only on the second run:

The album addition (`--album-addition CDDA`) was caught by the letter-case
rule and became `(Cdda)` — and because the second run then no longer
recognised the addition, it appended it again. Now an existing addition is
split off **before** the letter-case rule and re-appended afterwards in its
own spelling. A second run reports zero changes.

One test pins down the core promise: writing tags does not change the audio
CRC. The `verify` logic from the SFV part therefore still works after a tag
run.

### Order in `build`

`--tag` runs before `--rename`, and both before creating NFO, SFV and M3U.
This is not cosmetics: if the SFV were created before the tag run, every
checksum would be wrong immediately. File sizes are read again after tagging,
so `#Size` in the NFO matches the files.

## As a library

`releaser/__init__.py` exports a flat API. The audio layer is only loaded on
demand via `__getattr__`, so the NFO part runs without mutagen:

```python
from releaser import scan_directory, Template, write_release_sfvs

result = scan_directory("/path/to/release")
nfo = Template.from_file("template.skl").render(result.release)
```

One test secures this layer separation by blocking the mutagen import and
still producing an NFO, names and an M3U.

## Comparison with the original

| Feature of the original | Status |
|---|---|
| read tags: MP3, FLAC, OGG, MPC | ✅ (MPC untested) |
| additionally: AAC, ALAC, EC-3 | ✅ (not in the original) |
| write tags: ID3v1, ID3v2, Vorbis | ✅ |
| write tags: APEv2, Lyrics3v2 | ✅ `--apev2`, `--lyrics3` |
| NFO from an `.skl` template | ✅ complete, incl. multi-disc and wrapping |
| SFV with comments, extra extensions | ✅ plus audio CRC and `verify` |
| M3U per disc and super M3U | ✅ |
| renaming with character set rules | ✅ as a plan with preview |
| length warnings | ✅ directory, file name, companion files |
| remove old NFO/SFV/M3U | ✅ `--clean` |
| process `.cue` files | ✅ incl. duration calculation |
| cover/JPG, "00" prefix rule | ✅ `--companion-prefix` |
| configuration file (`MP3releaser.ini`) | ✅ as TOML |
| ID3v1 genre list and mapping | ✅ 192 genres, with aliases |
| dupe check against existing releases | ✅ `dupe` |
| GUI | ✅ GTK 4 — plus guided mode and web interface |

Beyond the original: three delivery forms with a shared core, provenance
tracking of values, plan-before-execution for every modifying operation, and
`metrics` to compare the forms.

## What the second walk-through revealed

Five bugs, all arising from the interplay of parts — each module on its own
was fine.

1. **Genre versus letter case.** `normalise_genre` brings the genre to its
   canonical spelling so that ID3v1 finds its number. Afterwards the
   letter-case rule kicked in and turned `Drum & Bass` into `DRUM & BASS` —
   and mutagen compares exactly, so ID3v1 held 255 ("unknown") again. The
   genre is now exempt from the rule once it has been recognised; unknown
   genres still follow it.
2. **Reading without writing.** Ogg Vorbis, Opus and Musepack were read but
   not written — the tag run reported "cannot carry tags", although Vorbis
   comments exist precisely for that. A test now compares the list of readers
   with the list of writers; anything missing must be explicitly declared
   tagless.
3. **Spaces in the SFV name.** The disc identifier came from the directory
   name, not from the number. Next to a folder `Disc 2` the SFV was called
   `…-disc 2.sfv` — and the M3U next to it `…-cd2.m3u`. Both now use the
   number.
4. **Companion files measured differently.** The `.nfo` followed the
   configured name pattern, `.sfv` and `.m3u` did not. All three now get the
   same stem.
5. **A measurement that writes.** `metrics` created a probe file in the
   working directory to test whether it is writable. A measurement must not
   create anything, not even something short-lived — it now asks instead of
   trying.

Plus one improvement: a typo in the configuration had no effect and went
unnoticed. Unknown keys are now reported, with a suggestion ("'grupp' is not
evaluated — did you mean 'group'?"):

```
Konfiguration: [naming] 'grupp' wird nicht ausgewertet - meintest du 'group'?
```

## What the first walk-through revealed

Four bugs nobody would have noticed before:

1. **Audio CRC in the MP4 container.** For `.m4a` the "audio CRC" simply was
   the file CRC — telling damaged from merely retagged did not work for AAC
   at all. The `mdat` box is used now.
2. **Compilations.** With different artists, the scanner wrote the artist
   into the *title field*. When writing tags, that would have ended up in the
   files as the title. The model now keeps both separate; they are only
   combined for display, in exactly one place (`compose_track_title`).
3. **Stale companion files.** A second `build` run after a rename left the old
   SFV behind, which then reported nothing but missing files.
4. **Positional arguments.** A new field in the middle of `Track` shifted all
   positional calls — three tests broke immediately. The field is now at the
   end, with a comment.

Also: CLI errors no longer appear as a traceback but as a message with exit
code 2.

## Configuration

The ~25 command-line switches are the point where the original tipped over
into its flood of check boxes. The same information lives here in a TOML file:

```toml
[naming]
group = "GRP"
case = "lower"
companion_prefix = "00-"        # .nfo, images, .sfv and .m3u
prefix_all = true               # false: .nfo and images only

[tags]
case = "capitalize"
album_addition = "CDDA"
write_apev2 = true

[build]
audio_crc = true
```

Precedence: an explicitly set switch beats the file, the file beats the
default. This is implemented by making the CLI defaults `None` — `None` means
"not given", not "off".

The file is looked up in `./mp3releaser.toml`, `./.mp3releaser.toml`,
`$XDG_CONFIG_HOME/mp3releaser/config.toml` and
`~/.config/mp3releaser/config.toml`. `config --example` prints a commented
template.

This is also the data basis of all interfaces: command line, desktop
application and web interface read the same file — all three sections — and
call the same core. The service layer builds the profiles in one place
(`naming_from_config`, `tags_from_config`, `build_options_from_config`).

## CUE sheets

A CUE describes the track layout of an audio file that exists as one piece.
Durations follow from the distance to the next `INDEX 01`; the last track runs
to the end of the file, whose length the CUE does not know — it comes from the
audio layer. CUE files are read as UTF-8 (with or without BOM), falling back
to CP1252 and CP437.

**The consequence is the real work:** all tracks then point to the same file.
Without countermeasures, renaming would touch it several times, the M3U would
list it several times, and the total size would multiply with every track.
All three places are handled accordingly; the file size is distributed
proportionally to the duration.

## Dupe check

Compares a release name with known ones — a text file or a directory of
releases. The comparison uses a normalised form without the group tag, source
and format information, so that

```
Der_Artist-Das_Album-CDDA-2026-GRP
der.artist-das.album-WEB-2026-ANDERE
```

are recognised as the same release. A group tag is only split off from three
parts onwards (`Artist-Album-GRP`); with `Artist-Album`, the last part is the
album. In addition, a fuzzy comparison finds typos. It returns candidates, not
verdicts.

Building the word list called for restraint: "Album", "Single" and "Sampler"
often appear in the actual title. Removing them made two different releases
collapse into one in a test.

## ID3v1 genres

ID3v1 knows genres only as numbers. Writing "electronic" instead of
"Electronic" gets you 255 ("unknown") there — the information is silently
lost on writing. The name is therefore brought to its canonical spelling, with
aliases for common variants (`DnB`, `Hip Hop`, `rock n roll`,
`Alternative Rock` → `Alt. Rock`). Unknown genres remain as free text and
produce a warning instead of being discarded.

The list is checked against mutagen's in a test so the two do not drift
apart, and another test makes sure every alias resolves.

## Lyrics3v2

A tag format from 1998 that mutagen does not support. It sits at the end of
the file, in front of an ID3v1 block if there is one:

```
[audio data][Lyrics3v2][APEv2][ID3v1]
```

Establishing this order was the tricky part: mutagen always appends ID3v1 at
the very end, so the legacy formats have to be written first and ID3v1 appended
last. In the first attempt, ID3v1 sat between Lyrics3 and APEv2 — and my own
reader could no longer find the block.

## Three delivery forms

The same program is meant to appear in three forms: as source code for the
command line, as a bundled application (AppImage) and as a container with a
web interface. They differ not in **what** they can do but in **what they
require**.

For this to hold, the entire workflow logic lives in `service.py` and writes
nothing to the console. The interfaces are thin layers on top. Anyone building
another one calls the service layer and writes no workflow logic of their own
— otherwise the forms drift apart, and the presentation would no longer
compare three packagings of the same program but three different programs.

One test pins this down: the guided mode produces exactly the same files as
the direct call.

### `metrics` — measuring the differences instead of claiming them

The output below is German; the rows are: form, start-up time, memory, program
code, third-party libraries, total, privileges needed, where the data lives.

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

The form is detected at run time: `APPIMAGE`/`APPDIR` in the environment,
`/.dockerenv` or a container hint in `/proc/self/cgroup`, otherwise source.
`--json` prints the same in machine-readable form so that the three outputs
can be laid side by side.

Only what can honestly be determined is measured. Where that is not possible,
it says `unbekannt` ("unknown") instead of a plausible number.

The most uncomfortable row is "privileges needed": of all things, the most
modern form demands the most. Whoever may start a container effectively has
root on the host.

## Fields: the original's design decision, reassessed

The original built its form from the loaded `.skl`: fields without a matching
tag were greyed out. That was right in 2003, because the template was the only
consumer of the input.

Today the same model feeds **three** consumers: the NFO via the template, the
file names via the name patterns, the tags via the tag profile. A field
without a tag in the template may still be needed — `#Catnr` ends up in the
album tag with `catalog_in_album`, `#Source` is part of the default directory
pattern. Greying out would mean that you cannot enter values the program uses
right afterwards.

`fields.py` therefore keeps the insight and drops the restriction: all fields
stay, but the template determines how they look. The group headings in the
output are German ("in the template", "in the directory name", "not used"):

```
$ releaser fields /path/to/release template.skl

in der Vorlage
   Artist              59  'Ein ziemlich langer Artistname'  (aus den Tags)
   Quelle              59  ''
   Format              59  'MP3'  (abgeleitet)

im Verzeichnisnamen
   Artist              59  ...
   Quelle              59  ''

nicht verwendet
   Subgenre             -  ''
```

Three things appear there that no other software shows:

**The field width.** A value wider than its space in the template is cut off
in the NFO — silently. `overflow_warnings()` reports it beforehand, together
with the part that would remain.

**The usage.** A field can appear in several groups. Whatever is not used
anywhere ends up in a group of its own: visible and collapsed, not disabled —
the template may change after all.

**The origin.** `provenance.py` remembers where each value came from: from the
tags, from a file name, from a CUE, from the directory name, or derived. A
title from a well-kept tag deserves different confidence than one guessed from
`03-from-the-file-name.mp3`. `origins.uncertain()` lists exactly the fields
worth a look.

The scanner knew all this already — it just threw it away until now.

## Delivery as a bundle

```
./packaging/build.sh binary     # one file, 21 MB, runs without Python
./packaging/build.sh appdir     # AppDir, directly startable via ./AppRun
./packaging/build.sh            # additionally the AppImage (needs appimagetool)
PYTHON=python3.12 ./packaging/build.sh   # with a specific interpreter
```

PyInstaller bundles the Python interpreter and mutagen into one file. This is
checked with `env -i` and `PATH=/nonexistent`: without Python, without
libraries, without PATH, the complete workflow runs through — tag, rename,
NFO, SFV, M3U — and `verify` afterwards reports "2 ok".

**GTK is not bundled.** The library is too closely interwoven with the system;
two GTK versions in the same process do not get along. The graphical interface
therefore uses the host's GTK, and `metrics` says so — instead of making a
claim the bundle does not keep.

Only the Python side of PyGObject is bundled, including the **GTK overrides**
(`gi.overrides.Gtk`, `gi.overrides.Gdk`). PyInstaller only picked those up
when its GTK 3 hook kicked in; on a machine with GTK 4 only they were missing,
and the interface crashed on start-up. They are now listed explicitly in the
spec. Conversely, graphics libraries that GTK brings along on the host anyway
(X11, xcb, cairo, fontconfig, freetype …) are left out — the same names are on
the AppImage community's exclude list. A test starts the interface from the
AppDir under `xvfb-run`.

The interface only makes it into the bundle if the building interpreter can
import PyGObject and GTK 4; otherwise `build.sh` warns. The finished AppImage
needs glibc 2.38 or newer — that is determined by the machine it is built on.
`build.sh` also runs `appimagetool` without FUSE, so it works in containers
and CI.

### Publishing a new version

GitHub Actions builds the AppImage (`.github/workflows/release.yml`) as soon
as a version tag is pushed:

```bash
# bump the version in pyproject.toml and releaser/__init__.py, commit, then:
git tag v0.22.2
git push origin v0.22.2
```

The workflow builds on Ubuntu 24.04 with the same setup as above, runs the
complete test suite first (under `xvfb` with GTK 4 and WebKitGTK), then the
bundle tests including starting the interface, starts the AppImage without
Python and without `PATH` — and only then creates the release with the
AppImage and `SHA256SUMS`. If the tag does not match the version in the code,
it aborts. `appimagetool` is pinned to one version with a checksum. Started by
hand (*Actions → Release → Run workflow*) it only produces an artifact for
trying out, no release.

`AppRun` needs no external programs: no `readlink`, no `dirname`. A bundle
that requires a working `PATH` variable would miss its purpose. A test starts
it with `PATH=/nonexistent`.

## The three forms side by side

The rows are: start-up time, memory, delivery size, privileges needed, where
the data lives.

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

Same software, same capabilities, different requirements. The row
"privileges needed" is the most uncomfortable one: of all things, the most
modern form demands the most.

## Web interface

```bash
RELEASER_MOUNTS="incoming:/data/incoming,archive:/data/archive:ro" releaser web
docker compose up
```

Once again a thin layer over `uistate` — only this time there is a network
between state and display. That has three consequences that are visible in the
code.

**The state lives on the server.** Every session has its own `AppState` there,
addressed by a cookie, expiring after an hour. Whoever runs the service has
access to it. In the other two forms the same state lives in the memory of
your own computer. One test pins down that two clients do not see each other's
input. The session store is thread-safe, because FastAPI runs the endpoints in
a thread pool.

**The file browser is restricted.** There is only `MountedSource` here. What
is visible is what someone put into the Compose file beforehand — the user of
the interface does not decide that. The page says so too, in a banner above
the browser ("This version only sees the mounted folders: … What is entered
here lives on the server, not on this computer."):

> Diese Fassung sieht nur die eingehängten Ordner: eingang, archiv (nur
> lesen). Was hier eingegeben wird, liegt auf dem Server, nicht auf diesem
> Rechner.

**No uploading.** Browsers cannot rename the original files; the result would
be a copy in the container and a ZIP back. Full functionality only works via
mounted folders — which is why there is deliberately no drag and drop.

### Tested in a real browser engine

The other web tests go through the API — the JavaScript never runs there.
`tools/webcheck.py` therefore loads the page with **WebKitGTK** from a real
server and operates it: click, double-click, type, open dialogs. Fourteen
checks, under `xvfb-run`, included as a regular test.

```
  [ok ] Banner nennt Beschränkung und Datenlage
  [ok ] ohne Auswahl sind alle Aktionen gesperrt
  [ok ] Doppelklick öffnet den Ordner
  [ok ] Gruppe „nicht verwendet“ ist eingeklappt
  [ok ] Überlänge wird rot markiert ({'counter': '92/59', 'red': True})
  [ok ] Umbenennungsplan erscheint im Dialog
  14 von 14 Pruefungen bestanden
```

The test rig itself had two bugs that only the run revealed: exceptions in
GObject callbacks were swallowed, so the chain silently stopped instead of
reporting — and all scripts shared the global namespace, which is why a
`const` from step one broke the second step. A dedicated test now checks that
the rig does report errors.

### What goes out

Never a path of the host system. The browser sees
`incoming/Artist-Album-2026-GRP`; the way back in runs exclusively through
`MountedSource.resolve()`. Template names must not contain path separators or
null bytes, otherwise they would be a second way out.

The container runs as its own user, without capabilities, with
`no-new-privileges`, and the port is bound to `127.0.0.1`. One test checks
that `RELEASER_MOUNTS` and the Compose file's `volumes` match — a mount point
without a volume would be a folder that does not exist.

## Desktop application (GTK 4)

The labels are German: *Einlesen* (read in), *Vorlage* (template), *Tags*,
*Umbenennen* (rename), *Erzeugen* (create files).

```
+----------------------------------------------------------+
| Header bar: Einlesen  Vorlage  |  Tags  Umbenennen  Erzeugen|
+--------------------+-------------------------------------+
| Browser            | Fields, grouped by usage              |
| (tree on the left) | with width, character counter, origin |
+--------------------+-------------------------------------+
| Status line        | Messages (collapsible)                |
+----------------------------------------------------------+
```

`gtkui.py` is pure presentation — every decision lives in `uistate.py`. The
input fields are as wide as their space in the template; next to them a
counter `29/9` turns red before anything gets cut off.

The module can be **imported without GTK**. `is_available()` says whether the
library is present; `requirements_hint()` names the package and a way that
works without a graphics stack. Otherwise the package could not even be
loaded on a server.

### Tested against real GTK

GTK calls would otherwise only fail on first start. The tests therefore really
build the window — under `xvfb-run`, in a subprocess, because GTK crashes
without a display instead of raising an exception. Tested are the window
construction, the rows of the browser, writing an input through to the model,
rejecting invalid input and building the plan windows.

This revealed an operating bug no logic test would have found: selecting a row
triggered a redraw, and the redraw threw away the selection just made —
"Einlesen" had no effect. The list is now only rebuilt when its contents have
changed, and the selection is a separate piece of state next to the opened
directory.

## Standard template

`templates/standard.skl` contains every field that can be entered in an
interface, plus the computed values — bitrate, sample rate, durations, size,
track list with continuation line, notes and group news. 78 columns wide,
frame from code page 437, original design.

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

It is **loaded automatically** in all three forms: on the desktop and on the
command line from `templates/`, in the AppImage from `usr/share/mp3releaser/`,
in the container from the mounted template folder. An explicitly chosen or
saved template takes precedence.

The only tags left out are those that would repeat an existing value with a
different alignment (`Tpti#` next to `#Tpti`, `#Releasenc` next to `#Release`
…), the position markers `#Notesmark` and `#Notesmarkend`, and `#Bm`, which
the original never used. One test makes sure every other tag is in there — a
forgotten one would stand out.

The file is generated by `tools/make_standard_skl.py`: an `.skl` is exact to
the column, and one space too many shifts the right-hand frame. The generator
builds every line to the same width and checks that itself.

## Checking

One command, two subjects — the path decides what gets checked.

**A template**, before anyone uses it (German output: "4 notes", "#Album is
missing — the album appears nowhere", "#Artist only has 8 characters of room,
at least 24 are recommended"):

```
$ releaser check eng.skl
eng.skl: 4 Hinweise
  ! #Album fehlt - das Album taucht nirgends auf [#Album]
  ! #Trk fehlt - die Trackliste taucht nirgends auf [#Trk]
  ! weder #Release noch #Artist und #Album - die Kopfzeile bleibt leer
  ! #Artist hat nur 8 Zeichen Platz, empfohlen sind mindestens 24 [#Artist]
```

Checked are fields that are too narrow, missing tags, typos such as
`#Quatsch`, naming-only tags such as `#Grp` (they would end up verbatim in the
NFO), a missing continuation line in the track list, and the overall width.
All of that is in the `.skl` itself and would otherwise only show up with a
release whose values happen to be long enough. In the interface there is a
"Vorlage prüfen" (check template) button for it.

**A finished release**, after everything has been created ("checksum differs:
expected …, found …", "no image in the directory"):

```
$ releaser check /path/to/release
Der_Artist-Das_Album-FLAC-2026-GRP: 1 Fehler, 1 Anmerkungen
  x Prüfsumme weicht ab: erwartet 2CFAFC5D, gefunden B7C5EC05 [01-….flac]
  - kein Bild im Verzeichnis
```

NFO, SFV and playlist present, checksums match, all tracks tagged, no
duplicate track numbers, names not too long — and with `--against`
additionally the dupe check. The exit code is 1 if something is really broken;
a missing image is merely a note.

## Undo

Renaming is the operation that cannot be recomputed from the files —
afterwards nobody knows what things used to be called. Every executed plan is
therefore logged, in `~/.local/state/mp3releaser/undo.json`.

```
$ releaser undo --list
 1. 2026-09-19 14:27  Der_Artist-Das_Album-FLAC-2026-GRP  (3 Umbenennungen)
$ releaser undo --apply
3 Umbenennung(en) zurueckgenommen.
```

Not in the release directory, because that is itself renamed and possibly
cleaned up on the next `--clean`.

**Tags can be undone as well.** Before writing, the old values of the changed
fields are recorded — only those fields; writing back unchanged ones would
touch files nobody modified. Both kinds share the same log ("renames",
"tagged files"):

```
$ releaser undo --list
 1. 2026-09-20 14:23  Der_Artist-Das_Album-FLAC-2026-GRP  (3 Umbenennungen)
 2. 2026-09-20 14:22  rel  (2 getaggte Dateien)
```

The log is written in `apply_tags`, not in the service layer above it. There
is a reason: the `tag` command bypassed the service layer and therefore
initially remained unlogged — the same mistake that had shown up with `rename`
before. At the point every write has to pass through, nobody can bypass it any
more. A single damaged entry in the log is skipped instead of making the whole
log unreadable.

The undo runs in reverse order: first the root directory, then the disc
folders, finally the files. That is also the reason for a pitfall I tripped
over first: the logged path of a file points to the *old* folder name. The
pre-check therefore has to work out where the file is today — checked naively,
every file would be "no longer present".

## NFO preview

A third tab shows the finished `.nfo` and changes with every input — you type
into a field and watch the ASCII frame fill up (German status: "41 lines,
widest 78 characters · template: example.skl"):

```
+------------------------------------------------------------------+
|                    Der Artist - Das Album                        |
|   Artist      : Der Artist                                       |
|   Album       : Das Album                                        |
|   01.Titel 1                                          [03:35]    |
+------------------------------------------------------------------+
41 Zeilen, breiteste 78 Zeichen · Vorlage: example.skl
```

If a note such as "2 Feld(er) werden abgeschnitten" (2 fields will be cut off)
appears below the preview, a value does not fit into its space — you now see
that before the file is created, not afterwards inside it.

The same applies to the track list, but with a condition: if the template has
a continuation line, a long title wraps and is not lost. If it lacks one, the
title is cut off — and *that* is reported.

No line wrapping: the template is exact to the column; wrapping would tear the
frame apart. The view scrolls horizontally instead.

Both interfaces have it, from the same source. On the web it is an endpoint of
its own instead of a field in the state — the file is a few kilobytes and is
only loaded when the tab is open.

## Window logic without a window

`uistate.py` contains everything a window does, just without a window: which
folder is open, which release was loaded, which fields were changed, **which
buttons can be used** and what happens on a click.

The GTK and browser layers on top remain pure presentation. There are two
reasons for this. First, desktop and web then do not merely behave similarly
but identically — one test loads the same release via `LocalSource` and via
`MountedSource` and compares the result field by field. Second, the behaviour
can be tested without a graphical environment; whatever goes wrong after that
is layout.

### `enabled()` instead of scattered event handlers

Which button is active when is defined in one place:

```python
Action.APPLY_RENAME: bool(plan and plan.changes and plan.is_safe)
```

This yields rules the interface does not need to know itself:

* "Umbenennen" (rename) can only be used after a preview — and only if the
  plan has no collisions.
* If someone changes a field, both plans expire. They referred to the old
  state, and a button that executes an outdated plan is worse than a grey
  button.
* "Dateien erzeugen" (create files) needs a template — unless the `.nfo` is
  deselected.

### Input is not lost, but not waved through either

`set_field()` checks the type before writing to the model: letters in the year
field are reported, not accepted. Every manual change sets the field's origin
to "by hand" — so the "uncertain" warning disappears exactly when someone has
had a look.

Errors from deep down become messages instead of crashes: a path leading out
of the mount point ends up as a red line in the message list and the browser
stays empty. The same applies to failing write actions — missing write
permission, for example, is shown as a message on the web instead of a bare
server error 500. And if something changed between preview and execution so
that the rename plan is no longer safe, nothing is renamed and the interface
says so.

## File browser

Both interfaces show a tree on the left. What they are allowed to show differs
— and that is the point:

| | `LocalSource` | `MountedSource` |
|---|---|---|
| Reach | the entire file system | only what was mounted |
| Paths going out | real paths | virtual, `mountpoint/subfolder` |
| Who decides | the user | whoever runs the container |

The output is German ("source: local file system — reach: the user's entire
file system"; "mounted directories — only what was mounted"):

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

The same directory, two forms — in the second case `geheim` ("secret") does
not exist for the program. The web interface therefore gets **no** drag and
drop variant: browsers cannot rename the original files; the result would be a
copy in the container and a ZIP back. Full functionality only exists via
mounted folders, and someone enters those into the Compose file beforehand.

Configuration works as usual with Docker:

```
RELEASER_MOUNTS=incoming:/data/incoming,archive:/data/archive:ro
```

### The restriction has to hold

`MountedSource` never hands out host paths and checks every way back in. Not
only the normal case is tested, but above all what has to fail: `..` in every
spelling, absolute paths, unknown mount points, null bytes — and **symlinks**
that lead out of the mount point. The last case is the least conspicuous: the
path looks harmless until it is resolved, which is why the check happens
afterwards, not before.

## Guided mode

`wizard` guides you through the four steps and shows what would happen before
every modifying action. It has no workflow logic of its own, only questions.

Without a terminal it aborts instead of waving the defaults through — a
question nobody sees must not be silently answered "yes" when files are
renamed behind it. For demonstrations and tests there is `--batch` as an
explicit opt-in.

## Status

The feature set of the original is covered, plus four interfaces (command
line, guided mode, GTK 4, web) in three delivery forms. 735 tests, each layer
checked at its own level:

| Level | How it is tested |
|---|---|
| core, service layer | directly, without an interface |
| window logic | without a window, with a scripted input/output object |
| GTK 4 | window really built, under `xvfb-run` |
| web API | over HTTP with `TestClient` |
| web page | operated in WebKitGTK — clicks, input, dialogs |
| bundle | started with `env -i` and `PATH=/nonexistent`; GUI started from the AppDir |
| EC-3 parser | against `ffprobe` as an independent oracle |
| checksums | against a separate bit-by-bit CRC32 implementation |
| this README | against the command list, the module tree and the test count |

The last row has a reason: the head of the (German) README long reflected the
state of the first day, because text replacements silently failed to apply — a
replacement without a match reports nothing. `tests/test_readme.py` now checks
for both language versions that every command mentioned exists, every existing
command is mentioned, the module tree is correct and the stated test count is
current.

The fixes from the bug review for 0.22.1 are listed with cause and effect in
[`CHANGE.md`](CHANGE.md) (German).

### From the first trial

Three pieces of feedback from the first real start of the AppImage:

* **The "Namen" (names) tab.** Directory and file patterns can now be changed
  in the interface, with a preview that updates while typing. The directory
  name can also be set **by hand**: a pattern without tags is taken
  literally, and the character rules still apply.
* **Notes and group news** have become multi-line. Before, they sat in a
  single-line input with substitute characters — unusable.
* **Fields were hidden.** Without a loaded template almost everything ends up
  in the "nicht verwendet" (not used) group, and that was collapsed. It now
  stays open as long as no template is loaded, and a hint explains what is
  missing without a template.

**The crash when changing a tag.** On every change of a value, the entire form
was rebuilt — while the changed input field still had the focus. GTK
destroyed the widget, whose focus controller then fired again and accessed
memory that had already been freed. The result was a crash, not an exception,
and therefore not a message either.

Two safeguards: a pure change of value no longer rebuilds the form at all —
groups and field widths do not change in that case anyway; only the origin
label is updated in place. And a field that still reports "leave" while being
torn down writes nothing any more. Both paths are tested.

In addition: exceptions from event handlers are caught and appear as a red
message *and* on standard error. GTK would otherwise swallow them — the window
simply stood still without anyone learning why.

### From the second trial

* **Separate letter case.** Directory and files each have their own rule — in
  the scene the folder is capitalised and the files are lower case.
  `--case-dir` and `--case-file`, in the interface two drop-downs.
* **Prefix for all companion files.** `--prefix-all` includes `.sfv` and
  `.m3u`; without the option the original behaviour remained (only `.nfo` and
  images). Until then, SFV and M3U built their names themselves and did not
  know the prefix rule at all.
* **Images** in the release folder are detected and renamed along with the
  rest, with the same stem as the other companion files. The preview names the
  image found.
* **Save as default.** A button in the header bar writes template, patterns,
  group, letter case and prefix to `~/.config/mp3releaser/config.toml`. On the
  next start everything is set — crucial for a demonstration. Saving merges
  into the existing file; hand-maintained sections such as `[tags]` are kept.
* **A single click opened the folder.** `GtkListBox` triggers `row-activated`
  on a single click by default. Now a click selects and a double click opens.

### From the third trial

* **Directory capitalised, files lower case.** The interface default is now
  `capitalize` for the folder and `lower` for the files:
  `Die_Aerzte-Ein_Album-CDDA-2026-GRP` with `01-die_aerzte-erster_titel.flac`
  inside.
* **Underscores are word boundaries.** In Python, `_` counts as a word
  character — without special handling `der_artist` became a single word and
  thus `Der_artist`. After the rule chain, however, the words look exactly
  like that.
* **Acronyms stay as they are**, up to four characters: `CDDA`, `WEB`, `GRP`,
  `DJ`. Longer ones are normalised so that `REMIXED` does not remain in
  capitals for good.
* **Companion files follow the file letter case**, not the directory's. They
  are files — a folder may be capitalised and the `.nfo`, `.sfv`, `.m3u` and
  image inside it still consistently lower case:

```
Der_Artist-Das_Album-2026-GRP/
    00-der_artist-das_album-2026-grp.jpg
    00-der_artist-das_album-2026-grp.m3u
    00-der_artist-das_album-2026-grp.nfo
    00-der_artist-das_album-2026-grp.sfv
    01-der_artist-titel_1.flac
    02-der_artist-titel_2.flac
```

### From the fourth trial

* **`00-` is the default**, for all companion files. It can be switched off
  with `--no-prefix` and restricted to `.nfo` and images via
  `prefixed_suffixes` (configuration: `prefix_all = false`).
* **Format marker in the folder name.** The new naming tag `#Fmt` inserts a
  marker before the year, derived from what the scanner found:

  | detected | marker | folder |
  |---|---|---|
  | MP3 | none | `der_artist-das_album-cdda-2026-grp` |
  | FLAC | `FLAC` | `der_artist-das_album-cdda-flac-2026-grp` |
  | AAC | `AAC` | `der_artist-das_album-cdda-aac-2026-grp` |
  | EC-3 with JOC | `ATMOS` | `der_artist-das_album-cdda-atmos-2026-grp` |

  MP3 is the implicit normal case and gets no marker — that is how the scene
  handled it too. Atmos trumps the container format: an EC-3 file with JOC is
  an Atmos release to the listener, not an EAC3 release. If the marker is
  missing, no double separator remains; the `collapse` rule takes care of
  that.

### What the fifth pass revealed

* **One default for all interfaces.** It was scattered: the library said
  "lower case for both", the drop-down on the desktop showed "capitalize" and
  the web interface used something else again. Now
  `service.naming_from_config()` provides it in one place, and a test compares
  desktop and web field by field.
* **Display and reality.** The letter-case drop-downs were preset instead of
  reading the state — they showed "capitalize" while "lower" applied.
* **Typos in the pattern.** `#Quatsch` survived the rule chain and ended up
  verbatim in the name. Unknown tags are now reported.
* **Empty directory pattern.** It targeted the *parent* directory. The
  collision check happened to catch it, because the parent always exists. It
  is now rejected explicitly.
* **Names tab on the web as well.** Patterns, group and preview were only
  reachable on the desktop, although the logic is shared.

### What the sixth pass revealed

* **Three places bypassed the default.** `service.build()`,
  `service.process()` and the guided mode fell back to the library default
  without a profile — so they named things differently from every interface.
  A test now checks that no `NamingProfile()` remains there.
* **Bitrate warning for lossless formats.** FLAC has a different bitrate for
  every file; the "different bitrates" message appeared for every FLAC release
  and was pure noise. It now only applies to lossy formats. MP3 files encoded
  with ABR count as variable as well.
* **Overlong paths.** A path component beyond 255 characters made the
  operating system throw — on the web a server error with a traceback instead
  of a message. It is now rejected beforehand.
* **Control characters in the NFO.** A null byte from a broken tag survived
  into the output and would have destroyed the column alignment. File names
  were already protected, the NFO was not.

Cross-checked without findings: all sixteen commands, the audio layer with
damaged files of every format, the SKL renderer with degenerate templates
(1000 tracks, tags without room, only continuation lines) and a second `build`
run on the same release.

### From the seventh trial

Special characters from titles ended up unchanged in file names. The new rule
`alnum` keeps only letters, digits and separators; everything else becomes a
separator. Apostrophes disappear entirely, otherwise `Don't` would become
`don_t`.

It runs **after** `transliterate` — first `ä` becomes `ae`, then filtering
happens. In the opposite order the umlaut would vanish without a trace.

**For names only, not for tags.** In the files, commas, brackets and umlauts
are preserved; they belong there. One test keeps both side by side (folder,
file, tag):

```
Ordner   Die_Aerzte-Ein_Album_Deluxe_Teil_2-FLAC-2026-GRP
Datei    02-die_aerzte-rocknroll_live_koeln.flac
Tag      'Die Ärzte' | 'Ein Album (Deluxe), Teil 2' | "Rock'n'Roll (Live @ Köln)"
```

This revealed a follow-up bug: a special character directly in front of a
pattern hyphen swallowed it — `…(Mix)-CDDA…` became `…mix_cdda…`. When a run
of separators meets, the hyphen now wins, because it separates the components
in the pattern.

### What the eighth pass revealed

* **Backslashes in the M3U.** The original ran on Windows and wrote
  `CD1\01-….flac`. On Linux no player finds that. Forward slashes are now the
  default; `--m3u-windows-paths` restores the old behaviour.
* **Pattern field and reality.** Setting the directory name by hand changes
  the pattern — the input field above it kept showing the old one.
* **The dupe check did not know the new formats.** `ATMOS`, `EAC3`, `ALAC`,
  `OPUS` and `MPC` did not count as format information, so a FLAC and an Atmos
  version of the same album counted as different releases.

Cross-checked without findings: the content of all generated files for a
two-disc release with umlauts (NFO in CP437, SFV with audio CRC, super M3U,
`verify` reports "2 ok" per disc), a release with a single untagged file, a
source folder with a comma in its name, and a run over sixty files.

### What the ninth pass revealed

* **Truncated track titles were not reported.** `overflows()` only knows the
  header data. Whether a long title wraps or gets lost depends on whether the
  template has a continuation line — that is now shown below the preview.
* **Two cryptic messages.** `metrics --compare` did not name the file when the
  JSON was broken, and a `KeyError` brought its quotation marks along:
  `Fehler: 'unbekannte Namensregel: …'`.

Cross-checked without findings: empty titles, titles consisting only of
special characters, duplicate track numbers (the collision is detected), disc
folders with spaces in their names, the preview for compilations and
multi-disc releases, and whether the overflow warning matches the actually
rendered text — with 200-character values the NFO stays exactly 78 columns
wide.

### What the tenth pass revealed

* **Unusable input became program errors instead of findings.** `check` on a
  directory without audio files aborted with exit code 2 instead of delivering
  a report with one error. Now it is a finding about the release, not an error
  of the program.
* **A binary file counted as a template** — with four notes about missing
  tags. A file without a single tag is now an error, and an unusual extension
  a remark.
* **Parity.** Checking and undo existed only on the command line and half on
  the desktop. Both now live in `uistate` and are available in all three
  interfaces — on the desktop as buttons, on the web via `/api/check` and
  `/api/undo`.

Cross-checked without findings: undo after deleting a file (detected and
refused; `--force` reverts what it can), undo of a multi-disc run, two stacked
runs in the log and a failed plan that logs nothing.

### What the eleventh pass revealed

* **In the service, one user could undo another user's rename.** The log
  exists once on the server and is shared by all sessions. Bernd saw in the
  log what Anna had renamed — including the release name — and could revert it
  with one click. Reproduced with two clients against the same service.

  Now every session remembers which entries it created itself, and in the
  service it may only see and undo those. On your own computer the shared log
  remains: there you should also be able to undo what the command line did.

  For the presentation this is a tangible case: the same function is harmless
  on your own computer and an intrusion in the shared service. The difference
  is not in the function's code, but in who owns the place where the state
  lives.
* **Undoing tags left traces.** The values came back, but an ID3v1 block
  created by the tag run remained — as did APEv2 and Lyrics3v2. For MP3 the log
  now records which blocks existed before, and the undo removes the others.

* **Folders mounted read-only were written to.** `:ro` in `RELEASER_MOUNTS`
  was part of the mount point's description but was not checked before
  renaming, tagging and creating files. In a real container the kernel would
  have refused — in the middle of the operation, with a system error. Now
  previews remain allowed, execution is blocked, and the status line says "nur
  lesend" (read-only).

Cross-checked without findings: undoing tags for MP3, AAC, Ogg and FLAC — each
exactly the original state, including the total `3/12` — and the audio CRC is
unchanged after writing and undoing.

### While building the standard template

* **The build script used a stale bundle.** `build.sh appdir` only built the
  single file if there was none. An old one stayed around — the AppImage then
  did not know `check` and `undo`, although the source had long had them. Now
  it rebuilds as soon as a source file is newer than the bundle, and
  `releaser --version` tells you which version you have.
* **A skipped test was outdated.** The bundle's end-to-end test had not run
  here for weeks, because no bundle had been built. It therefore never saw the
  changed default for letter case — it still expected the lower-case folder.
  Skipped tests rot unnoticed; an additional test now checks that the bundle
  knows every command of the source.

### The tests and the user directory

With tag undo, every test that sets tags wrote an entry into the undo log —
the real one, under `~/.local/state`. One test run left seventeen entries, and
a subsequent `releaser undo` would have touched test files instead of your own
releases. In addition, the interface tests depended on what had last been
saved as the default.

`tests/conftest.py` now redirects `XDG_STATE_HOME` and `XDG_CONFIG_HOME` into a
throw-away directory for every test. One test checks that the redirection
takes effect.

### What is open

* **Musepack** is read and written but untested — ffmpeg cannot create MPC.
* **Atmos (JOC)** is only tested against synthetic sync frames; ffmpeg's EC-3
  encoder does not produce JOC.
* **Three assumptions about the SKL engine** (see "Assumptions made") have not
  yet been verified against real reference NFOs.
* **The container measurement** in the comparison table is estimated until
  `docker compose` has run once.
