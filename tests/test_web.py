"""Tests der Weboberfläche.

Geprüft wird über den HTTP-Weg, nicht an der Dienstschicht vorbei - genau der
Weg, den ein Browser nimmt. Schwerpunkt neben dem Ablauf: dass die Fassung
wirklich nur die eingehängten Ordner zeigt und keine Wirtspfade herausgibt.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from releaser.browse import Mount, MountedSource
from releaser.naming import NamingProfile
from releaser.tagwriter import TagProfile

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from releaser.frontends.web.app import SessionStore, create_app, state_json  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht vorhanden")


def encode(target: Path, *args: str) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    *args, str(target), "-y"], check=True)
    return target


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Ein eingehängter Ordner - und einer daneben, der es nicht ist."""
    release = tmp_path / "eingang" / "Artist-Album-2026-GRP"
    for no in (1, 2):
        encode(release / f"0{no}-x.mp3", "-c:a", "libmp3lame",
               "-metadata", f"title=Titel {no}", "-metadata", "artist=Der Artist",
               "-metadata", "album=Das Album", "-metadata", f"track={no}/2",
               "-metadata", "date=2026", "-metadata", "genre=Electronic")
    (tmp_path / "geheim").mkdir()
    (tmp_path / "geheim" / "passwoerter.txt").write_text("geheim")

    templates = tmp_path / "vorlagen"
    templates.mkdir()
    (templates / "vorlage.skl").write_bytes(
        ("|#Release            |\n|#Artist             |\n"
         "|#Album              |\n|#N #Trk             |\n").encode("cp437"))
    return tmp_path


@pytest.fixture
def client(tree: Path) -> TestClient:
    from releaser.service import naming_from_config

    app = create_app(
        MountedSource([Mount("eingang", tree / "eingang")]),
        # dieselbe Voreinstellung wie beim echten Start
        naming=naming_from_config(group="GRP"),
        tags=TagProfile(),
        templates_dir=tree / "vorlagen",
    )
    return TestClient(app)


def load_release(client: TestClient) -> dict:
    client.post("/api/browse", json={"path": "eingang"})
    return client.post("/api/load",
                       json={"path": "eingang/Artist-Album-2026-GRP"}).json()


# ================================================================== Auskunft


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "mp3releaser" in response.text


def test_info_names_the_scope(client):
    info = client.get("/api/info").json()
    assert info["mounts"]["scope"] == "nur was eingehängt wurde"
    assert [m["name"] for m in info["mounts"]["mounts"]] == ["eingang"]
    assert info["templates"] == ["vorlage.skl"]


def test_metrics_are_reachable_over_http(client):
    payload = client.get("/api/metrics").json()
    assert "variant" in payload and "total_bytes" in payload


# ================================================================== Auswahl


@needs_ffmpeg
def test_roots_show_only_the_mounts(client):
    state = client.get("/api/state").json()
    assert [e["name"] for e in state["entries"]] == ["eingang"]


@needs_ffmpeg
def test_browsing_returns_virtual_paths_only(client):
    state = client.post("/api/browse", json={"path": "eingang"}).json()
    paths = [e["path"] for e in state["entries"]]
    assert paths == ["eingang/Artist-Album-2026-GRP"]
    assert not any(p.startswith("/") for p in paths)


@needs_ffmpeg
def test_serialised_state_contains_no_host_paths(client, tree):
    state = load_release(client)
    text = str(state)
    assert str(tree) not in text
    assert "/tmp/" not in text.replace("/tmp/", "", 0) or str(tree) not in text


@pytest.mark.parametrize("attempt", [
    "eingang/../geheim", "../geheim", "/etc/passwd", "geheim",
])
def test_paths_outside_the_mount_are_refused(client, attempt):
    response = client.post("/api/browse", json={"path": attempt})
    state = response.json()
    assert state["entries"] == [] or state["current_path"] != attempt
    assert any(m["level"] == "error" for m in state["messages"])


def test_loading_outside_the_mount_is_refused(client):
    state = client.post("/api/load", json={"path": "../geheim"}).json()
    assert state["loaded"] is False
    assert any(m["level"] == "error" for m in state["messages"])


# ==================================================================== Ablauf


@needs_ffmpeg
def test_load_delivers_fields_with_width_and_origin(client):
    client.post("/api/template", json={"name": "vorlage.skl"})
    state = load_release(client)

    assert state["loaded"] is True
    fields = {f["name"]: f for group in state["groups"] for f in group["fields"]}
    assert fields["artist"]["value"] == "Der Artist"
    assert fields["artist"]["origin"] == "aus den Tags"
    assert fields["artist"]["width"] is not None
    assert [g["title"] for g in state["groups"]][-1] == "nicht verwendet"


