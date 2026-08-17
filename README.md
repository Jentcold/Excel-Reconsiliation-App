# Stocktake

**Three monthly Excel exports in, one reconciled table out — computed when the files arrive, not when the page opens.**

Built during an internship at a phone distributor, where reconciling sales against
stock was a recurring manual job: open the daily sell-out report, the monthly sales
summary and the warehouse inventory, match products across three different naming
conventions by hand, and paste the result into a fourth workbook. Stocktake does
that join on upload and serves the result to everyone else instantly.

`FastAPI` · `pandas` · `Appwrite` · `vanilla JS` — no frontend framework, no build step.

---

## What it does

- **Uploads** three kinds of workbook — DSR (monthly sales), PSI (daily sell-out),
  Inventory — with retention rules that match how the files are actually sent.
- **Reconciles** them against a product mapping table, since the same phone is
  named three different ways across the three sources.
- **Serves** the result as three on-screen sheets, a small analytics dashboard, an
  item catalogue with photos, and an optional formatted `.xlsx` download.
- **Separates** three roles server-side: admins manage accounts, commercial owns
  the data, sales sees only the item catalogue.

## The design decision 

The first version computed the table whenever someone opened it. Every tab switch
meant downloading three workbooks from object storage, parsing them with openpyxl,
and re-running the join — several seconds, paid again by every user, every visit,
for a result that hadn't changed since the morning.

So the work moved to the write side. Now:

1. **On upload**, the workbook is parsed once and reduced to the columns the table
   needs (`processing/extract.py`), stored as JSON beside the raw file. Parsing is
   the expensive step and it depends on nothing else, so a report uploaded in March
   is parsed in March and never again. This doubles as validation — an unreadable
   workbook is rejected while the person who picked it is still looking at it.
2. **Then the table is rebuilt** — a join over those extracts, with no Excel parsing
   in it — and stored as the single current payload. Every write path does this:
   uploads, deletions, and each mapping row imported, added, edited or deleted.
3. **Reads never compute.** The table, the analytics and the export all fetch that
   payload. There's no recompute button and no version picker, because there's only
   ever one current version.

Measured on the deployed data: **3 ms** for a warm read, **473 ms** on a cold
process, against **~6 s** for an upload. The cost sits with the one person already
watching a progress bar, and everyone else gets an instant table.

Two supporting caches, because each round trip to Appwrite Cloud costs a few
hundred milliseconds:

- **Session checks** are held 30 seconds against the session secret — without it,
  every request paid two round trips instead of one. The short window means a
  revoked session or a changed role takes effect almost immediately.
- **The payload and the extracts** are kept in process. A file id names immutable
  content — replacing a file means a new id — so it's a safe cache key.

On the frontend, each tab keeps its own DOM pane rather than being torn down and
rebuilt. Returning to a tab is instant, and a slow response can only ever paint
into its own pane, never on top of the tab you switched to while waiting.

## Retention rules

These follow the shape of the incoming files rather than imposing a scheme on them.

**DSR and Inventory** — one file per calendar month, named for the month alone:
`DSR - Mar`, `DSR - July`, abbreviated or full. Re-uploading a month replaces that
month's file, since the file *is* that month's current state.

There's no year in the name, so it's inferred: the current year, unless the month
hasn't come round yet, which makes it last year's. That's what carries January — a
`DSR - Dec` uploaded on 1 Jan 2027 is tagged December 2026, not a December 2027 that
hasn't happened. A month of slack is allowed, so a file prepared slightly early
isn't thrown back a year.

The table reads the **newest three months on file** — the current one and the two
before it — rather than counting back from today, so it still fills in when this
month's report hasn't landed yet. Older months stay uploaded and stay listed,
marked "not in the table". Inventory uses only its most recent month.

**PSI** — the current month to date, sent daily, every day retained. Unlike the DSR
it's uniform, so the filename needs nothing at all: it's filed under the day it's
uploaded, and uploading again the same day replaces that day's file. A name that
spells out a full date is honoured, so a missed day can be backfilled on purpose;
a name carrying only a month says nothing about which day and is ignored rather
than guessed at. The table always uses the most recent day.

## Sheets

Split across three so each fits on screen without sideways scrolling:

