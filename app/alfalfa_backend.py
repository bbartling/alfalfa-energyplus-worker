"""An external client of Alfalfa. No EnergyPlus runtime or model rewriting here."""
import hashlib
import json
import os
import tarfile
from datetime import timedelta
from pathlib import Path

import requests
from alfalfa_client.alfalfa_client import AlfalfaClient


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False))
    temporary.replace(path)


def download_archive(host, run_id, destination):
    response = requests.get(f'{host}/api/v2/runs/{run_id}/download', timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)
    # Verify the official archive without extracting untrusted paths.
    with tarfile.open(destination, 'r:gz') as archive:
        return archive.getnames()


def run(job, request):
    folder = Path(os.getenv('TWIN_DATA', '/data')) / job
    model = Path(os.getenv('ALFALFA_MODEL', '/models/schedule_model'))
    host = os.getenv('ALFALFA_URL', 'http://web')
    client = AlfalfaClient(host)
    run_id = None
    started = False
    write_json(folder / 'status.json', {'id': job, 'status': 'running'})
    try:
        run_id = client.submit(str(model))
        write_json(folder / 'status.json', {'id': job, 'status': 'running', 'alfalfa_run_id': run_id})
        start = request.intervals[0].timestamp
        client.start(run_id, start_datetime=start, end_datetime=start + timedelta(days=1), external_clock=True)
        started = True
        available = client.get_inputs(run_id)
        mapping = {'heating_setpoint_c': 'CONSTANT HEATING', 'cooling_setpoint_c': 'COMPACT COOLING'}
        missing = set(mapping.values()) - set(available)
        if missing:
            raise ValueError(f'Alfalfa model missing registered inputs: {missing}')
        outputs = client.get_outputs(run_id)
        temperature_points = sorted(k for k in outputs if k.endswith(' Air Temperature'))
        if not temperature_points:
            raise ValueError('upstream model has no exposed zone temperatures')
        write_json(folder / 'provenance.json', {
            'backend': 'upstream Alfalfa REST API via alfalfa-client==1.0.0',
            'alfalfa_url': host, 'alfalfa_run_id': run_id, 'model_id': request.model_id,
            'model_files_sha256': {str(p.relative_to(model)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in model.rglob('*') if p.is_file()},
            'input_mapping': mapping, 'temperature_points': temperature_points,
            'weather_is_measured': False,
            'runtime_policy': 'observation only; not inferred into setpoints',
            'clock': 'Alfalfa external clock; 1-minute steps; 15 steps per interval',
            'comparison': 'all zones retained; sensor-to-zone mapping not assumed'})
        comparisons = []
        for observation in request.intervals:
            controls = {name: getattr(observation, field) for field, name in mapping.items()}
            client.set_inputs(run_id, controls)
            temperatures = {k: [] for k in temperature_points}
            before = client.get_sim_time(run_id)
            for minute in range(15):
                client.advance(run_id)
                now = client.get_sim_time(run_id)
                if now != before + timedelta(minutes=minute + 1):
                    raise ValueError(f'unexpected Alfalfa clock: {now}')
                outputs = client.get_outputs(run_id)
                for name, value in controls.items():
                    if outputs.get(name) is None or abs(outputs[name] - value) > 0.01:
                        raise ValueError(f'Alfalfa control readback mismatch: {name}')
                for name in temperatures:
                    temperatures[name].append(outputs[name])
            comparisons.append({
                'timestamp': observation.timestamp.isoformat(), 'sim_time': str(now), 'controls': controls,
                'zone_temperature_means_c': {k: sum(v)/len(v) for k,v in temperatures.items()},
                'measured_temperature_c': observation.zone_temperature_mean_c,
                'hvac_runtime_seconds': observation.hvac_runtime_seconds})
            write_json(folder / 'progress.json', {'completed_intervals': len(comparisons), 'alfalfa_run_id': run_id})
        client.stop(run_id)
        started = False
        archive_files = download_archive(host, run_id, folder / 'alfalfa-run.tar.gz')
        write_json(folder / 'results.json', {
            'backend': 'alfalfa', 'alfalfa_run_id': run_id, 'archive_files': archive_files,
            'metrics': {'guideline14_compliance': 'not assessed',
                        'temperature_comparison': 'requires explicit sensor-to-zone mapping'},
            'intervals': comparisons})
        write_json(folder / 'status.json', {'id': job, 'status': 'completed', 'alfalfa_run_id': run_id})
    except Exception as error:
        write_json(folder / 'status.json', {'id': job, 'status': 'failed', 'alfalfa_run_id': run_id, 'error': str(error)})
    finally:
        if started:
            try:
                client.stop(run_id)
            except Exception as error:
                write_json(folder / 'cleanup_error.json', {'error': str(error), 'alfalfa_run_id': run_id})
