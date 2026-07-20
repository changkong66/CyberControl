from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from liyans.core.config import HotReloadingTomlConfig
from liyans.core.provider_policy import ProviderPolicyError, ProviderPolicyRegistry
from liyans.core.tenant import (
    TenantContext,
    TenantIsolationError,
    assert_tenant,
    tenant_scope,
)
from liyans.infrastructure.observability.audit import (
    AuditService,
    InMemoryAuditStore,
    verify_audit_chain,
)
from liyans.infrastructure.resilience import CircuitBreaker, CircuitState


@pytest.mark.asyncio
async def test_audit_hash_chain_detects_tampering() -> None:
    store = InMemoryAuditStore()
    audit = AuditService(store)
    await audit.record(
        tenant_id="tenant-a",
        category="TEST",
        action="FIRST",
        outcome="SUCCEEDED",
        actor_ref="subject:test",
    )
    await audit.record(
        tenant_id="tenant-a",
        category="TEST",
        action="SECOND",
        outcome="SUCCEEDED",
        actor_ref="subject:test",
    )
    records = await store.records("tenant-a")
    assert verify_audit_chain(records)
    records[1] = replace(records[1], outcome="FAILED")
    assert not verify_audit_chain(records)


@pytest.mark.asyncio
async def test_hot_config_rejects_invalid_candidate_without_swapping(tmp_path: Path) -> None:
    config_path = tmp_path / "providers.toml"
    config_path.write_text(
        'schema_version="provider-policy.v1"\npolicy_version="1.0.0"\ndefault_fail_closed=true\n',
        encoding="utf-8",
    )
    config = HotReloadingTomlConfig(
        config_path,
        validator=ProviderPolicyRegistry.from_document,
    )
    original = await config.load()
    config_path.write_text(
        'schema_version="provider-policy.v1"\npolicy_version="2.0.0"\ndefault_fail_closed=false\n',
        encoding="utf-8",
    )
    with pytest.raises(ProviderPolicyError):
        await config.load()
    assert config.snapshot.digest == original.digest


@pytest.mark.asyncio
async def test_hot_config_lifecycle_and_rejection_listeners_are_bounded(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "providers.toml"
    config_path.write_text(
        'schema_version="provider-policy.v1"\npolicy_version="1.0.0"\ndefault_fail_closed=true\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="positive"):
        HotReloadingTomlConfig(
            config_path,
            validator=ProviderPolicyRegistry.from_document,
            poll_interval_seconds=0,
        )

    config = HotReloadingTomlConfig(
        config_path,
        validator=ProviderPolicyRegistry.from_document,
        poll_interval_seconds=0.001,
    )
    with pytest.raises(RuntimeError, match="has not been loaded"):
        _ = config.snapshot

    await config.start()
    task = config._task
    await config.start()
    assert config._task is task
    await config.close()

    observed: list[str] = []

    def broken_listener(_path: Path, _error: Exception) -> None:
        raise RuntimeError("listener failure")

    async def closing_listener(path: Path, error: Exception) -> None:
        observed.append(f"{path.name}:{type(error).__name__}")
        config._closed = True

    config.add_rejection_listener(broken_listener)
    config.add_rejection_listener(closing_listener)
    config_path.write_text("invalid = [", encoding="utf-8")
    config._last_mtime_ns = 0
    config._closed = False
    await config._watch()
    assert observed == ["providers.toml:TOMLDecodeError"]


@pytest.mark.asyncio
async def test_hot_config_watcher_tolerates_a_missing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = HotReloadingTomlConfig(
        tmp_path / "missing.toml",
        validator=lambda _document: None,
        poll_interval_seconds=0.001,
    )

    async def stop_after_sleep(_seconds: float) -> None:
        config._closed = True

    monkeypatch.setattr(asyncio, "sleep", stop_after_sleep)
    await config._watch()


def test_tenant_scope_denies_cross_tenant_access() -> None:
    context = TenantContext(
        tenant_id="tenant-a",
        subject_ref="subject:test",
        roles=frozenset(),
        scopes=frozenset(),
        trace_id="a" * 32,
    )
    with tenant_scope(context):
        assert assert_tenant("tenant-a") == context
        with pytest.raises(TenantIsolationError):
            assert_tenant("tenant-b")


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_recovers_half_open_probe() -> None:
    breaker = CircuitBreaker(
        "test",
        failure_threshold=1,
        reset_timeout_seconds=0.01,
    )

    async def fail() -> None:
        raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        await breaker.execute(fail)
    assert breaker.state == CircuitState.OPEN
    await asyncio.sleep(0.02)

    async def succeed() -> str:
        return "ok"

    assert await breaker.execute(succeed) == "ok"
    assert breaker.state == CircuitState.CLOSED
