from __future__ import annotations

from typing import TypeVar

from liyans_contracts.common import canonical_sha256
from liyans_contracts.topic4_common import Topic4RecordV1

RecordT = TypeVar("RecordT", bound=Topic4RecordV1)


def build_topic4_record(model: type[RecordT], /, **values: object) -> RecordT:
    draft = model.model_construct(record_sha256="0" * 64, **values)
    digest = canonical_sha256(draft.model_dump(mode="json", exclude={"record_sha256"}))
    return model(record_sha256=digest, **values)


def record_integrity_valid(record: Topic4RecordV1) -> bool:
    expected = canonical_sha256(record.model_dump(mode="json", exclude={"record_sha256"}))
    return record.record_sha256 == expected
