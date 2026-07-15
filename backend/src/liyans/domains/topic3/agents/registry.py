from __future__ import annotations

from liyans_contracts.enums import SourceAgent

from liyans.providers.topic3 import Topic3ProviderRegistry

from .base import Topic3Agent
from .code_sandbox import CodeSandboxAgent
from .extension import ExtensionAgent
from .lecturer import LecturerAgent
from .mindmap import MindMapAgent
from .tester import TesterAgent


class Topic3AgentRegistry:
    def __init__(self, providers: Topic3ProviderRegistry) -> None:
        agents: list[Topic3Agent] = [
            LecturerAgent(providers),
            MindMapAgent(),
            TesterAgent(providers),
            CodeSandboxAgent(providers),
            ExtensionAgent(providers),
        ]
        self._agents = {agent.source_agent: agent for agent in agents}

    def require(self, agent: SourceAgent) -> Topic3Agent:
        return self._agents[agent]
