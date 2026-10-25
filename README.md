# SupportNova (Lumora Support)

Complaint handling with two independent checks: an AI reads each complaint and suggests a plan, and a rule engine
decides independently; where they differ the rules win. Customers can also ask questions in a chat, by email, and
place orders. Django + Django Ninja backend, React + Vite frontend, PostgreSQL.

## Quick start (Docker)

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) and nothing else: no Python, Node or database.

```bash
git clone <repo-url> && cd support_nova
docker compose up
```

The first start takes about 10 minutes (it builds the images, installs the packages, creates the database, loads the
sample data and downloads a ~190 MB search model once). Later starts take 1-2 minutes. When you see
`[frontend] ready`, open:

| What | Address |
|---|---|
| Website | http://localhost:5173 |
| API documentation | http://localhost:8001/api/docs |
| Database (pgAdmin, DBeaver, psql) | `localhost:5433`, user / password / database: `supportnova` |

**Sign in** (demo data; the password is `DEMO_PASSWORD`, default `Lumora@2026`):

| Role | Username |
|---|---|
| Administrator | `admin` |
| Manager / reviewer | `manager1` / `reviewer1` |
| Agents | `agent1`, `agent2` |
| Customers | `cust001`, `cust002`, ... |

**The AI needs a key.** Without one everything works except the AI parts, which show a clear "not set up" message.
Copy `.env.example` to `.env`, set `DEEPSEEK_API_KEY`, then `docker compose up -d` again. Email is optional and also
set in `.env`.

Your code stays on your PC and is mounted into the containers: edit a file and the backend restarts / the page
reloads by itself. `Ctrl+C` stops everything; `docker compose up -d` runs it in the background.

## Everyday commands

Run these from the repository folder. `backend` is the service name; commands run inside its container.

| Do this | Command |
|---|---|
| Start / stop | `docker compose up -d` / `docker compose down` |
| Watch the logs | `docker compose logs -f backend` (or `frontend`, `db`) |
| Any Django command | `docker compose exec backend uv run manage.py <command>` |
| Run the tests (PostgreSQL) | `docker compose exec backend uv run manage.py test` |
| Make migrations after changing a model | `docker compose exec backend uv run manage.py makemigrations` |
| Add a Python package | `docker compose exec backend uv add <package>` then `docker compose build backend` |
| Add a frontend package | `docker compose exec frontend bun add <package>` |
| A database shell | `docker compose exec db psql -U supportnova` |
| Rebuild the images (dependency files changed) | `docker compose build` |
| **Start again from nothing** (deletes the database) | `docker compose down -v` then `docker compose up` |

New migrations are applied on every start, so after pulling someone else's changes `docker compose up` is enough.
Data loading is done once, for whatever is missing (`manage.py bootstrap_data`); it never touches data that is
already there. The other seed commands (`seed_catalog`, `load_rules`, `load_dataset`, ...) work the same way as
before, with the `docker compose exec backend uv run manage.py` prefix. `BOOTSTRAP_DATASET=1` in `.env` also loads
the 500 sample complaints on the first start.

## How it fits together

```
 your PC (code)  ──mounted──▶  backend container   Django, runs migrations + first-run data, then runserver
                               frontend container  Vite dev server; forwards /api to the backend (no CORS)
                               db container        PostgreSQL 17, data in the Docker volume "pgdata"
```

- The Python environment lives inside the image (`/opt/venv`), the frontend packages in a Docker volume: the `.venv`
  and `node_modules` on your PC are never used, so Windows, macOS and Linux all behave the same.
- Secrets are read from `.env` when the containers start. They are never copied into an image.
- The email assistant listens in the backend container once an administrator switches it on
  (Settings > Customer chat).
- Ports 8001 / 5433 are used because 8000 / 5432 are often taken. Change them with `BACKEND_PORT`, `DB_PORT`,
  `FRONTEND_PORT` in `.env`.

## Moving data between machines (and from the old SQLite file)

Without Docker the project still works on SQLite: leave `DATABASE_URL` unset and use the `uv run manage.py ...`
commands directly. To copy an existing SQLite database into the Docker PostgreSQL **once**:

```bash
# 1. on the machine with the SQLite file (Windows: set PYTHONUTF8=1 first)
cd support_nova_project
uv run manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.Permission -e sessions -e admin.LogEntry --output ../docker/data/sqlite_dump.json
# 2. start only the database, then load the dump into an empty one (no sample data first)
cd .. && docker compose up -d db
docker compose run --rm -e AUTO_BOOTSTRAP=0 backend uv run manage.py loaddata /app/docker/data/sqlite_dump.json
# 3. start everything
docker compose up -d
```

`docker/data/` is ignored by git because dumps contain password hashes. To hand a teammate your PostgreSQL data:

```bash
docker compose exec db sh -c "pg_dump -U supportnova -Fc supportnova > /tmp/b.dump"
docker compose cp db:/tmp/b.dump ./docker/data/backup.dump
# on the other machine, with the stack running:
docker compose cp ./docker/data/backup.dump db:/tmp/b.dump
docker compose exec db pg_restore -U supportnova -d supportnova --clean --if-exists /tmp/b.dump
```

## Troubleshooting

- **`port is already allocated`**: another program uses that port. Set `BACKEND_PORT`, `FRONTEND_PORT` or `DB_PORT` in `.env`.
- **First start seems stuck**: the sample policies need the search model (~190 MB, downloaded once). Watch `docker compose logs -f backend`.
- **`bad interpreter` / `\r` errors**: a script got Windows line endings. `.gitattributes` prevents it; run `git add --renormalize .` and rebuild.
- **The website loads but every request fails**: the backend is still starting or failed; check `docker compose logs backend`.
- **Packages missing after a pull**: `docker compose build` (Python) or just `docker compose up` (frontend reinstalls by itself).

## Without Docker

Python 3.13 with [uv](https://docs.astral.sh/uv/), and [Bun](https://bun.sh) for the frontend.

```bash
uv sync                                   # once
cd support_nova_project
uv run manage.py migrate && uv run manage.py bootstrap_data
uv run manage.py runserver 8001           # API
cd ../frontend && bun install && API_URL=http://127.0.0.1:8001 bun run dev   # website
```
