from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskImportIn(BaseModel):
    mode: Literal["skip", "upsert"] = "skip"
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskImportResultOut(BaseModel):
    ok: bool = True
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: list[dict[str, str]] = Field(default_factory=list)
    total: int = 0
