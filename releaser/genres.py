"""ID3v1-Genreliste und Zuordnung.

ID3v1 kennt Genres nur als Zahl. Wer "electronic" statt "Electronic" in das
ID3v2-Feld schreibt, bekommt in ID3v1 den Wert 255 ("unbekannt") - die Angabe
geht beim Schreiben also stillschweigend verloren.

Deshalb wird der Genrename vor dem Schreiben auf die kanonische Schreibweise
der Liste gebracht. Passt er auf keinen Eintrag, bleibt er als Freitext stehen
und es gibt eine Warnung, statt ihn zu verwerfen.

Die Liste umfasst die 80 ursprünglichen Genres plus die Winamp-Erweiterungen.
Ein Test gleicht sie gegen mutagens Liste ab, damit beide nicht auseinander
laufen.
"""

from __future__ import annotations

import re
from typing import Optional

#: Index = ID3v1-Genrenummer.
GENRES: tuple[str, ...] = (
    'Blues', 'Classic Rock', 'Country', 'Dance', 'Disco', 'Funk', 'Grunge',
    'Hip-Hop', 'Jazz', 'Metal', 'New Age', 'Oldies', 'Other', 'Pop', 'R&B',
    'Rap', 'Reggae', 'Rock', 'Techno', 'Industrial', 'Alternative', 'Ska',
    'Death Metal', 'Pranks', 'Soundtrack', 'Euro-Techno', 'Ambient',
    'Trip-Hop', 'Vocal', 'Jazz+Funk', 'Fusion', 'Trance', 'Classical',
    'Instrumental', 'Acid', 'House', 'Game', 'Sound Clip', 'Gospel',
    'Noise', 'Alt. Rock', 'Bass', 'Soul', 'Punk', 'Space', 'Meditative',
    'Instrumental Pop', 'Instrumental Rock', 'Ethnic', 'Gothic', 'Darkwave',
    'Techno-Industrial', 'Electronic', 'Pop-Folk', 'Eurodance', 'Dream',
    'Southern Rock', 'Comedy', 'Cult', 'Gangsta Rap', 'Top 40',
    'Christian Rap', 'Pop/Funk', 'Jungle', 'Native American', 'Cabaret',
    'New Wave', 'Psychedelic', 'Rave', 'Showtunes', 'Trailer', 'Lo-Fi',
    'Tribal', 'Acid Punk', 'Acid Jazz', 'Polka', 'Retro', 'Musical',
    'Rock & Roll', 'Hard Rock', 'Folk', 'Folk-Rock', 'National Folk',
    'Swing', 'Fast-Fusion', 'Bebop', 'Latin', 'Revival', 'Celtic',
    'Bluegrass', 'Avantgarde', 'Gothic Rock', 'Progressive Rock',
    'Psychedelic Rock', 'Symphonic Rock', 'Slow Rock', 'Big Band', 'Chorus',
    'Easy Listening', 'Acoustic', 'Humour', 'Speech', 'Chanson', 'Opera',
    'Chamber Music', 'Sonata', 'Symphony', 'Booty Bass', 'Primus',
    'Porn Groove', 'Satire', 'Slow Jam', 'Club', 'Tango', 'Samba',
    'Folklore', 'Ballad', 'Power Ballad', 'Rhythmic Soul', 'Freestyle',
    'Duet', 'Punk Rock', 'Drum Solo', 'A Cappella', 'Euro-House',
    'Dance Hall', 'Goa', 'Drum & Bass', 'Club-House', 'Hardcore', 'Terror',
    'Indie', 'BritPop', 'Afro-Punk', 'Polsk Punk', 'Beat',
    'Christian Gangsta Rap', 'Heavy Metal', 'Black Metal', 'Crossover',
    'Contemporary Christian', 'Christian Rock', 'Merengue', 'Salsa',
    'Thrash Metal', 'Anime', 'JPop', 'Synthpop', 'Abstract', 'Art Rock',
    'Baroque', 'Bhangra', 'Big Beat', 'Breakbeat', 'Chillout', 'Downtempo',
    'Dub', 'EBM', 'Eclectic', 'Electro', 'Electroclash', 'Emo',
    'Experimental', 'Garage', 'Global', 'IDM', 'Illbient', 'Industro-Goth',
    'Jam Band', 'Krautrock', 'Leftfield', 'Lounge', 'Math Rock',
    'New Romantic', 'Nu-Breakz', 'Post-Punk', 'Post-Rock', 'Psytrance',
    'Shoegaze', 'Space Rock', 'Trop Rock', 'World Music', 'Neoclassical',
    'Audiobook', 'Audio Theatre', 'Neue Deutsche Welle', 'Podcast',
    'Indie Rock', 'G-Funk', 'Dubstep', 'Garage Rock', 'Psybient',
)

_NORMALISE = re.compile(r"[^a-z0-9]+")


def _key(name: str) -> str:
    """Vergleichsform: nur Buchstaben und Ziffern, klein."""
    return _NORMALISE.sub("", name.lower())


#: Vergleichsform -> (kanonischer Name, Nummer)
_LOOKUP: dict[str, tuple[str, int]] = {}
for _index, _name in enumerate(GENRES):
    _LOOKUP.setdefault(_key(_name), (_name, _index))

#: Gängige Schreibweisen, die auf keinen Listeneintrag passen würden.
ALIASES: dict[str, str] = {
    "hiphop": "Hip-Hop",
    "rnb": "R&B",
    "randb": "R&B",
    "rhythmandblues": "R&B",
    "drumandbass": "Drum & Bass",
    "dnb": "Drum & Bass",
    "dandb": "Drum & Bass",
    "rocknroll": "Rock & Roll",
    "rockandroll": "Rock & Roll",
    "triphop": "Trip-Hop",
    "synthpop": "Synthpop",
    "eurodance": "Eurodance",
    "idm": "IDM",
    "ebm": "EBM",
    "electronica": "Electronic",
    "electro": "Electro",
    # Die ID3v1-Liste fuehrt Nummer 40 als "Alt. Rock" - ein Alias auf
    # "Alternative Rock" liefe ins Leere.
    "alternativerock": "Alt. Rock",
    "acapella": "A Cappella",
}


def lookup(name: str) -> Optional[tuple[str, int]]:
    """(kanonischer Name, ID3v1-Nummer) oder None."""
    if not name:
        return None
    key = _key(name)
    if key in _LOOKUP:
        return _LOOKUP[key]
    alias = ALIASES.get(key)
    if alias:
        return _LOOKUP.get(_key(alias))
    return None


def canonical(name: str) -> Optional[str]:
    found = lookup(name)
    return found[0] if found else None


def number(name: str) -> Optional[int]:
    found = lookup(name)
    return found[1] if found else None


def normalise(name: str) -> tuple[str, Optional[int], Optional[str]]:
    """(Name zum Schreiben, ID3v1-Nummer, Warnung).

    Unbekannte Genres bleiben unverändert - verwerfen wäre schlimmer als ein
    Genre, das nur ID3v2 überlebt.
    """
    if not name:
        return "", None, None
    found = lookup(name)
    if found is None:
        return name, None, (f"Genre {name!r} steht nicht in der ID3v1-Liste - "
                            "es überlebt nur in ID3v2")
    return found[0], found[1], None
