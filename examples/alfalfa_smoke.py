"""Exercise official upstream model submission, preprocessing, control, and stop."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from alfalfa_client.alfalfa_client import AlfalfaClient
from app.alfalfa_backend import download_archive

client = AlfalfaClient(os.getenv('ALFALFA_URL', 'http://web'))
run_id = client.submit('/models/schedule_model')
print('Submitted official schedule_model:', run_id, flush=True)
started = False
try:
    start = datetime(2025, 7, 7)
    client.start(run_id, start_datetime=start, end_datetime=start + timedelta(days=1), external_clock=True)
    started = True
    inputs = client.get_inputs(run_id)
    outputs = client.get_outputs(run_id)
    print('Inputs:', inputs, flush=True)
    print('Outputs:', sorted(outputs), flush=True)
    before = client.get_sim_time(run_id)
    evidence = []
    for i, (heating, cooling) in enumerate([(19, 25), (20, 24), (18, 26)]):
        controls = {'CONSTANT HEATING': heating, 'COMPACT COOLING': cooling}
        client.set_inputs(run_id, controls)
        client.advance(run_id)
        now = client.get_sim_time(run_id)
        outputs = client.get_outputs(run_id)
        assert now == before + timedelta(minutes=i + 1), (before, now)
        for key, value in controls.items():
            assert abs(outputs[key] - value) < 0.01, (key, outputs[key], value)
        evidence.append({'sim_time': str(now), 'controls': controls, 'outputs': outputs})
    client.stop(run_id)
    started = False
    files = download_archive(os.getenv('ALFALFA_URL', 'http://web'), run_id, Path('/data/alfalfa-smoke.tar.gz'))
    result = {'alfalfa_run_id': run_id, 'status': client.status(run_id), 'archive_files': files, 'evidence': evidence}
    Path('/data/alfalfa-smoke.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
finally:
    if started:
        client.stop(run_id)
