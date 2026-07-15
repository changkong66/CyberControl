import pytest

from liyans.api.topic1_limits import Topic1ImportBodyLimitMiddleware


async def noop_app(_scope, _receive, _send) -> None:
    return None


def test_topic1_body_limit_rejects_nonpositive_configuration() -> None:
    with pytest.raises(ValueError, match="positive"):
        Topic1ImportBodyLimitMiddleware(noop_app, max_body_bytes=0)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("invalid", None), ("-1", None), ("42", 42)],
)
def test_topic1_body_limit_parses_content_length_defensively(value, expected) -> None:
    assert Topic1ImportBodyLimitMiddleware._content_length(value) == expected
