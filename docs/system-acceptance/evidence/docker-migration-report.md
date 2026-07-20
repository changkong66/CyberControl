# Docker Data Disk Migration Evidence

## Before Migration

- Docker Desktop server: `29.6.1`
- Source VHDX: `C:\Users\wch06\AppData\Local\Docker\wsl\disk\docker_data.vhdx`
- Source VHDX size: `25.24 GiB`
- Target directory: `D:\Docker\wsl`
- C: free: `12.88 GiB`
- D: free: `85.65 GiB`
- Containers: `19 total, 0 running`
- Images: `38`
- Volumes: `38`
- Compose projects observed: `3`
- Migration state: `NOT_STARTED`

## Inventory Digests

- Container inventory SHA256: `FACB2F75ED7DC6BBA5511F42C362E3EE3E3B48530001369970B1A6E944571699`
- Image inventory SHA256: `D455AE05618191ACA044FEC7AF21A79D46BB0A7871D7F329C18AAD14125FDB55`
- Volume inventory SHA256: `C963EEEBD6D16CAB2FB94EA684C4FCEC7A21643B85667119F30F5404F33DEB69`

## Protected Volumes

- `cybercontrol-acceptance_liyans-postgres`
- `cybercontrol-acceptance_liyans-runtime`
- `cybercontrol-prc_liyans-postgres`
- `cybercontrol-prc_liyans-runtime`
- `infra_liyans-postgres`
- `cybercontrol-trivy-cache`

## Reproduction Commands

```powershell
docker info
docker ps -a --no-trunc
docker image ls --digests --no-trunc
docker volume ls
docker system df -v
docker compose ls --all
```

The official Docker Desktop GUI migration checkpoint remains pending:

`Settings -> Resources -> Advanced -> Disk image location -> D:\\Docker\\wsl`

## After Migration

- Official Docker Desktop migration: `COMPLETED`
- Data VHDX: `D:\Docker\wsl\DockerDesktopWSL\disk\docker_data.vhdx`
- Old C: VHDX exists: `false`
- Data VHDX size: `25.24 GiB`
- C: free: `34.67 GiB`
- D: free: `60.32 GiB`
- Containers: `19 total, 0 running`
- Images: `38`
- Volumes before release-volume creation: `38`
- Image inventory SHA256 matched: `true`
- Volume inventory SHA256 matched: `true`

## PostgreSQL Integrity

- Alembic head: `20260716_0009`
- Tenant tables / FORCE RLS tables: `68 / 68`
- Append-only triggers: `55`
- Audit chain breaks: `0`
- Outbox DEAD / OPEN / PUBLISHED: `0 / 0 / 26`
- Preserved verification state: `RELEASED`
- Authorization consumptions: `1`
- Committed publication batches: `1`
- Public stream events: `1`

Migration acceptance result: `ACCEPTED_NO_ASSET_LOSS`

## Release PostgreSQL Volume

- Name: `cybercontrol_release_postgres`
- Driver: `local`
- Purpose label: `release-acceptance`
- Data class label: `isolated-clean-postgres`
- Initial read-only empty-volume check: `passed`
- Existing development volumes modified or deleted: `none`
