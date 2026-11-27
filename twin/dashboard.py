"""Small HTML reports. No external assets."""

from html import escape


def index_page(cards: list[dict]) -> str:
    rows = []
    if not cards:
        rows.append("<p class='muted'>No sites yet. The demo poster registers two offices on startup.</p>")
    for card in cards:
        decision = card["decision"] or "not calibrated"
        metric = "—"
        if card["cv_rmse_pct"] is not None:
            metric = (
                f"CV(RMSE) {card['cv_rmse_pct']:.1f}% · NMBE {card['nmbe_pct']:.1f}%"
                f" <span class='muted'>({escape(card['split'])} {escape(card['fuel'])})</span>"
            )
        rows.append(
            "<a class='card' href='/sites/{site}'>"
            "<strong>{site}</strong>"
            "<span>{kind}</span>"
            "<span class='pill {tone}'>{decision}</span>"
            "<span>{metric}</span>"
            "</a>".format(
                site=escape(card["site_id"]),
                kind=escape(card["building_type"]),
                tone="ok" if decision == "promoted" else "idle",
                decision=escape(decision),
                metric=metric,
            )
        )
    return _page("Sites", "<h1>Building twin</h1><p>Calibration status from monthly meter summaries.</p>" + "".join(rows))


def site_page(report: dict) -> str:
    calibration = report["calibration"]
    if calibration is None:
        cal = "<p class='muted'>No calibration yet.</p>"
    else:
        cal = (
            f"<p>Decision <span class='pill {'ok' if calibration['decision']=='promoted' else 'bad'}'>"
            f"{escape(str(calibration['decision']))}</span></p>"
            f"<p class='muted'>Engine: {escape(calibration['engine'].get('name', ''))}</p>"
            + _metric_table(calibration["metrics"])
            + _param_list(calibration["parameters"])
        )
    scenarios = _scenario_table(report["scenarios"])
    setpoints = _setpoint_table(report["setpoints"])
    body = (
        f"<p><a href='/'>All sites</a></p>"
        f"<h1>{escape(report['site_id'])}</h1>"
        f"<p>{escape(report['building_type'])} · {report['floor_area_m2']:.0f} m² · "
        f"{escape(report['timezone'])} · {report['months_received']} summaries</p>"
        f"<h2>Guideline 14</h2>{cal}"
        f"<h2>ROI what-ifs</h2>{scenarios}"
        f"<h2>Setpoints</h2>{setpoints}"
    )
    return _page(report["site_id"], body)


def _metric_table(metrics: list[dict]) -> str:
    if not metrics:
        return "<p class='muted'>No metrics.</p>"
    rows = []
    for item in metrics:
        limits = item.get("limits") or {}
        limit_text = "—"
        if limits:
            limit_text = f"{limits['cv_rmse_pct']:.0f}% / {limits['nmbe_pct']:.0f}%"
        passed = item.get("pass")
        label = "pass" if passed else ("fail" if passed is False else "diagnostic")
        rows.append(
            "<tr><td>{split}</td><td>{fuel}</td><td>{grain}</td><td>{n}</td>"
            "<td>{cv:.1f}%</td><td>{nmbe:.1f}%</td><td>{limits}</td>"
            "<td class='{tone}'>{label}</td></tr>".format(
                split=escape(str(item["split"])),
                fuel=escape(str(item["fuel"])),
                grain=escape(str(item["granularity"])),
                n=item["n"],
                cv=item["cv_rmse_pct"],
                nmbe=item["nmbe_pct"],
                limits=limit_text,
                tone="ok" if passed else "bad",
                label=label,
            )
        )
    return (
        "<table><thead><tr><th>Split</th><th>Fuel</th><th></th><th>n</th>"
        "<th>CV(RMSE)</th><th>NMBE</th><th>Limits</th><th></th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _param_list(parameters: dict) -> str:
    parts = [f"<li>{escape(name)}: {value}</li>" for name, value in parameters.items()]
    return "<ul>" + "".join(parts) + "</ul>"


def _scenario_table(scenarios: list[dict]) -> str:
    if not scenarios:
        return "<p class='muted'>No what-ifs yet.</p>"
    rows = []
    for item in scenarios:
        result = item.get("result") or {}
        payback = result.get("simple_payback_years")
        payback_text = "—" if payback is None else f"{payback:.1f} y"
        band = result.get("cost_savings_band_usd") or [None, None]
        rows.append(
            "<tr><td>{name}</td><td>{kwh:.0f}</td><td>{therms:.1f}</td><td>{usd:,.0f}</td>"
            "<td>{payback}</td><td>{npv:,.0f}</td><td>{low:,.0f} – {high:,.0f}</td></tr>".format(
                name=escape(item["name"]),
                kwh=result.get("annual_kwh_savings") or 0,
                therms=result.get("annual_therm_savings") or 0,
                usd=result.get("annual_cost_savings_usd") or 0,
                payback=payback_text,
                npv=result.get("npv_usd") or 0,
                low=band[0] or 0,
                high=band[1] or 0,
            )
        )
    return (
        "<table><thead><tr><th>What-if</th><th>kWh/y</th><th>therm/y</th><th>$/y</th>"
        "<th>Payback</th><th>NPV</th><th>Band</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _setpoint_table(setpoints: list[dict]) -> str:
    if not setpoints:
        return "<p class='muted'>No setpoints.</p>"
    rows = []
    for item in setpoints:
        confidence = item.get("confidence")
        confidence_text = "—" if confidence is None else f"{confidence:.2f}"
        rows.append(
            "<tr><td>{eq}</td><td>{kind}</td><td>{period}</td><td>{value}</td><td>{unit}</td>"
            "<td>{source}</td><td>{confidence}</td><td>{method}</td></tr>".format(
                eq=escape(str(item["equipment_id"])),
                kind=escape(str(item["kind"])),
                period=escape(str(item["period"])),
                value=item["value"],
                unit=escape(str(item["unit"])),
                source=escape(str(item["source"])),
                confidence=confidence_text,
                method=escape(str(item.get("method") or "")),
            )
        )
    return (
        "<table><thead><tr><th>Equipment</th><th>Kind</th><th>Period</th><th>Value</th>"
        "<th>Unit</th><th>Source</th><th>Confidence</th><th>Method</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; font: 16px/1.45 ui-sans-serif, system-ui, sans-serif; background: #f4f1ea; color: #1d1a16; }}
main {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 64px; }}
h1 {{ font-size: 1.8rem; margin-bottom: 0.2rem; }}
h2 {{ margin-top: 2rem; font-size: 1.15rem; }}
a {{ color: #1f4b6e; }}
.card {{ display: grid; gap: 4px; margin: 12px 0; padding: 16px; background: white; border-radius: 12px;
  text-decoration: none; color: inherit; box-shadow: 0 1px 0 rgba(0,0,0,0.04); }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 12px; overflow: hidden; }}
th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; font-variant-numeric: tabular-nums; }}
th {{ font-size: 0.78rem; letter-spacing: 0.03em; text-transform: uppercase; color: #655e55; }}
.pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #ece7df; font-size: 0.85rem; }}
.ok {{ color: #0d6b3d; }}
.bad {{ color: #8d2430; }}
.muted {{ color: #655e55; }}
</style>
</head>
<body><main>{body}</main></body>
</html>"""
