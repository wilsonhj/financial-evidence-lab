"""Asynchronous worker packages for Financial Evidence Lab.

Concrete ingestion (M1), extraction (M3), and forecasting (M5) workers are
delivered by their milestone packages. The scaffold only declares the shared
worker metadata so the monorepo, tooling, and tests have a stable target.
"""

__version__ = "0.0.0"

WORKSTREAMS = ("ingestion", "extraction", "forecasting")
