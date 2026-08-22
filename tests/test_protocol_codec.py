import json

from eres_print_agent.models import AgentHeartbeat, PrintJobReceived
from eres_print_agent.net.protocol_codec import decode, encode


def test_encode_round_trips_through_json():
    message = PrintJobReceived(jobId="job-1")
    raw = encode(message)
    parsed = json.loads(raw)
    assert parsed["type"] == "print.job.received"
    assert parsed["jobId"] == "job-1"
    assert "ts" in parsed


def test_decode_valid_print_job_dispatch():
    raw = json.dumps(
        {
            "type": "print.job",
            "ts": "2026-01-01T00:00:00.000Z",
            "jobId": "job-1",
            "printerId": "HP LaserJet",
            "documentType": "test-page",
            "documentId": "test",
            "documentUrl": "https://example.com/doc.pdf",
            "copies": 1,
        }
    )
    message = decode(raw)
    assert message is not None
    assert message.type == "print.job"
    assert message.jobId == "job-1"


def test_decode_returns_none_for_unknown_type():
    raw = json.dumps({"type": "not.a.real.type", "ts": "2026-01-01T00:00:00.000Z"})
    assert decode(raw) is None


def test_decode_returns_none_for_malformed_json():
    assert decode("not json at all") is None


def test_decode_returns_none_for_missing_required_fields():
    raw = json.dumps({"type": "print.job.cancel", "ts": "2026-01-01T00:00:00.000Z"})  # missing jobId
    assert decode(raw) is None


def test_agent_heartbeat_default_queue_depth_is_none():
    message = AgentHeartbeat()
    assert message.queueDepth is None
