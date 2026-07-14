# Global Contract Unification

## Canonical source

All wire contracts are authored once in the Python package
`liyans_contracts`. Generated JSON Schema and TypeScript are build artifacts.
No backend module or frontend feature may define a duplicate wire enum.

## Version rules

- Wire schema values use `<domain>.<message>.v<major>`.
- `v1` is immutable. A changed field, enum, default, validation rule, or meaning
  requires `v2`.
- Every model rejects unknown fields.
- Runtime build, policy, prompt, toolchain, and knowledge-base versions are
  separate from wire schema versions.
- Historical records retain their original schema and binding versions.

## Shared identifiers

| Identifier | Meaning |
|---|---|
| `tenant_id` | authorization and storage isolation boundary |
| `session_id` | user learning session |
| `verification_id` | one immutable verification run |
| `candidate_id` | logical generated resource identity |
| `candidate_version` | monotonically increasing candidate revision |
| `trace_id` | distributed trace correlation only |
| `idempotency_key` | caller-selected deduplication identity |

## Shared hash rules

- SHA-256 uses lowercase hexadecimal.
- JSON is canonicalized before hashing.
- A document hash excludes its own hash field.
- Hash comparison is over exact candidate or artifact versions, never an alias
  such as `latest`.

## Contract ownership

The contract registry at `packages/contracts-python/src/liyans_contracts/registry.py`
is the authoritative schema inventory. Adding a schema requires an owner, wire
version, visibility, and compatibility classification.

`config/contract-catalog.json` is the implementation roadmap for every frozen
C1-C12 schema. `CODED_BASELINE` means a canonical Pydantic model exists;
`DESIGN_FROZEN` means the name and owner are frozen but the model is implemented
with its owning module. The Topic 3 Envelope, Block, Candidate, error receipt,
and SSE chunk wrappers are now coded as the strict v1 alignment baseline.

## Topic 3 compatibility

The Topic 3 public Envelope remains an imported frozen contract. Topic 4 adds
payload types and does not redefine the Envelope header. Until the original
Topic 3 Envelope fields are coded, `EnvelopeHeaderV1` in the shared package is
the implementation baseline and must be reconciled against the frozen Topic 3
document before the first integration release.

## Model request compatibility

`ResponsesLiteRequestV1` is an internal adapter contract, not a claim about a
provider-native API. Provider adapters translate it to approved provider wire
formats and must validate the presence of both `instructions` and `tools`.
