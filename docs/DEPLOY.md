# Put BloodLink online (free): GitHub + Neon + Render

Time: about 30 minutes the first time. Cost: $0.

What you will have: a public https address such as `https://bloodlink.onrender.com`, a PostgreSQL database that keeps
your data, and the background jobs (reminders, urgent-request escalation, alert delivery) running every 5 minutes while the
site is awake.

## Know these free-plan facts first (checked October 2026)
* **Render free sites sleep** after 15 minutes without visitors and take about a minute to wake. **Open the site 2 minutes before a demo.**
* **Render's disk is wiped on every deploy**, so SQLite cannot be used online. That is why we use Neon for the database.
* **Neon free:** 0.5 GB storage, 100 compute-hours a month, the database sleeps after 5 minutes idle (the app reconnects by itself).
* Render's free plan has **no cron jobs and no pre-deploy command**, so `render.yaml` runs the jobs inside the web process
  (`RUN_JOBS_IN_PROCESS=1`) with one worker. Jobs only run while the site is awake. For guaranteed reminders use a paid cron job.
* Prices and limits change; check render.com/pricing and neon.com/pricing.

## 1. Put the code on GitHub
1. Install **Git** (git-scm.com) and make a free **GitHub** account.
2. On GitHub: **New repository** (e.g. `bloodlink`), leave it empty, any visibility.
3. In the project folder (Command Prompt):
   ```
   git init
   git add .
   git commit -m "BloodLink"
   git branch -M main
   git remote add origin https://github.com/YOUR-NAME/bloodlink.git
   git push -u origin main
   ```
   `venv`, `.env` and database files are already ignored, so no secrets or huge folders are uploaded.
   If `git add .` lists a `.env` file, stop: it must never be pushed.

## 2. Create the database on Neon
1. neon.com > sign up > **Create project** (any region close to your users, e.g. Singapore or Mumbai).
2. On the project page click **Connect** and copy the connection string. It looks like
   `postgresql://user:password@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`. Keep it secret.

## 3. Add the demo data (optional, recommended for a class demo)
Do this **before** the first live start, from your own computer, while the Neon database is empty:
```
venv\Scripts\activate
set DATABASE_URL=postgresql://user:password@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require
python seed.py
```
You should see "Database seeded". The demo logins (Admin123 etc.) are public in the README, so **change the admin password
after the demo**, or skip seeding and let the app create your own admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

## 4. Deploy on Render
1. render.com > sign up with GitHub > **New + > Blueprint** > choose your repository. Render reads `render.yaml`.
2. Fill in the values it asks for:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | the Neon connection string from step 2 |
   | `ADMIN_EMAIL`, `ADMIN_PASSWORD` | your own admin login (a strong password) |
   | `PUBLIC_BASE_URL` | leave empty now; after the first deploy set it to your `https://....onrender.com` address |
   | `BUSINESS_EMAIL` | a contact address shown in the footer and policies |

   `SECRET_KEY` is generated for you.
3. Click **Apply**. The first build takes 3 to 6 minutes. When it says **Live**, open the address.
4. Set `PUBLIC_BASE_URL` to that address (Environment tab) and save; Render restarts the site.

No Blueprint? **New + > Web Service**: build `pip install -r requirements.txt`, start
`gunicorn app:app --workers 1 --threads 4 --timeout 60`, health check `/healthz`, plan Free, and add the same environment
variables plus `PYTHON_VERSION=3.12.7` and `RUN_JOBS_IN_PROCESS=1`.

## 5. Check it works
* `https://YOUR-ADDRESS/healthz` shows `ok`. `https://YOUR-ADDRESS/api/v1/docs` opens the API page.
* Log in with the admin account. Chat location sharing and QR scanning work because the site is https.
* **Email** (password reset): add `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` in Render > Environment
  (see EMAIL_SETUP.md). Without them the link is only written to the Render **Logs** tab.
* Optional: `REQUIRE_2FA_ROLES=admin,hospital`, then turn on two-factor login in the account menu.

## Updating the live site
```
git add .
git commit -m "describe the change"
git push
```
Render rebuilds automatically. New database columns are added by the app on start; nothing else to run.

## If something goes wrong
| Symptom | Fix |
|---|---|
| Build fails on `pip install` | Check **Logs**; make sure `PYTHON_VERSION` is `3.12.7` and `requirements.txt` is in the repo root. |
| Site crashes at start: "Set the SECRET_KEY" | The `SECRET_KEY` variable is missing. Add any long random text. |
| `could not connect` / `SSL` / timeout to the database | Re-copy the Neon string; it must end with `?sslmode=require`. The first request after a quiet period can take a few seconds while Neon wakes. |
| Page takes a minute to open | Render woke the sleeping free site. Open it before your demo. |
| Logged out every deploy | Normal if `SECRET_KEY` changed; keep the generated value. |
| No chat notifications or reminders for hours | The site was asleep, so the jobs did not run. Visit the site, or use a paid cron job. |
| Data disappeared | You deployed with SQLite. Set `DATABASE_URL` to Neon. |
