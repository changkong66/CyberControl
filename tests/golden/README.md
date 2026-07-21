# Phase 7 Academic Golden Facts

This directory is intentionally empty until a qualified human reviewer supplies
an independently reviewed academic fact set. It is not valid to reclassify the
Topic1 demonstration bundle, generated benchmark chunks, model output, or test
fixtures as human-reviewed facts.

The acceptance input consists of two files that are deliberately not included
as placeholders:

- `phase7-academic-golden-facts.v1.jsonl`: one UTF-8 JSON object per fact. Each
  record requires `fact_id`, `claim`, `expected_outcome`, `citations`, and
  `license_expression`.
- `phase7-academic-golden-review.v1.json`: reviewer attestation with schema
  `phase7.academic-golden-review.v1`, the exact facts SHA256, a non-empty
  reviewer subject reference, review timestamp, review policy version, and an
  `ACCEPTED` decision.

The reviewer must confirm the cited source is usable for this purpose and that
the expected outcome is independently verified. The dataset validator rejects
missing required fields, duplicate fact identifiers, a hash mismatch, or any
review decision other than `ACCEPTED`.

Use `tools/acceptance/build-phase7-dataset-inventory.py` to materialize the
synthetic retrieval corpus, inventory all dataset classes, and verify whether
the human-reviewed set is eligible for accuracy acceptance.
