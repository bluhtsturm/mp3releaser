"""Weboberfläche.

Wie die Desktop-Anwendung eine dünne Schicht über :mod:`releaser.uistate` -
nur dass zwischen Zustand und Anzeige hier ein Netz liegt. Das hat drei
Folgen, die im Code sichtbar sind:

**Der Zustand liegt auf dem Server.** Jede Sitzung hat dort ihren eigenen
``AppState``. Wer den Dienst betreibt, hat Zugriff darauf. Bei der lokalen
Fassung liegt derselbe Zustand im Arbeitsspeicher des eigenen Rechners.

**Die Dateiauswahl ist beschränkt.** Es gibt hier ausschließlich
:class:`~releaser.browse.MountedSource`. Sichtbar ist, was jemand vorher in
die Compose-Datei geschrieben hat - der Nutzer der Oberfläche entscheidet das
nicht. Ein Hochladen per Drag & Drop gibt es bewusst nicht: Browser können
die Originaldateien nicht umbenennen, es entstünde eine Kopie im Container
und ein ZIP zurück. Voller Funktionsumfang geht nur über eingehängte Ordner.

**Pfade bleiben virtuell.** Nach außen geht nie ein Pfad des Wirtsystems.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

try:
    # Auf Modulebene, nicht in der Funktion: wegen ``from __future__ import
    # annotations`` sind Typangaben Zeichenketten, und FastAPI loest sie
    # gegen die Modulebene auf. Lokale Importe waeren dort unsichtbar - die
    # Endpunkte wuerden dann Query-Parameter statt Response und Cookie sehen.
    from fastapi import Body, Cookie, FastAPI, HTTPException, Response
    from fastapi.responses import FileResponse, JSONResponse

    FASTAPI_AVAILABLE = True
except ImportError:                    # pragma: no cover - ohne FastAPI
    FASTAPI_AVAILABLE = False

from ...browse import AccessError, MountedSource, describe, from_environment
from ...naming import NamingProfile, format_plan as format_rename_plan
from ...runtime import as_dict as metrics_dict, collect as collect_metrics
from ...service import BuildOptions
from ...tagwriter import TagProfile, format_plan as format_tag_plan
from ...uistate import AppState

STATIC = Path(__file__).parent / "static"
COOKIE = "releaser_session"
#: Sitzungen werden verworfen, wenn sie lange nicht benutzt wurden.
SESSION_TTL = 3600.0
MAX_SESSIONS = 64


@dataclass
class Session:
    state: AppState
    touched: float = field(default_factory=time.monotonic)


class SessionStore:
    """Ein Zustand je Sitzung - auf dem Server, nicht beim Nutzer.

    Genau hier unterscheidet sich die Webfassung von den anderen beiden: was
    der Nutzer eingegeben hat, liegt im Arbeitsspeicher eines fremden
    Rechners, bis die Sitzung abläuft.
    """

    def __init__(self, source: MountedSource, naming: NamingProfile,
                 tags: TagProfile, ttl: float = SESSION_TTL,
                 limit: int = MAX_SESSIONS,
                 default_template: Optional[Path] = None,
                 build_options: Optional[BuildOptions] = None):
        self.source = source
        #: wird in jeder neuen Sitzung gleich geladen
        self.default_template = default_template
        self.naming = naming
        self.tags = tags
        #: Vorlage fuer die Erzeugungsoptionen; jede Sitzung bekommt eine
        #: eigene Kopie, weil das Laden einer Vorlage sie veraendert
        self.build_options = build_options or BuildOptions()
        self.ttl = ttl
        self.limit = limit
        self._sessions: dict[str, Session] = {}
        # FastAPI fuehrt synchrone Endpunkte in einem Thread-Pool aus. Ohne
        # Sperre konnten zwei gleichzeitige Anfragen das Sitzungsverzeichnis
        # waehrend des Aufraeumens veraendern ("dictionary changed size
        # during iteration").
        self._lock = threading.RLock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def _expire(self) -> None:
        now = time.monotonic()
        for key in [k for k, s in self._sessions.items()
                    if now - s.touched > self.ttl]:
            del self._sessions[key]
        while len(self._sessions) > self.limit:
            oldest = min(self._sessions, key=lambda k: self._sessions[k].touched)
            del self._sessions[oldest]

    def get(self, key: Optional[str]) -> tuple[str, AppState]:
        with self._lock:
            self._expire()
            if key and key in self._sessions:
                session = self._sessions[key]
                session.touched = time.monotonic()
                return key, session.state

            key = secrets.token_urlsafe(16)
            # Das Protokoll liegt einmal auf dem Server und gehoert allen
            # Sitzungen gemeinsam. Rueckgaengig darf jede aber nur das eigene.
            state = AppState(source=self.source,
                             naming=self.naming, tags=self.tags,
                             build_options=replace(self.build_options),
                             undo_scope="session")
            if self.default_template is not None:
                state.load_template(self.default_template)
                state.clear_messages()
            state.show_roots()
            self._sessions[key] = Session(state)
            self._expire()
            return key, state

    def drop(self, key: Optional[str]) -> bool:
        if not key:
            return False
        with self._lock:
            return self._sessions.pop(key, None) is not None


# ------------------------------------------------------------- Darstellung


def entry_json(entry) -> dict:
    return {
        "name": entry.name,
        "path": entry.path,
        "kind": entry.kind.value,
        "is_dir": entry.is_dir,
        "audio_files": entry.audio_files,
        "size": entry.size,
    }


def state_json(state: AppState) -> dict:
    """Alles, was die Oberfläche zum Zeichnen braucht."""
    groups = [
        {
            "title": title,
            "fields": [
                {
                    "name": view.spec.name,
                    "label": view.spec.label,
                    "value": view.value,
                    "width": view.width,
                    "origin": view.origin_label,
                    "hint": view.spec.hint,
                    "kind": view.spec.kind,
                    "overflows": view.overflows,
                }
                for view in views
            ],
        }
        for title, views in state.field_groups()
    ]
    preview = state.preview_names()
    return {
        "loaded": state.release is not None,
        "names": {
            "dir_pattern": state.naming.dir_pattern,
            "file_pattern": state.naming.file_pattern,
            "group": state.naming.group,
            "directory": preview["directory"],
            "files": preview["files"],
            # je Datei bearbeitbar - ohne Begrenzung, sonst liessen sich
            # die hinteren Dateien grosser Releases nicht umbenennen
            "rows": preview["rows"],
            "collisions": preview["collisions"],
            "companions": state.companion_preview(),
            "covers": [p.name for p in state.covers()],
        },
        "current_path": state.current_path,
        "selected_path": state.selected_path,
        "entries": [entry_json(e) for e in state.entries],
        "groups": groups,
        "overflows": state.overflows(),
        "status": state.status(),
        "messages": [{"level": m.level.value, "text": m.text}
                     for m in state.messages[-40:]],
        "enabled": {action.value: value
                    for action, value in state.enabled().items()},
        "template": state.template_path.name if state.template_path else None,
        "uncertain": state.origins.uncertain(),
    }


def create_app(source: Optional[MountedSource] = None,
               naming: Optional[NamingProfile] = None,
               tags: Optional[TagProfile] = None,
               templates_dir: Optional[Path] = None,
               build_options: Optional[BuildOptions] = None):
    """Baut die Anwendung. Ohne Quelle werden die eingehängten Ordner gelesen."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError(requirements_hint())

    from ...service import naming_from_config

    from ...service import STANDARD_TEMPLATE, bundled_template

    resolved = source if source is not None else from_environment()
    templates = Path(templates_dir) if templates_dir else None
    # Die Standardvorlage aus dem eingehaengten Vorlagenordner bevorzugen,
    # sonst die mitgelieferte - jede neue Sitzung hat damit gleich eine.
    preloaded = None
    if templates is not None and (templates / STANDARD_TEMPLATE).is_file():
        preloaded = templates / STANDARD_TEMPLATE
    elif templates is None:
        preloaded = bundled_template()
    store = SessionStore(resolved, naming or naming_from_config(),
                         tags or TagProfile(), default_template=preloaded,
                         build_options=build_options)

    app = FastAPI(title="mp3releaser", docs_url="/api/docs")
    app.state.store = store

    def session(response: Response, key: Optional[str]) -> AppState:
        key, state = store.get(key)
        response.set_cookie(COOKIE, key, httponly=True, samesite="strict")
        return state

    def answer(response: Response, state: AppState) -> JSONResponse:
        payload = state_json(state)
        # Meldungen sind gelesen, sobald sie ausgeliefert wurden - sonst
        # wiederholt die Oberflaeche sie bei jedem Abruf.
        state.clear_messages()
        return JSONResponse(payload, headers=dict(response.headers))

    # ----------------------------------------------------------- Auslieferung

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/info")
    def info():
        return {
            "mounts": describe(store.source),
            "sessions": len(store),
            "templates": ([p.name for p in sorted(templates.glob("*.skl"))]
                          if templates else []),
        }

    @app.get("/api/metrics")
    def metrics():
        return metrics_dict(collect_metrics())

    # --------------------------------------------------------------- Auswahl

    @app.get("/api/state")
    def read_state(response: Response,
                   releaser_session: Optional[str] = Cookie(default=None)):
        return answer(response, session(response, releaser_session))

    @app.post("/api/browse")
    def browse(response: Response, path: Optional[str] = Body(None, embed=True),
               releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        state.navigate(path)
        return answer(response, state)

    @app.post("/api/select")
    def select(response: Response, path: Optional[str] = Body(None, embed=True),
               releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        state.select(path)
        return answer(response, state)

    @app.post("/api/load")
    def load(response: Response, path: str = Body(..., embed=True),
             releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        state.load(path)
        return answer(response, state)

    @app.post("/api/template")
    def template(response: Response, name: str = Body(..., embed=True),
                 releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        if templates is None:
            raise HTTPException(404, "keine Vorlagen eingehängt")
        # Nur Dateinamen, keine Pfade - sonst waere das ein Weg nach draussen.
        if ("/" in name or "\\" in name or "\x00" in name
                or name.startswith(".")):
            raise HTTPException(400, "unzulässiger Vorlagenname")
        candidate = templates / name
        if not candidate.is_file():
            raise HTTPException(404, f"Vorlage nicht gefunden: {name}")
        state.load_template(candidate)
        return answer(response, state)

    @app.get("/api/nfo")
    def nfo_preview(response: Response,
                    releaser_session: Optional[str] = Cookie(default=None)):
        """Die fertige .nfo als Vorschau.

        Eigener Endpunkt statt im Zustand: die Datei ist mehrere Kilobyte
        gross und wird nicht bei jedem Klick gebraucht.
        """
        from ...nfoview import WEB_CELL, shapes_for

        state = session(response, releaser_session)
        lines, width = state.nfo_dimensions()
        text = state.nfo_preview()
        return JSONResponse({
            "text": text,
            # Block- und Rahmenzeichen als Flaechen fuer das Raster der Seite -
            # dieselbe Geometrie wie im Desktop, siehe releaser.nfoview
            "cell": list(WEB_CELL),
            "shapes": shapes_for(text, *WEB_CELL),
            "lines": lines,
            "width": width,
            "template": state.template_path.name if state.template_path else None,
            "overflows": state.overflows(),
            "truncated_tracks": state.truncated_tracks(),
        }, headers=dict(response.headers))

    @app.get("/api/check")
    def check(response: Response, what: str = "release",
              releaser_session: Optional[str] = Cookie(default=None)):
        """Prueft Vorlage oder Release - dieselben Pruefungen wie im Desktop."""
        state = session(response, releaser_session)
        report = (state.check_template() if what == "template"
                  else state.check_release())
        if report is None:
            return JSONResponse({"ok": False, "text": "",
                                 "messages": [{"level": m.level.value,
                                               "text": m.text}
                                              for m in state.messages[-5:]]},
                                headers=dict(response.headers))
        state.clear_messages()
        return JSONResponse({
            "ok": report.ok,
            "summary": report.summary(),
            "text": report.render(),
            "issues": [{"level": i.level.value, "message": i.message,
                        "subject": i.subject} for i in report.issues],
        }, headers=dict(response.headers))

    @app.get("/api/undo")
    def undo_list(response: Response,
                  releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        return JSONResponse(
            {"entries": [{"when": e.when, "release": e.release,
                          "count": e.count, "kind": e.kind.value,
                          "label": e.kind.label}
                         for e in state.undo_entries()]},
            headers=dict(response.headers))

    @app.post("/api/undo")
    def undo_apply(response: Response, force: bool = Body(False, embed=True),
                   releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        state.undo_last(force=force)
        return answer(response, state)

    @app.post("/api/pattern")
    def set_pattern(response: Response, which: str = Body(...),
                    value: str = Body(""),
                    releaser_session: Optional[str] = Cookie(default=None)):
        """Namensmuster ändern - dieselbe Logik wie im Desktop-Reiter „Namen“."""
        state = session(response, releaser_session)
        if which == "dirname":
            state.set_literal_dirname(value)
        else:
            state.set_pattern(which, value)
        return answer(response, state)

    @app.post("/api/filename")
    def set_filename(response: Response, index: int = Body(...),
                     value: str = Body(""),
                     releaser_session: Optional[str] = Cookie(default=None)):
        """Dateiname von Hand - leerer Wert heisst: wieder aus dem Muster."""
        state = session(response, releaser_session)
        state.set_file_name(index, value)
        return answer(response, state)

    # ----------------------------------------------------------------- Felder

    @app.post("/api/field")
    def set_field(response: Response, name: str = Body(...),
                  value: str = Body(""),
                  releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        state.set_field(name, value)
        return answer(response, state)

    # ------------------------------------------------------------------ Pläne

    @app.post("/api/plan/tags")
    def plan_tags_(response: Response,
                   releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        plan = state.preview_tags()
        payload = state_json(state)
        payload["plan"] = {
            "kind": "tags",
            "changes": len(plan.changes) if plan else 0,
            "safe": True,
            "text": format_tag_plan(plan, state.root) if plan else "",
        }
        state.clear_messages()
        return JSONResponse(payload, headers=dict(response.headers))

    @app.post("/api/plan/rename")
    def plan_rename_(response: Response,
                     releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        plan = state.preview_rename()
        payload = state_json(state)
        payload["plan"] = {
            "kind": "rename",
            "changes": len(plan.changes) if plan else 0,
            "safe": bool(plan and plan.is_safe),
            "text": (format_rename_plan(plan, state.root)
                     if plan and state.root else ""),
        }
        state.clear_messages()
        return JSONResponse(payload, headers=dict(response.headers))

    @app.post("/api/apply/tags")
    def apply_tags_(response: Response,
                    releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        state.apply_tags()
        return answer(response, state)

    @app.post("/api/apply/rename")
    def apply_rename_(response: Response,
                      releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        state.apply_rename()
        return answer(response, state)

    @app.post("/api/build")
    def build(response: Response,
              releaser_session: Optional[str] = Cookie(default=None)):
        state = session(response, releaser_session)
        created = state.build()
        payload = state_json(state)
        payload["created"] = [p.name for p in created]
        state.clear_messages()
        return JSONResponse(payload, headers=dict(response.headers))

    @app.post("/api/produce")
    def produce(response: Response,
                releaser_session: Optional[str] = Cookie(default=None)):
        """Das fertige Release in einem Schritt - siehe AppState.produce."""
        state = session(response, releaser_session)
        done = state.produce()
        payload = state_json(state)
        payload["done"] = done
        state.clear_messages()
        return JSONResponse(payload, headers=dict(response.headers))

    @app.post("/api/session/end")
    def end_session(response: Response,
                    releaser_session: Optional[str] = Cookie(default=None)):
        dropped = store.drop(releaser_session)
        response.delete_cookie(COOKIE)
        return {"dropped": dropped}

    @app.exception_handler(AccessError)
    def access_denied(_request, exc: AccessError):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    return app


def run(host: str = "0.0.0.0", port: int = 8000,
        source: Optional[MountedSource] = None,
        naming: Optional[NamingProfile] = None,
        tags: Optional[TagProfile] = None,
        templates_dir: Optional[Path] = None,
        build_options: Optional[BuildOptions] = None) -> int:
    import uvicorn

    uvicorn.run(create_app(source, naming, tags, templates_dir, build_options),
                host=host, port=port, log_level="info")
    return 0


def is_available() -> bool:
    if not FASTAPI_AVAILABLE:
        return False
    try:
        import uvicorn

        return uvicorn is not None
    except ImportError:
        return False


def requirements_hint() -> str:
    return (
        "Die Weboberfläche braucht FastAPI und uvicorn:\n"
        "    pip install 'mp3releaser[web]'\n"
        "Im Container sind beide bereits enthalten."
    )
