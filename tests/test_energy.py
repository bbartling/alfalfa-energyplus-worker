import pytest
from twin.energy import Params, electric_kwh, fit, gas_therms, predict
from twin.service import _apply_measures, month_from_payload, net_present_value, price_measures


def _month(**overrides):
    month = {
        "days": 30,
        "occupied_hours": 300,
        "run_hours": 200,
        "cooling_sp": 24,
        "heating_sp": 21,
        "oa_fraction": 0,
        "cdd": 10,
        "hdd": 100,
    }
    month.update(overrides)
    return month


def test_hand_computed_month():
    params = Params(10, 0.01, 0.0005)
    month = _month()
    assert electric_kwh(params, area=1000, month=month) == pytest.approx(3400)
    assert gas_therms(params, area=1000, month=month) == pytest.approx(50)


def test_one_degree_does_not_erase_cooling():
    params = Params(8, 0.01, 0.0004)
    base = predict(params, _month(cdd=120), 1000)[0]
    warmer = predict(params, _month(cdd=120, cooling_sp=25), 1000)[0]
    saved = base - warmer
    assert saved == pytest.approx(300)
    assert saved < 0.5 * base


def test_fit_recovers_off_grid_coefficients_with_noise():
    truth = Params(9.3, 0.0085, 0.00042)
    months = []
    weather = ((180, 20), (70, 60), (15, 140), (5, 200), (8, 180), (40, 90), (120, 30), (280, 8), (420, 6), (390, 7), (260, 18), (140, 40))
    for index, (hdd, cdd) in enumerate(weather):
        month = _month(days=30, hdd=hdd, cdd=cdd, occupied_hours=240, run_hours=220)
        electric, gas = predict(truth, month, 1600)
        factor = 1.04 if index % 2 == 0 else 0.96
        months.append({**month, "electric_kwh": electric * factor, "gas_therms": gas * factor})
    fitted = fit(months, 1600)
    assert fitted.base_w_m2 == pytest.approx(truth.base_w_m2, rel=0.15)
    assert fitted.cooling_kwh_per_cdd_m2 == pytest.approx(truth.cooling_kwh_per_cdd_m2, rel=0.15)
    assert fitted.heating_therm_per_hdd_m2 == pytest.approx(truth.heating_therm_per_hdd_m2, rel=0.15)


def test_fan_hours_are_averaged_and_trim_does_not_cut_lighting():
    payload = {
        "period": {"start": "2026-01-01T00:00:00Z", "end": "2026-02-01T00:00:00Z"},
        "run_hours": [{"hours": 100}, {"hours": 300}],
        "schedules": [{"windows": [{"days": "weekday", "start": "08:00", "end": "18:00"}]}],
        "setpoints": [],
        "outdoor_air": [],
        "weather": {"cdd_base_18c": 0, "hdd_base_18c": 100},
        "meters": [{"fuel": "electricity", "granularity": "month", "value": 1}],
        "faults": [],
    }
    month = month_from_payload(payload)
    assert month["run_hours"] == pytest.approx(200)
    trimmed = _apply_measures(month, [{"name": "trim_run_hours", "fraction": 0.2}])
    assert trimmed["run_hours"] == pytest.approx(160)
    assert trimmed["occupied_hours"] == month["occupied_hours"]


def test_fewer_than_twelve_months_are_not_annualized():
    params = Params(9, 0.01, 0.0004)
    months = []
    for cdd in (40, 80, 140):
        month = _month(cdd=cdd, hdd=40)
        electric, gas = predict(params, month, 1000)
        months.append({**month, "electric_kwh": electric, "gas_therms": gas})
    priced = price_measures(
        params,
        months,
        1000,
        [{"name": "raise_cooling_setpoint", "delta_c": 1}],
        {"implementation_usd": 1000, "electricity_usd_per_kwh": 0.1, "gas_usd_per_therm": 1, "discount_rate": 0, "horizon_years": 1},
        [params.as_dict()],
    )
    assert priced["annualized"] is False
    assert priced["annual_kwh_savings"] == pytest.approx(3 * 1000 * 0.01 * 30)


def test_zero_discount_npv_and_payback_inputs():
    assert net_present_value(1000, 500, 0, 3) == pytest.approx(500)
