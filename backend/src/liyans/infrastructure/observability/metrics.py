from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable
from threading import Lock
from time import perf_counter, time
from typing import Final

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.core import Metric
from prometheus_client.exposition import generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

APPROVED_HTTP_METHODS: Final = frozenset(
    {"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"}
)
APPROVED_DATABASE_POOL_NAMES: Final = frozenset(
    {"api", "identity-reconciler", "outbox-dispatcher", "other"}
)


class _BatchedHistogramChild:
    def __init__(self, histogram: _BatchedHistogram, label_values: tuple[str, ...]) -> None:
        self._histogram = histogram
        self._label_values = label_values

    def observe(self, value: float) -> None:
        self._histogram.observe(self._label_values, value)


class _BatchedHistogram:
    """Exact fixed-bucket histogram with one lock per observation.

    The public exposition is identical to prometheus_client's Histogram. The
    local implementation avoids taking one lock for every cumulative bucket on
    the SSE and Outbox hot paths, while retaining every observation.
    """

    def __init__(
        self,
        name: str,
        documentation: str,
        labelnames: tuple[str, ...],
        buckets: Iterable[float],
        *,
        registry: CollectorRegistry,
    ) -> None:
        self._name = name
        self._documentation = documentation
        self._labelnames = labelnames
        self._bounds = tuple(float(bound) for bound in buckets) + (float("inf"),)
        self._states: dict[tuple[str, ...], tuple[list[int], float, int, float]] = {}
        self._lock = Lock()
        registry.register(self)

    def labels(self, *label_values: str, **label_kwargs: str) -> _BatchedHistogramChild:
        if label_kwargs:
            if label_values or set(label_kwargs) != set(self._labelnames):
                raise ValueError("histogram labels must be positional or complete keyword labels")
            label_values = tuple(label_kwargs[name] for name in self._labelnames)
        values = self._normalize_label_values(label_values)
        with self._lock:
            if values not in self._states:
                self._states[values] = ([0] * len(self._bounds), 0.0, 0, time())
        return _BatchedHistogramChild(self, values)

    def observe(self, label_values: tuple[str, ...], value: float) -> None:
        if value < 0 or value != value or value == float("inf") or value == float("-inf"):
            raise ValueError("histogram observations must be finite and nonnegative")
        values = self._normalize_label_values(label_values)
        with self._lock:
            state = self._states.get(values)
            if state is None:
                state = ([0] * len(self._bounds), 0.0, 0, time())
            buckets, total, count, created = state
            buckets[bisect_left(self._bounds, value)] += 1
            self._states[values] = (buckets, total + value, count + 1, created)

    def _normalize_label_values(self, label_values: tuple[str, ...]) -> tuple[str, ...]:
        if len(label_values) != len(self._labelnames):
            raise ValueError("histogram label count does not match the metric definition")
        return tuple(str(value) for value in label_values)

    def collect(self):
        metric = Metric(self._name, self._documentation, "histogram")
        with self._lock:
            states = [
                (labels, list(buckets), total, count, created)
                for labels, (buckets, total, count, created) in self._states.items()
            ]
        for labels, buckets, total, count, created in states:
            label_set = dict(zip(self._labelnames, labels, strict=True))
            cumulative = 0
            for bound, bucket_count in zip(self._bounds, buckets, strict=True):
                cumulative += bucket_count
                metric.add_sample(
                    f"{self._name}_bucket",
                    {**label_set, "le": "+Inf" if bound == float("inf") else str(bound)},
                    float(cumulative),
                )
            metric.add_sample(f"{self._name}_sum", label_set, total)
            metric.add_sample(f"{self._name}_count", label_set, float(count))
            metric.add_sample(f"{self._name}_created", label_set, created)
        yield metric


