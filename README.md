# RELAY 📡

[![CI](https://github.com/JimmYCHUU/RELAY/actions/workflows/ci.yml/badge.svg)](https://github.com/JimmYCHUU/RELAY/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)

Automated sponsored-content reporting for Somoy TV. RELAY ingests your per-brand
campaign sheet and the supervisor's matched files, matches every photocard to its
view counts across Facebook / Instagram / X, flags what it can't prove, and
generates the sponsor report .xlsx in exactly your current format — Sum, Total
views, Average rows, styling and all.

---

## Install & run

**On Windows, just double-click `Start RELAY.bat`** — see
[Route 0](#route-0--windows-double-click-no-docker-no-terminal) below. It does
everything itself and needs no Docker and no terminal.

Otherwise there are two ways to run RELAY. **Docker** is the least work and keeps
your machine clean; **native Python** is better if you want to edit the code, and
it is the only way to do the one-time Meta sign-in (a container has no screen to
open a browser window on). Many people use both: Docker for the dashboard,
native Python once for the login.

---

### Route 0 — Windows double-click (no Docker, no terminal)

Copy the RELAY folder anywhere on the PC and **double-click `Start RELAY.bat`**.

The first run sets everything up — it finds Python (offering to install it if the
PC has none), builds a private environment in `.venv-win\`, installs the
dependencies and downloads the browser the collectors drive. That takes a few
minutes and about 150 MB. **Every run after that just starts RELAY**, which takes
a second or two; the setup is repeated only if `requirements.txt` changes.

The dashboard opens in the default browser by itself. Leave the black window
open while working — closing it stops RELAY.

A few things worth knowing:

- It binds to `127.0.0.1` only, so **Windows never asks about the firewall** and
  nothing on the network can reach it.
- If port 8501 is busy (usually another RELAY still open), it quietly takes the
  next free one and opens that.
- Reports and run history land in `data\` **beside the .bat**, wherever you put
  the folder.
- To undo the install completely, delete the `.venv-win` folder.
- The one-time Meta sign-in still applies if you want the collectors — see
  [One-time setup](#one-time-setup-the-meta-sign-in). Matching, the dashboard and
  report generation need no sign-in at all.

### What you need first

| | Windows double-click | Docker route | Native route |
|---|---|---|---|
| Docker Desktop / Engine | — | **required** | — |
| Python | installed for you if missing | — | **3.12 or newer** |
| Git | — (copy the folder) | to clone the repo | to clone the repo |
| Free disk | ~700 MB (with Chromium) | ~1.5 GB (image incl. Chromium) | ~700 MB (with Chromium) |
| A desktop session | only for the Meta login | only for the Meta login | only for the Meta login |

RELAY runs on **Windows, macOS and Linux**. Nothing is sent anywhere — it talks
to Facebook/Instagram/X only when you explicitly start a collector, using a
browser profile stored on your own machine.

---

### Route A — Docker (recommended for just using it)

**1. Install Docker**

<details>
<summary><b>Windows</b></summary>

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/). It
needs WSL2, which its installer sets up for you; reboot when it asks. Then open
Docker Desktop once and wait for it to say *Engine running*.

Or with winget:
```powershell
winget install Docker.DockerDesktop
```
</details>

<details>
<summary><b>macOS</b></summary>

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(pick the Apple-silicon or Intel build to match your Mac), or:
```bash
brew install --cask docker
```
Launch Docker from Applications once so the engine starts.
</details>

<details>
<summary><b>Linux</b></summary>

```bash
# Fedora / RHEL
sudo dnf install docker docker-compose-plugin
# Debian / Ubuntu
sudo apt install docker.io docker-compose-plugin

sudo systemctl enable --now docker
sudo usermod -aG docker $USER      # then log out and back in, so you can drop `sudo`
```
</details>

**2. Get the code and start it**

```bash
git clone https://github.com/JimmYCHUU/RELAY.git
cd RELAY
docker compose up -d --build
```

First build takes a few minutes (it bakes in Chromium for the collectors).
When it finishes, open **http://localhost:8501**.

```bash
docker compose logs -f      # watch it
docker compose down         # stop it
```

> **⚠️ After every code change, rebuild:** `docker compose up -d --build`.
> The Dockerfile *copies* `relay/` into the image at build time, so a running
> container keeps serving the code it was built with — edit a file, and the
> dashboard will not change until you rebuild. If the UI looks out of date,
> this is almost always why (also hard-refresh the browser: **Ctrl/Cmd+Shift+R**).

---

### Route B — Native Python (Windows / macOS / Linux)

**1. Install Python 3.12+**

<details>
<summary><b>Windows</b></summary>

Download from [python.org](https://www.python.org/downloads/) and **tick
"Add python.exe to PATH"** in the installer. Or:
```powershell
winget install Python.Python.3.12
```
Check it: `py -3.12 --version`
</details>

<details>
<summary><b>macOS</b></summary>

```bash
brew install python@3.12
```
Check it: `python3.12 --version`
</details>

<details>
<summary><b>Linux</b></summary>

```bash
sudo dnf install python3.12 git      # Fedora / RHEL
sudo apt install python3.12 python3.12-venv git   # Debian / Ubuntu
```
</details>

**2. Clone, create a virtual environment, install**

<details open>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
git clone https://github.com/JimmYCHUU/RELAY.git
cd RELAY
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
If PowerShell blocks the activate script, allow it for your user once:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
(`cmd.exe` users: activate with `.venv\Scripts\activate.bat` instead.)
</details>

<details open>
<summary><b>macOS / Linux</b></summary>

```bash
git clone https://github.com/JimmYCHUU/RELAY.git
cd RELAY
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
</details>

**3. Install the browser (only if you want the collectors)**

Matching, the dashboard and report generation work without this. The
Facebook/Instagram/X collectors need a real browser:

```bash
playwright install chromium              # Windows, macOS, Fedora, Arch…
playwright install --with-deps chromium  # Debian/Ubuntu only: also pulls system libs (needs sudo)
```

On Fedora/Arch, `--with-deps` is not supported — use the plain form; if Chromium
complains about a missing library, install it from your distro's packages.

**4. Run it**

```bash
python -m relay.cli serve            # dashboard → http://localhost:8501
python -m relay.cli serve --port 9000   # if 8501 is taken
```

Run it from the repo root — `data/` is resolved relative to your working
directory unless you set `RELAY_DATA_DIR`.

---

### One-time setup: the Meta sign-in

Only needed for the Facebook/Instagram collectors. It opens a real browser
window so you can log in yourself — 2FA included. RELAY never sees or stores
your password; the resulting session lives in `data/profiles/meta/` on your
machine and nowhere else.

```bash
python -m relay.cli login meta
```

Log in, then **close the window**. That's it — it persists between runs.

> **Running in Docker?** Do this step natively on the host (Route B, steps 1–3,
> then this command). `docker-compose.yml` mounts `./data` into the container,
> so the container picks the session straight up. A container has no display of
> its own, and the dashboard's login button will tell you the same thing.

### Where your files live

Everything RELAY reads or writes stays under `./data` (created on first run):

```
data/uploads/   files you drop in the dashboard
data/input/     optional: drop monthly files here instead of uploading
data/output/    generated reports land here
data/profiles/  the Meta browser session (from `relay login meta`)
data/db/        run history — the SQLite audit log
```

Point `RELAY_DATA_DIR` at another folder to move all of it. Sponsor workbooks
and Business Suite exports are **git-ignored** (`*.xlsx`, `*.csv`) — real
performance data never gets committed.

### Check it worked

```bash
pytest                                # 153 tests, all should pass
curl http://localhost:8501/api/runs   # dashboard alive → JSON run history
```

## The monthly workflow

1. Download the brand's campaign Google Sheet as `.xlsx`.
2. Get the three matched files from your supervisor (mainpage / subpage / insta) —
   optional, but they auto-resolve most cells. Multi-brand files that separate
   sponsors with a bare brand-name row work as-is; RELAY finds the right section.
3. Export your content data from Meta Business Suite (Insights → Content →
   export) and drop it in too — **one file covers all your pages**, so this is a
   single download per month, not one per page. It carries Meta's **exact** Views
   per post, which is what the report's Views column has always meant.
4. Open the dashboard → drop files → set the brand and tick the campaign tabs →
   **Run matching**.
5. Review: green = matched, amber = estimated, blue = manual, red outline =
   missing. Click ✎ on any cell to estimate from reactions or type an exact value.
6. **Generate .xlsx** → download → e-mail it. Untick "mark estimated cells" for
   the sponsor-facing copy.
7. Optionally drop last cycle's hand-made report under *Cross-check* to verify
   RELAY cell-by-cell.

### One workbook per brand, however many tabs

A sponsor's campaign usually lives in several tabs of one workbook — Ruchi's June
runs as `June`, `June ratio 2` and `8 Teams Special` — and the sponsor is handed
**one file**, not three.

So the campaign-sheet panel lists every tab with a tick box. All of them start
ticked, and **"Deliver these tabs as one workbook"** is on: matching still runs
per tab (each has its own header row and its own brand colour), but the report
comes out as one continuous table, renumbered 1..n, with a **Source tab** column
saying which tab each row came from and a single set of totals at the bottom.

Untick that box to get a separate file per tab instead. Untick individual tabs to
leave them out entirely.

**Different brands never merge.** Add Ruchi (3 tabs → one workbook), then add
Cocola (2 tabs → a second workbook); *Generate every workbook (.zip)* bundles
them without a sponsor ever seeing another sponsor's numbers.

### What the report carries

Per row: `No · Date · Content's name`, then each of the three Facebook links with
its own **Views · Reach · Engagement**, then the X link with Impressions and the
Instagram link with Views.

Reach and Engagement are Meta's own columns from the Business Suite export —
Engagement is the export's *"Reactions, comments and shares"* figure, not a number
RELAY adds up, so it matches what you see in Business Suite. They are Facebook-only:
neither X's public page nor the Instagram export publishes an equivalent, and a
cell RELAY filled from a collector visit or a typed override has no reach or
engagement to report, so those stay blank rather than showing a zero the post
never reported.

The footer carries **Sum** per column, then **Total views**, **Total reach
(Facebook)**, **Total engagement (Facebook)** and **Average views per content** —
all live Excel formulas.

## CLI

```bash
# list month tabs
python -m relay.cli sheets "Campaign.xlsx"

# full run with cross-check
python -m relay.cli run \
  --campaign "Campaign.xlsx" \
  --sheet April --brand "Brand A" \
  --mainpage "mainpage matched.xlsx" \
  --subpage  "subpage matched.xlsx" \
  --insta    "insta matched.xlsx" \
  --insights "insights-export.csv" \
  --reference "FB Photocard (April).xlsx"
```

`--insights` takes a Business Suite content export. One export normally covers
every page, so a single `--insights` is usually enough; the flag repeats if you
export pages separately. It is the source of exact Facebook figures — everything
below is only for what no export covers.

## Collectors (opt-in browser automation)

Collectors fill what the exports and matched files can't: real public X view
counts, resolution of `share/p` links back to a post the export knows, and the
reaction totals that feed the last-resort estimate.

```bash
python -m relay.cli login meta        # one-time headed login (2FA fine; cookies stay local)
python -m relay.cli run ... --collect-x                 # public X, no login ever
python -m relay.cli run ... --collect-fb --k 95         # MBS session + shared-post heuristic
python -m relay.cli run ... --collect-x --dry-run       # log intended visits, touch nothing
```

Account safety is enforced in code (`relay/collectors/base.py`): randomized
8–15 s pacing, a hard 200-navigation session budget, and immediate abort (with
session preserved) the moment a checkpoint/captcha appears. X credentials are
never entered or stored anywhere — X collection is public-page only.

## Matching rules (as you confirmed them)

| Report column | Source |
|---|---|
| FB Link 1 (Somoy News TV) | mainpage file `Views_Match_1` |
| FB Link 2 (Somoy Shongbad) | subpage file `Views_Match_1` |
| FB Link 3 (category subpage) | **highest** of subpage `Views_Match_2..N` (extras are scraper snapshots; discards logged) |
| …but see below | with an export loaded, these two get **reordered onto the right columns** |
| Instagram | insta file `Views_Match_1` |
| X impressions | collector only — never fabricated |

**The export also fixes which column a value belongs in.** Your supervisor's
`Views_Match_N` order doesn't track Link 2 / Link 3 — their file lists values in
whatever order its scraper found them, which puts a sizeable share of checkable
cells on the wrong page's column (row totals stay right, the columns are
swapped). With an export loaded, RELAY reorders their values onto
the columns the export attributes them to. It never changes a number, only which
cell it sits in, and each moved value says where it came from.

Where the supervisor's file has no value, RELAY reads the **exact** figure from
your Business Suite export. It cannot match on the link alone — Facebook's
`pfbid` blobs differ between a copied link and the export — so it joins on the
caption (scoped to the same page and ±3 days) and, for mainpage posts whose
headline was rewritten, on Meta's numeric post id read from the live page. Each
filled cell carries a comment naming the export file and post id, so the sponsor
can trace the number back to a row in the file you hand them.

The reactions × k estimate is the last resort only — for posts no export covers.
Its multiplier is fitted from your own export data rather than guessed: measured
across a month of real posts, the views-per-reaction ratio spans an order of
magnitude — several hundred × at a handful of reactions down to tens of × on the
busiest posts — so a single fixed multiplier fits only a small minority of them.
Posts with zero reactions are left blank rather than estimated as zero.

Anything unresolved is *flagged*, never guessed; estimates are always labeled
with the reactions and k used.

## Troubleshooting

**The dashboard looks out of date — Autopilot or a drop zone is missing.**
You're on Docker and the container is still running the code it was *built*
with. Rebuild and hard-refresh:
```bash
docker compose up -d --build     # then Ctrl/Cmd+Shift+R in the browser
```
To confirm what the server is actually serving:
```bash
curl -s http://localhost:8501/ | grep -c autopilotBtn    # 1 = current, 0 = stale
```

**Windows: "&lt;brand&gt;: Invalid format string" after Run matching.**
Fixed. The campaign parser formatted a backfilled date with `%-d`, a directive
only glibc understands — the Windows C runtime rejects it, and only sheets with a
blank Date cell to repair ever hit it. Update to the current code; a test now
fails if any such directive is reintroduced.

**Windows: `Start RELAY.bat` flashes and closes.**
It shouldn't — every failure path pauses. If it does, open Command Prompt in the
RELAY folder and run `"Start RELAY.bat"` so the output stays on screen.

**`playwright: command not found`, or "Executable doesn't exist".**
The browser wasn't installed: `playwright install chromium` (see Route B step 3).
Make sure your virtual environment is active first.

**The login window never opens.**
You're inside Docker — there is no display in the container. Run
`python -m relay.cli login meta` on the host; the session is shared through the
`./data` volume.

**Port 8501 is already in use.**
Native: `python -m relay.cli serve --port 9000`. Docker: change the left-hand
number in `docker-compose.yml` (`"9000:8501"`) and `docker compose up -d`.

**Linux: permission denied writing to `data/` after using Docker.**
The container runs as root, so files it created are root-owned:
```bash
sudo chown -R $USER:$USER data
```

**Windows: `Activate.ps1 cannot be loaded`.**
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then activate again.

**A collector stopped early saying the budget is spent, or a checkpoint appeared.**
That's deliberate (`relay/collectors/base.py`): 200 navigations per session, and
an immediate stop on any captcha/checkpoint. Your login is preserved — rerun
later and it picks up where it left off from the SQLite checkpoint.

## Tests

```bash
pytest            # 153 tests, incl. cell-by-cell E2E vs the real April report
```

> **Data privacy:** the sample workbooks (campaign sheets, supervisor matched
> files, hand-made reports) contain real sponsor performance data and are
> deliberately **excluded from git** (`*.xlsx` and `*.csv` in `.gitignore`, the
> latter covering Business Suite exports). Keep them next
> to the repo locally to run the full E2E suite; without them the file-dependent
> tests skip automatically, which is what CI does.
