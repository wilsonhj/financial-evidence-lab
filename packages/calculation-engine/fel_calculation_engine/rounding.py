"""ISO 4217 minor-unit quanta for quantizing currency amounts at graph edges (T0403)."""

from __future__ import annotations

from decimal import Decimal

from fel_calculation_engine.errors import UnitError

# Minor units per ISO 4217 (2024 list). Everything not listed here is unknown to the
# engine and must be given an explicit quantum — the engine never guesses cents.
_MINOR_UNITS: dict[str, int] = {
    **dict.fromkeys(
        (
            "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BMD BND BOB BRL BSD BTN "
            "BWP BYN BZD CAD CDF CHF CNY COP CRC CUP CVE CZK DKK DOP DZD EGP ERN ETB EUR FJD "
            "FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IRR JMD KES KGS "
            "KHR KYD KZT LAK LBP LKR LRD LSL MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN "
            "MYR MZN NAD NGN NIO NOK NPR NZD PAB PEN PGK PHP PKR PLN QAR RON RSD RUB SAR SBD "
            "SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TOP TRY TTD TWD "
            "TZS UAH USD UYU UZS WST YER ZAR ZMW ZWG"
        ).split(),
        2,
    ),
    **dict.fromkeys("BIF CLP DJF GNF ISK JPY KMF KRW PYG RWF UGX VND VUV XAF XOF XPF".split(), 0),
    **dict.fromkeys("BHD IQD JOD KWD LYD OMR TND".split(), 3),
    "CLF": 4,
    "UYW": 4,
}


def minor_unit_quantum(currency: str) -> Decimal:
    """``Decimal("0.01")`` for USD, ``Decimal("1")`` for JPY, ``Decimal("0.001")`` for KWD."""
    try:
        digits = _MINOR_UNITS[currency]
    except KeyError as exc:
        raise UnitError(
            f"no ISO 4217 minor unit known for {currency!r}; supply an explicit quantum",
            currency=currency,
        ) from exc
    return Decimal(1).scaleb(-digits)


__all__ = ["minor_unit_quantum"]
