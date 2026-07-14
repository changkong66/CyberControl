from __future__ import annotations

import asyncio
import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path, PurePosixPath

from liyans.core.errors import ErrorCategory, ErrorCode, LiyanError
from liyans.infrastructure.persistence.artifacts import StoredArtifactObject

NAMESPACE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class FileSystemArtifactObjectStore:
    """Immutable local object store for development and single-node deployments."""

    def __init__(self, root: Path, *, max_object_bytes: int = 64 * 1024 * 1024) -> None:
        if max_object_bytes < 1:
            raise ValueError("max_object_bytes must be positive")
        self._root = root.resolve()
        self._max_object_bytes = max_object_bytes
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink():
            raise ValueError("artifact root cannot be a symbolic link")

    async def put(
        self,
        *,
        tenant_id: str,
        storage_namespace: str,
        object_key: str,
        content: bytes,
    ) -> StoredArtifactObject:
        if not content or len(content) > self._max_object_bytes:
            raise self._invalid_path("Artifact content size is outside the accepted range.")
        target = self._target_path(tenant_id, storage_namespace, object_key)
        digest = sha256(content).hexdigest()
        created = await asyncio.to_thread(self._put_atomic, target, content, digest)
        return StoredArtifactObject(
            tenant_id=tenant_id,
            storage_namespace=storage_namespace,
            object_key=object_key,
            byte_size=len(content),
            sha256=digest,
            created=created,
        )

    async def read(
        self,
        *,
        tenant_id: str,
        storage_namespace: str,
        object_key: str,
        expected_byte_size: int,
        expected_sha256: str,
    ) -> bytes:
        target = self._target_path(tenant_id, storage_namespace, object_key)
        return await asyncio.to_thread(
            self._read_verified,
            target,
            expected_byte_size,
            expected_sha256,
        )

    def _target_path(self, tenant_id: str, namespace: str, object_key: str) -> Path:
        if not tenant_id or len(tenant_id) > 128:
            raise self._invalid_path("The artifact tenant identifier is invalid.")
        if not NAMESPACE_PATTERN.fullmatch(namespace):
            raise self._invalid_path("The artifact storage namespace is invalid.")
        if not object_key or len(object_key) > 1024 or "\\" in object_key:
            raise self._invalid_path("The artifact object key is invalid.")
        logical_key = PurePosixPath(object_key)
        if (
            logical_key.is_absolute()
            or logical_key.as_posix() != object_key
            or any(part in {"", ".", ".."} for part in logical_key.parts)
            or any(":" in part for part in logical_key.parts)
        ):
            raise self._invalid_path("The artifact object key is not canonical.")
        tenant_partition = sha256(tenant_id.encode("utf-8")).hexdigest()
        target = self._root / tenant_partition / namespace
        for part in logical_key.parts:
            target /= part
        resolved_parent = target.parent.resolve()
        if self._root != resolved_parent and self._root not in resolved_parent.parents:
            raise self._invalid_path("The artifact object key escapes the storage root.")
        return target

    def _put_atomic(self, target: Path, content: bytes, digest: str) -> bool:
        target.parent.mkdir(parents=True, exist_ok=True)
        self._assert_no_symlink_path(target.parent)
        if target.is_symlink():
            raise self._invalid_path("Artifact objects cannot be symbolic links.")
        if target.exists():
            self._assert_existing_matches(target, content, digest)
            return False

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=".liyans-stage-",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_path, target)
            except FileExistsError:
                self._assert_existing_matches(target, content, digest)
                return False
            temporary_path.unlink()
            temporary_path = None
            target.chmod(0o440)
            self._fsync_directory(target.parent)
            return True
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _assert_existing_matches(self, target: Path, content: bytes, digest: str) -> None:
        if target.is_symlink() or not target.is_file():
            raise self._invalid_path("Artifact objects must be immutable regular files.")
        existing = self._read_file(target)
        if len(existing) != len(content) or sha256(existing).hexdigest() != digest:
            raise LiyanError(
                ErrorCode.ARTIFACT_CONFLICT,
                "The immutable artifact object key is already bound to different content.",
                category=ErrorCategory.DATABASE,
                status_code=409,
            )

    def _read_verified(self, target: Path, expected_size: int, expected_digest: str) -> bytes:
        if expected_size < 1 or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise self._integrity_error()
        if not target.is_file() or target.is_symlink():
            raise LiyanError(
                ErrorCode.ARTIFACT_NOT_FOUND,
                "The immutable artifact object is unavailable.",
                category=ErrorCategory.DATABASE,
                status_code=404,
            )
        content = self._read_file(target)
        if len(content) != expected_size or sha256(content).hexdigest() != expected_digest:
            raise self._integrity_error()
        return content

    @staticmethod
    def _read_file(target: Path) -> bytes:
        with target.open("rb") as stream:
            return stream.read()

    def _assert_no_symlink_path(self, directory: Path) -> None:
        current = directory
        while current != self._root:
            if current.is_symlink():
                raise self._invalid_path("Artifact storage cannot traverse a symbolic link.")
            current = current.parent
        if current.is_symlink():
            raise self._invalid_path("Artifact storage root cannot be a symbolic link.")

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _invalid_path(message: str) -> LiyanError:
        return LiyanError(
            ErrorCode.ARTIFACT_PATH_INVALID,
            message,
            category=ErrorCategory.CONTRACT,
            status_code=422,
        )

    @staticmethod
    def _integrity_error() -> LiyanError:
        return LiyanError(
            ErrorCode.ARTIFACT_INTEGRITY_FAILED,
            "The immutable artifact failed its integrity check.",
            category=ErrorCategory.DATABASE,
            status_code=500,
        )
