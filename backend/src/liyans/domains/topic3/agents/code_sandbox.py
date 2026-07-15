from __future__ import annotations

import re
from typing import Any

from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic3 import BlockType, CodeSandboxContentV1

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError

from .base import AgentExecutionContext, ProviderBackedAgent
from .prompts import common_instructions

PROHIBITED_CODE_PATTERNS = (
    re.compile(r"\b(?:os\.system|subprocess|socket|requests|urllib|shutil|eval|exec)\b"),
    re.compile(r"\b(?:system|unix|dos|webread|webwrite|ftp|tcpclient|udpport)\s*\(", re.I),
    re.compile(r"\b(?:fopen|delete|rmdir|movefile|copyfile)\s*\(", re.I),
)


class CodeSandboxAgent(ProviderBackedAgent[CodeSandboxContentV1]):
    source_agent = SourceAgent.CODE_SANDBOX
    resource_type = ResourceType.SIMULATION_CODE
    content_model = CodeSandboxContentV1
    block_type = BlockType.CODE
    content_schema_version = "topic3.code-sandbox-content.v1"
    max_output_tokens = 12288

    def prompt_instructions(self, context: AgentExecutionContext) -> list[dict[str, Any]]:
        return [
            *common_instructions(context),
            {
                "stage": "code-runtime-boundary",
                "instruction": (
                    "Generate only deterministic Python numerical simulation or MATLAB "
                    "script code. No filesystem mutation, process execution, network "
                    "access, dynamic evaluation, "
                    "credential access, package installation, or GUI automation is allowed."
                ),
            },
            {
                "stage": "code-teaching-structure",
                "instruction": (
                    "Provide one entrypoint, explicit parameters, expected observations, "
                    "result analysis, and safety notes. Prefer bounded arrays, fixed "
                    "simulation horizons, and reproducible seeds."
                ),
            },
        ]

    def validate_content(
        self,
        content: CodeSandboxContentV1,
        context: AgentExecutionContext,
    ) -> None:
        del context
        for file in content.files:
            for pattern in PROHIBITED_CODE_PATTERNS:
                if pattern.search(file.content):
                    raise LiyanError(
                        ErrorCode.TOPIC3_AGENT_OUTPUT_INVALID,
                        "The generated simulation code violates the Topic 3 sandbox policy.",
                        category=ErrorCategory.PROVIDER,
                        status_code=502,
                        details={"path": file.path},
                    )
