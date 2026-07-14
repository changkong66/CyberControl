from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from .common import FROZEN_MODEL_CONFIG, MUTABLE_MODEL_CONFIG


class ProviderCapability(StrEnum):
    TEXT_GENERATION = "TEXT_GENERATION"
    CODE_ASSISTANCE = "CODE_ASSISTANCE"
    MULTIMODAL_GENERATION = "MULTIMODAL_GENERATION"
    EMBEDDING = "EMBEDDING"


class ProviderStatus(StrEnum):
    ALLOWLISTED_DISABLED = "ALLOWLISTED_DISABLED"
    ENABLED = "ENABLED"
    PROHIBITED = "PROHIBITED"


class LiteToolDefinitionV1(BaseModel):
    model_config = FROZEN_MODEL_CONFIG

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1024)
    input_schema: dict[str, Any]


class ResponsesLiteRequestV1(BaseModel):
    """Internal provider-neutral request, translated by approved adapters."""

    model_config = MUTABLE_MODEL_CONFIG

    schema_version: Literal["responses.lite.request.v1"]
    request_id: UUID
    provider_alias: Literal["spark_text", "xfyun_code", "seedance"]
    model_alias: str = Field(min_length=1, max_length=128)
    instructions: list[dict[str, Any]] = Field(min_length=1, max_length=64)
    tools: list[LiteToolDefinitionV1] = Field(min_length=1, max_length=64)
    input_segments: list[dict[str, Any]] = Field(min_length=1, max_length=1024)
    response_schema: dict[str, Any]
    temperature: float = Field(ge=0.0, le=0.3)
    max_output_tokens: int = Field(ge=128)
    timeout_ms: int = Field(ge=1000, le=120000)
