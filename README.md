# EFFICA

FastAPI, Next.js, MariaDB, and the MariaDB-backed worker compose the application.

## Local development

- Python 3.12+, Node.js 22 LTS, `uv`, `ssh`, and `sshpass` are required.
- The root `.env` is the only environment file and must have mode `600`.
- Local development never starts a local MariaDB. An SSH tunnel to the EC2-local
  MariaDB rewrites `DATABASE_URL` only for the lifetime of the process.
- FastAPI listens on `127.0.0.1:8000`; Next.js listens on `127.0.0.1:3000`.
- Run Python tests from the repository root (`uv run pytest`). Do not invoke
  them from `apps/web`; collection paths are rooted at the process cwd.
- `DB_TUNNEL_PORT` may be set if the default local forwarding port `13306` is occupied.

Copy `.env.example` to `.env` and fill every required value.

Google is the only user-facing sign-in provider. Local production-like runs
must configure `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`; mock OAuth exists
only behind `APP_ENV=test` and is never returned by `/api/v1/auth/providers`.
The only supported runtime entrypoint is
`./.agents/scripts/run.sh`. Use `./.agents/scripts/run.sh start` for the
MariaDB-backed local stack and `./.agents/scripts/run.sh verify` for the
complete quality gate. There is intentionally no root-level `run.sh`.

`LLM_PROVIDER_MODE=stub` keeps an offline deterministic single-model flow for
tests. Auto mode is the default: it enables live analysis when `OPENAI_API_KEY`
is present and otherwise stays offline. Live analysis uses the OpenAI Responses
API only. The default is `gpt-5.6-luna` with `xhigh` reasoning; an
administrator can change the active GPT model and reasoning effort through
`/api/v1/admin/models`, and the worker reloads that configuration for each job.
Startup rejects a missing key or a non-OpenAI endpoint. The provider enforces bounded
timeouts/retries, a rate limiter, circuit breaking, strict output validation,
source-identity masking, and redacted metrics.

## Production

Production splits the runtime: MariaDB, FastAPI, and the worker run on EC2.
EC2 nginx exposes only `/api/*` and `/health/*` over TLS. Next.js runs only on
Vercel. The browser talks to Vercel over HTTPS; Vercel's same-origin `/api/v1/*`
rewrite talks to the EC2 nginx API origin, so browser CORS configuration is not
required.

The canonical production origin is `https://effica.vercel.app`. The only
supported deployment entrypoint is `./.agents/scripts/deploy.sh`; it executes
the locked preflight, database backup, atomic EC2 release, Vercel deployment,
and post-deploy health checks. There is intentionally no root-level
`deploy.sh` and no GitHub Actions deployment or CI workflow. Production
startup fails closed unless MariaDB, HTTPS origins, the exact Google callback
URL, and Google OAuth credentials are configured.

`npm run dev` remains available for local development, while the package
intentionally has no `next start` script. Do not ship Next.js from EC2.

The DB administrator receives `ALL PRIVILEGES` on the application database only, and
`DB_ADMIN_PASSWORD` must equal `EC2_PASSWORD`. Back up MariaDB, including `stored_blobs`, before
destructive migrations or retention work.
