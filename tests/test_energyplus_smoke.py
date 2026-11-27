"""A few short EnergyPlus runs. Excluded from the default pytest addopts.

CI runs this file with the marker so the image and the meter parser stay wired.
The full coarse-plus-refinement sweep is a worker job and is not part of CI.
"""

import pytest
from twin.eplus import simulate
from twin.eplus_calibrate import base_case

WEATHER = "USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw"


@pytest.mark.energyplus
def test_two_short_runs_score_facility_electricity():
    low = simulate(base_case(lighting_w_m2=6, plug_w_m2=4), WEATHER, "smoke", timeout=180)
    high = simulate(base_case(lighting_w_m2=16, plug_w_m2=12), WEATHER, "smoke", timeout=180)
    low_kwh = sum(low["electric"].values())
    high_kwh = sum(high["electric"].values())
    assert low_kwh > 0
    assert high_kwh > low_kwh
    assert 1 in low["electric"]
