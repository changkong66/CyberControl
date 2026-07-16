from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import numpy as np
from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_c3 import (
    StabilityCheckResultV1,
    StabilityConclusion,
    StabilityDomain,
    StabilityModelV1,
)
from liyans_contracts.topic4_common import VerificationVerdict

from liyans.domains.verification.records import build_topic4_record

STABILITY_ENGINE_VERSION = "c3-stability-engine-v1"


@dataclass(frozen=True, slots=True)
class StabilityPolicy:
    tolerance: float = 1e-8
    max_polynomial_degree: int = 256
    max_matrix_dimension: int = 64

    def __post_init__(self) -> None:
        if not math.isfinite(self.tolerance) or not 0 < self.tolerance <= 0.01:
            raise ValueError("stability tolerance must be finite and between zero and 0.01")
        if not 1 <= self.max_polynomial_degree <= 1024:
            raise ValueError("max_polynomial_degree must be between 1 and 1024")
        if not 1 <= self.max_matrix_dimension <= 128:
            raise ValueError("max_matrix_dimension must be between 1 and 128")


def stability_model_payload(
    *,
    domain: StabilityDomain,
    representation: str,
    numerator_coefficients: list[float],
    denominator_coefficients: list[float],
    state_space_matrices: dict[str, list[list[float]]],
    sample_time_seconds: float | None,
    assumptions: list[str],
) -> dict[str, object]:
    return {
        "domain": domain.value,
        "representation": representation,
        "numerator_coefficients": numerator_coefficients,
        "denominator_coefficients": denominator_coefficients,
        "state_space_matrices": state_space_matrices,
        "sample_time_seconds": sample_time_seconds,
        "assumptions": assumptions,
        "engine_version": STABILITY_ENGINE_VERSION,
    }


class StabilityModelBuilder:
    def build(
        self,
        *,
        verification_id: UUID,
        claim_id: UUID,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
        domain: StabilityDomain,
        representation: str,
        numerator_coefficients: list[float] | None = None,
        denominator_coefficients: list[float] | None = None,
        state_space_matrices: dict[str, list[list[float]]] | None = None,
        sample_time_seconds: float | None = None,
        assumptions: list[str] | None = None,
    ) -> StabilityModelV1:
        numerator = [float(value) for value in (numerator_coefficients or [])]
        denominator = [float(value) for value in (denominator_coefficients or [])]
        matrices = {
            key: [[float(item) for item in row] for row in value]
            for key, value in (state_space_matrices or {}).items()
        }
        model_assumptions = list(assumptions or [])
        payload = stability_model_payload(
            domain=domain,
            representation=representation,
            numerator_coefficients=numerator,
            denominator_coefficients=denominator,
            state_space_matrices=matrices,
            sample_time_seconds=sample_time_seconds,
            assumptions=model_assumptions,
        )
        digest = canonical_sha256(payload)
        return build_topic4_record(
            StabilityModelV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="stability-model.v1",
            stability_model_id=uuid5(claim_id, f"stability-model:{digest}"),
            verification_id=verification_id,
            claim_id=claim_id,
            domain=domain,
            representation=representation,
            numerator_coefficients=numerator,
            denominator_coefficients=denominator,
            state_space_matrices=matrices,
            sample_time_seconds=sample_time_seconds,
            assumptions=model_assumptions,
            model_sha256=digest,
        )


