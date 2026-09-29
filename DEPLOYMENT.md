# Deploying SupportNova on Vercel

This branch (`deploy/vercel`, pushed as `main` of the deployment repository) runs the whole app as
**one Vercel project** with two [services](https://vercel.com/docs/services) (`vercel.json`):

| Service    | Folder                  | Serves                                   |
| ---------- | ----------------------- | ---------------------------------------- |
| `frontend` | `frontend/`             | the React app (Vite build), every path   |
| `backend`  | `support_nova_project/` | Django: `/api/...`, `/admin/...`, `/static/...` |

Vercel keeps the full path, so Django still sees `/api/complaints` - no code or URL changes.

## What differs from local development (only when `VERCEL=1`)

- **Database:** Postgres from `DATABASE_URL` (Vercel's disk is read-only, SQLite cannot work).
- **Search:** FAISS is left out of `support_nova_project/requirements.txt` to keep the bundle small;
  `vector_search` falls back to the same exact search in numpy (identical results).
- **Files:** uploads, saved emails and the embedding model live in `/tmp`, which is temporary. The
  model (66 MB) is downloaded again after each cold start; uploaded files disappear then too.
- **Uploads** are capped at 4 MB (Vercel's request limit is 4.5 MB).
- `DEBUG` is off and a real `DJANGO_SECRET_KEY` is required.

## One-time setup

1. **Import the repository** in Vercel (Add New -> Project -> the deployment repository). Keep the
   root directory as the repository root; `vercel.json` defines the services.
2. **Add a database:** Storage -> Neon Postgres (free). This sets `DATABASE_URL` for you.
3. **Environment variables** (Settings -> Environment Variables):

   | Name                 | Value                                                        |
   | -------------------- | ------------------------------------------------------------ |
   | `DJANGO_SECRET_KEY`  | a long random string                                         |
   | `JWT_SECRET_KEY`     | another long random string                                   |
   | `DEEPSEEK_API_KEY`   | your DeepSeek key (plus `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`) |
   | `FRONTEND_URL`       | `https://<your-project>.vercel.app` (links in emails)        |
   | `TIME_ZONE`          | `Asia/Karachi` (default)                                     |
   | `EMAIL_HOST` etc.    | optional; without it emails are only written to `/tmp`       |

4. **Create the tables and copy the data** from your computer (Vercel does not run migrations):

   ```bash
   # 1. export the local SQLite data (without the tables Django re-creates itself)
   cd support_nova_project
   python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission -e admin.logentry -e sessions -o dump.json

   # 2. point at the Neon database (copy DATABASE_URL from Vercel) and load it
   uv pip install "psycopg[binary]"
   set DATABASE_URL=postgresql://...        # PowerShell: $env:DATABASE_URL="postgresql://..."
   python manage.py migrate
   python manage.py loaddata dump.json
   ```

   This keeps every analysed complaint, so no GenAI calls are repeated. Uploaded files in `media/`
   are not copied: policy text and sections are in the database, but "view document" and attachment
   downloads need the files re-uploaded after deployment.

5. **Deploy** (every push to `main` of the deployment repository redeploys).

## If Services is not available on the account

Services is in beta. The fallback is two Vercel projects on the same repository and branch:
the frontend project with root directory `frontend/` and a rewrite of `/api/(.*)` to the backend
project's URL, and the backend project with root directory `support_nova_project/`.

## Known limits on the free plan

- A request may run up to 300 s; submitting a complaint takes about 25 s (GenAI + validation).
- The first request after an idle period is slow (Python start, model download, search index build).
- Scheduled jobs such as `fetch_emails` can run at most once a day with Vercel Cron on Hobby.
