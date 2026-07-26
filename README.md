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

There are two ways to run RELAY. **Docker** is the least work and keeps your
machine clean; **native Python** is better if you want to edit the code, and it
is the only way to do the one-time Meta sign-in (a container has no screen to
open a browser window on). Many people use both: Docker for the dashboard,
native Python once for the login.

### What you need first

| | Docker route | Native route |
|---|---|---|
| Docker Desktop / Engine | **required** | — |
| Python | — | **3.12 or newer** |
| Git | to clone the repo | to clone the repo |
| Free disk | ~1.5 GB (image incl. Chromium) | ~700 MB (with Chromium) |
| A desktop session | only for the Meta login | only for the Meta login |

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
   optional, but they auto-resolve most cells. Multi-brand files with `Bkash`-style
   separator rows work as-is; RELAY finds the right section.
3. Export your content data from Meta Business Suite (Insights → Content →
   export) and drop it in too — **one file covers all your pages**, so this is a
   single download per month, not one per page. It carries Meta's **exact** Views
   per post, which is what the report's Views column has always meant.
4. Open the dashboard → drop files → pick brand + month tab → **Run matching**.
5. Review: green = matched, amber = estimated, blue = manual, red outline =
   missing. Click ✎ on any cell to estimate from reactions or type an exact value.
6. **Generate .xlsx** → download → e-mail it. Untick "mark estimated cells" for
   the sponsor-facing copy.
7. Optionally drop last cycle's hand-made report under *Cross-check* to verify
   RELAY cell-by-cell.

## CLI

```bash
# list month tabs
python -m relay.cli sheets "White Plus Updated FB Photocard Campaign _ Mar'26.xlsx"

# full run with cross-check
python -m relay.cli run \
  --campaign "White Plus Updated FB Photocard Campaign _ Mar'26.xlsx" \
  --sheet April --brand "White Plus" \
  --mainpage "white plus mainpage matched (1).xlsx" \
  --subpage  "white plus subpage matched (2).xlsx" \
  --insta    "white plus insta matched (3).xlsx" \
  --insights "WhitePlusApril.csv" \
  --reference "White Plus FB Photocard (April).xlsx"
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
`Views_Match_N` order doesn't track Link 2 / Link 3 — on April 2026 that put
36% of checkable cells on the wrong page's column (row totals were right, the
columns were swapped). With an export loaded, RELAY reorders their values onto
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
across 1,820 real posts, reach/reactions ranged from ~294× at 1–4 reactions down
to ~61× at 500+, so a single fixed multiplier matched fewer than a fifth of them.
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