@needs_ffmpeg
def test_editing_a_field_reaches_the_model(client):
    load_release(client)
    state = client.post("/api/field",
                        json={"name": "artist", "value": "Von Hand"}).json()
    fields = {f["name"]: f for group in state["groups"] for f in group["fields"]}
    assert fields["artist"]["value"] == "Von Hand"
    assert fields["artist"]["origin"] == "von Hand"


@needs_ffmpeg
def test_invalid_number_is_reported_not_stored(client):
    load_release(client)
    state = client.post("/api/field",
                        json={"name": "year", "value": "zweitausend"}).json()
    fields = {f["name"]: f for group in state["groups"] for f in group["fields"]}
    assert fields["year"]["value"] == "2026"
    assert any(m["level"] == "error" for m in state["messages"])


@needs_ffmpeg
def test_rename_needs_a_preview_before_it_may_run(client, tree):
    load_release(client)
    state = client.get("/api/state").json()
    assert state["enabled"]["apply_rename"] is False

    plan = client.post("/api/plan/rename", json={}).json()
    assert plan["plan"]["changes"] > 0 and plan["plan"]["safe"] is True
    assert plan["enabled"]["apply_rename"] is True
    assert (tree / "eingang" / "Artist-Album-2026-GRP").is_dir()   # noch nichts

    after = client.post("/api/apply/rename", json={}).json()
    # Voreinstellung: Ordner kapitalisiert
    assert after["current_path"] == "eingang/Der_Artist-Das_Album-2026-GRP"
    assert (tree / "eingang" / "Der_Artist-Das_Album-2026-GRP").is_dir()


@needs_ffmpeg
def test_tag_plan_and_apply(client):
    load_release(client)
    client.post("/api/field", json={"name": "genre", "value": "drum and bass"})

    plan = client.post("/api/plan/tags", json={}).json()
    assert plan["plan"]["changes"] > 0
    assert "genre" in plan["plan"]["text"]

    after = client.post("/api/apply/tags", json={}).json()
    assert after["enabled"]["apply_tags"] is False


@needs_ffmpeg
def test_build_needs_a_template(client):
    load_release(client)
    state = client.post("/api/build", json={}).json()
    assert state["created"] == []
    assert any(m["level"] == "error" for m in state["messages"])


@needs_ffmpeg
def test_build_creates_the_files(client, tree):
    client.post("/api/template", json={"name": "vorlage.skl"})
    load_release(client)

    state = client.post("/api/build", json={}).json()
    assert sorted(Path(n).suffix for n in state["created"]) == [
        ".m3u", ".nfo", ".sfv"]
    release = tree / "eingang" / "Artist-Album-2026-GRP"
    assert (release / "00-artist-album-2026-grp.sfv").is_file()


# ================================================================= Vorlagen


def test_template_names_may_not_contain_paths(client):
    for attempt in ("../geheim.skl", "/etc/passwd", ".versteckt"):
        response = client.post("/api/template", json={"name": attempt})
        assert response.status_code in (400, 404), attempt


def test_unknown_template_is_reported(client):
    assert client.post("/api/template",
                       json={"name": "gibtsnicht.skl"}).status_code == 404


# ================================================================ Sitzungen


@needs_ffmpeg
def test_two_clients_do_not_share_their_state(tree):
    app = create_app(MountedSource([Mount("eingang", tree / "eingang")]))
    first, second = TestClient(app), TestClient(app)

    load_release(first)
    first.post("/api/field", json={"name": "artist", "value": "Nur bei mir"})

    assert second.get("/api/state").json()["loaded"] is False
    assert app.state.store.__len__() == 2


def test_session_can_be_ended(client):
    client.get("/api/state")
    assert client.post("/api/session/end", json={}).json()["dropped"] is True


def test_sessions_expire(tree):
    store = SessionStore(MountedSource([Mount("eingang", tree / "eingang")]),
                         NamingProfile(), TagProfile(), ttl=0.0)
    key, _state = store.get(None)
    assert store.get(key)[0] != key          # abgelaufen, neue Sitzung


def test_session_count_is_capped(tree):
    store = SessionStore(MountedSource([Mount("eingang", tree / "eingang")]),
                         NamingProfile(), TagProfile(), limit=3)
    for _ in range(10):
        store.get(None)
    assert len(store) <= 3


# ============================================================== Meldungen


