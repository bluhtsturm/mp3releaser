"""Einstiegspunkt der gebuendelten Fassung.

Ohne Argumente startet die grafische Oberflaeche, sofern GTK vorhanden ist -
sonst die Kommandozeilenhilfe. Mit Argumenten verhaelt sich das Buendel wie
``python -m releaser``.
"""

import os
import sys

#: Wo Distributionen ihre Typelibs ablegen: Debian/Ubuntu, Fedora/openSUSE,
#: Arch, selbst gebaut
HOST_TYPELIB_DIRS = (
    "/usr/lib/x86_64-linux-gnu/girepository-1.0",
    "/usr/lib64/girepository-1.0",
    "/usr/lib/girepository-1.0",
    "/usr/local/lib/girepository-1.0",
)


def use_host_glib(environ=os.environ, isdir=os.path.isdir) -> None:
    """GLib, GTK und ihre Typelibs kommen vom Wirt (siehe pyinstaller.spec).

    Die Laufzeit-Hooks von PyInstaller zeigen GObject-Introspection und GIO
    auf Ordner im Buendel. GIO soll die Module des Wirts laden, die zu dessen
    GLib passen - im Buendel liegen keine mehr. Typelibs kommen zuerst vom
    Wirt, passend zu seinen Bibliotheken; die mitgebrachte libgirepository
    saehe sonst nur unter dem Pfad von Debian/Ubuntu nach. Die Typelibs im
    Buendel bleiben als Rueckfall dahinter: Schlanken Installationen von
    Fedora oder Arch fehlt etwa cairo-1.0.typelib.
    """
    environ.pop("GIO_MODULE_DIR", None)
    search = [path for path in HOST_TYPELIB_DIRS if isdir(path)]
    if environ.get("GI_TYPELIB_PATH"):
        search.append(environ["GI_TYPELIB_PATH"])
    if search:
        environ["GI_TYPELIB_PATH"] = os.pathsep.join(search)


def main() -> int:
    if getattr(sys, "frozen", False):
        use_host_glib()

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
