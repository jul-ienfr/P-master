from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.runtime.health import HealthMonitor
from src.runtime.operator_bridge import OperatorBridge


class FakeBridgeStore:
    def __init__(self):
        self.bridge_dir = Path("bridge")
        self.published = []
        self.commands = []

    def publish_runtime_state(self, payload):
        self.published.append(dict(payload))
        return payload

    def consume_pending_commands(self, limit=8):
        commands = list(self.commands[:limit])
        self.commands = self.commands[limit:]
        return commands


class FakeHistoryStore:
    def __init__(self):
        self.file_path = Path("runtime_history.jsonl")


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def test_operator_bridge_rate_limits_publication():
    store = FakeBridgeStore()
    bridge = OperatorBridge(
        root=ROOT,
        bridge_store=store,
        history_store=FakeHistoryStore(),
        runtime_api_port=8005,
        build_state=lambda: {"session_id": "runtime-1"},
        apply_command=lambda command: None,
        push_incident=lambda *args, **kwargs: None,
        publish_interval_s=60.0,
    )

    bridge.publish_state(force=False)
    bridge.publish_state(force=False)
    bridge.publish_state(force=True)

    assert len(store.published) == 2


def test_operator_bridge_processes_commands_and_reports_failures():
    store = FakeBridgeStore()
    incidents = []
    applied = []
    store.commands = [
        {"command_id": "ok-1", "kind": "operator_patch", "payload": {"paused": True}},
        {"command_id": "bad-1", "kind": "operator_patch", "payload": {"paused": False}},
    ]

    def apply_command(command):
        if command["command_id"] == "bad-1":
            raise RuntimeError("command_failure")
        applied.append(command)

    bridge = OperatorBridge(
        root=ROOT,
        bridge_store=store,
        history_store=FakeHistoryStore(),
        runtime_api_port=8005,
        build_state=lambda: {},
        apply_command=apply_command,
        push_incident=lambda *args, **kwargs: incidents.append({"args": args, "kwargs": kwargs}),
    )

    bridge.process_pending_commands(limit=8)

    assert [item["command_id"] for item in applied] == ["ok-1"]
    assert incidents[0]["args"][0] == "bridge_command_error"
    assert incidents[0]["kwargs"]["command_id"] == "bad-1"


def test_operator_bridge_marks_api_health_on_start_failure():
    store = FakeBridgeStore()
    monitor = HealthMonitor()

    def fake_factory(*args, **kwargs):
        return FakeProcess(returncode=1)

    bridge = OperatorBridge(
        root=ROOT,
        bridge_store=store,
        history_store=FakeHistoryStore(),
        runtime_api_port=8005,
        build_state=lambda: {},
        apply_command=lambda command: None,
        push_incident=lambda *args, **kwargs: None,
        health_monitor=monitor,
        process_factory=fake_factory,
        sleep_fn=lambda _: None,
    )

    try:
        bridge.start_api_process()
    except RuntimeError:
        pass

    snapshot = monitor.snapshot()
    assert snapshot["api"]["status"] == "unavailable"
    assert snapshot["api"]["reasons"] == ["api_process_exited_early"]
