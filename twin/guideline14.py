"""ASHRAE Guideline 14 CV(RMSE) and NMBE.

NMBE = sum(y - yhat) / ((n - p) * mean(y)) * 100
CV(RMSE) = sqrt(sum((y - yhat)^2) / (n - p)) / mean(y) * 100

Hourly limits are 30% and 10%. Monthly limits are 15% and 5%.
`p` defaults to 1 and is recorded with every result. Daily data is a
diagnostic only; it is not a Guideline 14 claim.
"""

from __future__ import annotations

import math

LIMITS = {
    "hourly": {"cv_rmse_pct": 30.0, "nmbe_pct": 10.0},
    "monthly": {"cv_rmse_pct": 15.0, "nmbe_pct": 5.0},
}


def cv_rmse_nmbe(measured: list[float], simulated: list[float], p: int = 1) -> dict:
    if len(measured) != len(simulated) or not measured:
        raise ValueError("measured and simulated series must be the same non-empty length")
    n = len(measured)
    if p < 0 or n <= p:
        raise ValueError("n - p must be positive")
    mean = sum(measured) / n
    if mean == 0:
        raise ValueError("mean measured energy is zero")
    residual = [y - yhat for y, yhat in zip(measured, simulated, strict=True)]
    nmbe = sum(residual) / ((n - p) * mean) * 100
    cv = math.sqrt(sum(item * item for item in residual) / (n - p)) / mean * 100
    return {"n": n, "p": p, "cv_rmse_pct": cv, "nmbe_pct": nmbe}


def assess(measured: list[float], simulated: list[float], granularity: str, p: int = 1) -> dict:
    stats = cv_rmse_nmbe(measured, simulated, p=p)
    limits = LIMITS.get(granularity)
    if limits is None:
        passed = None
        claim = "diagnostic"
    else:
        passed = stats["cv_rmse_pct"] <= limits["cv_rmse_pct"] and abs(stats["nmbe_pct"]) <= limits["nmbe_pct"]
        claim = "guideline14"
    return {
        **stats,
        "granularity": granularity,
        "limits": limits,
        "pass": passed,
        "claim": claim,
    }
