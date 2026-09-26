"""Gemeinsame Test-Einstellungen.

Die Tests duerfen nichts im Benutzerverzeichnis dessen anfassen, der sie
laufen laesst - und nicht von dessen Einstellungen abhaengen:

* **Zustand** (``$XDG_STATE_HOME``): Jeder Test, der Tags schreibt oder
  umbenennt, legt einen Eintrag im Rueckgaengig-Protokoll an. Ohne diese
  Umleitung saeuberten siebzehn Eintraege aus Testlaeufen das echte
  Protokoll - und ein ``releaser undo`` haette danach Testdateien statt der
  eigenen Releases angefasst.
* **Konfiguration** (``$XDG_CONFIG_HOME``): Die Oberflaechen lesen die
  gespeicherten Voreinstellungen. Ohne Umleitung haengt das Ergebnis eines
  Tests davon ab, was der Pruefende zuletzt gespeichert hat.

Beides gilt fuer jeden Test automatisch. Einzelne Tests koennen die
Variablen weiterhin selbst setzen; ihr ``monkeypatch`` wirkt danach.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_user_directories(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("benutzer")
    monkeypatch.setenv("XDG_STATE_HOME", str(base / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base / "config"))
    yield
