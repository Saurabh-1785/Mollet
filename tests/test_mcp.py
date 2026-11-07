"""The classroom MCP tools, called directly."""

from mollet import db, mcp_server


def test_get_problem_hides_tests(client):
    out = mcp_server.get_problem("fizzbuzz")
    assert out["entry"] == "fizzbuzz"
    assert "hidden_tests" not in out
    assert "error" in mcp_server.get_problem("nope")


def test_student_history_has_mistakes(client):
    db.add_attempt(student_id="student_002", problem_id="fizzbuzz", code="x", passed=0,
                   passed_count=1, total=6, mistake="used = instead of ==", feedback="")
    out = mcp_server.get_student_history("student_002")
    assert out["recent_mistakes"][0]["mistake"] == "used = instead of =="
    assert "error" in mcp_server.get_student_history("ghost")


def test_mcp_endpoint_mounted(client):
    r = client.post("/classroom/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
        headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["serverInfo"]["name"] == "mollet-classroom"
