"""Closed extraction transport types; no persistence or financial computation."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

Action = Literal["create", "cancel", "rerun", "accept", "edit", "reject", "merge", "correct"]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractionPermissions(ClosedModel):
    workspace_id: UUID
    allowed_actions: list[Action]
