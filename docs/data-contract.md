# Data contract

The IoT FDD application pushes compact operating summaries. It does not push raw 1–5 minute telemetry, and there is no Parquet upload.

A year of monthly summaries for 20 pieces of equipment is a few hundred kilobytes (run-hour profiles are 168 numbers, plus a handful of setpoints, one outdoor-air fraction, fault counts, and meter totals). Optional hourly whole-building electricity for a year is about 350 KB. REST batches carry that easily. Chunk only if a body would exceed a few megabytes; that does not happen for this schema.

MQTT is not used. The same JSON could be a message, but a weekly or monthly POST does not need a broker.

## Register a site

`POST /v1/sites` with a bearer API key.

```json
{
  "site_id": "site-cold-office",
  "timezone": "America/Denver",
  "latitude": 39.74,
  "longitude": -104.99,
  "floor_area_m2": 1600,
  "building_type": "small-office"
}
```

Timestamps in batches are RFC 3339 UTC. Schedule clocks are local standard time (`HH:MM`, no daylight-saving shift). The service can convert an instant to that clock with the site's IANA timezone.

## Operations batch

`POST /v1/sites/{site_id}/operations` or `POST /v1/hooks/operations` (same JSON, for a single webhook URL).

`batch_id` is the idempotency key. The same body returns `"duplicate": true` and does not write again. A different body with the same id is `409`.

```json
{
  "schema_version": "1.0",
  "batch_id": "6f1b5d0e-2b7a-4c1e-9c51-1d2f3a4b5c6d",
  "site_id": "site-cold-office",
  "generated_at": "2026-04-01T00:00:00Z",
  "period": {"start": "2026-03-01T00:00:00Z", "end": "2026-04-01T00:00:00Z", "label": "month"},
  "run_hours": [
    {"equipment_id": "rtu-1", "hours": 220, "method": "status>0.5"}
  ],
  "schedules": [
    {"equipment_id": "rtu-1", "name": "occupied", "windows": [{"days": "weekday", "start": "07:00", "end": "18:00"}]}
  ],
  "setpoints": [
    {"equipment_id": "rtu-1", "kind": "duct_static", "period": "always", "unit": "Pa", "value": 375, "source": "actual"}
  ],
  "sensors": [
    {"equipment_id": "rtu-1", "kind": "supply_air_temp", "unit": "degC", "samples_while_running": [13.0, 13.1]},
    {"equipment_id": "rtu-1", "kind": "zone_temp", "unit": "degC", "occupied_samples": [21.0], "unoccupied_samples": [18.0]}
  ],
  "outdoor_air": [
    {"equipment_id": "rtu-1", "oa_fraction_mean": 0.15, "economizer_hours": 12, "economizer_enabled": true}
  ],
  "faults": [
    {"equipment_id": "rtu-1", "rule_id": "economizer-stuck", "count": 0, "exclude_from_calibration": false}
  ],
  "meters": [
    {"meter_id": "elec-main", "fuel": "electricity", "unit": "kWh", "start": "2026-03-01T00:00:00Z", "end": "2026-04-01T00:00:00Z", "value": 18240, "granularity": "month"}
  ],
  "weather": {"source": "site-summary", "drybulb_mean_c": 8.4, "hdd_base_18c": 280, "cdd_base_18c": 8}
}
```

`hour_of_week`, when present, is 168 fractions in `[0, 1]`. Sensor arrays are a sample of operation (at most 2000 values), not a history dump. Unknown fields, including a raw `records` array, are rejected.

Setpoint kinds: `supply_air_temp` (°C), `duct_static` (Pa), `zone_heating`, `zone_cooling`, `chw`, `hw`. Period is `occupied`, `unoccupied`, or `always`.

If a setpoint is omitted, it is inferred and stored with `source=inferred`, a `method`, and `confidence` in `[0, 1]`:

- Steady-state percentile (`steady-state-percentile`): mean of samples between the 10th and 90th percentiles. Used for supply air temperature, duct static, and chilled or hot water temperature.
- Deadband percentile (`deadband-percentile`): 10th percentile is the heating setpoint and 90th is the cooling setpoint, checked against the lower and upper quartile means. Occupied and unoccupied samples are inferred separately. A deadband that is not plausible lowers the confidence.

An `source=actual` value is never replaced. Extra sensor samples for that point are ignored.

Meters are monthly totals, with optional daily or hourly rows. If a monthly row is present it is the total; otherwise finer rows are summed. Electricity is kWh. Gas is therm. Weather is a period summary (mean dry-bulb, HDD and CDD base 18 °C) plus the site location from registration.

`GET /v1/sites/{site_id}/coverage?start=&end=` lists missing months.

## Calibration and what-ifs

`POST /v1/sites/{site_id}/calibrations` fits lighting W/m², cooling COP, and infiltration to the usable months (faults with `exclude_from_calibration` are dropped). The last two usable months are the holdout. The model is promoted only when train and holdout both pass Guideline 14.

`POST /v1/sites/{site_id}/scenarios` applies `raise_cooling_setpoint`, `lower_heating_setpoint`, or `trim_run_hours` and returns annual kWh, therms, cost savings, simple payback, NPV, and a band from the nearest parameter sets.

HTML reports: `GET /` and `GET /sites/{site_id}`. JSON: `GET /v1/sites/{site_id}/report`.
