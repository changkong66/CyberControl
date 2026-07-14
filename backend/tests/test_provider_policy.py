from pathlib import Path

import pytest
from liyans.core.provider_policy import ProviderPolicyError, ProviderPolicyRegistry

POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "providers.toml"


def test_provider_policy_fails_closed() -> None:
    registry = ProviderPolicyRegistry.load(POLICY_PATH)
    assert registry.default_fail_closed is True
    assert registry.enabled_external_aliases() == []


def test_external_embedding_is_prohibited() -> None:
    registry = ProviderPolicyRegistry.load(POLICY_PATH)
    with pytest.raises(ProviderPolicyError):
        registry.assert_can_enable("external_embedding")