class StabilityAnalyzer:
    def __init__(self, policy: StabilityPolicy | None = None) -> None:
        self.policy = policy or StabilityPolicy()

    def analyze(
        self,
        model: StabilityModelV1,
        *,
        trace_id: str,
        tenant_id: str,
        created_at: datetime,
        expected_conclusion: StabilityConclusion = StabilityConclusion.STABLE,
    ) -> StabilityCheckResultV1:
        if model.tenant_id != tenant_id:
            raise ValueError("stability analysis cannot cross tenant boundaries")
        self._validate_model_integrity(model)
        if model.representation == "STATE_SPACE":
            poles = self._state_space_poles(model.state_space_matrices)
            method = "EIGENVALUES"
            criterion_values = self._state_space_criteria(poles)
        else:
            coefficients = self._characteristic_coefficients(model)
            poles = self._polynomial_poles(coefficients)
            if model.domain == StabilityDomain.CONTINUOUS:
                first_column, singular = self._routh_first_column(coefficients)
                criterion_values = {
                    f"routh_first_column_{index}": value for index, value in enumerate(first_column)
                }
                criterion_values["routh_singular"] = float(singular)
                method = "ROUTH_HURWITZ"
            else:
                criterion_values = self._root_criteria(poles)
                method = "JURY"
        conclusion, counterexample = self._conclude(model.domain, poles)
        verdict, confidence = self._verdict(conclusion, expected_conclusion)
        result_id = uuid5(
            NAMESPACE_URL,
            f"liyans:c3:stability:{model.claim_id}:{model.model_sha256}:{STABILITY_ENGINE_VERSION}",
        )
        return build_topic4_record(
            StabilityCheckResultV1,
            trace_id=trace_id,
            tenant_id=tenant_id,
            version_cas=1,
            created_at=created_at,
            immutable=True,
            schema_version="stability-check.result.v1",
            stability_check_result_id=result_id,
            verification_id=model.verification_id,
            claim_id=model.claim_id,
            stability_model_id=model.stability_model_id,
            conclusion=conclusion,
            method=method,
            poles=[self._format_complex(pole) for pole in poles],
            criterion_values=criterion_values,
            counterexample=counterexample,
            verdict=verdict,
            confidence=confidence,
        )

    def _validate_model_integrity(self, model: StabilityModelV1) -> None:
        payload = stability_model_payload(
            domain=model.domain,
            representation=model.representation,
            numerator_coefficients=list(model.numerator_coefficients),
            denominator_coefficients=list(model.denominator_coefficients),
            state_space_matrices={
                key: [list(row) for row in value]
                for key, value in model.state_space_matrices.items()
            },
            sample_time_seconds=model.sample_time_seconds,
            assumptions=list(model.assumptions),
        )
        if canonical_sha256(payload) != model.model_sha256:
            raise ValueError("stability model SHA256 does not match its immutable payload")
        for value in model.numerator_coefficients + model.denominator_coefficients:
            if not math.isfinite(value) or abs(value) > 1e100:
                raise ValueError("stability model contains a non-finite or oversized coefficient")
        for matrix in model.state_space_matrices.values():
            if len(matrix) > self.policy.max_matrix_dimension:
                raise ValueError("state-space matrix exceeds the safety dimension limit")
            if any(len(row) > self.policy.max_matrix_dimension for row in matrix):
                raise ValueError("state-space matrix exceeds the safety dimension limit")
            if any(not math.isfinite(value) for row in matrix for value in row):
                raise ValueError("state-space matrix contains a non-finite value")

    def _characteristic_coefficients(self, model: StabilityModelV1) -> list[float]:
        coefficients = list(model.denominator_coefficients)
        if model.representation == "CHARACTERISTIC_POLYNOMIAL" and not coefficients:
            coefficients = list(model.numerator_coefficients)
        if not coefficients:
            raise ValueError("stability model requires characteristic polynomial coefficients")
        if len(coefficients) - 1 > self.policy.max_polynomial_degree:
            raise ValueError("characteristic polynomial degree exceeds the safety limit")
        first_nonzero = next(
            (
                index
                for index, coefficient in enumerate(coefficients)
                if abs(coefficient) > self.policy.tolerance
            ),
            None,
        )
        if first_nonzero is None:
            raise ValueError("characteristic polynomial cannot be identically zero")
        return coefficients[first_nonzero:]

    @staticmethod
    def _polynomial_poles(coefficients: list[float]) -> list[complex]:
        if len(coefficients) <= 1:
            return []
        roots = np.roots(np.asarray(coefficients, dtype=np.float64))
        return [complex(root) for root in roots]

    def _state_space_poles(self, matrices: dict[str, list[list[float]]]) -> list[complex]:
        raw = matrices.get("A")
        if not raw or len(raw) != len(raw[0]) or any(len(row) != len(raw) for row in raw):
            raise ValueError("state-space matrix A must be a non-empty square matrix")
        if len(raw) > self.policy.max_matrix_dimension:
            raise ValueError("state-space matrix A exceeds the safety dimension limit")
        values = np.asarray(raw, dtype=np.float64)
        return [complex(value) for value in np.linalg.eigvals(values)]

    def _routh_first_column(self, coefficients: list[float]) -> tuple[list[float], bool]:
        degree = len(coefficients) - 1
        width = (len(coefficients) + 1) // 2
        table = [[0.0] * width for _ in range(degree + 1)]
        table[0][: len(coefficients[0::2])] = coefficients[0::2]
        if degree >= 1:
            table[1][: len(coefficients[1::2])] = coefficients[1::2]
        singular = False
        epsilon = self.policy.tolerance
        for row in range(2, degree + 1):
            previous = table[row - 1]
            before = table[row - 2]
            if abs(previous[0]) <= epsilon:
                previous[0] = epsilon
                singular = True
            for column in range(width - 1):
                table[row][column] = (
                    previous[0] * before[column + 1] - before[0] * previous[column + 1]
                ) / previous[0]
            if all(abs(value) <= epsilon for value in table[row]):
                singular = True
        return [row[0] for row in table], singular

    def _state_space_criteria(self, poles: list[complex]) -> dict[str, float]:
        return {
            "max_real_part": max((pole.real for pole in poles), default=float("-inf")),
            "pole_count": float(len(poles)),
        }

    def _root_criteria(self, poles: list[complex]) -> dict[str, float]:
        return {
            "max_modulus": max((abs(pole) for pole in poles), default=0.0),
            "pole_count": float(len(poles)),
        }

    def _conclude(
        self,
        domain: StabilityDomain,
        poles: list[complex],
    ) -> tuple[StabilityConclusion, dict[str, object] | None]:
        tolerance = self.policy.tolerance
        if any(not math.isfinite(pole.real) or not math.isfinite(pole.imag) for pole in poles):
            return StabilityConclusion.INDETERMINATE, {"reason": "NON_FINITE_POLE"}
        if domain == StabilityDomain.CONTINUOUS:
            if any(pole.real > tolerance for pole in poles):
                offenders = [self._format_complex(pole) for pole in poles if pole.real > tolerance]
                return StabilityConclusion.UNSTABLE, {
                    "reason": "RIGHT_HALF_PLANE_POLE",
                    "offending_poles": offenders,
                }
            boundary = [pole for pole in poles if abs(pole.real) <= tolerance]
            if boundary:
                if self._has_repeated_boundary_pole(boundary):
                    return StabilityConclusion.UNSTABLE, {
                        "reason": "REPEATED_IMAGINARY_AXIS_POLE",
                        "offending_poles": [self._format_complex(pole) for pole in boundary],
                    }
                return StabilityConclusion.MARGINAL, {
                    "reason": "IMAGINARY_AXIS_POLE",
                    "boundary_poles": [self._format_complex(pole) for pole in boundary],
                }
            return StabilityConclusion.STABLE, None
        outside = [pole for pole in poles if abs(pole) > 1.0 + tolerance]
        if outside:
            return StabilityConclusion.UNSTABLE, {
                "reason": "OUTSIDE_UNIT_CIRCLE_POLE",
                "offending_poles": [self._format_complex(pole) for pole in outside],
            }
        boundary = [pole for pole in poles if abs(abs(pole) - 1.0) <= tolerance]
        if boundary:
            if self._has_repeated_boundary_pole(boundary):
                return StabilityConclusion.UNSTABLE, {
                    "reason": "REPEATED_UNIT_CIRCLE_POLE",
                    "offending_poles": [self._format_complex(pole) for pole in boundary],
                }
            return StabilityConclusion.MARGINAL, {
                "reason": "UNIT_CIRCLE_POLE",
                "boundary_poles": [self._format_complex(pole) for pole in boundary],
            }
        return StabilityConclusion.STABLE, None

    def _has_repeated_boundary_pole(self, poles: list[complex]) -> bool:
        tolerance = max(self.policy.tolerance * 10, 1e-7)
        return any(
            abs(left - right) <= tolerance
            for index, left in enumerate(poles)
            for right in poles[index + 1 :]
        )

    @staticmethod
    def _verdict(
        conclusion: StabilityConclusion,
        expected: StabilityConclusion,
    ) -> tuple[VerificationVerdict, float]:
        if conclusion == StabilityConclusion.INDETERMINATE:
            return VerificationVerdict.INSUFFICIENT_EVIDENCE, 0.30
        if conclusion == expected:
            return VerificationVerdict.SUPPORTED, 0.995
        if conclusion == StabilityConclusion.MARGINAL or expected == StabilityConclusion.MARGINAL:
            return VerificationVerdict.PARTIALLY_SUPPORTED, 0.88
        return VerificationVerdict.CONTRADICTED, 0.995

    @staticmethod
    def _format_complex(value: complex) -> str:
        real = 0.0 if abs(value.real) < 1e-12 else value.real
        imaginary = 0.0 if abs(value.imag) < 1e-12 else value.imag
        if imaginary == 0.0:
            return f"{real:.12g}"
        return f"{real:.12g}{imaginary:+.12g}j"
