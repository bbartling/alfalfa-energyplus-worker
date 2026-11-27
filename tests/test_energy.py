import pytest
from twin.energy import Params, electric_kwh, gas_therms
from twin.service import net_present_value


def test_hand_computed_month():
    params = Params(10, 4, 0.5)
    electric = electric_kwh(
        params,
        area=1000,
        days=30,
        occupied_hours=300,
        run_hours=200,
        cooling_sp=24,
        oa_fraction=0,
        cdd=10,
    )
    gas = gas_therms(params, area=1000, heating_sp=21, oa_fraction=0, hdd=100)
    assert electric == pytest.approx(3450)
    assert gas == pytest.approx(31.25)


def test_zero_discount_npv_and_payback_inputs():
    assert net_present_value(1000, 500, 0, 3) == pytest.approx(500)
