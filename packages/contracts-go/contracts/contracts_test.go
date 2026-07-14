package contracts

import (
	"encoding/json"
	"testing"
)

func TestTopic3EnvelopeJSONRoundTrip(t *testing.T) {
	t.Parallel()

	raw := []byte(`{
		"schema_version":"topic3.envelope.v1",
		"envelope_id":"11111111-1111-4111-8111-111111111111",
		"event_type":"topic3.contract.test",
		"message_kind":"EVENT",
		"tenant_id":"tenant-a",
		"session_id":"22222222-2222-4222-8222-222222222222",
		"subject_ref":"subject:test",
		"correlation_id":"33333333-3333-4333-8333-333333333333",
		"sequence":0,
		"partition_key":"tenant-a:session",
		"producer":{"agent":"Lecturer","service":"test","instance_id":"go-test","build_version":"test-v1"},
		"delivery":{"mode":"AT_LEAST_ONCE","idempotency_key":"contract:test:000000000000","attempt":1,"max_attempts":3,"priority":"NORMAL","available_at":"2026-07-14T00:00:00Z"},
		"trace_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		"created_at":"2026-07-14T00:00:00Z",
		"payload":{"verified":true}
	}`)

	var envelope Topic3EnvelopeV1
	if err := json.Unmarshal(raw, &envelope); err != nil {
		t.Fatalf("unmarshal Topic3 Envelope: %v", err)
	}
	if envelope.TenantId != "tenant-a" {
		t.Fatalf("unexpected tenant: %s", envelope.TenantId)
	}
	if envelope.MessageKind != MessageKindEVENT {
		t.Fatalf("unexpected message kind: %s", envelope.MessageKind)
	}
	encoded, err := json.Marshal(envelope)
	if err != nil {
		t.Fatalf("marshal Topic3 Envelope: %v", err)
	}
	if len(encoded) == 0 {
		t.Fatal("encoded Envelope is empty")
	}
}

func TestCandidateAndBlockTypes(t *testing.T) {
	t.Parallel()

	candidate := CandidateV1{
		SchemaVersion:               "topic3.candidate.v1",
		CandidateId:                 UUID("44444444-4444-4444-8444-444444444444"),
		CandidateVersion:            1,
		BlueprintId:                 UUID("55555555-5555-4555-8555-555555555555"),
		BlueprintVersion:            "blueprint-v1",
		BlueprintSha256:             "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
		ResourceType:                ResourceTypeLecturerDoc,
		Status:                      CandidateStatusCOMPLETE,
		PersonalizationPolicyDigest: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
		CandidateSha256:             "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
		CreatedAt:                   DateTime("2026-07-14T00:00:00Z"),
		Provenance: CandidateProvenanceV1{
			Agent:               SourceAgentLecturer,
			AgentBuildVersion:   "agent-v1",
			PromptBundleVersion: "prompt-v1",
			ProviderAlias:       "spark_text",
		},
		Blocks: []BlockV1{
			{
				SchemaVersion:        "topic3.block.v1",
				BlockId:              "block-1",
				BlockType:            BlockTypeMARKDOWN,
				Ordinal:              0,
				ContentSchemaVersion: "lecturer.block.v1",
				Content:              map[string]any{"text": "transfer function"},
				ContentSha256:        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				Status:               BlockStatusCOMPLETE,
				CreatedAt:            DateTime("2026-07-14T00:00:00Z"),
			},
		},
	}

	encoded, err := json.Marshal(candidate)
	if err != nil {
		t.Fatalf("marshal Candidate: %v", err)
	}
	var decoded CandidateV1
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("unmarshal Candidate: %v", err)
	}
	if decoded.ResourceType != ResourceTypeLecturerDoc || len(decoded.Blocks) != 1 {
		t.Fatalf("candidate round trip lost contract data: %#v", decoded)
	}
}

func TestReleaseAuthorizationBooleanType(t *testing.T) {
	t.Parallel()

	authorization := ReleaseAuthorizationPayloadV1{OneTimeUse: true}
	if !authorization.OneTimeUse {
		t.Fatal("one_time_use must remain a Go boolean")
	}
}
