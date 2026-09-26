"""Kompatibilitätsschicht.

Die Kommandozeile ist nach :mod:`releaser.frontends.cli` gezogen, weil sie
nur noch eine von mehreren Oberflächen ist. Dieser Einstiegspunkt bleibt
bestehen, damit ``python -m releaser`` und bestehende Aufrufe weiter
funktionieren.
"""

from .frontends.cli import main

__all__ = ["main"]
