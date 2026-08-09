# Getting Started in IntelliJ IDEA — step by step

This is a **Python** project (not Java). IntelliJ can run Python once you add the
free Python plugin. Follow these in order. Total time: ~10 minutes.

---

## Part 1 — One-time prerequisites

### 1.1 Install Python (if you don't have it)
- Check first: open a terminal and type `python3 --version` (Mac/Linux) or
  `python --version` (Windows). If you see `Python 3.9` or higher, skip this step.
- If not, download from https://www.python.org/downloads/ and install.
  **On Windows, tick "Add Python to PATH"** on the first install screen.

### 1.2 Add the Python plugin to IntelliJ
IntelliJ IDEA doesn't do Python out of the box (PyCharm does; IntelliJ needs a plugin).
1. Open IntelliJ.
2. `File → Settings` (Windows/Linux) or `IntelliJ IDEA → Settings` (Mac).
3. Click **Plugins** → **Marketplace** tab → search **"Python"**
   (the one by JetBrains) → **Install** → **Restart IDE**.

---

## Part 2 — Open the project

1. `File → Open…`
2. Navigate to and select the **`Lexicon`** folder (the whole folder,
   not a single file) → **OK**.
3. IntelliJ opens it and starts indexing (a progress bar at the bottom — wait for it).

---

## Part 3 — Tell IntelliJ which Python to use (the "interpreter")

A project needs a Python interpreter. We'll make a clean one just for this project
(a "virtual environment" — a private box of libraries so nothing conflicts).

1. `File → Project Structure → Project` (or `Settings → Project: … → Python Interpreter`).
2. Next to **Python Interpreter / SDK**, click **Add Interpreter → Add Local Interpreter**.
3. Choose **Virtualenv Environment → New environment**.
   - Base interpreter: pick the Python 3.x you installed.
   - Location: leave the default (it creates a `venv` folder inside the project).
4. Click **OK**. IntelliJ now uses that environment.

> If you get stuck here, you can skip the venv and just point it at your system
> Python 3 — it still works, it's just less tidy.

---

## Part 4 — Install the project's libraries

The project needs three small libraries (listed in `requirements.txt`).

1. Open the built-in terminal: `View → Tool Windows → Terminal` (or the **Terminal**
   tab at the bottom). It opens **inside the project folder** already.
2. Type this and press Enter:
   ```bash
   pip install -r requirements.txt
   ```
   (If `pip` isn't found, use `python -m pip install -r requirements.txt`.)
3. Wait for it to say it installed `lxml`, `PyYAML`, and `pytest`.

---

## Part 5 — Run it (three things to try)

Use the **Terminal** tab for all of these.

### 5.1 Run the tests (this is "the gate")
```bash
pytest -v
```
You should see **13 passed**. Green = the harness is working. Each test name tells
you what it checks (e.g. `test_handle_time_excludes_acw`).

### 5.2 Generate the NICE XML from each vendor's sample
```bash
python src/transform_queue.py fixtures/avaya_queue_sample.csv
python src/transform_queue_genesys.py fixtures/genesys_queue_sample.json
```
Each prints the NICE WFM XML to the screen. To save it to a file instead:
```bash
python src/transform_queue.py fixtures/avaya_queue_sample.csv > my_output.xml
```

### 5.3 Run the drift sensor on an output file
```bash
python src/transform_queue.py fixtures/avaya_queue_sample.csv > my_output.xml
python src/sensor.py my_output.xml
```
It reports "OK" for clean output.

### (Optional) Run a file without typing — the IntelliJ way
Open `src/transform_queue.py`, then click the green **▶ Run** arrow in the top
right. (Command-line is easier here because these scripts expect a file argument.)

---

## Part 6 — Understand what's in the project

Think of the project in two halves:

**A. The harness (mostly NOT code — this is "Lexicon")**
| Folder / file | What it is | Plain meaning |
|---------------|-----------|---------------|
| `ontology/canonical_wfm.yaml` | the source of truth | what each NICE field *means* (definitions, units, rules) |
| `ontology/avaya_cms_dialect.yaml` | Avaya translation | how each Avaya `hsplit`/`hagent` column maps to a NICE field, **and the traps** |
| `ontology/genesys_api_dialect.yaml` | Genesys translation | same, for Genesys metrics (milliseconds, tHandle includes ACW) |
| `guides/inferential/QUEUE_glossary.md` | the guide the **AI reads first** | the rules in plain English before it writes code |
| `guides/inferential/QUEUE_cross_vendor.md` | the cheat sheet | same concept, opposite math per vendor |
| `schema/HistPlugin.dtd` | structure rules | the official XML shape NICE requires |
| `CLAUDE.md` | agent instructions | tells a coding agent to read the guide and pass the gate |

**B. The integration (the actual code + its checks)**
| Folder / file | What it is | Plain meaning |
|---------------|-----------|---------------|
| `src/transform_queue.py` | the **correct** Avaya converter | reads the CSV, writes the NICE XML the right way |
| `src/transform_queue_genesys.py` | the correct Genesys converter | same, for the Genesys JSON |
| `src/transform_queue_baseline_BUGGY.py` | the **wrong** version (on purpose) | what a generic AI produces — for the before/after demo |
| `src/sensor.py` | the drift scanner | flags vendor words leaking into the output |
| `fixtures/*.csv, *.json` | sample inputs | small pretend vendor data |
| `fixtures/golden/*.xml` | the **correct answers** | hand-made expected output the tests compare against |
| `tests/test_contract_queue*.py` | the gate | checks the output means the right thing |

### How the pieces connect (the flow)
```
vendor sample (fixtures/)  ->  transformer (src/)  ->  NICE XML
                                     ^                     |
             reads the guide (guides/) and                | checked by
             the ontology (ontology/)                     v
                                            tests + DTD + sensor  =  the gate
```
Plain version: the **ontology + guide** tell you the meaning; the **transformer**
does the conversion; the **tests + sensor** refuse to let a wrong meaning through.

### The one idea to remember
NICE `HandleTime` = **talk + hold**.
- **Avaya:** `acdtime` is talk *without* hold, so you **add** `holdtime`; keep ACW out.
- **Genesys:** `tHandle` already *includes* ACW and is in milliseconds, so you
  **subtract** ACW and divide by 1000.

Same field, opposite math. A generic AI maps each vendor's own "handle time"
straight across and is wrong both times. The harness catches it. That's Lexicon.

---

## Part 7 — See the "before/after" (the demo)
Open `DEMO_RUNBOOK.md` and follow it — it runs the buggy version, shows the gate
catching it, then the correct version passing. Great for the presentation.

---

## Troubleshooting
- **`pytest` not found** → run `python -m pytest -v` instead, or re-run
  `pip install -r requirements.txt`.
- **`No module named lxml`** → the libraries didn't install into the interpreter
  IntelliJ is using. Re-open the Terminal (Part 4) and run the pip command again.
- **`python` not recognized (Windows)** → use `py` instead of `python`, or reinstall
  Python with "Add to PATH" ticked.
- **Wrong interpreter** → bottom-right of IntelliJ shows the current interpreter;
  click it to switch to the project venv.
- **Tests fail after you edit code** → that's the point; the gate is catching a
  change. Undo your edit or fix the mapping.
