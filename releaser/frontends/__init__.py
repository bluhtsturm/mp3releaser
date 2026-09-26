"""Oberflächen.

Der Kern des Programms kennt keine Oberfläche. Was hier liegt, sind dünne
Schichten darüber, die alle dieselbe Dienstschicht (``releaser.service``)
benutzen:

* ``cli`` - Kommandozeile
* ``wizard`` - gefuehrter Modus, aufgerufen ueber ``releaser wizard``
* ``gtkui`` - Desktop-Anwendung (GTK 4); laesst sich auch ohne GTK importieren
* ``web`` - Weboberflaeche (FastAPI), nur mit eingehaengten Verzeichnissen

Wer eine weitere Oberfläche baut, ruft die Dienstschicht auf und schreibt
keine eigene Ablauflogik. Sonst driften die Formen auseinander, und genau das
soll nicht passieren.
"""

from . import cli, gtkui, wizard  # noqa: F401

# web wird bewusst nicht mitimportiert: FastAPI ist eine optionale
# Abhaengigkeit, und die Kommandozeile soll ohne sie starten.
__all__ = ["cli", "gtkui", "wizard", "web"]
