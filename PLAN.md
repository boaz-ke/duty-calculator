# Vehicle Duty Calculator — Implementation Plan

## 1. What we are building

An easy-to-use web app that estimates Kenyan vehicle import/transfer duty charges using the official KRA CRSP workbook data. Regular users will pick a vehicle (or enter its details), a year of manufacture and import route, and instantly see the expected customs charges. Only an administrator can upload a new CRSP release; the app validates it, compares it with the live version, and only activates it after approval.

The core idea: the Excel workbook is the **source of truth**, the app is a **friendly front end + calculation engine** around it. Price lists and calculation rules are stored per CRSP release so the tool always uses the latest official data and past releases remain available for audit.

## 2. What is in the current workbook

The single file `New-CRSP---July-2025.xlsx` contains four sheets:

| Sheet | Content | Approx. data size |
|---|---|---|
| `M.Vehicle CRSP July 2025` | Make, model, model number, transmission, drive, engine capacity, body type, GVW, seating, fuel, CRSP (KES) | ~5,280 vehicles |
| `Motor Cycles July 2025` | Same style of catalogue for motorcycles | ~465 motorcycles |
| `Tractors & Graders July 2025` | Manufacturer sections with model, horsepower/cc, CRSP (KES) | ~116 machines |
| `TEMPLATE 2025` | Depreciation schedules + 11 tax "tabulation" blocks with duty calculation formulas | 207 rows |

### How the TEMPLATE sheet works

The template has two broad calculation paths shown side by side:

- **Direct Imports to Kenya** — depreciation bands for vehicles older than 1 year up to 8 years (0.20 → 0.65).
- **Previously Registered in Kenya** — depreciation schedule from 1 year up to "over 15 years" (0.20 → 0.95).

Each tabulation block then calculates, from a **Current Retail Selling Price (CRSP)**:

Customs value → Import duty → Excise value → Excise duty → VAT value → VAT → RDL → IDF → **Grand Total**

Each block applies its own duty/excise rates and its own "back-calculation" denominator. The blocks are:

| # | Template block | Typical vehicles | Duty | Excise | Notes |
|---|---|---|---|---|---|
| 1 | Engine ≤ 1500cc | Small sedans, hatchbacks, S/Cab pick-ups, small vans/lorries/buses | 35% | 20% | Excludes public-school buses |
| 2 | Engine > 1500cc (HS 8702/8703/8704) | Larger cars, pick-ups, trucks, buses | 35% | 25% | Excludes codes 8703.24.90 / 8703.33.90 |
| 3 | HS 8703.24.90 & 8703.33.90 | Petrol passenger cars > 3000cc, diesel passenger cars > 2500cc | 35% | 35% | High-cc passenger cars only |
| 4 | 100% electric MVs | Electric cars, vans, buses | 25% | 10% | Label in source says 35% but the formula uses 25% — verify |
| 5 | School buses for public schools | School buses | 35% | 25% | Needs a user flag |
| 6 | Prime movers | Tractor units | 25% | 0% | |
| 7 | Trailers | Trailers | 35% | 0% | |
| 8 | Ambulances | Ambulances | 0% | 25% | |
| 9 | Motor cycles | Motorcycles | 25% | Fixed KES 12,952.83 per unit | Plus VAT on the fixed excise amount |
| 10 | Special purpose | Special-purpose vehicles | 0% | 0% | Only VAT, IDF and RDL |
| 11 | Heavy machinery | Tractors, graders, loaders, excavators | 0% | 0% | Only VAT, IDF and RDL |

All blocks add VAT (16%), RDL (2%) and IDF (2.5%) on their respective bases.

### Data quality observations (important for the build)

The workbook is not machine-clean:

- Fuel values contain typos and variants: `GASOLINE`, `PETROL`, ` DIESEL`, `ELECCTRIC`, `ELECTRIC(EV)`, `PLUG-IN-HYBRID`, etc.
- Body types contain many spellings/abbreviations: `S/WAGON`, `HATCBACK`, `D/CAB`, `PRIM� MOVER`, `TRK`, numeric `3`, etc.
- Engine capacity is mixed: numeric `cc` for combustion vehicles, text like `63 kWh` for electric ones.
- GVW is sometimes a number and sometimes text like `2285 kg`.
- Model-number duplicates exist (same model with different model numbers or years), so exact matching needs care.
- A few rows have null engine capacity, and two CRSP values are missing.
- The motor-cycle block's customs-value formula appears to divide by 1.25 twice, which may be an error in the source template or an intentional factor — it must be replicated exactly but verified against KRA's published method.
- Tractors/graders live in their own sheet, and there is no tractor-specific template block; they most likely fall under Heavy machinery (block 11), but this should be confirmed with the user before development.

