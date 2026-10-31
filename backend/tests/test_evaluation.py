import time

from fastapi.testclient import TestClient

from app.main import app


def test_evaluation_runs_real_agent_and_reports_metrics():
    with TestClient(app) as c:
        assert c.get("/api/v1/evaluation/latest").json() is None  # nothing is shown until a real run exists
        assert c.post("/api/v1/evaluation/run").json()["started"]
        for _ in range(120):
            if not c.get("/api/v1/evaluation/status").json()["running"]:
                break
            time.sleep(1)
        run = c.get("/api/v1/evaluation/latest").json()
        assert run and run["metrics"]["total_cases"] >= 15 and len(run["results"]) == run["metrics"]["total_cases"]
        assert run["metrics"]["passed"] == sum(r["passed"] for r in run["results"])  # metrics derive from results
        assert {r["category"] for r in run["results"]} >= {"pdf", "transcript", "solved_reuse", "ambiguous", "unknown", "contradiction", "prompt_injection"}
        assert all(r["failures"] for r in run["results"] if not r["passed"])  # every failure carries a reason
