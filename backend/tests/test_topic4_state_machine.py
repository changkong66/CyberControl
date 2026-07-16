from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from liyans_contracts.verification import VerificationState, VerificationStateChangedPayloadV1

from liyans.domains.verification.records import build_topic4_record, record_integrity_valid
from liyans.domains.verification.service import VerifierRuntimeVersions
from liyans.domains.verification.state_machine import (
    InvalidVerificationTransition,
    VerificationStateMachine,
)


def test_release_path_is_deterministic() -> None:
    machine = VerificationStateMachine()
    state = VerificationState.ACCEPTED
    revision_round = 0
    path = (
        VerificationState.SNAPSHOT_VALIDATING,
        VerificationState.CLAIM_EXTRACTING,
        VerificationState.CLAIMS_READY,
        VerificationState.MODULE_DISPATCHING,
        VerificationState.VERIFYING,
        VerificationState.AGGREGATING,
        VerificationState.RELEASE_PENDING,
        VerificationState.RELEASED,
    )
    for target in path:
        decision = machine.transition(state, target, revision_round=revision_round)
        assert decision.previous_state == state
        assert decision.current_state == target
        state = decision.current_state
        revision_round = decision.revision_round
    assert revision_round == 0


def test_revision_path_increments_round_and_reenters_snapshot_validation() -> None:
    machine = VerificationStateMachine()
    first = machine.transition(
        VerificationState.AGGREGATING,
        VerificationState.REVISION_PLANNING,
        revision_round=0,
    )
    assert first.revision_round == 1
    waiting = machine.transition(
        first.current_state,
        VerificationState.REVISION_WAITING,
        revision_round=first.revision_round,
    )
    reverify = machine.transition(
        waiting.current_state,
        VerificationState.REVERIFYING,
        revision_round=waiting.revision_round,
    )
    restarted = machine.transition(
        reverify.current_state,
        VerificationState.SNAPSHOT_VALIDATING,
        revision_round=reverify.revision_round,
    )
    assert restarted.revision_round == 1


def test_revision_budget_and_terminal_states_are_closed() -> None:
    machine = VerificationStateMachine()
    with pytest.raises(InvalidVerificationTransition, match="budget"):
        machine.transition(
            VerificationState.AGGREGATING,
            VerificationState.REVISION_PLANNING,
            revision_round=2,
        )
    with pytest.raises(InvalidVerificationTransition, match="terminal"):
        machine.transition(
            VerificationState.RELEASED,
            VerificationState.SNAPSHOT_VALIDATING,
            revision_round=0,
        )


def test_state_machine_rejects_skipped_stages() -> None:
    with pytest.raises(InvalidVerificationTransition):
        VerificationStateMachine().transition(
            VerificationState.ACCEPTED,
            VerificationState.RELEASE_PENDING,
            revision_round=0,
        )


def test_topic4_record_builder_binds_canonical_sha256() -> None:
    now = datetime.now(UTC)
    record = build_topic4_record(
        VerificationStateChangedPayloadV1,
        trace_id="a" * 32,
        tenant_id="tenant-a",
        version_cas=1,
        created_at=now,
        immutable=True,
        schema_version="verification.state_changed.v1",
        verification_id=uuid4(),
        previous_state=None,
        current_state=VerificationState.ACCEPTED,
        state_version=1,
        reason_code="VERIFICATION_ACCEPTED",
        revision_round=0,
        changed_at=now,
    )
    assert record_integrity_valid(record)
    assert not record_integrity_valid(record.model_copy(update={"record_sha256": "0" * 64}))


def test_runtime_versions_reject_empty_or_oversized_values() -> None:
    with pytest.raises(ValueError):
        VerifierRuntimeVersions("", "b", "p", "p", "r", "k", "t", "s", "l")
    with pytest.raises(ValueError):
        VerifierRuntimeVersions("a" * 129, "b", "p", "p", "r", "k", "t", "s", "l")
