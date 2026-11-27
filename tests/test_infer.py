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


def test_inference_requires_a_sample():
    with pytest.raises(ValueError):
        infer_steady([13.0, 13.0])
