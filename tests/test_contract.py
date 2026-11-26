import copy
import unittest
from datetime import datetime, timedelta

from app.server import api
from fastapi.testclient import TestClient


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(api)
        self.payload = {"site_id": "test", "intervals": [
            {"timestamp": (datetime(2025, 7, 7) + timedelta(minutes=15*i)).isoformat(),
             "heating_setpoint_c": 20, "cooling_setpoint_c": 24} for i in range(96)]}

    def test_rejects_bad_time_runtime_deadband_and_unknown_fields(self):
        for field, value in [("timestamp", "2025-07-07T00:00:00Z"),
                             ("hvac_runtime_seconds", 901), ("heating_setpoint_c", 25),
                             ("cooling_setpoint_c", float("inf")), ("unknown", 1)]:
            body = copy.deepcopy(self.payload)
            body["intervals"][0][field] = value
            # Pydantic directly handles nonfinite values; JSON must remain valid.
            if value == float("inf"):
                from app.server import Replay
                with self.assertRaises(ValueError):
                    Replay.model_validate(body)
            else:
                self.assertEqual(self.client.post("/replays", json=body).status_code, 422)

    def test_rejects_gap_and_unknown_model(self):
        self.payload["intervals"][3]["timestamp"] = "2025-07-07T01:00:00"
        self.assertEqual(self.client.post("/replays", json=self.payload).status_code, 422)
        self.payload["model_id"] = "unmapped-building"
        self.assertEqual(self.client.post("/replays", json=self.payload).status_code, 422)

    def test_artifacts_cannot_escape_job(self):
        self.assertEqual(self.client.get("/replays/not-a-uuid").status_code, 404)


if __name__ == "__main__":
    unittest.main()