## 3. Core design

### Data model (versioned)

The app should never overwrite "the" CRSP. Every release is a **CRSP version**:

```text
CRSP release (version)
    ├── price catalogues   (motor vehicles / motor cycles / tractors & graders)
    ├── depreciation schedules (direct imports / previously registered)
    └── tax rule set       (the 11 template blocks: rates, denominators, thresholds)
```

Suggested database tables:

- `releases` — id, label (`CRSP July 2025`), publication/effective date, source filename, checksum, uploaded-by, status (`draft`, `validated`, `live`, `archived`, `rejected`), timestamps.
- `catalogue_rows` — version, category (`motor_vehicle` / `motor_cycle` / `heavy_machinery`), canonical make/model, model number, engine capacity (cc or kWh), fuel, body type, seating, CRSP (KES), original source row for traceability.
- `rate_plans` — version + template block key + the parsed rates/denominator/fixed amounts (parsed from the TEMPLATE sheet, not hard-coded).
- `depreciation_schedules` — version + route (`direct` / `previously_registered`) + band label + rate.
- `calculations` (optional) — audit log of queries: inputs, release version used, result. Useful for support and compliance.

This design makes "upload the latest KRA document" safe: nothing changes for regular users until the admin validates and publishes the new version.

### Calculation flow

1. User selects the vehicle category and import route:
   - Direct import (never registered in Kenya)
   - Previously registered in Kenya
   - New vehicle (no depreciation)
2. User picks a make/model from the active catalogue — the app then knows engine, fuel and body type, and auto-fills CRSP — or enters the vehicle details and CRSP manually.
3. User enters the year of manufacture (or vehicle age).
4. Optional: extra depreciation % (a common manual adjustment in the template).
5. The engine determines the correct template block:
   - body type + fuel + capacity → block 1/2/3
   - user flag or body type → electric, school bus, ambulance, prime mover, trailer, motorcycle, machinery
6. Depreciation is looked up from the active release's schedule; direct imports older than 8 years should warn that importation is not permitted under the usual KRA rules.
7. The app runs the exact template formula for that block and displays:
   - CRSP / depreciated value
   - Customs value
   - Import duty, excise, VAT, RDL, IDF
   - Grand total in KES (and taxes per KES 1,000 of CRSP, which is how the template tables are naturally read)

### Classification rules must be explicit and configurable

The 11 template blocks are the heart of the calculation, so the mapping from "a real vehicle" to "which block" should be a small rule table stored in code/config, e.g.:

```text
fuel = electric                    → block 4
body = ambulance                   → block 8
is_school_bus_for_public_schools   → block 5
category = motor_cycle             → block 9
category = prime_mover             → block 6
category = trailer                 → block 7
category = tractor/grader/loader   → block 11 (confirm)
body = passenger car:
    petrol and cc > 3000           → block 3
    diesel and cc > 2500           → block 3
    cc <= 1500                     → block 1
    otherwise                      → block 2
body = van/pickup/truck/bus:
    cc <= 1500                     → block 1
    otherwise                      → block 2
```

The body-type dictionary in the workbook must be normalised into these canonical groups (`sedan`, `suv`, `wagon`, `hatchback`, `coupe`, `van/minivan`, `pickup`, `truck`, `bus`, `ambulance`, ...) because the source data uses dozens of variant spellings.

## 4. User experience

### Regular user (calculator)

One page, mobile-friendly, three logical steps:

1. **Vehicle** — search by make/model with suggestions; or choose "not in list" and enter body type, fuel and engine capacity. Optional CRSP override.
2. **Import details** — route (direct / previously registered / new), year of manufacture or age, optional extra depreciation.
3. **Result** — readable breakdown with the total duty clearly displayed, plus a "per KES 1,000" summary and optional print/download/PDF/Excel export.

Edge cases shown clearly: vehicle too old for direct import, no catalogue match (with manual CRSP fallback), electric vehicle capacity shown in kWh, motorcycles with fixed excise.

### Admin flow

An admin page lists all releases:

| Version | Published | Effective | Status | Uploaded by | Actions |
|---|---|---|---|---|---|
| CRSP July 2025 | 2025-07-01 | active | live | Admin | View / Archive |

Uploading a new document runs a wizard:

1. **Upload file** — validated extension, size, checksum.
2. **Parse & validate** — all four sheets parsed; required columns present; prices numeric and positive; catalogues normalised; template rates read from the formulas.
3. **Preview diff** — counts of new/changed/removed models and makes; any new tax-rate changes detected vs. the current release; warnings for dirty data.
4. **Publish** — admin confirms the effective date; the previous release is archived automatically; regular users immediately use the new release.
5. **Rollback** — any past release can be re-activated if the new one is found to be wrong.

