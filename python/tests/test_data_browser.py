"""Unit tests for the Data page helpers (``PiFinder.data_browser``).

The helpers take user supplied relative paths and must never escape the data
root; these tests lock in the traversal guards and the basic list / mkdir /
upload / delete / zip behaviour on a temporary directory.
"""

import io
import zipfile

import pytest

from PiFinder import data_browser
from PiFinder import server as server_module
from PiFinder.data_browser import DataPathError


@pytest.fixture
def root(tmp_path):
    (tmp_path / "obslists").mkdir()
    (tmp_path / "obslists" / "messier.txt").write_text("M1\nM2\n")
    (tmp_path / "captures").mkdir()
    (tmp_path / "captures" / "sweep_20260101_010203").mkdir()
    (tmp_path / "captures" / "sweep_20260101_010203" / "sweep.json").write_text("{}")
    (tmp_path / "captures" / "0001.png").write_bytes(b"\x89PNG")
    (tmp_path / "observations.db").write_bytes(b"sqlite")
    return tmp_path


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["..", "../x", "obslists/../../etc"])
def test_resolve_rejects_paths_outside_root(root, bad):
    with pytest.raises(DataPathError):
        data_browser.resolve(root, bad)


@pytest.mark.unit
def test_resolve_treats_absolute_paths_as_root_relative(root):
    # a leading slash means "from the data root", never the filesystem root
    assert data_browser.resolve(root, "/etc/passwd") == (root / "etc/passwd").resolve()


