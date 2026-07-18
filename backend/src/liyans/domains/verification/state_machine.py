from __future__ import annotations

from dataclasses import dataclass

from liyans_contracts.verification import VerificationState


class InvalidVerificationTransition(ValueError):
    pass


TERMINAL_STATES = frozenset(
    {
        VerificationState.RELEASED,
        VerificationState.BLOCKED,
        VerificationState.FAILED,
        VerificationState.EXPIRED,
        VerificationState.CANCELLED,
    }
)

ALLOWED_TRANSITIONS: dict[VerificationState, frozenset[VerificationState]] = {
    VerificationState.ACCEPTED: frozenset(
        {
            VerificationState.SNAPSHOT_VALIDATING,
            VerificationState.CANCELLED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
        }
    ),
    VerificationState.SNAPSHOT_VALIDATING: frozenset(
        {
            VerificationState.CLAIM_EXTRACTING,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.CLAIM_EXTRACTING: frozenset(
        {
            VerificationState.CLAIMS_READY,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.CLAIMS_READY: frozenset(
        {
            VerificationState.MODULE_DISPATCHING,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.MODULE_DISPATCHING: frozenset(
        {
            VerificationState.VERIFYING,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.VERIFYING: frozenset(
        {
            VerificationState.AGGREGATING,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.AGGREGATING: frozenset(
        {
            VerificationState.RELEASE_PENDING,
            VerificationState.REVISION_PLANNING,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.REVISION_PLANNING: frozenset(
        {
            VerificationState.REVISION_WAITING,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.REVISION_WAITING: frozenset(
        {
            VerificationState.REVERIFYING,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.REVERIFYING: frozenset(
        {
            VerificationState.SNAPSHOT_VALIDATING,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.RELEASE_PENDING: frozenset(
        {
            VerificationState.RELEASED,
            VerificationState.REVIEW_REQUIRED,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.FAILED,
            VerificationState.CANCELLED,
        }
    ),
    VerificationState.REVIEW_REQUIRED: frozenset(
        {
            VerificationState.RELEASE_PENDING,
            VerificationState.REVISION_PLANNING,
            VerificationState.BLOCKED,
            VerificationState.EXPIRED,
            VerificationState.CANCELLED,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class TransitionDecision:
    previous_state: VerificationState
    current_state: VerificationState
    revision_round: int


class VerificationStateMachine:
    def transition(
        self,
        current: VerificationState,
        target: VerificationState,
        *,
        revision_round: int,
    ) -> TransitionDecision:
        if current in TERMINAL_STATES:
            raise InvalidVerificationTransition(f"terminal state {current} cannot transition")
        if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise InvalidVerificationTransition(f"transition {current} -> {target} is not allowed")

        next_round = revision_round
        if target == VerificationState.REVISION_PLANNING:
            next_round += 1
            if next_round > 2:
                raise InvalidVerificationTransition("revision round budget is exhausted")
        if current == VerificationState.REVERIFYING and revision_round == 0:
            raise InvalidVerificationTransition("reverification requires a revision round")

        return TransitionDecision(
            previous_state=current,
            current_state=target,
            revision_round=next_round,
        )
