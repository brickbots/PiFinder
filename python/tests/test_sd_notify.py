import socket

import pytest

from PiFinder.utils import sd_notify


@pytest.mark.unit
class TestSdNotify:
    def test_noop_without_notify_socket(self, monkeypatch):
        # Development runs / tests: no systemd, no socket — must be silent.
        monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
        sd_notify("READY=1")  # must not raise

    def test_sends_state_to_socket(self, monkeypatch, tmp_path):
        sock_path = str(tmp_path / "notify.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        server.bind(sock_path)
        server.settimeout(2)
        try:
            monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
            sd_notify("READY=1")
            assert server.recv(64) == b"READY=1"
        finally:
            server.close()

    def test_broken_socket_is_swallowed(self, monkeypatch, tmp_path):
        # Socket path set but nothing listening: failure must not propagate.
        monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "gone.sock"))
        sd_notify("READY=1")  # must not raise
