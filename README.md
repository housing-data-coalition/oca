# NYC Housing Court Filings

The OCA Data Collective regularly receives housing court filings data from the New York State Office of Court Administration (OCA). In this repository we manage the Extract-Transform-Load process for getting raw XML filings data from OCA via SFTP, parsing the nested XML data into a set of tables, and making those CSV files publicly available for download. These data are also now publicly available in XML format on the court system's [website](https://ww2.nycourts.gov/landlord-tenant-data-34621).

To work with these data you can use the [NYCDB](https://github.com/nycdb/nycdb) to automatically load all of the tables into a PostgreSQL database for analysis. You can also find documentation about the data, including a [data dictionary](https://docs.google.com/spreadsheets/d/1GMDomQr8gEave6uLpLby9gQU0oMoGRL39kQdNbBJEqE) on the [NYCDB wiki](https://github.com/nycdb/nycdb/wiki/Dataset:-OCA-Housing-Court-Records).

The OCA Data Collective includes the [Right to Counsel Coalition](https://www.righttocounselnyc.org/), [BetaNYC](https://beta.nyc/), the [Association for Neighborhood and Housing Development](https://anhd.org/), the [University Neighborhood Housing Program](https://unhp.org), and [JustFix](https://www.justfix.org/). It is also affiliated with the [Housing Data Coalition](https://www.housingdatanyc.org/) (HDC). 

## Attribution

When utilizing this work, please use one of the following attributions and links:

> Data from the New York State Office of Court Administration via the OCA Data Collective in collaboration with the [Right to Counsel Coalition](https://www.righttocounselnyc.org/).

> Data from the New York State Office of Court Administration via the OCA Data Collective. This data has been obtained and made available through the collaborative efforts of the [Right to Counsel Coalition](https://www.righttocounselnyc.org/), [BetaNYC](https://beta.nyc/), the [Association for Neighborhood and Housing Development](https://anhd.org/), the [University Neighborhood Housing Program](https://unhp.org), and [JustFix](https://www.justfix.org/).

## License 

This work is licensed under a [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License](http://creativecommons.org/licenses/by-nc-sa/4.0/). 

<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/"><img alt="Creative Commons License" style="border-width:0" src="https://i.creativecommons.org/l/by-nc-sa/4.0/88x31.png" /></a>

## CSV Files

[![Date Last Updated](https://oca-2-dev.s3.amazonaws.com/public/last-updated-shield.svg)](https://oca-2-dev.s3.amazonaws.com/public/last-updated-date.txt)

* [`oca_index`](https://oca-2-dev.s3.amazonaws.com/public/oca_index.csv)
* [`oca_causes`](https://oca-2-dev.s3.amazonaws.com/public/oca_causes.csv)
* [`oca_addresses`](https://oca-2-dev.s3.amazonaws.com/public/oca_addresses.csv)
* [`oca_parties`](https://oca-2-dev.s3.amazonaws.com/public/oca_parties.csv)
* [`oca_events`](https://oca-2-dev.s3.amazonaws.com/public/oca_events.csv)
* [`oca_appearances`](https://oca-2-dev.s3.amazonaws.com/public/oca_appearances.csv)
* [`oca_appearance_outcomes`](https://oca-2-dev.s3.amazonaws.com/public/oca_appearance_outcomes.csv)
* [`oca_motions`](https://oca-2-dev.s3.amazonaws.com/public/oca_motions.csv)
* [`oca_decisions`](https://oca-2-dev.s3.amazonaws.com/public/oca_decisions.csv)
* [`oca_judgments`](https://oca-2-dev.s3.amazonaws.com/public/oca_judgments.csv)
* [`oca_warrants`](https://oca-2-dev.s3.amazonaws.com/public/oca_warrants.csv)


## About the data

The data we receive from OCA is an extract of all landlord and tenant cases in NYC housing court, without personally identifying information. For more details about the raw data and the final parsed tables, see [`/docs`](/docs).

## About the code

The ETL pipeline lives under [`lib/`](lib/). See [`lib/README.md`](lib/README.md) for stage-by-stage architecture, module map, and SQL script roles.

### Local setup

You need credentials for OCA SFTP and the BetaNYC AWS for S3 (file storage) and RDS (PostgreSQL database), plus Docker and Docker Compose.

Copy the example env file and fill in credentials:

```bash
cp .env.example .env     # Or 'copy .env.example .env' on Windows
```

Required variables: `DATABASE_URL`, `AWS_*`, `SFTP_*`, and `MODE=2` for full publish. Optional runtime controls are documented in [`.env.example`](.env.example).

**Typical weekly run** (process new SFTP files only; geocodes addresses in the staging CSV before S3 upload, then promotes and publishes):

```bash
docker compose run --rm app python oca_update.py
```

**RDS geocode backfill** (on-demand; rows in `oca_addresses` where `lat IS NULL` only; does not publish public CSVs):

```bash
docker compose run --rm app python oca_geocode_backfill.py
```

Use the same `DATABASE_URL` and `DB_SCHEMA` as weekly ETL. Optional flags: `--geocode-workers`, `--census-batch-chunk-size` (or env `GEOCODE_WORKERS`, `CENSUS_BATCH_CHUNK_SIZE`). After backfill, run view rebuild + publish separately if S3 public files must reflect new coordinates.

**Refactor / replay run** (isolated schema and S3 prefix, force replay from S3 private backups):

```bash
docker compose run --rm app env \
  DB_SCHEMA=refactor \
  S3_PREFIX=refactor/ \
  REPROCESS_GLOB='LandlordTenant.Incr.2024-*.zip' \
  FORCE_REPROCESS=true \
  GEOCODE_WORKERS=2 \
  python oca_update.py
```

Compose reads `.env` from the repo root for `DATABASE_URL`, AWS, and SFTP. Override any variable inline with `env VAR=value ...` as above.

Run the test suite in Docker:

```bash
docker compose run --rm app python -m unittest discover -s tests -p "test_*.py"
```

### Weekly scheduling and Kubernetes

See [`docs/operations/weekly-etl-scheduling.md`](docs/operations/weekly-etl-scheduling.md) for:

- local Docker + **cron** (weekly example),
- **Kubernetes CronJob** (`k8s/k8s-cron-job.yaml`, 2Gi memory limit, secrets via `oca-etl-secrets`),
- **AWS EventBridge + ECS Fargate** (weekly task schedule).

Create cluster secrets from [`k8s/oca-etl-secret.example.yaml`](k8s/oca-etl-secret.example.yaml); do not commit real credentials.

### Runtime controls

Optional env vars (and matching `oca_update.py` CLI flags) tune isolation, replay, memory, and parse throughput. When unset, defaults preserve standard weekly behavior: new SFTP files only, `public` schema, CPU-count geocode workers.

| Variable | Purpose | Default |
|----------|---------|---------|
| `DB_SCHEMA` | PostgreSQL `search_path` target | `public` |
| `S3_PREFIX` | Prefix for `private/` and `public/` S3 keys | none |
| `REPROCESS_GLOB` | Filename glob for S3 private zip replay | none |
| `FORCE_REPROCESS` | Replay manifest-completed glob matches | `false` |
| `GEOCODE_WORKERS` | Geosupport multiprocessing pool size | CPU count |
| `CENSUS_BATCH_CHUNK_SIZE` | Census batch geocoder chunk | `2500` |
| `CSV_ROW_CHECK_CHUNK_SIZE` | Staging CSV preprocess / row-check chunk | `1000` |
| `PARSE_WRITE_BATCH_ENABLED` | Buffer parser DuckDB writes in txn windows | `1` (on) |
| `PARSE_WRITE_BATCH_SIZE` | Max buffered INSERTs before flush | `128` |
| `PARSE_WRITE_FLUSH_EVERY_N_CASES` | Flush cadence per parse worker | `16` |
| `DB_KEEPALIVES_*` | PostgreSQL TCP keepalive tuning (see `.env.example`) | RDS-friendly defaults |

Long runs (multi-hour XML parse, S3 upload, geocoding) may idle the RDS connection; the pipeline uses TCP keepalives and automatic reconnect (`ensure_connection`) before RDS-heavy stages. Optional `DB_KEEPALIVES_IDLE` / `DB_KEEPALIVES_INTERVAL` / `DB_KEEPALIVES_COUNT` override libpq defaults.

Use an isolated `S3_PREFIX` (e.g. `refactor/`) for refactor and end-to-end test runs so reads and writes stay out of production public paths. Memory target per job is **≤ 2 GiB**; lower `GEOCODE_WORKERS` if geocoding approaches the limit.

### Jupyter notebook for maintenance

Comment out `CMD ["python", "oca_update.py"]` in the Dockerfile, then:

```bash
docker compose up -d
docker compose exec app /bin/bash
jupyter notebook --allow-root --ip 0.0.0.0 --no-browser
```

### General rules for setting up a S3 Bucket

```json
{
    "Version": "2012-10-17",
    "Id": "Policy1234",
    "Statement": [
        {
            "Sid": "Stmt1623892536589",
            "Effect": "Allow",
            "Principal": {
                "AWS": "arn:aws:iam::...user or api account"
            },
            "Action": "s3:*",
            "Resource": "arn:aws:s3:::...bucket or specific folder..."
        },
         {
            "Sid": "IPAllow",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::oca-2-dev/public/*",
            "Condition": {
                "IpAddress": {
                    "aws:SourceIp": [
                        "192.168.1.1"
                    ]
                }
            }
        }
    ]
}
```

<!-- 
the max timeout of 15 minutes. this does not provide much flexibility for longer runtimes.

### (Optional) Running on AWS ECR and Lambda

Setup [AWS CLI](https://aws.amazon.com/cli/) and create an ECR repository.

```
cp .env.example .env   # fill all the credentials. Change the db to a remote dbi instead of the local docker.

aws configure

docker build . -t oca-weekly --build-arg MODE=2 --build-arg SFTP_HOST=sftp.[rest of the url] .
```

Follow the push commands. You can to the screen by clicking into the repository you create and on the "View push commands" on the right below the breadcrumbs. Skip the second command `docker build -t ...`

![Push commands](./docs/ecr-push-commands.png)

Now in Lambda, create a new function from a Container Image and then 'Browse Images'. *You need to replace / deploy a new image any time you update the ECR image.*  

Increase Memory to `10240` MB and Ephemeral storage to `8000` MB. AND Timeout to `15` minutes.


#### Tiggers

![Setting up a trigger](./docs/lambda-tigger.png) 


### (Optional) RDS Clone

If you have an existing database on Amazon, you can use S3 to "clone" the CSV files to the RDS service (or you can do a sql.dump). To enable add  the RDS database uri to the `CLONED_DATABASE_URL` variable in the .env file. 

Make sure to run `CREATE EXTENSION aws_s3 CASCADE;` as you may encounter the error message `schema "aws_commons" does not exist"` if you do not. Read [this](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PostgreSQL.S3Import.html) for more details on setting up Postgresql for s3 imports.

After the main process is done, additional scripts will overwrite the contents on the RDS. Make sure there are proper permissions for the RDS to connect to S3 (if there is a bucket policy).

![Adding IAM to allow for S3 access](./docs/rds_iam.png)

-->