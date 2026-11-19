"""The /api/* control and camera endpoints need the Web UI login session.

Read-only status endpoints stay open for automation tools.
"""

import queue

import pytest
from flask import Flask

from PiFinder.api_extensions import register_api_routes


class _FakeSharedState:
    def screen(self):
        return None

    def cam_raw(self):
        return None


class _FakeServer:
    def __init__(self):
        self.shared_state = _FakeSharedState()
        self.keyboard_queue = queue.Queue()
        self.button_dict = {"UP": 1}


@pytest.fixture
def client_and_server():
    app = Flask(__name__)
    app.secret_key = "test"
    server = _FakeServer()
    register_api_routes(app, server, require_auth=False)
    return app.test_client(), server


def _log_in(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True


@pytest.mark.unit
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/key"),
        ("post", "/api/stop"),
        ("get", "/api/camera/raw"),
        ("get", "/api/camera/debug"),
    ],
)
def test_protected_endpoints_refuse_without_login(client_and_server, method, path):
    client, server = client_and_server
    resp = getattr(client, method)(path, json={"button": "UP"})
    assert resp.status_code == 401
    assert server.keyboard_queue.empty()


@pytest.mark.unit
def test_key_works_with_login(client_and_server):
    client, server = client_and_server
    _log_in(client)
    resp = client.post("/api/key", json={"button": "UP"})
    assert resp.status_code == 200
    assert server.keyboard_queue.get_nowait() == 1


@pytest.mark.unit
def test_screen_stays_open(client_and_server):
    client, _ = client_and_server
    resp = client.get("/api/screen")
    assert resp.status_code == 200
