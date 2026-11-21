"""Tests fuer Feldererkennung, Ausrichtung und Zeilenreplikation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.model import Disc, Release, Track
from releaser.skl import Template, parse_line
from releaser.tags import Settings


def make_release(**kw) -> Release:
    base = dict(
        artist="Beispiel Artist",
        album="Ein Album",
        year=2026,
        genre="Electronic",
        ripper="someone",
        encoder="LAME 3.100",
        audio_format="MP3",
        source="CDDA",
        url="https://example.invalid",
        bitrate=320,
        samplerate=44100,
        channel_mode="Joint-Stereo",
        notes=["Erste Notizzeile.", "Zweite Notizzeile."],
        discs=[
            Disc(1, tracks=[
                Track(1, "Kurzer Titel", 215.0, size_bytes=8_600_000),
                Track(2, "Ein deutlich laengerer Tracktitel der umbrochen werden muss", 301.0, size_bytes=12_000_000),
            ])
        ],
    )
    base.update(kw)
    return Release(**base)


# ------------------------------------------------------------------- Parsing


def test_longest_match_wins():
    pl = parse_line("#Releasenc")
    assert [f.tag.name for f in pl.fields] == ["Releasenc"]

    pl = parse_line("#Albwthadd")
    assert [f.tag.name for f in pl.fields] == ["Albwthadd"]

    pl = parse_line("#10Hz")
    assert [f.tag.name for f in pl.fields] == ["10Hz"]


def test_left_field_absorbs_trailing_spaces():
    line = "  #Artist        |"
    pl = parse_line(line)
    f = pl.field_for("Artist")
    assert f.start == 2
    assert f.end == line.index("|")   # bis direkt vor dem Rahmen
    assert f.width == 15


def test_left_field_stops_at_next_tag():
    pl = parse_line("#Artist   #Album   |")
    a = pl.field_for("Artist")
    assert a.end == 10          # nicht in '#Album' hinein


def test_right_field_absorbs_leading_spaces():
    line = "|        Size# MB |"
    pl = parse_line(line)
    f = pl.field_for("Size#")
    assert f.start == 1                       # direkt hinter dem Rahmen
    assert f.end == line.index("Size#") + 5   # endet mit dem Literal


def test_right_field_does_not_eat_previous_tag():
    pl = parse_line("#Artist        Size# MB")
    a = pl.field_for("Artist")
    s = pl.field_for("Size#")
    assert s.start >= a.end     # keine Ueberlappung


# ------------------------------------------------------------------ Rendering


def test_alignment_keeps_columns():
    W = 42  # alle Templatezeilen exakt gleich breit bauen
    rows = [
        "|" + "#Release".ljust(W - 2) + "|",
        "|" + "#Releasenc".ljust(W - 2) + "|",
        "|" + "Size# MB".rjust(W - 2) + "|",
    ]
    tpl = Template.parse("\n".join(rows))
    out = tpl.render(make_release(), trim_trailing=False).split("\n")
    assert len(set(len(l) for l in out)) == 1          # alle Zeilen gleich lang
    assert all(l.startswith("|") and l.endswith("|") for l in out)
    assert out[0][1:-1].strip() == out[1][1:-1].strip()
    assert out[0][1] == " "                            # zentriert -> Vorlauf
    assert out[1][1] != " "                            # linksbuendig -> kein Vorlauf
    assert out[2].endswith(" MB|")                     # rechtsbuendig
    assert out[2][1] == " "


def test_value_is_truncated_to_field_width():
    line = "|#Artist   |"
    tpl = Template.parse(line)
    r = make_release(artist="Ein viel zu langer Artistname")
    out = tpl.render(r, trim_trailing=False)
    assert len(out) == len(line)        # Spaltenraster bleibt erhalten
    assert out == "|Ein viel z|"


def test_tracklist_replicates_per_track():
    tpl = Template.parse("| #N #Trk          |")
    out = tpl.render(make_release()).split("\n")
    assert len(out) == 2
    assert out[0].startswith("| 01 Kurzer Titel")


def test_tracklist_wraps_into_continuation_line():
    tpl = Template.parse("| #N.#Trk        |\n|    #Trk        |")
    out = tpl.render(make_release()).split("\n")
    # Track 1 passt in eine Zeile, Track 2 braucht mehrere
    assert out[0].startswith("| 01.Kurzer")
    assert len(out) > 2
    assert out[1].startswith("| 02.")
    assert out[2].startswith("|    ")


def test_multi_disc_header_uses_continuation_line():
    r = make_release(discs=[
        Disc(1, tracks=[Track(1, "A", 100.0)]),
        Disc(2, tracks=[Track(1, "B", 100.0)]),
    ])
    tpl = Template.parse("| #N.#Trk        |\n|    #Trk        |")
    out = tpl.render(r).split("\n")
    assert "CD1" in out[0]
    assert any("CD2" in l for l in out)


def test_sn_tag_lists_per_disc_counts():
    r = make_release(discs=[
        Disc(1, tracks=[Track(1, "A", 10.0), Track(2, "B", 10.0)]),
        Disc(2, tracks=[Track(1, "C", 10.0)]),
    ])
    out = Template.parse("#Sn                 ").render(r)
    assert "CD1: 2" in out and "CD2: 1" in out


def test_notes_block_uses_continuation_line():
    pad = " " * 30
    tpl = Template.parse(f"| Notes: #Rnotes{pad}|\n|        #Rnotes{pad}|")
    out = tpl.render(make_release()).split("\n")
    assert out[0].startswith("| Notes: Erste Notizzeile.")
    assert out[1].startswith("|        Zweite Notizzeile.")


def test_notes_longer_than_field_wrap_into_continuation():
    pad = " " * 6
    tpl = Template.parse(f"| #Rnotes{pad}|\n|   #Rnotes{pad}|")
    r = make_release(notes=["eins zwei drei vier fuenf sechs"])
    out = tpl.render(r).split("\n")
    assert len(out) > 1
    assert out[1].startswith("|   ")


def test_field_widths_exposed_for_gui():
    tpl = Template.parse("|#Artist        |\n|#Album   |")
    widths = tpl.field_widths()
    assert widths["Artist"] == 15
    assert widths["Album"] == 9
    assert "Catnr" not in tpl.tag_names()


def test_charcase_exempts_url():
    from releaser.text import CharCase

    tpl = Template.parse("#Artist                 \n#Url                    ")
    out = tpl.render(make_release(), Settings(nfo_charcase=CharCase.UPPER)).split("\n")
    assert out[0] == "BEISPIEL ARTIST"
    assert out[1] == "https://example.invalid"


def test_bitrate_and_vbr():
    r = make_release(vbr=True, vbr_string="VBR (V0)")
    assert "VBR (V0)" in Template.parse("#Br         ").render(r)
    assert "320kbps" in Template.parse("#Br         ").render(make_release())


def test_example_template_roundtrip():
    path = Path(__file__).resolve().parents[1] / "templates" / "example.skl"
    tpl = Template.from_file(path, codepage="cp437")
    out = tpl.render(make_release(), trim_trailing=False)
    widths = {len(l) for l in out.split("\n") if l.strip()}
    # alle Rahmenzeilen bleiben gleich lang
    assert widths == {78}


def test_control_characters_are_stripped():
    """Ein defektes Tag darf die Spaltenausrichtung nicht zerstören."""
    from releaser.skl import strip_control

    assert strip_control("T\x00X") == "TX"
    assert strip_control("a\tb\nc") == "abc"
    assert strip_control("normal") == "normal"

    release = Release(artist="A\x07B", discs=[Disc(1, tracks=[
        Track(1, "Titel\x00mit Müll", 10.0)])])
    line = Template.parse("|#Artist   |").render(release, trim_trailing=False)
    assert line == "|AB        |"

    tracks = Template.parse("|#N #Trk              |").render(release)
    assert "\x00" not in tracks
    assert "Titelmit Müll" in tracks


def test_track_layout_reports_width_and_continuation():
    plain = "|#N #Trk    |"
    with_cont = plain + "\n|   #Trk    |"
    assert Template.parse(plain).track_layout() == (8, False)
    assert Template.parse(with_cont).track_layout() == (8, True)
    assert Template.parse("#Artist   ").track_layout() == (0, False)


# ------------------------------------------------ Korrekturen (Fehlerdurchsicht)


def test_space_before_kbps_goes_between_number_and_unit():
    template = Template.parse("#Br           |")
    release = make_release()
    assert template.render(release).startswith("320kbps ")
    spaced = template.render(release, Settings(space_before_kbps=True))
    assert spaced.startswith("320 kbps ")


def _words(text: str, drop: tuple[str, ...] = ()) -> list[str]:
    return [w for w in text.replace("|", " ").split() if w not in drop]


def test_wrapped_track_title_fits_a_narrower_continuation_line():
    """Umbrochen wurde mit der Breite der Hauptzeile - im schmaleren
    Fortsetzungsfeld fiel der Rest dann stillschweigend weg."""
    template = Template.parse("#N #Trk" + " " * 26 + "|\n"
                              "      #Trk" + " " * 6 + "|")
    title = "eins zwei drei vier fuenf sechs sieben acht neun zehn elf"
    release = make_release(discs=[Disc(1, tracks=[Track(1, title, 60.0)])])
    out = template.render(release)
    assert _words(out, drop=("01",)) == title.split()


def test_wrapped_notes_fit_a_narrower_continuation_line():
    template = Template.parse("#Rnotes" + " " * 24 + "|\n"
                              "  #Rnotes" + " " * 5 + "|")
    first = "Eine recht lange erste Notiz, die ueber mehrere Zeilen umbricht"
    release = make_release(notes=[first, "zweite"])
    out = template.render(release)
    assert _words(out) == (first + " zweite").split()
    widths = {len(line) for line in out.splitlines()}
    assert max(widths) <= 32


# ------------------------------------------------- Codepage beim Schreiben


def test_one_unmappable_character_keeps_the_block_graphics(tmp_path):
    """Ein einziges "’" in einem Tag lief frueher als Ausloeser fuer die
    ganze NFO durch die ASCII-Umwandlung - Rahmen und Blockgrafik der
    Vorlage verschwanden komplett."""
    from releaser.text import write_nfo

    art = "╔════╗ █▓▒░ ▄▀\n║ ÄÖÜ ║ ·°±²\n╚════╝"
    target = tmp_path / "x.nfo"
    write_nfo(target, art + "\nTitel: Don’t Stop – Live™ 東", crlf=False)
    text = target.read_bytes().decode("cp437")
    assert text.startswith(art + "\n")
    assert text.endswith("Titel: Don't Stop - LiveTM ?")


def test_standard_template_keeps_its_frame_with_an_unmappable_tag(tmp_path):
    """Der Fall aus der Erprobung: Atmos-Album, ein Titel mit typografischem
    Apostroph - die erzeugte .nfo hatte keinen einzigen Rahmenstrich mehr."""
    from releaser.text import read_template, write_nfo

    skl = Path(__file__).resolve().parent.parent / "templates" / "standard.skl"
    raw = skl.read_bytes()
    template = Template.parse(read_template(skl))
    release = make_release(artist="Beyoncé’s Band", audio_format="ATMOS")
    target = tmp_path / "out.nfo"
    write_nfo(target, template.render(release))
    out = target.read_bytes()
    assert out.split(b"\r\n")[0] == raw.splitlines()[0]
    assert "Beyoncé's Band".encode("cp437") in out
    assert sum(b >= 0x80 for b in out) > 0.5 * sum(b >= 0x80 for b in raw)


def test_decomposed_umlaut_stays_an_umlaut():
    from releaser.text import to_codepage

    assert to_codepage("ä ™").decode("cp437") == "ä TM"


def test_expanding_replacements_keep_the_frame_aligned(tmp_path):
    """Aus dem Test des AppImage 0.27.4: "™" wurde erst beim Schreiben zu
    "TM" - die Zeile war danach eine Spalte zu breit, der rechte Rahmen
    sprang aus der Reihe. Und die Vorschau zeigte "™", die Datei "TM"."""
    from releaser.text import read_template, write_nfo

    skl = Path(__file__).resolve().parent.parent / "templates" / "standard.skl"
    template = Template.parse(read_template(skl))
    release = make_release(discs=[Disc(1, tracks=[
        Track(1, "Don’t Stop – Live™", 60.0),
        Track(2, "東京 … Nacht", 60.0),
        Track(3, "Normal", 60.0)])])
    text = template.render(release)
    target = tmp_path / "out.nfo"
    write_nfo(target, text)
    written = target.read_bytes().decode("cp437").split("\r\n")
    frame = {len(line) for line in written if line.startswith("║")}
    assert len(frame) == 1, frame
    # Was gerendert wird, ist schon das, was in der Datei steht
    assert written == text.split("\n")
    assert any("Don't Stop - LiveTM" in line for line in written)
    assert any("?? ... Nacht" in line for line in written)


def test_utf8_keeps_every_character():
    from releaser.tags import Settings

    template = Template.parse("#Trk                    |")
    release = make_release(discs=[Disc(1, tracks=[Track(1, "Live™ 東京", 1.0)])])
    out = template.render(release, Settings(codepage="utf-8"))
    assert "Live™ 東京" in out
