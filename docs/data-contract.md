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

Timestamps in batches are RFC 3339 UTC. Schedule clocks are local standard time (`HH:MM`, no daylight-saving shift). The service can convert an instant to that clock with the site's IANA timezone. The EnergyPlus file does not also enable `RunPeriodControl:DaylightSavingTime`, so a summer hour is not shifted a second time. Weekday and weekend profiles follow `Schedule:Week:Daily` (and `hour_of_week` when the summary includes it), not the day-schedule name. Design-day schedules are left as generated until a weather station is selected. EnergyPlus then uses the nearest station in the OpenStudio standards set. That file is a typical year (TMY3, CWEC, or CZ2010), not the actual year of the bills. The run records the station id and `weather_kind`. Site location and the heating and cooling design days are replaced with that station's. The monthly HDD and CDD in the summary still drive the screening model.

## Operations batch

`POST /v1/sites/{site_id}/operations` or `POST /v1/hooks/operations` (same JSON, for a single webhook URL).

Outbound webhooks are https only. The host is resolved at registration and again at delivery, and a private, loopback, or link-local address is rejected. The secret in the request is not stored. The response includes a random signing key, and each delivery is signed as `timestamp.body` with retry and backoff.

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

Sensors are quantile summaries, not sample arrays: `{n, hours, p05, p10, p25, p50, p75, p90, p95}` for each mode. A zone heating setpoint is the upper quantile (`p90`) of `heating_active` hours, and a cooling setpoint is the lower quantile (`p10`) of `cooling_active` hours. A mode with fewer than 8 hours is not emitted. Two supply-air modes are stored as `method=reset` with both values, not their mean. Confidence below 0.6 is dropped and the prototype default is used.

An `source=actual` value for a kind wins over an inferred value for every period, including `always`. Request bodies larger than 1 MB are rejected.

Meters are monthly totals. `role` is `main` or `sub`; only a main meter is used for calibration, so a main meter plus RTU submeters are not added together. A period shorter than 95% of its calendar month, or a main meter that covers less than 95% of the period, is stored but excluded. A period that overlaps one already stored is rejected. Electricity is kWh. Gas is accepted as therm, kWh, or m³ and stored as therm. Weather is a period summary (mean dry-bulb, HDD and CDD base 18 °C) plus the site location from registration. Hourly Guideline 14 is not claimed.

`GET /v1/sites/{site_id}/coverage?start=&end=` lists missing months.

## Calibration and what-ifs

Site registration accepts `heating_fuel` (`gas`, `electric`, or `heat_pump`, default `heat_pump`) and `system_type` (default `psz-ac`). EnergyPlus calibration is the checked-in small-office packaged RTU. A heat pump site tunes heating COP. A gas or electric site locks the compressor out and runs the fuel coil, with electricity as the fuel type when `heating_fuel` is `electric`. Any other building or system is `422`.

`POST /v1/sites/{site_id}/calibrations` fits a screening change-point model (baseload W/m², cooling kWh per CDD per m², heating therm per HDD per m²) to the usable months. Faults with `exclude_from_calibration` are dropped. The result is labeled `screening` and is not a Guideline 14 promotion. `?engine=energyplus` is the path that can be promoted under Guideline 14.

`POST /v1/sites/{site_id}/scenarios` applies `raise_cooling_setpoint`, `lower_heating_setpoint`, or `trim_run_hours` and returns annual kWh, therms, cost savings, simple payback, NPV, and a band from the nearest parameter sets.

HTML reports: `GET /` and `GET /sites/{site_id}`. JSON: `GET /v1/sites/{site_id}/report`.
