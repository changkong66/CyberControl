from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProviderPolicyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProviderCapabilityPolicy:
    alias: str
    capability: str
    allowlisted: bool
    enabled_by_default: bool
    prohibited: bool
    runtime_validation_required: bool

    def assert_can_enable(self) -> None:
        if self.prohibited or not self.allowlisted:
            raise ProviderPolicyError(f"provider capability is prohibited: {self.alias}")


@dataclass(frozen=True, slots=True)
class ProviderPolicyRegistry:
    schema_version: str
    policy_version: str
    default_fail_closed: bool
    providers: dict[str, ProviderCapabilityPolicy]

    @classmethod
    def load(cls, path: Path) -> ProviderPolicyRegistry:
        with path.open("rb") as handle:
            document: dict[str, Any] = tomllib.load(handle)
        return cls.from_document(document)

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> ProviderPolicyRegistry:

        providers: dict[str, ProviderCapabilityPolicy] = {}
        for alias, raw in document.get("providers", {}).items():
            providers[alias] = ProviderCapabilityPolicy(
                alias=alias,
                capability=str(raw["capability"]),
                allowlisted=bool(raw.get("allowlisted", False)),
                enabled_by_default=bool(raw.get("enabled_by_default", False)),
                prohibited=bool(raw.get("prohibited", False)),
                runtime_validation_required=bool(raw.get("runtime_validation_required", False)),
            )

        registry = cls(
            schema_version=str(document["schema_version"]),
            policy_version=str(document["policy_version"]),
            default_fail_closed=bool(document.get("default_fail_closed", True)),
            providers=providers,
        )
        registry.validate()
        return registry

    def validate(self) -> None:
        if not self.default_fail_closed:
            raise ProviderPolicyError("provider policy must fail closed")

        for policy in self.providers.values():
            if policy.enabled_by_default and (policy.prohibited or not policy.allowlisted):
                raise ProviderPolicyError(
                    f"non-allowlisted provider cannot be enabled: {policy.alias}"
                )

    def enabled_external_aliases(self) -> list[str]:
        return sorted(
            alias
            for alias, policy in self.providers.items()
            if policy.enabled_by_default and not policy.prohibited
        )

    def assert_can_enable(self, alias: str) -> ProviderCapabilityPolicy:
        try:
            policy = self.providers[alias]
        except KeyError as exc:
            raise ProviderPolicyError(f"unknown provider alias: {alias}") from exc
        policy.assert_can_enable()
        return policy
