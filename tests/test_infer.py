import pytest
from twin.infer import infer_steady, infer_zone


def test_supply_air_setpoint_ignores_startup_spikes():
    samples = [13.0] * 20 + [0.0, 40.0]
    inferred = infer_steady(samples)
    assert inferred.value == 13.0
    assert inferred.method == "steady-state-percentile"
    assert inferred.confidence > 0.6


def test_zone_deadband_recovers_occupied_setpoints():
    heating, cooling = infer_zone([21.0] * 40 + [24.0] * 40)
    assert heating.value == 21.0
    assert cooling.value == 24.0
    assert heating.method == "deadband-percentile"
    assert cooling.confidence > 0.6
    assert cooling.value - heating.value == 3.0


def test_flat_zone_temperature_has_low_confidence():
    heating, cooling = infer_zone([22.0] * 30)
    assert heating.confidence < 0.5
    assert cooling.confidence < 0.5


def _q(value, **overrides):
    summary = {"n": 20, "hours": 20, "p05": value, "p10": value, "p25": value, "p50": value, "p75": value, "p90": value, "p95": value}
    summary.update(overrides)
    return summary


def _batch(sensors, setpoints=None):
    from twin.schemas import OperationsBatch

    return OperationsBatch.model_validate(
        {
            "schema_version": "1.0",
            "batch_id": "00000000-0000-0000-0000-000000000001",
            "site_id": "site-cold-office",
            "generated_at": "2026-01-01T00:00:00Z",
            "period": {"start": "2026-01-01T00:00:00Z", "end": "2026-02-01T00:00:00Z", "label": "month"},
            "sensors": sensors,
            "setpoints": setpoints or [],
            "weather": {"source": "site-summary", "drybulb_mean_c": 0, "hdd_base_18c": 10, "cdd_base_18c": 0},
        }
    )


def test_cooling_only_month_does_not_invent_a_heating_setpoint():
    from twin.service import apply_inference

    batch = _batch(
        [
            {
                "equipment_id": "rtu-1",
                "kind": "zone_temp",
                "unit": "degC",
                "occupied_cooling_active": _q(24),
            }
        ]
    )
    result = apply_inference(batch)
    kinds = [(item.kind, item.value) for item in result.setpoints]
    assert ("zone_cooling", 24.0) in kinds
    assert not any(item.kind == "zone_heating" for item in result.setpoints)


def test_floating_zone_with_no_active_mode_is_not_inferred():
    from twin.service import apply_inference

    batch = _batch([{"equipment_id": "rtu-1", "kind": "zone_temp", "unit": "degC"}])
    assert apply_inference(batch).setpoints == []


def test_heating_setpoint_is_the_upper_quantile_of_heating_active_hours():
    from twin.service import apply_inference

    batch = _batch(
        [
            {
                "equipment_id": "rtu-1",
                "kind": "zone_temp",
                "unit": "degC",
                "unoccupied_heating_active": _q(15.6),
            }
        ]
    )
    heating = apply_inference(batch).setpoints[0]
    assert heating.kind == "zone_heating"
    assert heating.value == 15.6
    assert heating.method == "mode-quantile"


def test_supply_air_reset_keeps_both_modes():
    from twin.service import apply_inference

    batch = _batch(
        [
            {
                "equipment_id": "rtu-1",
                "kind": "supply_air_temp",
                "unit": "degC",
                "reset_modes": [_q(12.8), _q(15.5)],
            }
        ]
    )
    sat = apply_inference(batch).setpoints[0]
    assert sat.method == "reset"
    assert sat.modes == [12.8, 15.5]
    assert sat.value != pytest.approx(14.15)


def test_actual_setpoint_wins_over_any_inferred_period():
    from twin.service import apply_inference, month_from_payload

    batch = _batch(
        [
            {
                "equipment_id": "rtu-1",
                "kind": "zone_temp",
                "unit": "degC",
                "occupied_cooling_active": _q(26),
            }
        ],
        setpoints=[
            {
                "equipment_id": "rtu-1",
                "kind": "zone_cooling",
                "period": "always",
                "unit": "degC",
                "value": 23,
                "source": "actual",
            }
        ],
    )
    result = apply_inference(batch)
    assert [item.value for item in result.setpoints] == [23]
    assert month_from_payload(result.model_dump(mode="json"))["cooling_sp"] == 23


def test_gas_kwh_and_cubic_metres_become_therms():
    from twin.schemas import Meter

    kwh = Meter.model_validate(
        {
            "meter_id": "gas",
            "fuel": "natural_gas",
            "unit": "kWh",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-02-01T00:00:00Z",
            "value": 29.300111,
        }
    )
    cubic = Meter.model_validate(
        {
            "meter_id": "gas",
            "fuel": "natural_gas",
            "unit": "m3",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-02-01T00:00:00Z",
            "value": 2.83168,
        }
    )
    assert kwh.unit == "therm" and kwh.value == pytest.approx(1)
    assert cubic.unit == "therm" and cubic.value == pytest.approx(1)


def test_inference_requires_a_sample():
    with pytest.raises(ValueError):
        infer_steady([13.0, 13.0])
