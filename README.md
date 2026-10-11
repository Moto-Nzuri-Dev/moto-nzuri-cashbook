# Moto Nzuri Cashbook

Cash Book & Float Management System for Moto Nzuri / Sprinkle Solutions Ltd.
Python/FastAPI backend, SQLite on your own computer, PostgreSQL (Supabase) when hosted.
Live address: **https://cashbook.motonzuri.co.ke**

## What it does

- **Floats** – record money received (from the Boss, Macharia, etc.), add every expense against it, see the balance or overspend live.
- **Expenses** – description, category, amount **plus the M-Pesa transaction charge**, M-Pesa code, date. Paste an M-Pesa SMS and it fills in code, amount, charge, payee and date.
- **Proof photos** – receipt or M-Pesa screenshot per expense, shrunk on the phone to ~200 KB (the server re-checks and shrinks anything bigger).
- **Rules** – proof is required from KES 500 (admin can change it); an M-Pesa code can be claimed only once in the whole system; no future dates, zero or negative amounts.
- **Submit to boss** – blocked until required proof is attached; a note is required when there's a balance or overspend. The float then **locks**.
- **Boss sign-off** – the boss logs in, ticks "I have checked", and **Approves** (locked for good) or **Queries** with a reason (unlocks for the manager to fix and resubmit). Nobody can approve their own float.
- **Evidence pack PDF** – one PDF per float: summary, categories, and every expense beside its photo, stamped with the status.
- **Field & Office reports** – daily/weekly/one-off written updates with photos, a "decision needed" line, boss Approve/Decline/Noted, and a reply thread. PDF per report.
- **Team view** – admin and boss see every manager consolidated; each manager sees only their own floats and reports.
- **Safety** – phone + password sign-in, lock-out after 5 wrong tries (15 min), auto sign-out after 60 min idle, activity log of every change, all money stored in whole cents.

### Roles

| Role | Can do |
|---|---|
| **admin** (Gideon) | Everything a manager can, plus add/edit people, change rules, see everyone, read the activity log. Can review other people's floats, never his own. |
| **manager** | Record own floats, expenses, proof, reports. Sees only their own. |
| **boss** | Sees everyone, approves/queries floats, decides on reports, replies. Cannot change any figures. |

## Run it on your computer

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python run.py
```

Open http://localhost:8000. The first visit asks you to create the administrator account.
Data is kept in `data/cashbook.db`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

To also test against PostgreSQL: set `TEST_DATABASE_URL=postgresql://...` (an empty test database — tables are dropped and recreated).

## Go live: GitHub → Render → Supabase → your domain

1. **GitHub** – create a private repository (e.g. `moto-nzuri-cashbook`) and upload everything in this folder.
2. **Supabase** – in your project: *Connect* → copy the **Session pooler** connection string (it works over IPv4, which Render needs). Put your database password into it.
3. **Render** – *New → Blueprint* → choose the repository. Render reads `render.yaml`. When asked, paste the Supabase string into `DATABASE_URL`. `SECRET_KEY` is generated for you. Deploy. Check `https://<your-app>.onrender.com/api/health` shows `"database":"postgres"`.
4. **Domain** – in Render: *Settings → Custom Domains → Add* `cashbook.motonzuri.co.ke`. Render shows a CNAME target.
   In cPanel open **Zone Editor** (not "Create Subdomain") → motonzuri.co.ke → *+ CNAME Record*: name `cashbook`, target = the Render address. Wait for Render to show the domain as verified; it issues the HTTPS certificate itself.
5. Open https://cashbook.motonzuri.co.ke, create the admin account, then add the boss and managers under **People**.

Tables are created automatically on first start. Photos are stored in the database, so nothing is lost when Render restarts.

## Environment variables

| Name | Purpose |
|---|---|
| `DATABASE_URL` | Supabase/Postgres string. Empty = local SQLite file. |
| `SECRET_KEY` | Signs the login cookie. Changing it signs everyone out. |
| `COOKIE_SECURE` | `1` on the live HTTPS site. |
| `IDLE_TIMEOUT_MIN` | Minutes idle before sign-out (default 60). |
| `APP_TIMEZONE` | Default `Africa/Nairobi`. |

## Project layout

```
app/
  main.py            app start-up, security headers, error handling, page serving
  config.py          settings from environment variables
  models.py          database tables (money in cents)
  security.py        passwords, sessions, who-can-see/change-what
  services.py        money, rules, photo compression, M-Pesa SMS reader, activity log
  pdf.py             evidence pack and report PDFs
  routers/           auth, admin (people/settings/log), floats & expenses, dashboard, field reports
  static/            the web app (index.html, app.js, app.css, logo, icons)
tests/               pytest suite
run.py               start locally
render.yaml          Render deployment
```

## Backups

Supabase keeps daily backups on paid plans. On the free plan, export from the Supabase dashboard (*Database → Backups* or the SQL editor) regularly, or ask for a scheduled export to be added.
