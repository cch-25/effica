# Perspective News Platform

FastAPI, Next.js, MariaDB, and the MariaDB-backed worker compose the application. Operational
entrypoints are intentionally limited to the two repository-root files `run.sh` and `deploy.sh`.

## Local development

- Python 3.12+, Node.js 22 LTS, `uv`, `ssh`, and `sshpass` are required.
- The root `.env` is the only environment file and must have mode `600`.
- Local development never starts a local MariaDB. `run.sh` opens an SSH tunnel to the EC2-local
  MariaDB and rewrites `DATABASE_URL` only for the lifetime of the process.
- FastAPI listens on `127.0.0.1:8000`; Next.js listens on `127.0.0.1:3000`.

Copy `.env.example` to `.env`, fill every required value, then run:

`LLM_PROVIDER_MODE=stub` runs the complete offline three-model flow. To switch
to live providers, set it to `live` and configure all three
`LLM_{PRIMARY,SECONDARY,TERTIARY}_{ENDPOINT,MODEL_ID,ALIAS,API_KEY}` groups.
Startup rejects incomplete live configuration. Each provider enforces bounded
timeouts/retries, a rate limiter, circuit breaking, strict output validation,
source-identity masking, and redacted metrics.

```sh
./run.sh                 # tunnel + migration + FastAPI + Next.js
./run.sh worker          # optional worker in another terminal
./run.sh check-db
./run.sh migrate
./run.sh seed
./run.sh verify
```

`./run.sh help` lists every supported operation. Ctrl-C stops both local servers and the SSH
tunnel. `DB_TUNNEL_PORT` may be set if the default local forwarding port `13306` is occupied.

## Production deployment

`./deploy.sh` performs a complete EC2 deployment: source and sanitized root `.env` synchronization,
MariaDB installation and loopback binding, database/user provisioning, Python and Node dependency
installation, Alembic migration, Next.js build, inline systemd/Nginx configuration, service restart,
and health verification. The DB administrator receives `ALL PRIVILEGES` on the application database
only, and `DB_ADMIN_PASSWORD` must equal `EC2_PASSWORD`.

MariaDB, FastAPI, and Next.js stay on EC2 loopback behind Nginx. TLS is intentionally deferred.
Back up MariaDB, including `stored_blobs`, before destructive migrations or retention work.
