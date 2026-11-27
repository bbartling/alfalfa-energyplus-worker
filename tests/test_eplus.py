import pytest
from twin.eplus import monthly_energy, weather_file
from twin.eplus_calibrate import apply_measures, base_case, conditions_from_payloads, fit, price_energyplus
from twin.idfedit import MODEL_AREA_M2, apply_case, load_model, parse_idf


def test_summaries_set_the_occupied_window_and_setpoints():
    payloads = [
        {
            "schedules": [{"windows": [{"days": "weekday", "start": "07:00", "end": "18:00"}]}],
            "setpoints": [
                {"kind": "zone_heating", "period": "occupied", "value": 21.0},
                {"kind": "zone_cooling", "period": "occupied", "value": 24.0},
                {"kind": "zone_heating", "period": "unoccupied", "value": 18.0},
                {"kind": "zone_cooling", "period": "unoccupied", "value": 27.0},
            ],
        }
    ]
    case = conditions_from_payloads(payloads)
    assert case["occupied_start"] == "07:00"
    assert case["occupied_end"] == "18:00"
    assert case["heating_setpoint_c"] == 21.0
    assert case["unoccupied_cooling_c"] == 27.0


def test_case_is_written_into_the_prototype():
    case = base_case(
        lighting_w_m2=11,
        plug_w_m2=9,
        fan_efficiency=0.5,
        cooling_cop=3.2,
        infiltration_multiplier=2,
        occupied_start="07:00",
        occupied_end="18:00",
        heating_setpoint_c=21,
        unoccupied_heating_c=15.6,
    )
    original = next(obj for obj in load_model() if obj[0] == "ZoneInfiltration:DesignFlowRate" and obj[1].startswith("Perimeter"))
    edited = parse_idf(apply_case(load_model(), case, "smoke"))
    lights = next(obj for obj in edited if obj[0] == "Lights")
    plugs = next(obj for obj in edited if obj[0] == "ElectricEquipment")
    fan = next(obj for obj in edited if obj[0] == "Fan:OnOff")
    coil = next(obj for obj in edited if obj[0] == "Coil:Cooling:DX:SingleSpeed")
    infiltration = next(obj for obj in edited if obj[0] == "ZoneInfiltration:DesignFlowRate" and obj[1].startswith("Perimeter"))
    run_period = next(obj for obj in edited if obj[0] == "RunPeriod")
    heating = next(obj for obj in edited if obj[0] == "Schedule:Day:Interval" and "HTGSETP" in obj[1] and "Wknd" not in obj[1])
    assert float(lights[6]) == 11
    assert float(plugs[6]) == 9
    assert float(fan[3]) == 0.5
    assert float(coil[5]) == 3.2
    assert float(infiltration[7]) == pytest.approx(float(original[7]) * 2, rel=1e-4)
    assert (run_period[2], run_period[3], run_period[5], run_period[6]) == ("1", "1", "1", "3")
    assert "07:00" in heating and "21" in heating


def test_coarse_grid_then_refinement_recovers_the_better_lighting_level():
    months = [
        {"start": f"2026-0{month}-01T00:00:00+00:00", "electric_kwh": 100.0, "gas_therms": None}
        for month in range(1, 5)
    ]

    def run_fn(case, _span):
        kwh = 100 + abs(case["lighting_w_m2"] - 10)
        return {"electric": {month: kwh for month in range(1, 13)}, "gas": {}}

    fitted = fit(base_case(), months, MODEL_AREA_M2, run_fn)
    assert fitted["runs"] == 76
    assert fitted["parameters"]["lighting_w_m2"] == 10
    assert fitted["decision"] == "promoted"
    assert fitted["engine"]["name"] == "energyplus"
    assert fitted["engine"]["openstudio"] == "3.9.0"
    assert all(item["pass"] for item in fitted["metrics"])


def test_monthly_energy_reads_facility_meters_when_warmup_is_null(tmp_path):
    import sqlite3

    path = tmp_path / "eplusout.sql"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE EnvironmentPeriods (EnvironmentPeriodIndex INTEGER, EnvironmentName TEXT, EnvironmentType INTEGER);
        INSERT INTO EnvironmentPeriods VALUES (1, 'RUN PERIOD 1', 3);
        CREATE TABLE Time (TimeIndex INTEGER, Month INTEGER, WarmupFlag INTEGER, EnvironmentPeriodIndex INTEGER);
        INSERT INTO Time VALUES (1, 1, NULL, 1), (2, 1, 1, 1);
        CREATE TABLE ReportDataDictionary (
            ReportDataDictionaryIndex INTEGER, Name TEXT, ReportingFrequency TEXT, Units TEXT
        );
        INSERT INTO ReportDataDictionary VALUES (1, 'Electricity:Facility', 'Hourly', 'J');
        INSERT INTO ReportDataDictionary VALUES (2, 'NaturalGas:Facility', 'Hourly', 'J');
        CREATE TABLE ReportData (TimeIndex INTEGER, ReportDataDictionaryIndex INTEGER, Value REAL);
        INSERT INTO ReportData VALUES (1, 1, 3600000), (2, 1, 999), (1, 2, 105480400);
        """
    )
    connection.close()
    totals = monthly_energy(path)
    assert totals["electric"][1] == pytest.approx(1.0)
    assert totals["gas"][1] == pytest.approx(1.0)


def test_what_if_reruns_the_calibrated_energyplus_case():
    case = base_case(cooling_setpoint_c=24, occupied_end="18:00")
    calls = []

    def run_fn(current, span):
        calls.append((current["cooling_setpoint_c"], current["occupied_end"], span))
        kwh = 50 if current["cooling_setpoint_c"] > 24 else 80
        return {"electric": {month: kwh for month in range(1, 13)}, "gas": {month: 1 for month in range(1, 13)}}

    other = dict(case)
    other["lighting_w_m2"] = 12
    priced = price_energyplus(
        case,
        [{"name": "raise_cooling_setpoint", "delta_c": 1}],
        {
            "implementation_usd": 2500,
            "electricity_usd_per_kwh": 0.14,
            "gas_usd_per_therm": 1.1,
            "discount_rate": 0,
            "horizon_years": 1,
        },
        MODEL_AREA_M2,
        run_fn,
        ensemble=[case, other],
    )
    assert calls[0] == (24, "18:00", "year")
    assert calls[1][0] == 25
    assert priced["annual_kwh_savings"] == pytest.approx(30 * 12)
    assert priced["engine"] == "energyplus"
    assert priced["runs"] == 3
    trimmed = apply_measures(case, [{"name": "trim_run_hours", "fraction": 0.2}])
    assert trimmed["occupied_end"] == "16:00"


def test_weather_file_follows_latitude():
    assert weather_file(41).startswith("USA_IL_Chicago")
    assert weather_file(39.7).startswith("USA_MD_Baltimore")
    assert "Miami" in weather_file(25)
