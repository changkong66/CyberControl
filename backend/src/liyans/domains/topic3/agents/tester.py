from __future__ import annotations

from typing import Any

from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic3 import BlockType, TesterContentV1

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError

from .base import AgentExecutionContext, ProviderBackedAgent
from .prompts import common_instructions


class TesterAgent(ProviderBackedAgent[TesterContentV1]):
    source_agent = SourceAgent.TESTER
    resource_type = ResourceType.GRADIENT_QUIZ
    content_model = TesterContentV1
    block_type = BlockType.QUIZ
    content_schema_version = "topic3.tester-content.v1"
    max_output_tokens = 12288

    def prompt_instructions(self, context: AgentExecutionContext) -> list[dict[str, Any]]:
        return [
            *common_instructions(context),
            {
                "stage": "tester-matrix",
                "instruction": (
                    "Generate a balanced diagnostic set across concept, discrimination, "
                    "calculation, "
                    "engineering application, and misconception items where evidence permits. "
                    "Each item requires an answer, auditable solution steps, target "
                    "knowledge points, "
                    "difficulty, diagnostic tags, and a positive score."
                ),
            },
            {
                "stage": "tester-adaptation",
                "instruction": (
                    "Prioritize retrieval practice for high forgetting risk, increase "
                    "scaffolding for low proficiency, and use known Topic 1 misconceptions "
                    "as distractor diagnostics."
                ),
            },
        ]

    def validate_content(
        self,
        content: TesterContentV1,
        context: AgentExecutionContext,
    ) -> None:
        allowed = set(context.command.target_kp_ids)
        invalid = sorted(
            {
                kp_id
                for question in content.questions
                for kp_id in question.target_kp_ids
                if kp_id not in allowed
            }
        )
        if invalid:
            raise LiyanError(
                ErrorCode.TOPIC3_AGENT_OUTPUT_INVALID,
                "The Tester result references knowledge points outside the authorized target set.",
                category=ErrorCategory.PROVIDER,
                status_code=502,
                details={"invalid_kp_ids": invalid[:32]},
            )
