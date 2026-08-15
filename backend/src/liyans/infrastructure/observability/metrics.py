from __future__ import annotations

import asyncio
import ctypes
import gc
import json
import logging
import os
import sys
import tracemalloc
from bisect import bisect_left
from collections import Counter as CollectionCounter
from collections.abc import Iterable
from pathlib import Path
from threading import Lock
from time import perf_counter, time
from typing import Final

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.core import Metric
from prometheus_client.exposition import generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


def _read_process_memory() -> dict[str, int]:
    """Read Linux process memory counters without retaining process objects."""

    values: dict[str, int] = {}
    status_path = Path("/proc/self/status")
    try:
        for line in status_path.read_text(encoding="ascii").splitlines():
            name, separator, raw_value = line.partition(":")
            if not separator or name not in {
                "VmRSS",
                "VmSize",
                "VmPeak",
                "VmData",
                "RssAnon",
                "RssFile",
                "RssShmem",
            }:
                continue
            number = raw_value.strip().split(maxsplit=1)[0]
            values[name.lower() + "_bytes"] = int(number) * 1024
    except (FileNotFoundError, OSError, ValueError):
        pass

    try:
        for line in Path("/proc/self/smaps_rollup").read_text(encoding="ascii").splitlines():
            name, separator, raw_value = line.partition(":")
            if not separator or name not in {
                "Rss",
                "Pss",
                "Private_Clean",
                "Private_Dirty",
                "Anonymous",
                "Swap",
            }:
                continue
            number = raw_value.strip().split(maxsplit=1)[0]
            values["smaps_" + name.lower() + "_bytes"] = int(number) * 1024
    except (FileNotFoundError, OSError, ValueError):
        pass

    try:
        with Path("/proc/self/maps").open(encoding="ascii") as maps:
            values["memory_map_count"] = sum(1 for _ in maps)
    except (FileNotFoundError, OSError):
        pass
    return values


APPROVED_HTTP_METHODS: Final = frozenset(
    {"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"}
)
APPROVED_DATABASE_POOL_NAMES: Final = frozenset(
    {"api", "identity-reconciler", "outbox-dispatcher", "other"}
)


