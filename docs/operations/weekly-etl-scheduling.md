# Weekly OCA ETL scheduling and deployment

The OCA pipeline ingests new SFTP XML zip files weekly, geocodes addresses in the local staging CSV before S3 upload, promotes staging data in PostgreSQL, and publishes CSVs to S3 via `aws_s3`. All three supported schedulers run the same container entrypoint:

```bash
python oca_update.py
```

Historical RDS rows that still lack coordinates are handled separately by `oca_geocode_backfill.py` (not scheduled with weekly ETL). See [RDS geocode backfill](#rds-geocode-backfill-on-demand) below.

Cases marked deleted in OCA XML are tombstoned in `oca_metadata.deletedate` and purged from `oca_index` (and child tables) during weekly promotion. Historical orphans (tombstone without purge) are cleaned by `oca_deletion_backfill.py` — see [RDS deletion backfill](#rds-deletion-backfill-on-demand).

Use Docker (or the published image `justfixnyc/oca:latest`) with credentials supplied via environment variables or a secret store. See [Runtime controls](#runtime-controls) and the root [README](../../README.md).

## Runtime controls

| Variable | Purpose | Production default |
|----------|---------|-------------------|
| `MODE` | Publish mode (`2` = full S3 publish) | `2` |
| `DATABASE_URL` | PostgreSQL connection (RDS) | required |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 + RDS `aws_s3` credentials | required (or IAM role on ECS) |
| `AWS_S3_BUCKET_NAME` | Target bucket | required |
| `SFTP_*` | OCA SFTP download | required |
| `DB_SCHEMA` | `search_path` schema (refactor/E2E) | empty → `public` |
| `S3_PREFIX` | Key prefix for `private/` and `public/` | empty → bucket root |
| `REPROCESS_GLOB` | Replay zip files from S3 `private/` | empty |
| `FORCE_REPROCESS` | Replay manifest-completed files | `false` |
| `PARSE_FAIL_FAST` | Fail `parse_xml` and abort before export/promote when any zip has case-level parse failures | `false` |
| `GEOCODE_WORKERS` | Geosupport pool size | CPU count |
| `CENSUS_BATCH_CHUNK_SIZE` | Census batch chunk | `2500` |
| `CSV_ROW_CHECK_CHUNK_SIZE` | Staging CSV preprocess chunk | `1000` |

Refactor and E2E runs must set `S3_PREFIX=refactor/` (or another isolated prefix) so reads/writes stay out of production public paths.

Memory target: **≤ 2 GiB** per job. Tune `GEOCODE_WORKERS` down (e.g. `2`) if geocoding approaches the limit.

**Parse failures (default lenient):** With `PARSE_FAIL_FAST=false`, weekly runs still promote and publish; zips with any `cases_failed` in manifest `etl_files.details` do **not** reach `status = 'completed'` (requires **`cases_failed = 0`**) and are omitted from `completed_reprocess_files` on later `REPROCESS_GLOB` runs (no `FORCE_REPROCESS` needed to retry them). Set `PARSE_FAIL_FAST=true` to stop the run before export/promote.

## Publish behavior

- **Geocode timing:** weekly runs geocode all rows in `oca_addresses_staging.csv` locally (`geocode_staging` manifest step) before uploading staging CSVs to S3. Promotion imports coordinates (and sets `geom` on `oca_addresses`); there is no post-promotion RDS geocode in `oca_etl()`.
- **Core tables:** every table in `OCA_TABLES` is exported after promotion. Selective skip per table is unsafe when `oca_index_staging` has rows: promotion deletes child rows for the batch even when a child staging CSV was empty.
- **Address views:** `create_addresses_views.sql` runs on every successful weekly publish (views only; `geom` already on the base table).
- **S3 encryption:** SSE-S3 normalization runs only on objects exported in the current run (not a full public-prefix scan).

## RDS geocode backfill (on-demand)

Use when `oca_addresses` still has rows with `lat IS NULL` (e.g. pre-CSV-geocode history). **Not** wired into cron, Kubernetes CronJob, or ECS weekly tasks.

```bash
docker compose run --rm app python oca_geocode_backfill.py
```

Same secrets as weekly ETL (`DATABASE_URL`, `DB_SCHEMA`, AWS if needed for manifest only). Tune with `GEOCODE_WORKERS` / `CENSUS_BATCH_CHUNK_SIZE` or CLI flags.

- Selects only ungeocoded rows (`select_addresses_needing_geocode.sql`).
- Records manifest `mode='geocode_backfill'` with step `geocode_refresh` only.
- **Does not** run `create_addresses_views.sql` or publish public CSVs. Re-run publish (or a full `oca_update.py` publish path) if S3 must reflect backfilled coordinates.

## RDS deletion backfill (on-demand)

Use after deploying tombstone-aware promotion, or when validation shows case rows still present for deleted metadata. **Not** wired into weekly ETL.

```bash
docker compose run --rm app python oca_deletion_backfill.py
```

Same secrets as weekly ETL (`DATABASE_URL`, `DB_SCHEMA`). Records manifest `mode='deletion_backfill'` with step `deletion_backfill`.

- Deletes from `oca_index` only (child tables CASCADE); **`oca_metadata` rows are kept** (`deletedate` preserved).
- **Does not** publish public CSVs. Re-run weekly publish if S3 must drop deleted cases from snapshots.

**Validation** (expect `0` after a successful backfill):

```sql
SELECT COUNT(*)::bigint
FROM oca_index i
INNER JOIN oca_metadata m ON m.indexnumberid = i.indexnumberid
WHERE m.deletedate IS NOT NULL;
```

## 1. Local Docker + cron (weekly)

Best for a single host with Docker and an `.env` file.

**Weekly schedule example** (Saturdays 12:00 US/Eastern, same cadence as K8s manifest):

```cron
# /etc/cron.d/oca-etl — adjust path to your clone
0 12 * * 6 root cd /path/to/oca && /usr/bin/docker compose run --rm \
  -e MODE=2 \
  -e GEOCODE_WORKERS=2 \
  app python oca_update.py >> /var/log/oca-etl.log 2>&1
```

Ensure `.env` in the repo root defines `DATABASE_URL`, AWS, and SFTP variables (see `.env.example`). Do not commit `.env`.

**Manual run:**

```bash
docker compose run --rm app python oca_update.py
```

**Refactor / replay example:**

```bash
docker compose run --rm app env \
  DB_SCHEMA=oca_refactor \
  S3_PREFIX=refactor/ \
  REPROCESS_GLOB='LandlordTenant.Incr.2025-*.zip' \
  FORCE_REPROCESS=true \
  GEOCODE_WORKERS=2 \
  python oca_update.py
```

## 2. Kubernetes CronJob (weekly)

Manifest: [`k8s/k8s-cron-job.yaml`](../../k8s/k8s-cron-job.yaml).

**Schedule:** `0 12 * * 6` with `timeZone: America/New_York` (weekly Saturday noon).

**Memory:** requests `1536Mi`, limit `2Gi` (2 GB class).

**Secrets:** create `oca-etl-secrets` before applying the CronJob (see [`k8s/oca-etl-secret.example.yaml`](../../k8s/oca-etl-secret.example.yaml)).

```bash
kubectl apply -f k8s/oca-etl-secret.example.yaml   # after editing placeholders
kubectl apply -f k8s/k8s-cron-job.yaml
kubectl get cronjob oca-etl
```

Non-secret runtime knobs are set inline in the CronJob (`MODE`, `GEOCODE_WORKERS`, etc.). Override `DB_SCHEMA` / `S3_PREFIX` there for refactor jobs.

**One-off job from the CronJob template:**

```bash
kubectl create job --from=cronjob/oca-etl oca-etl-manual-$(date +%s)
kubectl logs -f job/oca-etl-manual-<timestamp>
```

## 3. AWS EventBridge + ECS Fargate (weekly, non-Kubernetes)

Use when production runs on AWS without a cluster. EventBridge starts an ECS task on a schedule; the task uses the same image and command as Docker/K8s.

**High-level steps**

1. Push `justfixnyc/oca:latest` (or your ECR mirror) and register a Fargate task definition with:
   - `command`: `["python", "oca_update.py"]`
   - `memory`: `2048` (hard limit, MiB)
   - `cpu`: `1024` (1 vCPU; adjust if needed)
   - Secrets from AWS Secrets Manager or SSM Parameter Store → container environment (same keys as `.env.example`)
   - Task role: S3 access for the bucket; execution role: ECR pull + secrets
2. Create an ECS cluster and service is optional; scheduled tasks can run standalone.
3. EventBridge rule (weekly Saturday 12:00 ET):

```json
{
  "scheduleExpression": "cron(0 12 ? * SAT *)",
  "scheduleExpressionTimezone": "America/New_York",
  "state": "ENABLED",
  "targets": [{
    "Arn": "arn:aws:ecs:us-east-1:ACCOUNT_ID:cluster/oca-etl",
    "RoleArn": "arn:aws:iam::ACCOUNT_ID:role/EventBridgeECSRunTask",
    "EcsParameters": {
      "TaskDefinitionArn": "arn:aws:ecs:us-east-1:ACCOUNT_ID:task-definition/oca-etl:1",
      "LaunchType": "FARGATE",
      "NetworkConfiguration": {
        "awsvpcConfiguration": {
          "subnets": ["subnet-xxx"],
          "securityGroups": ["sg-xxx"],
          "assignPublicIp": "DISABLED"
        }
      }
    }
  }]
}
```

Replace ARNs, subnets, and security groups. The task needs outbound HTTPS (SFTP, Census geocoder, S3, RDS) and RDS connectivity from the task subnets.

**Environment example (task definition fragment):**

```json
"environment": [
  { "name": "MODE", "value": "2" },
  { "name": "GEOCODE_WORKERS", "value": "2" },
  { "name": "CENSUS_BATCH_CHUNK_SIZE", "value": "2500" },
  { "name": "CSV_ROW_CHECK_CHUNK_SIZE", "value": "1000" }
],
"secrets": [
  { "name": "DATABASE_URL", "valueFrom": "arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:oca-etl:DATABASE_URL::" },
  { "name": "AWS_ACCESS_KEY_ID", "valueFrom": "..." }
]
```

On ECS, prefer IAM task roles for S3 instead of long-lived access keys when RDS `aws_s3` integration allows it.

## Validation checklist

- [ ] `docker compose run --rm app python -m unittest discover -s tests -p "test_*.py"`
- [ ] CronJob or ECS task memory limit ≤ 2 GiB; geocode workers tuned if OOM
- [ ] Secrets not stored in git-tracked manifests (use K8s Secret / Secrets Manager)
- [ ] Refactor runs use `S3_PREFIX=refactor/` (or dedicated prefix)

## Related files

- [`k8s/k8s-cron-job.yaml`](../../k8s/k8s-cron-job.yaml) — CronJob, resources, env
- [`k8s/oca-etl-secret.example.yaml`](../../k8s/oca-etl-secret.example.yaml) — secret template
- [`README.md`](../../README.md) — local setup and runtime controls
