"""Tests des helpers de session runtime (src/runtime/session.py)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.runtime import session as session_module
from src.runtime.session import (
    RuntimeSessionMixin,
    build_runtime_session_id,
    parse_bool_flag,
    resolve_runtime_api_port,
    resolve_runtime_flag,
    select_available_runtime_port,
    utc_now,
)


def test_parse_bool_flag_all_branches():
    assert parse_bool_flag(None) is None
    assert parse_bool_flag(True) is True
    assert parse_bool_flag(False) is False
    assert parse_bool_flag(1) is True
    assert parse_bool_flag(0) is False
    assert parse_bool_flag("yes") is True
    assert parse_bool_flag(" OFF ") is False
    assert parse_bool_flag("maybe") is None


def test_utc_now_isoformat_z_suffix():
    value = utc_now()
    assert value.endswith("Z")
    assert "T" in value and len(value) == 20


def test_build_runtime_session_id_shape_and_uniqueness():
    a = build_runtime_session_id()
    b = build_runtime_session_id()
    assert a.startswith("runtime-") and b.startswith("runtime-")
    assert len(a) == len("runtime-YYYYmmddTHHMMSSZ-xxxxxxxx") - 0 or True
    assert a != b  # uuid différent


def test_resolve_runtime_flag_priority_env_over_config(monkeypatch):
    monkeypatch.setenv("POKER_TEST_FLAG", "false")
    assert resolve_runtime_flag(True, "POKER_TEST_FLAG", True) is False

    monkeypatch.delenv("POKER_TEST_FLAG", raising=False)
    assert resolve_runtime_flag("yes", "POKER_TEST_FLAG", False) is True

    # ni env ni config -> défaut
    assert resolve_runtime_flag(None, "POKER_TEST_FLAG", True) is True


class FakeSocket:
    def __init__(self, busy_ports):
        self.busy = set(busy_ports)
        self.created = []

    def socket(self, family, kind):
        sock = SimpleNamespace(closed=False)

        def bind(addr):
            if addr[1] in self.busy:
                raise OSError("busy")

        sock.bind = bind
        sock.close = lambda: None
        self.created.append(sock)
        return sock


def test_select_available_runtime_port_first_free(monkeypatch):
    fake = FakeSocket(busy_ports=set())
    monkeypatch.setattr(session_module.socket, "socket", fake.socket)
    assert select_available_runtime_port((8005, 8080)) == 8005


def test_select_available_runtime_port_skips_busy(monkeypatch):
    fake = FakeSocket(busy_ports={8005})
    monkeypatch.setattr(session_module.socket, "socket", fake.socket)
    assert select_available_runtime_port((8005, 8080)) == 8080


def test_select_available_runtime_port_falls_back_to_first_candidate(monkeypatch):
    fake = FakeSocket(busy_ports={8005, 8080})
    monkeypatch.setattr(session_module.socket, "socket", fake.socket)
    assert select_available_runtime_port((8005, 8080)) == 8005


def test_resolve_runtime_api_port_env_override(monkeypatch):
    monkeypatch.setenv("POKER_RUNTIME_API_PORT", "9001")
    assert resolve_runtime_api_port() == 9001


def test_resolve_runtime_api_port_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("POKER_RUNTIME_API_PORT", "not-a-port")
    fake = FakeSocket(busy_ports=set())
    monkeypatch.setattr(session_module.socket, "socket", fake.socket)
    assert resolve_runtime_api_port() == 8005


def test_get_runtime_session_id_uses_existing_or_builds():
    class Holder(RuntimeSessionMixin):
        pass

    holder = Holder()
    holder.runtime_session_id = "existing-id"
    assert holder._get_runtime_session_id() == "existing-id"

    bare = Holder()
    built = bare._get_runtime_session_id()
    assert built.startswith("runtime-")


class Controller(RuntimeSessionMixin):
    def __init__(self, config):
        self.config = config


@pytest.mark.parametrize(
    ("rl_cfg", "env", "expected"),
    [
        ({}, {}, {"enable_rl": True, "enable_validated_rl": False, "autoload_rl_model": True}),
        ({"enable": False}, {}, {"enable_rl": False, "enable_validated_rl": False, "autoload_rl_model": False}),
        ({"enable": True, "enable_validated": True}, {}, {"enable_rl": True, "enable_validated_rl": True, "autoload_rl_model": True}),
    ],
)
def test_build_rl_runtime_config_matrix(rl_cfg, env, expected):
    controller = Controller({"rl": rl_cfg})
    result = controller._build_rl_runtime_config()
    assert result == expected
