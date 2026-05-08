from src.runtime.evidence_models import RuntimeReadiness
from src.runtime.table_session import TableSession
from src.vision.site_adapter import PokerStarsAdapter


def test_table_session_snapshot_keeps_isolated_runtime_state():
    session = TableSession(session_id="table-1", hwnd=123, adapter=PokerStarsAdapter())
    session.tracker_state = {"street": "FLOP"}
    session.visual_state = {"table_detected": True}
    session.temporal_state = {"pot": {"state": "confirmed"}}
    session.last_valid_state = {"spot_id": "live:FLOP:test"}
    session.update_readiness(RuntimeReadiness(state="actionable", actionable=True, score=0.9, state_confidence=0.9))
    session.record_incident("test_incident", reason="unit")

    snapshot = session.snapshot()
    assert snapshot["session_id"] == "table-1"
    assert snapshot["site_key"] == "pokerstars"
    assert snapshot["tracker_state"]["street"] == "FLOP"
    assert snapshot["incident_count"] == 1
    assert snapshot["readiness"]["state"] == "actionable"
