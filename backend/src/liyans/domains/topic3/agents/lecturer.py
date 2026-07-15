from __future__ import annotations

from typing import Any

from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic3 import BlockType, LecturerContentV1

from .base import AgentExecutionContext, ProviderBackedAgent
from .prompts import common_instructions


class LecturerAgent(ProviderBackedAgent[LecturerContentV1]):
    source_agent = SourceAgent.LECTURER
    resource_type = ResourceType.LECTURER_DOC
    content_model = LecturerContentV1
    block_type = BlockType.MARKDOWN
    content_schema_version = "topic3.lecturer-content.v1"
    max_output_tokens = 12288

    def prompt_instructions(self, context: AgentExecutionContext) -> list[dict[str, Any]]:
        return [
            *common_instructions(context),
            {
                "stage": "lecturer-structure",
                "instruction": (
                    "Produce objectives, progressive classroom sections, a concise summary, "
                    "misconception alerts, and explicit personalization notes. Every section must "
                    "bind to at least one requested knowledge point."
                ),
            },
            {
                "stage": "lecturer-depth",
                "instruction": (
                    f"Use {context.command.lecturer_depth.value} depth. Reinforce "
                    "low-retrievability knowledge, avoid redundant explanation of "
                    "strongly mastered material, and keep "
                    "all formulas and factual claims within Topic 1 evidence."
                ),
            },
        ]