@pytest.mark.unit
def test_resolve_rejects_symlink_pointing_out(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (root / "escape").symlink_to(outside)
    with pytest.raises(DataPathError):
        data_browser.resolve(root, "escape")


@pytest.mark.unit
def test_resolve_accepts_root_and_children(root):
    assert data_browser.resolve(root, "") == root.resolve()
    assert data_browser.resolve(root, "/obslists/") == (root / "obslists").resolve()


@pytest.mark.unit
def test_list_dir_root_sorts_folders_first(root):
    listing = data_browser.list_dir(root, "")
    names = [e["name"] for e in listing["entries"]]
    assert names == ["captures", "obslists", "observations.db"]
    assert listing["path"] == ""
    assert listing["parent"] is None
    assert listing["breadcrumbs"] == []
    db = listing["entries"][2]
    assert db["is_dir"] is False
    assert db["size"] == 6
    assert db["path"] == "observations.db"


@pytest.mark.unit
def test_list_dir_subfolder_has_breadcrumbs_and_parent(root):
    listing = data_browser.list_dir(root, "captures/sweep_20260101_010203")
    assert listing["parent"] == "captures"
    assert listing["breadcrumbs"] == [
        {"name": "captures", "path": "captures"},
        {"name": "sweep_20260101_010203", "path": "captures/sweep_20260101_010203"},
    ]
    assert [e["name"] for e in listing["entries"]] == ["sweep.json"]


@pytest.mark.unit
def test_list_dir_pattern_filters_entries(root):
    listing = data_browser.list_dir(root, "captures", "sweep_*")
    assert [e["name"] for e in listing["entries"]] == ["sweep_20260101_010203"]
    assert listing["pattern"] == "sweep_*"


@pytest.mark.unit
def test_list_dir_missing_folder_raises(root):
    with pytest.raises(DataPathError):
        data_browser.list_dir(root, "nope")
    with pytest.raises(DataPathError):
        data_browser.list_dir(root, "observations.db")


@pytest.mark.unit
def test_shortcuts_only_existing_folders(root):
    labels = [s["label"] for s in data_browser.shortcuts(root)]
    assert labels == ["Observing lists", "Captures", "SQM sweeps"]
    sweeps = next(s for s in data_browser.shortcuts(root) if s["label"] == "SQM sweeps")
    assert sweeps["path"] == "captures"
    assert sweeps["pattern"] == "sweep_*"


@pytest.mark.unit
def test_make_dir(root):
    assert data_browser.make_dir(root, "obslists", "new") == "obslists/new"
    assert (root / "obslists" / "new").is_dir()
    with pytest.raises(DataPathError):
        data_browser.make_dir(root, "obslists", "new")
    with pytest.raises(DataPathError):
        data_browser.make_dir(root, "obslists", "..")
    # a name with separators is reduced to its last component
    assert data_browser.make_dir(root, "", "a/b") == "b"


@pytest.mark.unit
def test_save_upload_writes_file_and_strips_dirs(root):
    rel = data_browser.save_upload(root, "obslists", "../../evil.txt", io.BytesIO(b"x"))
    assert rel == "obslists/evil.txt"
    assert (root / "obslists" / "evil.txt").read_bytes() == b"x"
    with pytest.raises(DataPathError):
        data_browser.save_upload(root, "missing", "a.txt", io.BytesIO(b"x"))
    with pytest.raises(DataPathError):
        data_browser.save_upload(root, "", "obslists", io.BytesIO(b"x"))


@pytest.mark.unit
def test_delete_file_and_folder(root):
    data_browser.delete(root, "observations.db")
    assert not (root / "observations.db").exists()
    data_browser.delete(root, "captures")
    assert not (root / "captures").exists()
    with pytest.raises(DataPathError):
        data_browser.delete(root, "captures")


@pytest.mark.unit
def test_delete_refuses_root(root):
    with pytest.raises(DataPathError):
        data_browser.delete(root, "")
    with pytest.raises(DataPathError):
        data_browser.delete(root, "..")
    assert root.exists()


@pytest.mark.unit
def test_delete_symlink_does_not_follow(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "keep.txt").write_text("keep")
    (root / "obslists" / "link").symlink_to(outside)
    # the link resolves outside the root, so it is refused; the target survives
    with pytest.raises(DataPathError):
        data_browser.delete(root, "obslists/link")
    assert (outside / "keep.txt").exists()


@pytest.mark.unit
def test_zip_dir_contains_relative_paths(root):
    fh, name = data_browser.zip_dir(root, "captures")
    assert name == "captures.zip"
    with zipfile.ZipFile(fh) as zf:
        assert sorted(zf.namelist()) == [
            "0001.png",
            "sweep_20260101_010203/sweep.json",
        ]
    fh.close()
    fh, name = data_browser.zip_dir(root, "")
    assert name == "PiFinder_data.zip"
    fh.close()


@pytest.mark.unit
def test_read_text_and_truncation(root):
    r = data_browser.read_text(root, "obslists/messier.txt")
    assert r == {"text": "M1\nM2\n", "size": 6, "truncated": False}
    r = data_browser.read_text(root, "obslists/messier.txt", limit=3)
    assert r["text"] == "M1\n" and r["truncated"] is True
    # binary content is decoded with replacement, never raises
    assert "\ufffd" in data_browser.read_text(root, "captures/0001.png")["text"]
    with pytest.raises(DataPathError):
        data_browser.read_text(root, "obslists")


@pytest.mark.unit
def test_list_dir_marks_text_files(root):
    listing = data_browser.list_dir(root, "")
    by_name = {e["name"]: e for e in listing["entries"]}
    assert by_name["observations.db"]["is_text"] is False
    assert by_name["obslists"]["is_text"] is False
    assert data_browser.list_dir(root, "obslists")["entries"][0]["is_text"] is True


@pytest.mark.unit
def test_file_for_download(root):
    assert data_browser.file_for_download(root, "obslists/messier.txt").is_file()
    with pytest.raises(DataPathError):
        data_browser.file_for_download(root, "obslists")


# --- HTTP routes -----------------------------------------------------------


@pytest.fixture
def client(monkeypatch, root):
    monkeypatch.setattr(server_module.data_browser, "data_root", lambda: root)
    srv = server_module.Server()
    c = srv.app.test_client()
    with c.session_transaction() as sess:
        sess["authenticated"] = True
    return c


@pytest.mark.unit
def test_route_list_and_shortcuts(client):
    r = client.get("/data/api/list?path=captures&pattern=sweep_*")
    d = r.get_json()
    assert d["status"] == "ok"
    assert [e["name"] for e in d["entries"]] == ["sweep_20260101_010203"]
    assert [s["label"] for s in d["shortcuts"]][0] == "Observing lists"
    assert client.get("/data/api/list?path=../etc").status_code == 404


@pytest.mark.unit
def test_route_mkdir_upload_delete(client, root):
    r = client.post("/data/api/mkdir", json={"path": "obslists", "name": "trip"})
    assert r.get_json() == {"status": "ok", "path": "obslists/trip"}

    r = client.post(
        "/data/api/upload",
        data={
            "path": "obslists/trip",
            "files": [(io.BytesIO(b"M13\n"), "globs.txt"), (io.BytesIO(b"x"), "b")],
        },
        content_type="multipart/form-data",
    )
    assert r.get_json()["saved"] == ["obslists/trip/globs.txt", "obslists/trip/b"]
    assert (root / "obslists/trip/globs.txt").read_bytes() == b"M13\n"

    r = client.post("/data/api/delete", json={"paths": ["obslists/trip/b"]})
    assert r.get_json()["deleted"] == ["obslists/trip/b"]
    r = client.post("/data/api/delete", json={"path": "obslists/trip"})
    assert r.get_json()["status"] == "ok"
    assert not (root / "obslists/trip").exists()

    r = client.post("/data/api/delete", json={"path": ""})
    assert r.status_code == 400
    assert root.exists()


@pytest.mark.unit
def test_route_download_file_and_folder(client):
    r = client.get("/data/download?path=obslists/messier.txt")
    assert r.status_code == 200
    assert r.data == b"M1\nM2\n"
    assert "attachment" in r.headers["Content-Disposition"]

    r = client.get("/data/download?path=captures")
    assert r.status_code == 200
    assert r.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.data)) as zf:
        assert "sweep_20260101_010203/sweep.json" in zf.namelist()

    assert client.get("/data/download?path=nope").status_code == 404


@pytest.mark.unit
def test_route_view_text(client):
    d = client.get("/data/api/view?path=obslists/messier.txt").get_json()
    assert d["status"] == "ok" and d["text"] == "M1\nM2\n"
    assert client.get("/data/api/view?path=obslists").status_code == 404


@pytest.mark.unit
def test_route_page_requires_auth(root, monkeypatch):
    monkeypatch.setattr(server_module.data_browser, "data_root", lambda: root)
    c = server_module.Server().app.test_client()
    assert c.get("/data").status_code == 302
    assert c.get("/data/api/list").status_code == 302
