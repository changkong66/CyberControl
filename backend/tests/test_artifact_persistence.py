from __future__ import annotations

import os
from hashlib import sha256

import pytest

from liyans.core.errors import ErrorCode, LiyanError
from liyans.infrastructure.persistence import FileSystemArtifactObjectStore


@pytest.mark.asyncio
async def test_filesystem_artifact_store_is_immutable_and_idempotent(tmp_path) -> None:
    store = FileSystemArtifactObjectStore(tmp_path)
    content = "闭环控制系统".encode()

    created = await store.put(
        tenant_id="tenant-a",
        storage_namespace="candidate-v1",
        object_key="lecturer/resource.md",
        content=content,
    )
    duplicate = await store.put(
        tenant_id="tenant-a",
        storage_namespace="candidate-v1",
        object_key="lecturer/resource.md",
        content=content,
    )
    restored = await store.read(
        tenant_id="tenant-a",
        storage_namespace="candidate-v1",
        object_key="lecturer/resource.md",
        expected_byte_size=len(content),
        expected_sha256=sha256(content).hexdigest(),
    )

    assert created.created is True
    assert duplicate.created is False
    assert restored == content


@pytest.mark.asyncio
async def test_filesystem_artifact_store_rejects_key_reuse_with_different_content(
    tmp_path,
) -> None:
    store = FileSystemArtifactObjectStore(tmp_path)
    await store.put(
        tenant_id="tenant-a",
        storage_namespace="candidate-v1",
        object_key="resource.md",
        content=b"first",
    )

    with pytest.raises(LiyanError) as error:
        await store.put(
            tenant_id="tenant-a",
            storage_namespace="candidate-v1",
            object_key="resource.md",
            content=b"second",
        )

    assert error.value.code == ErrorCode.ARTIFACT_CONFLICT


@pytest.mark.asyncio
async def test_filesystem_artifact_store_detects_content_tampering(tmp_path) -> None:
    store = FileSystemArtifactObjectStore(tmp_path)
    content = b"verified-content"
    stored = await store.put(
        tenant_id="tenant-a",
        storage_namespace="candidate-v1",
        object_key="resource.md",
        content=content,
    )
    object_path = next(tmp_path.rglob("resource.md"))
    object_path.chmod(0o660)
    object_path.write_bytes(b"tampered-content")

    with pytest.raises(LiyanError) as error:
        await store.read(
            tenant_id="tenant-a",
            storage_namespace="candidate-v1",
            object_key="resource.md",
            expected_byte_size=stored.byte_size,
            expected_sha256=stored.sha256,
        )

    assert error.value.code == ErrorCode.ARTIFACT_INTEGRITY_FAILED


@pytest.mark.asyncio
async def test_filesystem_artifact_store_rejects_existing_symbolic_link(tmp_path) -> None:
    store = FileSystemArtifactObjectStore(tmp_path)
    await store.put(
        tenant_id="tenant-a",
        storage_namespace="candidate-v1",
        object_key="resource.md",
        content=b"original",
    )
    object_path = next(tmp_path.rglob("resource.md"))
    link_target = tmp_path / "link-target.bin"
    link_target.write_bytes(b"original")
    object_path.chmod(0o660)
    object_path.unlink()
    try:
        os.symlink(link_target, object_path)
    except OSError:
        pytest.skip("symbolic link creation is unavailable in this Windows environment")

    with pytest.raises(LiyanError) as error:
        await store.put(
            tenant_id="tenant-a",
            storage_namespace="candidate-v1",
            object_key="resource.md",
            content=b"original",
        )

    assert error.value.code == ErrorCode.ARTIFACT_PATH_INVALID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "object_key",
    ["../escape", "/absolute", "nested//noncanonical", "windows\\escape", "C:drive"],
)
async def test_filesystem_artifact_store_rejects_noncanonical_paths(
    tmp_path,
    object_key: str,
) -> None:
    store = FileSystemArtifactObjectStore(tmp_path)

    with pytest.raises(LiyanError) as error:
        await store.put(
            tenant_id="tenant-a",
            storage_namespace="candidate-v1",
            object_key=object_key,
            content=b"content",
        )

    assert error.value.code == ErrorCode.ARTIFACT_PATH_INVALID