Every upload is logged (who, when, filename, checksum, approval) and the original file is kept for audit.

## 5. Recommended technology

For a small, internal team tool like this, keep the stack simple and boring:

- **Backend**: Python + FastAPI
  - Python/openpyxl is the natural fit for parsing the Excel file and mirroring its formulas.
  - The calculation engine is pure Python functions (easy to unit-test against golden values from the workbook).
- **Frontend**: Lightweight server-rendered pages (Jinja) with a small amount of vanilla JS/HTMX for search and async results. Avoid a heavy SPA until the user base grows.
- **Database**: SQLite is enough for a handful-to-tens of users and keeps deployment simple. PostgreSQL is a drop-in swap if multiple offices will use it concurrently.
- **Auth**: Simple email+password with two roles (`user`, `admin`). Sessions in an HTTP-only cookie. Admin endpoints protected by role checks.
- **Deployment**: Docker image on a small VPS or an office machine, HTTPS behind a reverse proxy (e.g., Caddy/Nginx). A Docker Compose file with just the app + DB volume.

### Why not Excel/VBA or a desktop app

Excel/VBA would be the fastest prototype but makes the admin-upload, version-history and role-based access harder, and every user would need their own file. A small web app is easier to keep one source of truth, to update, and to open from a phone.

## 6. Testing and correctness strategy

This app produces financial estimates, so correctness is the top requirement:

1. **Golden-value tests**: For every template block, compute results with the actual July 2025 workbook for sample CRSP values and compare the app's output to Excel's output to several decimal places.
2. **Depreciation tests**: boundary ages (exactly 1/2/8 years, "over 15"), direct vs previously registered.
3. **Classification tests**: representative models per body type/fuel/cc bucket.
4. **Import round-trip tests**: upload the current workbook, activate it, and prove the app's results match the pre-upload version of record.
5. **Malformed-file tests**: missing sheets, changed columns, non-numeric prices — the admin wizard must reject them without corrupting the live data.

## 7. Suggested delivery phases

| Phase | Scope | Deliverable |
|---|---|---|
| 0. Spec confirmation | Confirm the open questions in section 8 with the user/team; validate 3–5 real vehicles end-to-end in Excel | Agreed classification mapping + golden examples |
| 1. Calculation engine | Python module mirroring every template block + depreciation schedules | Unit-tested engine with golden Excel values |
| 2. Data ingestion | Parser + normaliser + validation + diff preview for the four sheets | Import pipeline with tests on the July 2025 file |
| 3. Admin upload | Releases table, upload wizard, publish/archive/rollback, audit log | Admin section in the app |
| 4. Calculator UI | Searchable catalogue, input form, result breakdown, export | Usable calculator for regular users |
| 5. Auth & deployment | Roles, HTTPS, Docker deployment | Production app accessible to the team |

Realistic total effort for a small team: roughly 3–5 weeks of focused development including testing and deployment.

## 8. Decisions to confirm before building

1. **Business scenario** — Is this for estimating import duty on used vehicles entering Kenya, for local resale valuation, or both? This determines how much weight "previously registered in Kenya" carries.
2. **Vehicle-type mapping** — Confirm which vehicle types map to prime movers, trailers, special purpose, heavy machinery and the high-cc block, and where tractors/graders sit (likely block 11).
3. **New-vehicle handling** — Confirm new vehicles simply use zero depreciation on the listed CRSP.
4. **Source anomalies** — Verify the electric duty label (35% vs 25%) and the motorcycle double `/1.25` against KRA's published rates or a known assessment before locking the engine.
5. **Users & hosting** — Who uses it, how many, and where should it be hosted (office LAN vs cloud)? Recommended default: internal web app, Docker + SQLite.
6. **Audit needs** — Should every calculation be saved for later review, or is saving only admin uploads enough?
7. **Exports** — Do users need PDF/Excel output or just an on-screen result?

## 9. Key risks

- **KRA changes workbook layout**: parse defensively, normalise column positions by header name, and require admin review of structural changes.
- **Dirty source data**: never trust make/model spelling; store original values alongside canonical values and let users pick from search results rather than typing free text.
- **Formula quirks in the template**: replicate them exactly in v1 (documented), then verify with KRA/industry practice.
- **Legal caveat**: display a small disclaimer that the result is an estimate using KRA CRSP guidelines and is not an official customs assessment.
- **Wrong version in use**: show the active release label and date in the app header so users know which CRSP the calculation is based on.
