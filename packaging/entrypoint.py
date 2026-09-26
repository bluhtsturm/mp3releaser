"""Einstiegspunkt der gebuendelten Fassung.

Ohne Argumente startet die grafische Oberflaeche, sofern GTK vorhanden ist -
sonst die Kommandozeilenhilfe. Mit Argumenten verhaelt sich das Buendel wie
``python -m releaser``.
"""

import sys


def main() -> int:
    from releaser.cli import main as cli_main

    if len(sys.argv) > 1:
        return cli_main(sys.argv[1:])

    from releaser.frontends.gtkui import is_available, requirements_hint, run

    if is_available():
        return run()
    print(requirements_hint(), file=sys.stderr)
    print("\nOhne Argumente startet die grafische Oberflaeche.\n"
          "Eine Uebersicht der Kommandos gibt es mit: mp3releaser --help",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
