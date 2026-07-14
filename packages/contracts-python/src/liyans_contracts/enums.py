from enum import StrEnum


class SourceAgent(StrEnum):
    LECTURER = "Lecturer"
    MIND_MAP = "MindMap"
    TESTER = "Tester"
    CODE_SANDBOX = "CodeSandbox"
    EXTENSION = "Extension"


class ResourceType(StrEnum):
    LECTURER_DOC = "Lecturer_Doc"
    MIND_MAP = "MindMap"
    GRADIENT_QUIZ = "Gradient_Quiz"
    SIMULATION_CODE = "Simulation_Code"
    EXTENSION_MATERIAL = "Extension_Material"


AGENT_RESOURCE_MATRIX: dict[SourceAgent, frozenset[ResourceType]] = {
    SourceAgent.LECTURER: frozenset({ResourceType.LECTURER_DOC}),
    SourceAgent.MIND_MAP: frozenset({ResourceType.MIND_MAP}),
    SourceAgent.TESTER: frozenset({ResourceType.GRADIENT_QUIZ}),
    SourceAgent.CODE_SANDBOX: frozenset({ResourceType.SIMULATION_CODE}),
    SourceAgent.EXTENSION: frozenset({ResourceType.EXTENSION_MATERIAL}),
}


class VerificationProfile(StrEnum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"
    CODE_STRICT = "CODE_STRICT"


class VerificationTrigger(StrEnum):
    INITIAL_GENERATION = "INITIAL_GENERATION"
    REVISION_REVERIFY = "REVISION_REVERIFY"
    MANUAL_REVERIFY = "MANUAL_REVERIFY"
    KNOWLEDGE_BASE_REVALIDATION = "KNOWLEDGE_BASE_REVALIDATION"
    POLICY_REVALIDATION = "POLICY_REVALIDATION"
