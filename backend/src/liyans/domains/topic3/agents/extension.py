from __future__ import annotations

from typing import Any

from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic3 import BlockType, ExtensionContentV1

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError

from .base import AgentExecutionContext, ProviderBackedAgent
from .prompts import common_instructions


class ExtensionAgent(ProviderBackedAgent[ExtensionContentV1]):
    source_agent = SourceAgent.EXTENSION
    resource_type = ResourceType.EXTENSION_MATERIAL
    content_model = ExtensionContentV1
    block_type = BlockType.EXTENSION
    content_schema_version = "topic3.extension-content.v1"

    def prompt_instructions(self, context: AgentExecutionContext) -> list[dict[str, Any]]:
        return [
            *common_instructions(context),
            {
                "stage": "extension-grounding",
                "instruction": (
                    "Every extension must explicitly connect to requested knowledge points "
                    "and include a citation text. Never invent a DOI, publication venue, "
                    "author, standard number, or URL. When Topic 1 evidence lacks a "
                    "verifiable source, describe an engineering direction "
                    "without fabricating bibliographic metadata."
                ),
            },
        ]

    def validate_content(
        self,
        content: ExtensionContentV1,
        context: AgentExecutionContext,
    ) -> None:
        allowed = set(context.command.target_kp_ids)
        for resource in content.resources:
            if not set(resource.relevance_to_kp_ids) <= allowed:
                raise LiyanError(
                    ErrorCode.TOPIC3_AGENT_OUTPUT_INVALID,
                    "The Extension result escaped the authorized knowledge-point boundary.",
                    category=ErrorCategory.PROVIDER,
                    status_code=502,
                    details={"resource_id": resource.resource_id},
                )
