"""Role module exports."""

from __future__ import annotations

from fel_workers.extraction.roles.base import ROLE_SPECS, RoleSpec, load_role_specs
from fel_workers.extraction.types import Role

__all__ = ["ROLE_SPECS", "Role", "RoleSpec", "load_role_specs"]
