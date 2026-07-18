\set ON_ERROR_STOP on

INSERT INTO tenants (
  tenant_id,
  slug,
  display_name,
  status,
  oidc_issuer,
  oidc_tenant_claim,
  settings_document,
  version
)
VALUES (
  'demo-academy',
  'demo-academy',
  'Demo Academy',
  'ACTIVE',
  :'oidc_issuer',
  'demo-academy',
  '{"development_fixture": true}'::jsonb,
  1
)
ON CONFLICT (tenant_id) DO UPDATE
SET
  slug = EXCLUDED.slug,
  display_name = EXCLUDED.display_name,
  status = EXCLUDED.status,
  oidc_issuer = EXCLUDED.oidc_issuer,
  oidc_tenant_claim = EXCLUDED.oidc_tenant_claim,
  settings_document = tenants.settings_document || EXCLUDED.settings_document,
  version = tenants.version + 1,
  updated_at = now()
WHERE (
  tenants.slug,
  tenants.display_name,
  tenants.status,
  tenants.oidc_issuer,
  tenants.oidc_tenant_claim,
  tenants.settings_document @> EXCLUDED.settings_document
) IS DISTINCT FROM (
  EXCLUDED.slug,
  EXCLUDED.display_name,
  EXCLUDED.status,
  EXCLUDED.oidc_issuer,
  EXCLUDED.oidc_tenant_claim,
  true
);
