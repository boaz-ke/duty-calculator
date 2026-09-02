"""Calculation engine mirroring the KRA TEMPLATE formulas."""

from __future__ import annotations

import math
from datetime import date
from typing import Any


VEHICLE_TYPES = {
    "passenger": "Passenger car / SUV / wagon (≤9 seats)",
    "pickup": "Pick-up (single / double cab)",
    "van_minibus": "Van / mini-bus",
    "bus": "Bus / lorry / truck",
    "school_bus": "School bus (public school)",
    "ambulance": "Ambulance",
    "prime_mover": "Prime mover (tractor head)",
    "trailer": "Trailer",
    "motorcycle": "Motor cycle",
    "machinery": "Tractor / grader / heavy machinery",
    "special_purpose": "Special purpose vehicle",
}

ROUTE_LABELS = {
    "direct": "Direct import to Kenya",
    "registered": "Previously registered in Kenya",
}


def current_year() -> int:
    return date.today().year


def years_old(yom: int, year: int | None = None) -> int:
    return max(0, (year if year is not None else current_year()) - yom)


def classify_block(
    vehicle_type: str,
    fuel: str = "",
    engine_cc: float | None = None,
) -> tuple[str, str]:
    """Return the template block key and a human-readable explanation."""
    direct = {
        "school_bus": "school_bus",
        "ambulance": "ambulance",
        "prime_mover": "prime_mover",
        "trailer": "trailer",
        "motorcycle": "motorcycle",
        "machinery": "heavy_machinery",
        "special_purpose": "special_purpose",
    }
    if vehicle_type in direct:
        return direct[vehicle_type], VEHICLE_TYPES[vehicle_type]

    regular = {"passenger", "pickup", "van_minibus", "bus"}
    if vehicle_type not in regular:
        raise ValueError("Unknown vehicle type.")

    if fuel == "electric" and vehicle_type in {"passenger", "van_minibus", "bus"}:
        return "electric", "100% electric vehicle"
    if fuel == "electric":
        raise ValueError(
            "Electric pick-ups and trucks do not map to a template block in this release; "
            "choose a different vehicle type or contact an administrator."
        )
    if fuel not in {"petrol", "diesel", "hybrid", "gas", ""}:
        raise ValueError("Unknown fuel type.")
    if engine_cc is None:
        raise ValueError("Engine capacity (cc) is required for this vehicle type.")
    if vehicle_type == "passenger" and (
        (fuel in {"petrol", "hybrid", "gas", ""} and engine_cc > 3000)
        or (fuel == "diesel" and engine_cc > 2500)
    ):
        return "mv_high_cc", "Petrol >3000cc / diesel >2500cc passenger vehicle"
    if engine_cc <= 1500:
        return "mv_small", "Engine capacity not exceeding 1500cc"
    return "mv_large", "Engine capacity exceeding 1500cc"


def depreciation_rate(
    dep_rows: list[dict[str, Any]], route: str, age: int | float
) -> float | None:
    """Find the depreciation rate for a route/age combination.

    Direct-import rows use bands such as '>1 <=2 years'; registered rows use
    exact age labels (1..15, then 'over 15 years').
    """
    if age <= 0:
        return 0.0
    if route == "registered":
        exact = {row["low"]: row["rate"] for row in dep_rows if row["low"] is not None}
        if age > 15:
            for row in dep_rows:
                if row["low"] == 999:
                    return row["rate"]
            return None
        key = int(age)
        return exact.get(key, 0.0)

    # direct imports
    for row in dep_rows:
        low = row.get("low")
        high = row.get("high")
        if low is not None and high is not None and low < age <= high:
            return row["rate"]
    if age <= 1:
        return 0.0
    return None


def calculate(
    block: dict[str, Any],
    route: str,
    crsp: float,
    depreciation: float,
    extra_depreciation: float = 0.0,
) -> dict[str, Any]:
    """Compute the full tax breakdown for one calculation."""
    if crsp <= 0:
        raise ValueError("CRSP value must be greater than zero.")
    if depreciation is None:
        raise ValueError("No depreciation rate is defined for this age and route.")
    if not 0 <= depreciation <= 1 or not 0 <= extra_depreciation <= 1:
        raise ValueError("Depreciation must be between 0% and 100%.")

    backout = block.get("backout_divisors") or []
    divisor_product = math.prod(backout)
    if not divisor_product:
        raise ValueError("Invalid tax block configuration.")

    customs_value = (
        (crsp / block["initial_divisor"]) * (1 - depreciation) / divisor_product
    ) * (1 - extra_depreciation)

    import_duty = customs_value * (block.get("duty_rate") or 0.0)
    excise_fixed = block.get("excise_fixed")
    if excise_fixed is not None:
        excise_duty = float(excise_fixed)
        excise_value = customs_value + import_duty
        vat_base = customs_value + import_duty + excise_duty
    else:
        excise_value = customs_value + import_duty
        excise_duty = excise_value * (block.get("excise_rate") or 0.0)
        vat_base = excise_value + excise_duty

    vat = vat_base * (block.get("vat_rate") or 0.0)
    is_direct = route == "direct"
    rdl = customs_value * (block.get("rdl_rate") or 0.0) if is_direct else 0.0
    idf = customs_value * (block.get("idf_rate") or 0.0) if is_direct else 0.0
    grand_total = import_duty + excise_duty + vat + rdl + idf

    return {
        "customs_value": round(customs_value, 2),
        "import_duty": round(import_duty, 2),
        "excise_value": round(excise_value, 2),
        "excise_duty": round(excise_duty, 2),
        "vat_base": round(vat_base, 2),
        "vat": round(vat, 2),
        "rdl": round(rdl, 2),
        "idf": round(idf, 2),
        "grand_total": round(grand_total, 2),
        "per_1000": round(grand_total / crsp * 1000.0, 2),
    }
