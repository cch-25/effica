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

`LLM_PROVIDER_MODE=stub` keeps an offline deterministic single-model flow for
tests. Auto mode is the default: it enables live analysis when `OPENAI_API_KEY`
is present and otherwise stays offline. Live analysis uses the OpenAI Responses
API only. The default is `gpt-5.6-luna` with `xhigh` reasoning; an
administrator can change the active GPT model and reasoning effort through
`/api/v1/admin/models`, and the worker reloads that configuration for each job.
Startup rejects a missing key or a non-OpenAI endpoint. The provider enforces bounded
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

`./deploy.sh` is the production entrypoint. It deploys only MariaDB, FastAPI, and the worker to EC2,
removes/disables any EC2 Next.js service and artifacts, exposes only `/api/*` and `/health/*` through
the TLS-enabled EC2 nginx site, configures the Vercel production environment, and deploys `apps/web` with
`vercel --prod`. The browser always talks to Vercel over HTTPS; Vercel's same-origin `/api/v1/*`
rewrite talks to the EC2 nginx API origin, so browser CORS configuration is not required.

Vercel is the only supported production host for Next.js. `npm run dev` remains available for local
development, while the package intentionally has no `next start` script. `make deploy-web` can be
used for a frontend-only Vercel production deployment after the project has been linked and its
production environment variables have been configured by `./deploy.sh`.

The DB administrator receives `ALL PRIVILEGES` on the application database only, and
`DB_ADMIN_PASSWORD` must equal `EC2_PASSWORD`. Back up MariaDB, including `stored_blobs`, before
destructive migrations or retention work.
