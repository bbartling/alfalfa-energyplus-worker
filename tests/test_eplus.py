import pytest
from twin.eplus import monthly_energy, weather_file
from twin.eplus_calibrate import apply_measures, base_case, conditions_from_payloads, fit, price_energyplus
from twin.idfedit import MODEL_AREA_M2, apply_case, load_model, parse_idf
from twin.weather import nearest_station


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


def test_hour_of_week_builds_the_weekday_and_weekend_masks():
    profile = []
    for day in range(7):
        for hour in range(24):
            profile.append(0.9 if day < 5 and 9 <= hour < 15 else 0.05)
    case = conditions_from_payloads(
        [
            {
                "run_hours": [{"hour_of_week": profile}],
                "schedules": [{"windows": [{"days": "weekday", "start": "07:00", "end": "18:00"}]}],
            }
        ]
    )
    assert case["occupied_start"] == "09:00"
    assert case["occupied_end"] == "15:00"
    assert case["weekday_hours"][9] and not case["weekday_hours"][8]
    assert not any(case["weekend_hours"])


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
    heating = next(obj for obj in edited if obj[0] == "Schedule:Day:Interval" and obj[1].endswith("HTGSETP_SCH_NO_OPTIMUM Wkdy Day"))
    assert float(lights[6]) == 11
    assert float(plugs[6]) == 9
    assert float(fan[3]) == 0.5
    assert float(coil[5]) == 3.2
    assert float(infiltration[7]) == pytest.approx(float(original[7]) * 2, rel=1e-4)
    assert (run_period[2], run_period[3], run_period[5], run_period[6]) == ("1", "1", "1", "3")
    assert "07:00" in heating and "21" in heating
    weekend = next(obj for obj in edited if obj[0] == "Schedule:Day:Interval" and obj[1].endswith("HTGSETP_SCH_NO_OPTIMUM Default"))
    original_design = next(
        obj for obj in load_model() if obj[0] == "Schedule:Day:Interval" and obj[1].endswith("HTGSETP_SCH_NO_OPTIMUM Winter Design Day")
    )
    design = next(obj for obj in edited if obj[1] == original_design[1])
    assert weekend[4:] == ["24:00", "15.6"]
    assert design[4:] == original_design[4:]
    assert not any(obj[0] == "RunPeriodControl:DaylightSavingTime" for obj in edited)
    denver = nearest_station(39.74, -104.99)
    located = parse_idf(apply_case(load_model(), case, "smoke", station=denver))
    location = next(obj for obj in located if obj[0] == "Site:Location")
    heating_day = next(obj for obj in located if obj[0] == "SizingPeriod:DesignDay" and obj[4] == "WinterDesignDay")
    assert location[1] == denver["city"]
    assert float(location[2]) == pytest.approx(denver["latitude"])
    assert "Denver" in denver["file"]
    assert denver["weather_kind"] == "tmy3"
    expected = next(day for day in denver["design_days"] if day[4] == "WinterDesignDay")
    assert float(heating_day[5]) == pytest.approx(float(expected[5]))


def test_heat_pump_writes_heating_cop_and_gas_locks_the_compressor_out():
    heat_pump = parse_idf(apply_case(load_model(), base_case(heating_fuel="heat_pump", heating_cop=2.5), "smoke"))
    dx = next(obj for obj in heat_pump if obj[0] == "Coil:Heating:DX:SingleSpeed")
    assert float(dx[4]) == 2.5
    gas = parse_idf(apply_case(load_model(), base_case(heating_fuel="gas"), "smoke"))
    locked = next(obj for obj in gas if obj[0] == "Coil:Heating:DX:SingleSpeed")
    unitary = next(obj for obj in gas if obj[0] == "AirLoopHVAC:UnitarySystem")
    fuel = next(obj for obj in gas if obj[0] == "Coil:Heating:Fuel")
    assert "99" in locked
    assert "50" in unitary
    assert fuel[3] == "NaturalGas"
    electric = parse_idf(apply_case(load_model(), base_case(heating_fuel="electric"), "smoke"))
    assert next(obj for obj in electric if obj[0] == "Coil:Heating:Fuel")[3] == "Electricity"


def test_heat_pump_sweep_adds_heating_cop():
    from twin.eplus_calibrate import coarse_cases

    assert len(coarse_cases(base_case())) == 64
    assert len(coarse_cases(base_case(heating_fuel="heat_pump"))) == 128


def test_coarse_grid_then_refinement_recovers_the_better_lighting_level():
    months = [
        {"start": f"2025-{month:02d}-01T00:00:00+00:00", "electric_kwh": 100.0, "gas_therms": None}
        for month in range(1, 13)
    ]

    def run_fn(case, _span):
        kwh = 100 + abs(case["lighting_w_m2"] - 10)
        return {"electric": {month: kwh for month in range(1, 13)}, "gas": {}}

    fitted = fit(base_case(), months, MODEL_AREA_M2, run_fn)
    assert fitted["runs"] == 76
    assert fitted["parameters"]["lighting_w_m2"] == 10
    assert fitted["decision"] == "promoted"
    assert fitted["engine"]["n_tuned_parameters"] == 6
    assert any(item["split"] == "loocv" and item["claim"] == "diagnostic" for item in fitted["metrics"])
    assert all(item["claim"] == "guideline14" for item in fitted["metrics"] if item["split"] == "all")
    assert fitted["engine"]["name"] == "energyplus"
    assert fitted["engine"]["openstudio"] == "3.9.0"
    assert all(item["pass"] for item in fitted["metrics"] if item["claim"] == "guideline14")


def test_fewer_than_twelve_months_is_not_a_guideline_14_claim():
    months = [
        {"start": f"2026-0{month}-01T00:00:00+00:00", "electric_kwh": 100.0, "gas_therms": None}
        for month in range(1, 5)
    ]

    def run_fn(_case, _span):
        return {"electric": {month: 100.0 for month in range(1, 13)}, "gas": {}}

    fitted = fit(base_case(), months, MODEL_AREA_M2, run_fn)
    assert fitted["decision"] == "insufficient-data"
    assert all(item["claim"] == "insufficient-data" for item in fitted["metrics"] if item["split"] == "all")


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
    assert priced["runs"] == 4
    assert priced["cost_savings_band_usd"][0] == pytest.approx(priced["cost_savings_band_usd"][1])
    trimmed = apply_measures(case, [{"name": "trim_run_hours", "fraction": 0.2}])
    assert trimmed["occupied_end"] == "16:00"


def test_the_calibrated_idf_hash_is_stable():
    from twin.eplus import idf_artifact

    first = idf_artifact(base_case(), "smoke")
    second = idf_artifact(base_case(), "smoke")
    assert first["idf_sha256"] == second["idf_sha256"]
    assert len(first["idf_sha256"]) == 64
    assert "idf" in first and first["idf"]


def test_weather_file_follows_latitude():
    assert weather_file(41.98, -87.92).startswith("USA_IL_Chicago")
    assert weather_file(39.17, -76.67).startswith("USA_MD_Baltimore")
    assert "Miami" in weather_file(25.8, -80.3)
    denver = weather_file(39.74, -104.99)
    assert "Denver" in denver and "Baltimore" not in denver
