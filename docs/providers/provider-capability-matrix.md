# Provider Capability Matrix

## Decision states

| State | Meaning |
|---|---|
| `ALLOWLISTED_DISABLED` | approved by project policy but disabled pending validation |
| `LOCAL_ENABLED` | local deterministic capability, no external AI call |
| `PROHIBITED` | not in the provider allowlist |

## Matrix

| Alias | Capability | State | Engineering decision |
|---|---|---|---|
| `spark_text` | text generation and constrained semantic synthesis | `ALLOWLISTED_DISABLED` | implement adapter and real smoke suite before enabling |
| `xfyun_code` | code assistance | `ALLOWLISTED_DISABLED` | generation assistance only; deterministic compilers and sandbox remain authoritative |
| `seedance` | multimodal generation | `ALLOWLISTED_DISABLED` | frozen alias only; require official endpoint and account evidence |
| external embedding API | embedding | `PROHIBITED` | no call may be made under the current allowlist |
| local hashed lexical vectors | deterministic retrieval features | `LOCAL_ENABLED` | primary Faiss vector source until policy changes |
| local BM25/formula/graph retrieval | retrieval | `LOCAL_ENABLED` | required retrieval channels |
| local SymPy/NumPy | math verification | `LOCAL_ENABLED` | deterministic evidence, never a generation provider |

## Validation checklist for each external provider

1. Official endpoint and account ownership are documented.
2. Authentication and secret rotation work without exposing credentials.
3. Request and response schemas are captured as fixtures.
4. `instructions` and `tools` map without silently dropping either field.
5. Streaming, timeout, retry, rate-limit, and cancellation behavior are tested.
6. Data classification and retention terms permit the intended payload.
7. PII-redacted smoke tests pass.
8. Provider failure cannot bypass verification or release controls.

## Enablement rule

An adapter may be enabled only when its capability record, ADR, smoke-test
artifact, and security review all reference the same adapter version and
endpoint identity. Configuration alone cannot override a prohibited capability.