class PlatformMetrics:
    """Low-cardinality process metrics backed by an app-local registry."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self._http_requests = Counter(
            "liyans_http_requests_total",
            "Completed HTTP requests.",
            ("method", "route", "status_class"),
            registry=self.registry,
        )
        self._http_duration = Histogram(
            "liyans_http_request_duration_seconds",
            "End-to-end HTTP request duration.",
            ("method", "route"),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self.registry,
        )
        self._outbox_operations = Counter(
            "liyans_outbox_operations_total",
            "Outbox dispatcher state transitions.",
            ("operation", "outcome"),
            registry=self.registry,
        )
        self._outbox_latency = _BatchedHistogram(
            "liyans_outbox_latency_seconds",
            "Outbox lifecycle latency by measured stage.",
            ("stage",),
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
            registry=self.registry,
        )
        self._sse_operations = Counter(
            "liyans_sse_operations_total",
            "SSE persistence, replay, notification, and fan-out operations.",
            ("operation", "outcome"),
            registry=self.registry,
        )
        self._sse_latency = _BatchedHistogram(
            "liyans_sse_latency_seconds",
            "SSE lifecycle latency by measured stage.",
            ("stage",),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self.registry,
        )
        self._sse_gauges = Gauge(
            "liyans_sse_runtime_gauge",
            "Low-cardinality SSE runtime lifecycle gauges.",
            ("metric",),
            registry=self.registry,
        )
        self._outbox_gauges = Gauge(
            "liyans_outbox_runtime_gauge",
            "Low-cardinality Outbox runtime lifecycle gauges.",
            ("metric",),
            registry=self.registry,
        )
        self._database_health_duration = Histogram(
            "liyans_database_health_duration_seconds",
            "Database readiness probe latency.",
            ("outcome",),
            buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 3),
            registry=self.registry,
        )
        self._component_ready = Gauge(
            "liyans_component_ready",
            "Whether a required process component is ready (1) or degraded (0).",
            ("component",),
            registry=self.registry,
        )
        self._database_pool_checked_out = Gauge(
            "liyans_database_pool_checked_out",
            "Connections currently checked out from a named SQLAlchemy pool.",
            ("pool",),
            registry=self.registry,
        )
        self._database_pool_capacity = Gauge(
            "liyans_database_pool_capacity",
            "Configured maximum size of a named SQLAlchemy pool.",
            ("pool",),
            registry=self.registry,
        )
        self._database_pool_acquisition_timeouts = Counter(
            "liyans_database_pool_acquisition_timeouts_total",
            "SQLAlchemy connection acquisition timeouts.",
            ("pool",),
            registry=self.registry,
        )

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE_LATEST

    def render(self) -> bytes:
        return generate_latest(self.registry)

    def observe_http(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        normalized_method = method.upper()
        if normalized_method not in APPROVED_HTTP_METHODS:
            normalized_method = "OTHER"
        normalized_route = route if route.startswith("/") and len(route) <= 256 else "unmatched"
        status_class = f"{status_code // 100}xx" if 100 <= status_code <= 599 else "unknown"
        self._http_requests.labels(
            normalized_method,
            normalized_route,
            status_class,
        ).inc()
        self._http_duration.labels(normalized_method, normalized_route).observe(
            max(0.0, duration_seconds)
        )

    def observe_outbox(self, operation: str, outcome: str, count: int = 1) -> None:
        if count > 0:
            self._outbox_operations.labels(operation, outcome).inc(count)

    def observe_outbox_latency(self, stage: str, duration_seconds: float) -> None:
        self._outbox_latency.observe((stage[:64],), max(0.0, duration_seconds))

    def observe_sse(self, operation: str, outcome: str, count: int = 1) -> None:
        if count > 0:
            self._sse_operations.labels(operation, outcome).inc(count)

    def observe_sse_latency(self, stage: str, duration_seconds: float) -> None:
        self._sse_latency.observe((stage[:64],), max(0.0, duration_seconds))

    def set_sse_gauge(self, metric: str, value: int) -> None:
        self._sse_gauges.labels(metric[:64]).set(max(0, value))

    def set_outbox_gauge(self, metric: str, value: int) -> None:
        self._outbox_gauges.labels(metric[:64]).set(max(0, value))

    def observe_database_health(self, *, healthy: bool, latency_ms: float) -> None:
        outcome = "healthy" if healthy else "unhealthy"
        self._database_health_duration.labels(outcome).observe(max(0.0, latency_ms / 1000))
        self.set_component_ready("database", healthy)

    def set_component_ready(self, component: str, ready: bool) -> None:
        self._component_ready.labels(component).set(1 if ready else 0)

    @staticmethod
    def _database_pool_label(pool_name: str) -> str:
        return pool_name if pool_name in APPROVED_DATABASE_POOL_NAMES else "other"

    def set_database_pool_capacity(self, pool_name: str, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("database pool capacity must be positive")
        label = self._database_pool_label(pool_name)
        self._database_pool_capacity.labels(label).set(capacity)
        self._database_pool_checked_out.labels(label).set(0)
        self._database_pool_acquisition_timeouts.labels(label).inc(0)

    def observe_database_pool_checkout(self, pool_name: str, delta: int) -> None:
        if delta == 0:
            return
        self._database_pool_checked_out.labels(self._database_pool_label(pool_name)).inc(delta)

    def observe_database_pool_acquisition_timeout(self, pool_name: str) -> None:
        self._database_pool_acquisition_timeouts.labels(self._database_pool_label(pool_name)).inc()


class HTTPMetricsMiddleware:
    def __init__(self, app: ASGIApp, *, metrics: PlatformMetrics) -> None:
        self.app = app
        self._metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = perf_counter()
        status_code = 500

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            route = scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            self._metrics.observe_http(
                method=scope.get("method", "OTHER"),
                route=route_path,
                status_code=status_code,
                duration_seconds=perf_counter() - started,
            )
