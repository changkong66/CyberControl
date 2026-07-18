# Topic4 Performance Acceptance Report

## 1. Accepted Thresholds

| Workload | Threshold | Evidence | Result |
| --- | --- | --- | --- |
| Local RAG, 100,000 chunks | p95 <= 200 ms | `c2-100k-benchmark.json` | 12.283 ms, passed |
| C12 committed replay | p95 <= 300 ms | 25-sample PostgreSQL assertion | passed |
| Concurrent C1 verification | 200 operations | real PostgreSQL integration | passed |
| Concurrent C12 consumption | 200 operations | real PostgreSQL integration | passed |

## 2. C2 Benchmark Detail

- Corpus: 100,000 knowledge chunks across 10 shards.
- Query count: 200 after 20 warmups.
- Retrieval p50: 9.747 ms.
- Retrieval p95: 12.283 ms.
- Retrieval p99: 13.574 ms.
- Retrieval max: 14.048 ms.
- Index build: 22.049 seconds.
- Index serialization: 9.106 seconds.
- Serialized index: 216.968 MiB.
- Peak process working set: 1,221.141 MiB.

## 3. Concurrency Results

The final PostgreSQL suite completed 200 independent C1 verification runs. It
asserted 200 accepted tasks, 200 completed snapshots, 200 unique verification
IDs, 200 reports, and no duplicate Claim identity.

The C12 contention test submitted 200 concurrent consumption calls for the same
one-time authorization. Every caller converged on the same immutable publication
batch, and the database contained one consumption identity and one committed
publication result.

## 4. Interpretation

Results are acceptance measurements on the repository test environment, not a
capacity guarantee for an unmeasured production host. Production sizing must
retain the same dataset, shard count, database configuration, and concurrency
profile when comparing against these thresholds.
