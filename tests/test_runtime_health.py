from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.runtime.health import HealthMonitor


def test_health_monitor_records_success_and_error_states():
    monitor = HealthMonitor()

    monitor.record_error("solver", "native_solver_down", status="degraded", cooldown_s=1.0)
    degraded = monitor.snapshot()

    assert degraded["solver"]["status"] == "degraded"
    assert degraded["solver"]["error_count"] == 1
    assert degraded["solver"]["last_error_at"] is not None
    assert degraded["solver"]["cooldown_until"] is not None
    assert degraded["solver"]["reasons"] == ["native_solver_down"]
    assert monitor.degraded_reasons() == ["solver:native_solver_down"]

    monitor.record_success("solver")
    healthy = monitor.snapshot()

    assert healthy["solver"]["status"] == "healthy"
    assert healthy["solver"]["last_success_at"] is not None
    assert healthy["solver"]["reasons"] == []
    assert monitor.degraded_reasons() == []
    assert monitor.overall_last_success_at() is not None
