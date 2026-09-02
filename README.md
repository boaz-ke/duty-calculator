# Vehicle Duty Calculator

An easy-to-use web app that estimates Kenyan vehicle duty using KRA's Current
Retail Selling Price (CRSP) workbook. Regular users search the CRSP catalogue,
enter the year of manufacture and import route, and see the full tax breakdown.
Administrators can upload a newly released KRA workbook as a draft and publish
it once validated — the previous release is kept for audit and rollback.

## Quick start with Docker (recommended)

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/), then
run everything with one command:

```bash
git clone https://github.com/nation9k/duty-calculator.git && cd duty-calculator && docker compose up -d --build
```

Open http://localhost:8000.

The first run creates an admin account (`admin` / `admin123`) and automatically
seeds the live CRSP release from the bundled July 2025 workbook. Data persists
in a Docker volume, so the database, changed passwords and uploaded CRSP
releases survive restarts.

To set your own admin credentials and session secret before first launch,
create a `.env` file in the project folder:

```dotenv
VDC_ADMIN_USER=you
VDC_ADMIN_PASSWORD="a-strong-password"
VDC_SECRET="a-long-random-secret"
PORT=8000
```

Then start with the same compose command. Change the default password from the
app after the first run regardless.

Useful commands:

```bash
docker compose up -d --build   # rebuild and start
docker compose logs -f          # follow the logs
docker compose down             # stop (keeps data)
```

## What is implemented

- Parser for all four sheets of the July 2025 workbook:
  - ~5,279 motor vehicles, ~465 motor cycles, ~112 tractors/graders/machinery
  - All 11 TEMPLATE rate blocks (duty/excise/VAT/RDL/IDF and the exact
    customs-value formulas used by KRA)
  - Both depreciation schedules (direct imports ≤8 years and previously
    registered 1 year → over 15 years)
- Versioned SQLite storage: a release stores its catalogue, tax blocks and
  depreciation schedules together.
- Searchable vehicle lookup with CRSP auto-fill.
- Calculation API and responsive web UI.
- Admin upload flow: parse → validate → review rates and warnings → make live,
  archive old release, or reactivate a past release.
- Unit/integration tests with golden values taken straight from the workbook.

## Run locally

Prefer Docker (above) for anything beyond local testing. To run directly,
requires Python 3.10+ with Flask, openpyxl and gunicorn:

```bash
pip install -r requirements.txt
python main.py
```

Then open http://localhost:5000.

On first startup the app parses the bundled `New-CRSP---July-2025.xlsx` and
creates a live release automatically. The SQLite database lives in
`data/vdc.sqlite3`. Flask's development server is fine for local use but use a
production WSGI server (e.g. gunicorn, as in the Dockerfile) when deploying.

## Admin

Default development credentials:

```text
username: admin
password: admin123
```

Set these via environment variables before deploying anywhere real:

```bash
export VDC_ADMIN_USER=you
export VDC_ADMIN_PASSWORD="a-strong-password"
export VDC_SECRET="a-random-session-secret"
```

The first launch stores the admin account (password hashed) in the SQLite
database. After that, the admin can change the password from the app
(**Change password** in the top navigation); the database password is what
counts, not the original environment variable.

Admin flow:

1. Sign in to **Admin**.
2. Upload the new `.xlsx` CRSP release (optionally set its effective date).
3. Review the parsed counts, the tax rates read from the TEMPLATE sheet, and
   data-quality warnings.
4. Click **Approve & make live**. The previous release is archived but remains
   available; archived releases can be re-activated from the admin list.

Admin password changes are stored per release database, so rotate the default
password immediately after the first deployment.

## How the calculation works

For a used vehicle, the app:

1. Looks up the vehicle's CRSP (or accepts a manual price).
2. Picks the correct TEMPLATE block from vehicle type, fuel and engine
   capacity (e.g. ≤1500cc vs >1500cc, high-cc passenger cars, electric,
   school buses, ambulances, motor cycles, machinery).
3. Applies the depreciation rate for the route and age.
4. Runs the exact KRA formula: retail price → customs value → import duty →
   excise → VAT → RDL → IDF → grand total.

The `Previously registered in Kenya` route uses the workbook's second
depreciation schedule and, like the workbook's right-hand template columns,
does **not** add RDL/IDF.

## Notes and caveats

- The results are an estimate based on the active KRA CRSP guidelines and are
  **subject to verification** by KRA. The app says so on every result.
- The source workbook contains messy data (fuel/body-type spellings, engine
  capacity stored as HP/kWh/cc text, model-number duplicates). The parser keeps
  original text for display and normalised values for calculation. Rows with
  unusable engine details still need the user to confirm capacity when the
  template requires a cc split.
- The workbook's direct-import side labels electric vehicles "Import Duty 35%"
  and prime movers "35%" while the formulas apply 25%. The app trusts the
  formula (25%), matching the template's actual calculation.
- Motor cycles use the workbook's fixed excise amount of KES 12,953 per unit,
  which is included in the VAT base exactly as the template does.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Layout

```text
app/
  parser.py      workbook parsing and normalisation
  engine.py      classification + KRA calculation formulas
  db.py          SQLite schema and queries
  views.py       web routes (calculator + admin upload)
templates/       HTML pages
static/          CSS and calculator JavaScript
tests/           golden-value tests against the July 2025 workbook
PLAN.md          full product and implementation plan
```
