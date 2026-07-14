from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from liyans.infrastructure.observability.context import current_message_trace


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = current_message_trace()
        document: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if context is not None:
            document.update(
                {
                    "trace_id": context.trace_id,
                    "span_id": context.span_id,
                    "envelope_id": context.envelope_id,
                    "tenant_id": context.tenant_id,
                }
            )
        if record.exc_info:
            document["exception_type"] = record.exc_info[0].__name__
        return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def configure_json_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
