"""Accounting identity checks (billings / margins / RPO preferences)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def check_accounting(payload: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    metric_id = payload.get("metric_id")
    if metric_id == "billings":
        # Billings may only be derived with cited revenue + Δdeferred (enforced via evidence).
        if payload.get("reported_or_derived") == "derived":
            lineage = payload.get("qualifiers", {}).get("derivation_inputs")
            if not isinstance(lineage, list) or len(lineage) < 2:
                blockers.append("billings_derivation_inputs_missing")
    if metric_id == "svc_gm":
        # Never proxy blended margin.
        if payload.get("qualifiers", {}).get("basis") == "blended":
            blockers.append("svc_gm_blended_forbidden")
    if metric_id == "crpo":
        # cRPO needs timing dimension verification.
        dims = payload.get("dimensions") or {}
        if "horizon" not in dims and "timing_verified" not in (payload.get("qualifiers") or {}):
            blockers.append("crpo_timing_unverified")
    if metric_id in {"sub_gm", "svc_gm"} and "value" in payload:
        try:
            value = Decimal(str(payload["value"]))
            if value > 100 and payload.get("unit") == "percent":
                blockers.append("margin_percent_out_of_range")
        except Exception:  # noqa: BLE001
            blockers.append("margin_value_invalid")
    return blockers


__all__ = ["check_accounting"]
