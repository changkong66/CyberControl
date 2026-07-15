from __future__ import annotations

import re

from liyans_contracts.enums import ResourceType, SourceAgent
from liyans_contracts.topic3 import (
    BlockType,
    MindMapContentV1,
    MindMapEdgeV1,
    MindMapNodeV1,
)

from .base import AgentExecutionContext, AgentExecutionOutcome, ProviderBackedAgent


class MindMapAgent(ProviderBackedAgent[MindMapContentV1]):
    source_agent = SourceAgent.MIND_MAP
    resource_type = ResourceType.MIND_MAP
    content_model = MindMapContentV1
    block_type = BlockType.MERMAID
    content_schema_version = "topic3.mindmap-content.v1"

    def __init__(self) -> None:
        pass

    async def execute(self, context: AgentExecutionContext) -> AgentExecutionOutcome:
        content = self._build_content(context)
        block = self.make_block(
            block_id="mindmap-graph",
            block_type=BlockType.MERMAID,
            ordinal=0,
            title="个性化知识拓扑",
            content_schema_version=self.content_schema_version,
            content=content.model_dump(mode="json"),
            created_at=context.command.requested_at,
        )
        return AgentExecutionOutcome(
            candidate=self._candidate(
                context,
                [block],
                provider_alias="local",
                provider_request_ids=[],
            ),
            provider_result=None,
            provider_request=None,
        )

    def prompt_instructions(self, context: AgentExecutionContext) -> list[dict[str, object]]:
        del context
        return []

    def _build_content(self, context: AgentExecutionContext) -> MindMapContentV1:
        graph = context.graph.content
        target_ids = set(context.command.target_kp_ids)
        included = set(target_ids)
        changed = True
        while changed:
            changed = False
            for edge in graph.prerequisites:
                if edge.dependent_kp_id in included and edge.prerequisite_kp_id not in included:
                    included.add(edge.prerequisite_kp_id)
                    changed = True
        if context.personalization.profile.knowledge_mastery >= 0.75:
            for edge in graph.prerequisites:
                if edge.prerequisite_kp_id in target_ids:
                    included.add(edge.dependent_kp_id)
        if len(included) > 256:
            included = set(sorted(included)[:256]) | target_ids

        point_by_id = {point.kp_id: point for point in graph.knowledge_points}
        memory_by_id = {item.kp_id: item for item in context.personalization.memory_states}
        ordered_points = sorted(
            (point_by_id[kp_id] for kp_id in included),
            key=lambda point: (point.topology_level, point.kp_id),
        )
        node_id_by_kp = {point.kp_id: f"K{index}" for index, point in enumerate(ordered_points)}
        nodes: list[MindMapNodeV1] = []
        for point in ordered_points:
            memory = memory_by_id.get(point.kp_id)
            mastery = (
                memory.retrievability
                if memory is not None
                else context.personalization.profile.knowledge_mastery
            )
            if point.kp_id in target_ids:
                state = "CURRENT"
            elif mastery >= 0.8:
                state = "MASTERED"
            elif mastery < 0.6:
                state = "WEAK"
            elif point.topology_level < max(point_by_id[kp].topology_level for kp in target_ids):
                state = "PREREQUISITE"
            else:
                state = "FUTURE"
            nodes.append(
                MindMapNodeV1(
                    node_id=node_id_by_kp[point.kp_id],
                    kp_id=point.kp_id,
                    label=point.title,
                    mastery=round(mastery, 6),
                    state=state,
                    collapsed=(state == "MASTERED" and point.kp_id not in target_ids),
                )
            )
        edges = [
            MindMapEdgeV1(
                source_node_id=node_id_by_kp[edge.prerequisite_kp_id],
                target_node_id=node_id_by_kp[edge.dependent_kp_id],
                relation="PREREQUISITE",
            )
            for edge in graph.prerequisites
            if edge.prerequisite_kp_id in included and edge.dependent_kp_id in included
        ]
        mermaid_lines = ["graph TD"]
        for node in nodes:
            label = re.sub(r"[\[\]{}()\"']", " ", node.label).strip()
            mermaid_lines.append(f'    {node.node_id}["{label}"]')
        for edge in edges:
            mermaid_lines.append(f"    {edge.source_node_id} --> {edge.target_node_id}")
        state_classes = {
            "CURRENT": "fill:#fff3bf,stroke:#b7791f,color:#1a202c",
            "WEAK": "fill:#ffe3e3,stroke:#c92a2a,color:#1a202c",
            "MASTERED": "fill:#e6fcf5,stroke:#087f5b,color:#495057",
            "PREREQUISITE": "fill:#e7f5ff,stroke:#1971c2,color:#1a202c",
            "FUTURE": "fill:#f1f3f5,stroke:#868e96,color:#495057",
        }
        for state, style in state_classes.items():
            mermaid_lines.append(f"    classDef {state.lower()} {style}")
            member_ids = [node.node_id for node in nodes if node.state == state]
            if member_ids:
                mermaid_lines.append(f"    class {','.join(member_ids)} {state.lower()}")
        return MindMapContentV1(
            schema_version="topic3.mindmap-content.v1",
            direction="TD",
            nodes=nodes,
            edges=edges,
            mermaid="\n".join(mermaid_lines),
        )