1. **Summary** — the most recent month, with the latest PSI collapsed to total and average.
2. **DSR by month** — the three months in the window.
3. **PSI detail** — the full daily columns.

The Excel download produces the same three sheets, formatted, with SUBTOTAL rows.

## Item catalogue

Imported from a specs workbook whose first sheet is named after a pricing tier
(`10%`), so it's taken by position, not name. The header row is found by looking
for the `Product Name` column.

Known columns are mapped; **every other column becomes a `{label, value}` spec
entry**, so when the spec columns change between revisions nothing is lost and no
code change is needed. Two behaviours worth knowing:

- **`Category` is carried down** — it's filled only on the first row of each group
  (merged cells), so it's forward-filled on import.
- **Item identity is Product Name + RAM + ROM.** The sheet has no code column and
  the same product recurs in different configurations, so the code is derived as a
  slug (`honor-magic-8-pro-16gb-1tb`) and each configuration gets its own card.

## Roles

| Role | Sees |
| --- | --- |
| `admin` | Everything, read-only, plus account management — its only write access |
| `commercial` | Everything, and owns the data: uploads, mapping, item cards |
| `sales` | The item catalogue only |

Roles are Appwrite user labels. The frontend hides tabs, but **every route enforces
the role server-side** — that is what actually protects the data. An unlabelled
account gets the least access.

Login runs Appwrite's server-side session flow: the API-key client creates the
session (Appwrite only returns the session *secret* to a key-authenticated request)
and the secret goes into an httpOnly cookie, so no token is ever readable from page
scripts.

## Storage

The free plan allows one bucket, so raw workbooks, item photos and cached output
share it, told apart by a prefix on the file id:

| Prefix | Contents | Referenced by |
| --- | --- | --- |
| `raw_` | DSR / PSI / inventory workbooks | `uploads.file_id` |
| `data_` | columns extracted from a workbook (JSON) | `uploads.extract_file_id` |
| `img_` | item photos | `items.image_file_id` |
| `cache_` | the processed table (JSON) | `cache_index.file_id` |

Nothing is *looked up* by prefix — each table holds the id of what it owns, so
lookups are exact. The prefix keeps the bucket readable in the console. The table
is stored as a JSON blob rather than a row so a column-per-PSI-date can't hit the
row size limit.

---

## Screen Shots





---

## Running it

Requires Python 3.11+ and an Appwrite project with a server API key scoped to
`users.*`, `databases.*` (or `tables.*`) and `storage.*`.

```bash
pip install -r backend/requirements.txt
```

```bash
cp backend/.env.example backend/.env
```

Fill in the endpoint, project id, API key and `BUCKET_ID`, then provision the
database, tables, indexes and bucket — the script is idempotent:

```bash
cd backend && python setup_appwrite.py
```

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

Serve the frontend from any static server; its origin must be listed in
`CORS_ORIGINS`:

```bash
python -m http.server 5500 --directory frontend
```

Accounts are never self-registered. Create the first admin in the Appwrite console
(Auth → Users → Create user) and give it the label `admin`; every other account is
created from the Accounts tab.

## Layout

```
backend/
  app/
    main.py              FastAPI app, CORS, error handling
    config.py            env-backed settings
    appwrite_client.py   Appwrite clients (TablesDB and Databases APIs)
    auth.py              sessions + role guards
    periods.py           "DSR - Mar" -> (year, month)
    cache.py             the one processed payload
    store.py             Storage helpers — one bucket, prefixed ids
    schema.py            table / role / kind names
    processing/
      loader.py          header-sniffing workbook reader
      extract.py         workbook -> just the needed columns, at upload
      pipeline.py        mapping x DSR x PSI x inventory -> three sheets
      export.py          formatted xlsx download
    routers/             auth_routes, admin, uploads, mapping, items, reports
  setup_appwrite.py      idempotent provisioning
frontend/
  index.html             login
  app.html               shell
  css/app.css            dark (default) + light themes
  js/                    api.js, ui.js, app.js, tabs/*
```

The reconciliation logic lives in `backend/app/processing/` — `extract.py` reduces a
workbook to what's needed, `pipeline.py` joins the sources into the three sheets.
