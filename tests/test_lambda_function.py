import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import lambda_function


def _set_base_env(monkeypatch, allow_stop="false", idle_threshold="3"):
    monkeypatch.setenv("INSTANCE_ID", "i-1234567890abcdef0")
    monkeypatch.setenv("STATE_TABLE", "autoshutdown-state")
    monkeypatch.setenv("IDLE_THRESHOLD", idle_threshold)
    monkeypatch.setenv("ALLOW_STOP", allow_stop)


def test_skips_when_instance_not_running(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setattr(lambda_function, "get_state_table", lambda _name: object())
    monkeypatch.setattr(lambda_function, "get_instance_state", lambda _iid: "stopped")

    reset_calls = []
    monkeypatch.setattr(
        lambda_function,
        "reset_idle_count",
        lambda instance_id, _table: reset_calls.append(instance_id),
    )

    result = lambda_function.lambda_handler({}, {})

    assert result == {"status": "skipped-stopped"}
    assert reset_calls == ["i-1234567890abcdef0"]


def test_active_connections_resets_counter(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setattr(lambda_function, "get_state_table", lambda _name: object())
    monkeypatch.setattr(lambda_function, "get_instance_state", lambda _iid: "running")
    monkeypatch.setattr(
        lambda_function, "check_ssh_connections", lambda _iid: (True, 2)
    )

    reset_calls = []
    monkeypatch.setattr(
        lambda_function,
        "reset_idle_count",
        lambda instance_id, _table: reset_calls.append(instance_id),
    )

    result = lambda_function.lambda_handler({}, {})

    assert result == {"status": "active", "connection_count": 2}
    assert reset_calls == ["i-1234567890abcdef0"]


def test_idle_below_threshold_updates_count(monkeypatch):
    _set_base_env(monkeypatch, idle_threshold="3")
    monkeypatch.setattr(lambda_function, "get_state_table", lambda _name: object())
    monkeypatch.setattr(lambda_function, "get_instance_state", lambda _iid: "running")
    monkeypatch.setattr(
        lambda_function, "check_ssh_connections", lambda _iid: (False, 0)
    )
    monkeypatch.setattr(lambda_function, "get_idle_count", lambda _iid, _table: 1)

    updates = []
    monkeypatch.setattr(
        lambda_function,
        "update_idle_count",
        lambda instance_id, count, _table: updates.append((instance_id, count)),
    )

    result = lambda_function.lambda_handler({}, {})

    assert result == {"status": "idle-but-not-stopping", "idle_count": 2}
    assert updates == [("i-1234567890abcdef0", 2)]


def test_threshold_reached_suppresses_stop_when_disabled(monkeypatch):
    _set_base_env(monkeypatch, allow_stop="false", idle_threshold="2")
    monkeypatch.setattr(lambda_function, "get_state_table", lambda _name: object())
    monkeypatch.setattr(lambda_function, "get_instance_state", lambda _iid: "running")
    monkeypatch.setattr(
        lambda_function, "check_ssh_connections", lambda _iid: (False, 0)
    )
    monkeypatch.setattr(lambda_function, "get_idle_count", lambda _iid, _table: 1)

    stopped = {"called": False}
    monkeypatch.setattr(
        lambda_function, "stop_instance", lambda _iid: stopped.__setitem__("called", True)
    )

    resets = []
    monkeypatch.setattr(
        lambda_function,
        "reset_idle_count",
        lambda instance_id, _table: resets.append(instance_id),
    )

    result = lambda_function.lambda_handler({}, {})

    assert result == {"status": "stop-suppressed", "idle_count": 2}
    assert stopped["called"] is False
    assert resets == ["i-1234567890abcdef0"]


def test_threshold_reached_stops_when_enabled(monkeypatch):
    _set_base_env(monkeypatch, allow_stop="true", idle_threshold="2")
    monkeypatch.setattr(lambda_function, "get_state_table", lambda _name: object())
    monkeypatch.setattr(lambda_function, "get_instance_state", lambda _iid: "running")
    monkeypatch.setattr(
        lambda_function, "check_ssh_connections", lambda _iid: (False, 0)
    )
    monkeypatch.setattr(lambda_function, "get_idle_count", lambda _iid, _table: 1)

    stops = []
    monkeypatch.setattr(lambda_function, "stop_instance", lambda iid: stops.append(iid))

    resets = []
    monkeypatch.setattr(
        lambda_function,
        "reset_idle_count",
        lambda instance_id, _table: resets.append(instance_id),
    )

    result = lambda_function.lambda_handler({}, {})

    assert result == {"status": "stopped", "idle_count": 2}
    assert stops == ["i-1234567890abcdef0"]
    assert resets == ["i-1234567890abcdef0"]
