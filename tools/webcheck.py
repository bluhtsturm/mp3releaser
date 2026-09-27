"""Prüfstand für die Weboberfläche in einer echten Browser-Engine.

Die Seite ist bisher nur über die API geprüft worden - das JavaScript selbst
lief dabei nie. Hier läuft es: WebKitGTK lädt die Seite von einem echten
Server, und über ``evaluate_javascript`` lässt sich der Zustand des DOM
abfragen und die Oberfläche bedienen.

Aufruf::

    xvfb-run -a python3 tools/webcheck.py /pfad/zum/eingang

Gibt je Prüfung eine Zeile aus und endet mit dem Ergebnis. Rückgabewert 0,
wenn alles stimmt.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import GLib, Gtk, WebKit  # noqa: E402

from releaser.browse import Mount, MountedSource  # noqa: E402
from releaser.naming import NamingProfile  # noqa: E402

PORT = 8765
TIMEOUT = 30.0


def start_server(mount: Path, templates: Path) -> threading.Thread:
    """Startet den echten Dienst in einem Hintergrund-Thread."""
    import uvicorn

    from releaser.frontends.web.app import create_app

    app = create_app(MountedSource([Mount("eingang", mount)]),
                     naming=NamingProfile(group="GRP"),
                     templates_dir=templates)
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    import urllib.request

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/info", timeout=1)
            return thread
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("Server ist nicht hochgekommen")


class Checker:
    """Führt Prüfschritte nacheinander in der Seite aus."""

    def __init__(self, view: WebKit.WebView, loop: GLib.MainLoop):
        self.view = view
        self.loop = loop
        self.results: list[tuple[bool, str]] = []
        self.steps: list = []
        self.index = 0

    def report(self, ok: bool, text: str) -> None:
        self.results.append((ok, text))
        print(f"  [{'ok ' if ok else 'FEHLER'}] {text}")

    # -- JavaScript ----------------------------------------------------

    def js(self, script: str, then) -> None:
        def safe(value):
            # GObject verschluckt Ausnahmen aus Rueckrufen - dann bricht die
            # Kette still ab und man sieht nur, dass Pruefungen fehlen.
            try:
                then(value)
            except Exception as error:      # noqa: BLE001
                self.report(False, f"Fehler im Pruefschritt: {error!r}")
                self.next()

        def done(view, result):
            try:
                value = view.evaluate_javascript_finish(result)
                payload = value.to_string() if value is not None else "null"
            except GLib.Error as error:
                payload = json.dumps({"error": str(error)})
            # Nicht jedes Skript liefert JSON zurueck - rohe Zeichenketten
            # sind fuer Schritte gedacht, deren Rueckgabe egal ist.
            try:
                safe(json.loads(payload) if payload not in ("", "undefined")
                     else None)
            except json.JSONDecodeError:
                safe(payload)

        # In geschweiften Klammern, damit ``const`` blockweise gilt: sonst
        # kollidiert der zweite Pruefschritt mit den Namen des ersten, weil
        # alle Skripte denselben globalen Namensraum benutzen.
        self.view.evaluate_javascript("{\n" + script + "\n}", -1,
                                      None, None, None, done)

    def wait(self, script: str, then, tries: int = 60) -> None:
        """Wartet, bis ein Ausdruck wahr wird - die Seite laedt asynchron."""
        def check(value):
            if value:
                then(value)
            elif tries > 0:
                GLib.timeout_add(100, lambda: (self.wait(script, then, tries - 1),
                                               False)[1])
            else:
                self.report(False, f"Zeitüberschreitung bei: {script[:60]}")
                self.next()

        self.js(script, check)

    def next(self, *_args) -> None:
        if self.index >= len(self.steps):
            self.loop.quit()
            return
        step = self.steps[self.index]
        self.index += 1
        step()


def build_steps(checker: Checker) -> None:
    c = checker

    def step_loaded():
        c.wait("JSON.stringify(document.querySelectorAll('.entry').length)",
               lambda n: (c.report(n == 1, f"Auswahl zeigt {n} Eintrag (eingang)"),
                          c.next()))

    def step_banner():
        c.js("JSON.stringify(document.getElementById('banner').textContent)",
             lambda text: (
                 c.report("eingehängten Ordner" in (text or "")
                          and "auf dem Server" in (text or ""),
                          "Banner nennt Beschränkung und Datenlage"),
                 c.next()))

    def step_buttons_disabled():
        c.js("JSON.stringify(['load','tags','rename','build']"
             ".map(id => document.getElementById(id).disabled))",
             lambda flags: (
                 c.report(flags == [True, True, True, True],
                          "ohne Auswahl sind alle Aktionen gesperrt"),
                 c.next()))

    def step_select():
        c.js("document.querySelector('.entry').click(); 'ok'", lambda _: None)
        c.wait("JSON.stringify(document.getElementById('load').disabled === false)",
               lambda _: (c.report(True, "Klick wählt aus, „Einlesen“ wird aktiv"),
                          c.next()))

    def step_open_and_select_release():
        c.js("""
             const entry = document.querySelector('.entry');
             entry.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
             'ok'
             """, lambda _: None)
        c.wait("JSON.stringify(document.getElementById('crumbs').textContent"
               " === 'eingang')",
               lambda _: (c.report(True, "Doppelklick öffnet den Ordner"),
                          c.next()))

    def step_template():
        c.js("""
             const select = document.getElementById('template');
             const option = [...select.options].find(o => o.value.endsWith('.skl'));
             if (!option) { JSON.stringify(null); }
             else {
               select.value = option.value;
               select.dispatchEvent(new Event('change'));
               JSON.stringify(option.value);
             }
             """,
             lambda name: (c.report(bool(name), f"Vorlage gewählt: {name}"),
                           c.next()))

    def step_load_release():
        c.js("""
             document.querySelector('.entry').click();
             setTimeout(() => document.getElementById('load').click(), 150);
             'ok'
             """, lambda _: None)
        c.wait("JSON.stringify(document.querySelectorAll('details').length)",
               lambda n: (c.report(n >= 4, f"{n} Feldgruppen gezeichnet"),
                          c.next()))

    def step_groups():
        c.js("JSON.stringify([...document.querySelectorAll('summary')]"
             ".map(s => s.textContent))",
             lambda titles: (
                 c.report(any(t.startswith("nicht verwendet") for t in titles)
                          and any(t.startswith("in den Tags") for t in titles),
                          f"Gruppen: {', '.join(t.split(' (')[0] for t in titles)}"),
                 c.next()))

    def step_unused_collapsed():
        c.js("""
             JSON.stringify([...document.querySelectorAll('details')]
               .filter(d => d.querySelector('summary')
                 .textContent.startsWith('nicht verwendet'))
               .map(d => d.open))
             """,
             lambda flags: (
                 c.report(flags == [False],
                          "Gruppe „nicht verwendet“ ist eingeklappt"),
                 c.next()))

    def step_field_value():
        c.js("""
             const inputs = [...document.querySelectorAll('.grid input')];
             const labels = [...document.querySelectorAll('.grid label')]
               .map(l => l.textContent);
             JSON.stringify(inputs[labels.indexOf('Artist')].value)
             """,
             lambda value: (c.report(value == "Der Artist",
                                     f"Artist-Feld zeigt {value!r}"),
                            c.next()))

    def step_counter_turns_red():
        c.js("""
             const labels = [...document.querySelectorAll('.grid label')]
               .map(l => l.textContent);
             const index = labels.indexOf('Album');
             const input = [...document.querySelectorAll('.grid input')][index];
             // Laenger als jedes Feld der Beispielvorlage (59 Zeichen)
             input.value = 'Ein wirklich ausserordentlich langer Albumtitel, '
                         + 'der in kein Feld dieser Vorlage hineinpasst';
             input.dispatchEvent(new Event('input'));
             const counter = [...document.querySelectorAll('.counter')][index];
             JSON.stringify({counter: counter.textContent,
                             red: counter.classList.contains('over'),
                             input: input.classList.contains('over')})
             """,
             lambda data: (
                 c.report(isinstance(data, dict) and data.get("red")
                          and data.get("input"),
                          f"Überlänge wird rot markiert ({data})"),
                 c.next()))

    def step_plan_dialog():
        c.js("document.getElementById('rename').click(); 'ok'", lambda _: None)
        c.wait("JSON.stringify(document.getElementById('plan').open)",
               lambda _: c.js(
                   "JSON.stringify(document.getElementById('planText').textContent)",
                   lambda text: (
                       c.report("->" in (text or ""),
                                "Umbenennungsplan erscheint im Dialog"),
                       c.next())))

    def step_cancel_changes_nothing():
        c.js("""
             document.getElementById('planCancel').click();
             JSON.stringify(document.getElementById('plan').open)
             """,
             lambda still_open: (
                 c.report(not still_open, "Abbrechen schließt den Dialog"),
                 c.next()))

    def step_file_name_by_hand():
        # Reiter "Namen": ein Dateiname wird überschrieben, der Server
        # bereinigt ihn, das Feld zeigt danach den übernommenen Namen und
        # ist als "von Hand" markiert.
        c.js("""
             [...document.querySelectorAll('.tab')]
               .find(t => t.dataset.tab === 'names').click();
             JSON.stringify('ok')
             """, lambda _: None)
        c.wait("JSON.stringify(document.querySelectorAll("
               "'#filenames input').length > 0)",
               lambda _: c.js("""
                   const input = document.querySelector(
                       '#filenames input[data-file-index="0"]');
                   input.value = '01 Teil I - Teil II.mp3';
                   input.dispatchEvent(new Event('change'));
                   JSON.stringify('ok')
                   """, lambda _: c.wait("""
                   JSON.stringify(document.querySelector(
                       '#filenames input[data-file-index="0"]')
                       .classList.contains('manual'))
                   """, lambda _: c.js("""
                   const row = document.querySelector('#filenames tbody tr');
                   JSON.stringify({
                     value: row.querySelector('input').value,
                     reset: !row.querySelector('button').disabled})
                   """, lambda got: (
                       c.report(got.get("value") == "01_Teil_I_-_Teil_II"
                                and got.get("reset"),
                                f"Dateiname von Hand übernommen ({got})"),
                       c.next())))))

    def step_nfo_tab():
        c.js("""
             [...document.querySelectorAll('.tab')]
               .find(t => t.dataset.tab === 'nfo').click();
             JSON.stringify('ok')
             """, lambda _: None)
        c.wait("JSON.stringify(document.getElementById('nfotext')"
               ".textContent.length > 50)",
               lambda _: c.js(
                   "JSON.stringify(document.getElementById('nfostatus').textContent)",
                   lambda text: (
                       c.report("Zeilen" in (text or ""),
                                f"NFO-Vorschau gefüllt ({text})"),
                       c.next())))

    def step_status():
        c.js("JSON.stringify(document.getElementById('status').textContent)",
             lambda text: (c.report("Tracks" in (text or ""),
                                    f"Statuszeile: {text}"),
                           c.next()))

    c.steps = [step_loaded, step_banner, step_buttons_disabled, step_select,
               step_open_and_select_release, step_template,
               step_load_release, step_groups,
               step_unused_collapsed, step_field_value,
               step_counter_turns_red, step_plan_dialog,
               step_cancel_changes_nothing, step_file_name_by_hand,
               step_nfo_tab, step_status]


def main() -> int:
    mount = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/webcheck/eingang")
    templates = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("templates")

    start_server(mount, templates)
    print(f"Server laeuft auf 127.0.0.1:{PORT}, Einhaengepunkt: {mount}")

    loop = GLib.MainLoop()
    window = Gtk.Window(default_width=1200, default_height=800)
    view = WebKit.WebView()
    window.set_child(view)
    window.present()

    checker = Checker(view, loop)
    build_steps(checker)

    def on_load(_view, event):
        if event == WebKit.LoadEvent.FINISHED:
            GLib.timeout_add(700, lambda: (checker.next(), False)[1])

    view.connect("load-changed", on_load)
    view.load_uri(f"http://127.0.0.1:{PORT}/")

    GLib.timeout_add(int(TIMEOUT * 1000), lambda: (loop.quit(), False)[1])
    loop.run()

    failed = [text for ok, text in checker.results if not ok]
    print()
    print(f"{len(checker.results) - len(failed)} von {len(checker.steps)} "
          f"Pruefungen bestanden")
    for text in failed:
        print(f"  fehlgeschlagen: {text}")
    return 0 if not failed and len(checker.results) == len(checker.steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