@needs_ffmpeg
def test_messages_are_delivered_once(client):
    load_release(client)
    first = client.get("/api/state").json()
    second = client.get("/api/state").json()
    assert second["messages"] == []
    assert isinstance(first["messages"], list)


def test_state_json_has_everything_the_page_draws(tree):
    from releaser.uistate import AppState

    state = AppState(source=MountedSource([Mount("eingang", tree / "eingang")]))
    state.show_roots()
    payload = state_json(state)
    for key in ("loaded", "entries", "groups", "status", "messages",
                "enabled", "overflows", "uncertain"):
        assert key in payload, key


# =================================================== Namen über die API


@needs_ffmpeg
def test_state_carries_the_name_preview(client):
    state = load_release(client)
    names = state["names"]

    assert names["directory"][0] == "Artist-Album-2026-GRP"
    assert names["directory"][1].startswith("Der_Artist")      # kapitalisiert
    assert len(names["files"]) == 2
    assert all(new.islower() for _old, new in names["files"])
    assert all(name.startswith("00-") for name in names["companions"])


@needs_ffmpeg
def test_patterns_can_be_changed_over_http(client):
    load_release(client)
    state = client.post("/api/pattern",
                        json={"which": "file", "value": "#N-#Trk"}).json()
    assert state["names"]["file_pattern"] == "#N-#Trk"
    assert state["names"]["files"][0][1].startswith("01-titel")


@needs_ffmpeg
def test_directory_name_can_be_set_by_hand_over_http(client):
    load_release(client)
    state = client.post("/api/pattern",
                        json={"which": "dirname", "value": "Eigener Name"}).json()
    assert state["names"]["directory"][1] == "Eigener_Name"


@needs_ffmpeg
def test_a_hash_in_a_manual_name_is_refused_over_http(client):
    load_release(client)
    state = client.post("/api/pattern",
                        json={"which": "dirname", "value": "Mit #Artist"}).json()
    assert any(m["level"] == "error" for m in state["messages"])


@needs_ffmpeg
def test_format_marker_appears_in_the_preview(client, tree):
    """FLAC-Release bekommt -flac- vor dem Jahr, MP3 nichts."""
    flac = tree / "eingang" / "Flac-Album-2026-GRP"
    encode(flac / "01-x.flac", "-c:a", "flac",
           "-metadata", "title=Titel", "-metadata", "artist=Der Artist",
           "-metadata", "album=Das Album", "-metadata", "DATE=2026")

    client.post("/api/browse", json={"path": "eingang"})
    state = client.post("/api/load",
                        json={"path": "eingang/Flac-Album-2026-GRP"}).json()
    assert "flac" in state["names"]["directory"][1].lower()

    mp3 = load_release(client)
    assert "-flac-" not in mp3["names"]["directory"][1].lower()


def test_unknown_pattern_over_http_is_reported(client):
    state = client.post("/api/pattern",
                        json={"which": "gibtsnicht", "value": "x"}).json()
    assert any(m["level"] == "error" for m in state["messages"])


@needs_ffmpeg
def test_overlong_path_becomes_a_message_not_a_server_error(client):
    """Ein unbehandelter Systemfehler waere im Betrieb ein 500 mit Traceback."""
    response = client.post("/api/browse",
                           json={"path": "eingang/" + "a" * 5000})
    assert response.status_code == 200
    assert any(m["level"] == "error" and "zu lang" in m["text"]
               for m in response.json()["messages"])


# ================================================== NFO-Vorschau


@needs_ffmpeg
def test_nfo_preview_over_http(client):
    client.post("/api/template", json={"name": "vorlage.skl"})
    load_release(client)

    data = client.get("/api/nfo").json()
    assert "Der Artist" in data["text"]
    assert data["lines"] > 1
    assert data["template"] == "vorlage.skl"
    assert data["overflows"] == []


@needs_ffmpeg
def test_nfo_preview_follows_an_edit(client):
    client.post("/api/template", json={"name": "vorlage.skl"})
    load_release(client)
    client.post("/api/field", json={"name": "artist", "value": "Ganz Anders"})

    assert "Ganz Anders" in client.get("/api/nfo").json()["text"]


def test_nfo_preview_without_a_template_explains_itself(client):
    data = client.get("/api/nfo").json()
    assert "Keine Vorlage" in data["text"]
    assert data["template"] is None


@needs_ffmpeg
def test_nfo_preview_reports_overflow(client, tree):
    narrow = tree / "vorlagen" / "eng.skl"
    narrow.write_bytes("|#Artist   |\n".encode("cp437"))

    client.post("/api/template", json={"name": "eng.skl"})
    load_release(client)
    client.post("/api/field",
                json={"name": "artist", "value": "Ein viel zu langer Name"})

    assert client.get("/api/nfo").json()["overflows"]


