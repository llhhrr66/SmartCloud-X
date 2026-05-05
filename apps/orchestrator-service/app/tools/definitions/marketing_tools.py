from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..registry import ToolDefinition

# ——————————————————————————————————————
# input / output schemas
# ——————————————————————————————————————


class GeneratePosterInput(BaseModel):
    title: str = Field(..., min_length=1, description="poster title")
    subtitle: str | None = None
    style: Literal["modern", "classic", "tech", "minimal"] = "modern"
    width: int = Field(default=1080, ge=100, le=4096)
    height: int = Field(default=1920, ge=100, le=4096)


class GeneratePosterOutput(BaseModel):
    poster_url: str
    thumbnail_url: str | None = None


class CreateCampaignInput(BaseModel):
    name: str = Field(..., min_length=1)
    description: str | None = None
    channel: Literal["email", "sms", "social", "all"] = "all"
    scheduled_at: str | None = None


class CreateCampaignOutput(BaseModel):
    campaign_id: str
    status: str = "created"


class GenerateCopyInput(BaseModel):
    product_name: str = Field(..., min_length=1)
    tone: Literal["professional", "casual", "humorous", "urgent"] = "professional"
    target_audience: str = "general"
    max_length: int = Field(default=200, ge=10, le=2000)


class GenerateCopyOutput(BaseModel):
    copy_text: str
    variations: list[str] = Field(default_factory=list)


# ——————————————————————————————————————
# tool definitions
# ——————————————————————————————————————

marketing_tools: list[ToolDefinition] = [
    ToolDefinition(
        name="generate_poster",
        description="generate a marketing poster with specified style and dimensions",
        input_schema=GeneratePosterInput,
        output_schema=GeneratePosterOutput,
        is_readonly=False,
        allowed_roles=["marketing", "admin"],
    ),
    ToolDefinition(
        name="create_campaign",
        description="create a marketing campaign",
        input_schema=CreateCampaignInput,
        output_schema=CreateCampaignOutput,
        is_readonly=False,
        allowed_roles=["marketing", "admin"],
    ),
    ToolDefinition(
        name="generate_copy",
        description="generate marketing copy with specified tone",
        input_schema=GenerateCopyInput,
        output_schema=GenerateCopyOutput,
        is_readonly=True,
        allowed_roles=["marketing", "admin"],
    ),
]
