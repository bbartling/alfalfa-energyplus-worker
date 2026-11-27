import math

import pytest
from twin.eplus_meters import hourly_kwh
from twin.guideline14 import assess, cv_rmse_nmbe


def test_nmbe_sign_and_cvrmse_match_the_definition():
    measured = [10.0, 10.0, 10.0]
    simulated = [12.0, 12.0, 12.0]
    stats = cv_rmse_nmbe(measured, simulated, p=1)
    # sum(y - yhat) = -6; n - p = 2; mean = 10
    assert stats["nmbe_pct"] == pytest.approx(-30)
    assert stats["cv_rmse_pct"] == pytest.approx(math.sqrt(6) * 10)
    assert stats["p"] == 1


def test_perfect_agreement_is_zero():
    stats = cv_rmse_nmbe([5.0, 7.0, 9.0], [5.0, 7.0, 9.0])
    assert stats["cv_rmse_pct"] == pytest.approx(0)
    assert stats["nmbe_pct"] == pytest.approx(0)


def test_monthly_and_hourly_limits():
    measured = [100.0, 100.0, 100.0, 100.0]
    close = [98.0, 101.0, 99.0, 102.0]
    monthly = assess(measured, close, "monthly")
    assert monthly["pass"] is True
    assert monthly["claim"] == "guideline14"
    biased = [80.0, 80.0, 80.0, 80.0]
    failed = assess(measured, biased, "monthly")
    assert failed["pass"] is False
    hourly = assess(measured, [94.0, 106.0, 94.0, 106.0], "hourly")
    assert hourly["pass"] is True
    assert hourly["limits"]["cv_rmse_pct"] == 30


def test_too_few_points_for_p():
    with pytest.raises(ValueError):
        cv_rmse_nmbe([10.0], [9.0], p=1)


def test_energyplus_meter_csv_feeds_guideline14(tmp_path):
    path = tmp_path / "eplusmtr.csv"
    path.write_text(
        "Date/Time,Electricity:Facility [J](Hourly)\n"
        " 01/01  01:00:00,3600000\n"
        " 01/01  02:00:00,7200000\n"
    )
    simulated = hourly_kwh(path)
    assert simulated == pytest.approx([1.0, 2.0])
    stats = assess([1.0, 2.0], simulated, "hourly")
    assert stats["cv_rmse_pct"] == pytest.approx(0)
    assert stats["pass"] is True