# ======================================== Prüfen und Rückgängig über HTTP


@needs_ffmpeg
def test_check_release_over_http(client):
    load_release(client)
    data = client.get("/api/check?what=release").json()

    assert data["ok"] is True
    assert "Artist-Album-2026-GRP" in data["text"]
    assert any("vorhanden" in i["message"] for i in data["issues"])


def test_check_template_over_http(client):
    client.post("/api/template", json={"name": "vorlage.skl"})
    data = client.get("/api/check?what=template").json()

    assert "vorlage.skl" in data["text"]
    assert isinstance(data["issues"], list)


def test_check_without_anything_loaded_reports_back(client):
    data = client.get("/api/check?what=template").json()
    assert data["text"] == ""
    assert any("Vorlage" in m["text"] for m in data["messages"])


def test_undo_list_is_empty_without_a_journal(client, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert client.get("/api/undo").json()["entries"] == []


@needs_ffmpeg
def test_undo_over_http(client, tree, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    load_release(client)
    client.post("/api/plan/rename", json={})
    client.post("/api/apply/rename", json={})

    renamed = tree / "eingang" / "Der_Artist-Das_Album-2026-GRP"
    assert renamed.is_dir()

    entries = client.get("/api/undo").json()["entries"]
    assert len(entries) == 1

    state = client.post("/api/undo", json={"force": False}).json()
    assert (tree / "eingang" / "Artist-Album-2026-GRP").is_dir()
    assert not renamed.exists()
    assert state["loaded"] is False          # Pfad zeigt ins Leere


# ============================= Rückgängig gehört der eigenen Sitzung


@needs_ffmpeg
def test_one_user_cannot_undo_another_users_rename(tree):
    """Das Protokoll liegt einmal auf dem Server - Rückgängig nur für das Eigene."""
    from releaser.service import naming_from_config

    app = create_app(MountedSource([Mount("eingang", tree / "eingang")]),
                     naming=naming_from_config(group="GRP"))
    anna, bernd = TestClient(app), TestClient(app)

    load_release(anna)
    anna.post("/api/plan/rename", json={})
    anna.post("/api/apply/rename", json={})
    renamed = tree / "eingang" / "Der_Artist-Das_Album-2026-GRP"
    assert renamed.is_dir()

    # Bernd sieht Annas Lauf nicht ...
    assert bernd.get("/api/undo").json()["entries"] == []
    # ... und kann ihn nicht zurücknehmen
    state = bernd.post("/api/undo", json={"force": False}).json()
    assert any("Nichts" in m["text"] for m in state["messages"])
    assert renamed.is_dir()

    # Anna kann es
    assert len(anna.get("/api/undo").json()["entries"]) == 1
    anna.post("/api/undo", json={"force": False})
    assert (tree / "eingang" / "Artist-Album-2026-GRP").is_dir()


@needs_ffmpeg
def test_one_user_cannot_see_another_users_tag_run(tree):
    from releaser.service import naming_from_config

    app = create_app(MountedSource([Mount("eingang", tree / "eingang")]),
                     naming=naming_from_config(group="GRP"))
    anna, bernd = TestClient(app), TestClient(app)

    load_release(anna)
    anna.post("/api/field", json={"name": "artist", "value": "Von Anna"})
    anna.post("/api/plan/tags", json={})
    anna.post("/api/apply/tags", json={})

    assert len(anna.get("/api/undo").json()["entries"]) == 1
    assert bernd.get("/api/undo").json()["entries"] == []


@needs_ffmpeg
def test_readonly_mount_is_respected_over_http(tree):
    """`:ro` in RELEASER_MOUNTS muss die Oberfläche selbst beachten."""
    app = create_app(MountedSource([Mount("archiv", tree / "eingang",
                                          writable=False)]))
    client = TestClient(app)
    client.post("/api/browse", json={"path": "archiv"})
    client.post("/api/load", json={"path": "archiv/Artist-Album-2026-GRP"})

    plan = client.post("/api/plan/rename", json={}).json()
    assert plan["plan"]["changes"] > 0                 # Vorschau geht
    assert plan["enabled"]["apply_rename"] is False    # Ausführen nicht

    client.post("/api/apply/rename", json={})
    assert (tree / "eingang" / "Artist-Album-2026-GRP").is_dir()
    assert "nur lesend" in client.get("/api/state").json()["status"]