class _JemallocStatsReader:
    """Read fixed-cardinality jemalloc process statistics when available."""

    _BYTE_STATS = ("allocated", "active", "resident", "retained")

    def __init__(self) -> None:
        self._mallctl = None
        if sys.platform == "win32":
            return
        try:
            library = ctypes.CDLL(None)
            mallctl = library.mallctl
            mallctl.argtypes = [
                ctypes.c_char_p,
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.c_void_p,
                ctypes.c_size_t,
            ]
            mallctl.restype = ctypes.c_int
            self._mallctl = mallctl
        except (AttributeError, OSError):
            return

    def _read(self, name: str, value_type: type[ctypes._SimpleCData]) -> int | None:
        if self._mallctl is None:
            return None
        value = value_type()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        try:
            result = self._mallctl(
                name.encode("ascii"),
                ctypes.byref(value),
                ctypes.byref(size),
                None,
                0,
            )
        except (OSError, TypeError):
            return None
        return int(value.value) if result == 0 else None

    def snapshot(self) -> dict[str, int] | None:
        if self._mallctl is None:
            return None
        epoch = ctypes.c_uint64(1)
        try:
            result = self._mallctl(
                b"epoch",
                None,
                None,
                ctypes.byref(epoch),
                ctypes.sizeof(epoch),
            )
        except (OSError, TypeError):
            return None
        if result != 0:
            return None
        values = {name: self._read(f"stats.{name}", ctypes.c_size_t) for name in self._BYTE_STATS}
        values["arenas"] = self._read("opt.narenas", ctypes.c_uint)
        if any(value is None for value in values.values()):
            return None
        return {name: int(value) for name, value in values.items()}


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
        self._jemalloc_stats = _JemallocStatsReader()
        self._memory_diagnostics_enabled = os.getenv(
            "LIYAN_MEMORY_DIAGNOSTICS",
            "",
        ).strip().lower() in {"1", "true", "yes", "on"}
        self._memory_diagnostics_interval = max(
            5.0,
            float(os.getenv("LIYAN_MEMORY_DIAGNOSTICS_INTERVAL_SECONDS", "30")),
        )
        self._next_memory_diagnostics_at = 0.0
        if self._memory_diagnostics_enabled and not tracemalloc.is_tracing():
            tracemalloc.start(
                max(
                    1,
                    min(
                        25,
                        int(os.getenv("LIYAN_MEMORY_DIAGNOSTICS_FRAMES", "8")),
                    ),
                )
            )
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
        self._allocator_bytes = Gauge(
            "liyans_jemalloc_bytes",
            "Current jemalloc process byte statistics when jemalloc is available.",
            ("metric",),
            registry=self.registry,
        )
        self._allocator_arenas = Gauge(
            "liyans_jemalloc_arenas",
            "Configured jemalloc arena count when jemalloc is available.",
            registry=self.registry,
        )
        self._allocator_available = Gauge(
            "liyans_jemalloc_available",
            "Whether fixed-cardinality jemalloc statistics are available.",
            registry=self.registry,
        )
        self._memory_diagnostics = Gauge(
            "liyans_memory_diagnostics_gauge",
            "Bounded process memory and task diagnostics when explicitly enabled.",
            ("metric",),
            registry=self.registry,
        )

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE_LATEST

    def render(self) -> bytes:
        self._refresh_jemalloc_metrics()
        self._refresh_memory_diagnostics()
        return generate_latest(self.registry)

    def _refresh_jemalloc_metrics(self) -> None:
        stats = self._jemalloc_stats.snapshot()
        if stats is None:
            self._allocator_available.set(0)
            for metric in _JemallocStatsReader._BYTE_STATS:
                self._allocator_bytes.labels(metric).set(0)
            self._allocator_arenas.set(0)
            return
        self._allocator_available.set(1)
        for metric in _JemallocStatsReader._BYTE_STATS:
            self._allocator_bytes.labels(metric).set(stats[metric])
        self._allocator_arenas.set(stats["arenas"])

    def _refresh_memory_diagnostics(self) -> None:
        if not self._memory_diagnostics_enabled:
            return
        now = perf_counter()
        if now < self._next_memory_diagnostics_at:
            return
        self._next_memory_diagnostics_at = now + self._memory_diagnostics_interval
        current, peak = tracemalloc.get_traced_memory()
        task_names: CollectionCounter[str] = CollectionCounter()
        task_frames = 0
        task_count = 0
        try:
            tasks = list(asyncio.all_tasks())
        except RuntimeError:
            tasks = []
        for task in tasks:
            task_count += 1
            task_kind = task.get_name().split(":", 1)[0][:64]
            task_names[task_kind] += 1
            task_frames += len(task.get_stack(limit=8))
        object_counts: CollectionCounter[str] = CollectionCounter()
        tracked_objects = 0
        for value in gc.get_objects():
            tracked_objects += 1
            value_type = type(value)
            module = value_type.__module__
            if isinstance(module, str) and module.startswith(
                ("liyans", "asyncio", "starlette", "uvicorn")
            ):
                object_counts[f"{module}.{value_type.__qualname__}"] += 1
        snapshot = tracemalloc.take_snapshot()
        top_allocations = [
            {
                "count": statistic.count,
                "size_bytes": statistic.size,
                "trace": str(statistic.traceback[0]),
            }
            for statistic in snapshot.statistics("traceback")[:8]
        ]
        diagnostics = {
            "tracemalloc_current_bytes": current,
            "tracemalloc_peak_bytes": peak,
            "tasks": task_count,
            "task_frames": task_frames,
            "tracked_objects": tracked_objects,
            "gc_generation_0": gc.get_count()[0],
            "gc_generation_1": gc.get_count()[1],
            "gc_generation_2": gc.get_count()[2],
        }
        diagnostics.update(_read_process_memory())
        for metric, value in diagnostics.items():
            self._memory_diagnostics.labels(metric).set(value)
        logger.info(
            "Memory diagnostics snapshot %s",
            json.dumps(
                {
                    "tasks": task_names.most_common(20),
                    "object_types": object_counts.most_common(20),
                    "top_allocations": top_allocations,
                },
                sort_keys=True,
            ),
        )

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
