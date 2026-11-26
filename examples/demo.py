"""Docker-only integration smoke: real HTTP ingestion and EnergyPlus simulation."""
import json
import time
import urllib.request
from datetime import datetime, timedelta

start = datetime(2025, 7, 7)
payload = {"site_id": "demo-building", "intervals": [
    {"timestamp": (start + timedelta(minutes=15*i)).isoformat(),
     "heating_setpoint_c": 20, "cooling_setpoint_c": 24 if 32 <= i < 72 else 28,
     "zone_temperature_mean_c": 24, "hvac_runtime_seconds": 300}
    for i in range(96)]}
request = urllib.request.Request("http://localhost:8080/replays", json.dumps(payload).encode(),
                                 {"Content-Type": "application/json"})
job = json.load(urllib.request.urlopen(request))
print(json.dumps(job), flush=True)
for _ in range(180):
    result = json.load(urllib.request.urlopen("http://localhost:8080" + job["status_url"]))
    if result["status"] in ("completed", "failed"):
        print(json.dumps(result, indent=2))
        assert result["status"] == "completed", result
        assert len(result["results"]["intervals"]) == 96
        break
    time.sleep(1)
else:
    raise TimeoutError("simulation did not finish")
