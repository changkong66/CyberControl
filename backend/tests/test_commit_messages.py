from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def load_validator() -> ModuleType:
    module_path = Path(__file__).resolve().parents[2] / "tools" / "validate_commit_messages.py"
    specification = importlib.util.spec_from_file_location(
        "liyans_commit_message_validator", module_path
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load commit validator from {module_path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


@pytest.mark.parametrize(
    "subject",
    [
        "feat(topic1): add knowledge topology repository",
        "ci: enforce release quality and supply-chain gates",
        "security(auth)!: rotate tenant claim binding",
        "chore(deps-python): update locked dependencies",
        "revert: remove unsafe runtime change",
    ],
)
def test_conventional_commit_subjects_are_accepted(subject: str) -> None:
    assert VALIDATOR.validate_subject(subject) == ()


@pytest.mark.parametrize(
    "subject",
    [
        "WIP topic1 repository",
        "fixup! feat(topic1): add repository",
        "Feat(topic1): uppercase type",
        "feat(Topic1): uppercase scope",
        "feat: ",
        "unclassified commit message",
        f"feat: {'x' * 101}",
    ],
)
def test_nonconforming_commit_subjects_are_rejected(subject: str) -> None:
    assert VALIDATOR.validate_subject(subject)
