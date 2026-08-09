"""
Lexicon — Integrity Layer UI (Streamlit page)

Wraps `src.integrity.run` and `src.integrity.registry` CLIs.
Lets a user warm history, run integrity on a day of Avaya CSVs (uploaded or
picked from a fixture), and see the sidecar findings/proposals.

Run:   streamlit run src/ui/app.py    (this file appears as a page in the sidebar)
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
from datetime import date

import streamlit as st
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[3]
STATE_ROOT = ROOT / "state"
OUT_ROOT = ROOT / "out"
DEFAULT_WARMUP_FIXTURE = ROOT / "fixtures" / "avaya_30d"
SCENARIOS_ROOT = ROOT / "fixtures" / "avaya_30d_scenarios"

st.set_page_config(page_title="Lexicon — Integrity Layer", layout="wide", page_icon="🩺")

st.title("Lexicon — Integrity Layer")
st.caption(
    "Catch the failures the transform + WFM cannot see: pipeline gaps and queue renumbers. "
    "Runs on top of the existing engine — never mutates its output."
)


# --------------------------------------------------------------------------
# Helpers — thin subprocess wrappers around the existing CLIs
# --------------------------------------------------------------------------
def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))


def customer_state_paths(customer: str) -> dict[str, pathlib.Path]:
    return {
        "history_queue":     STATE_ROOT / "history" / customer / "queue.jsonl",
        "history_agentq":    STATE_ROOT / "history" / customer / "agent_queue.jsonl",
        "history_agents":    STATE_ROOT / "history" / customer / "agent_system.jsonl",
        "baseline":          STATE_ROOT / "baselines" / customer / "queue_baselines.yaml",
        "registry":          STATE_ROOT / "queue_registry" / f"{customer}.yaml",
    }


def state_exists(customer: str) -> bool:
    return customer_state_paths(customer)["history_queue"].exists()


def state_summary(customer: str) -> dict:
    p = customer_state_paths(customer)
    days = set()
    if p["history_queue"].exists():
        for line in p["history_queue"].read_text().splitlines():
            if line.strip():
                days.add(json.loads(line)["day"])
    baseline = None
    if p["baseline"].exists():
        baseline = yaml.safe_load(p["baseline"].read_text())
    registry = None
    if p["registry"].exists():
        registry = yaml.safe_load(p["registry"].read_text())
    return {"days_in_history": len(days), "baseline": baseline, "registry": registry}


def warmup(customer: str, fixture_root: pathlib.Path) -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "src.integrity.run", "--warmup",
                 "--input", str(fixture_root),
                 "--customer", customer,
                 "--state-dir", str(STATE_ROOT)])


def run_integrity(customer: str, day_folder: pathlib.Path, run_date: str,
                  out_dir: pathlib.Path) -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "src.integrity.run",
                 "--input", str(day_folder),
                 "--customer", customer,
                 "--state-dir", str(STATE_ROOT),
                 "--out", str(out_dir),
                 "--run-date", run_date])


def reset_customer_state(customer: str) -> None:
    p = customer_state_paths(customer)
    for path in (p["history_queue"].parent, p["baseline"].parent):
        if path.exists():
            shutil.rmtree(path)
    if p["registry"].exists():
        p["registry"].unlink()


def ratify_proposal(customer: str, events_json: pathlib.Path, proposal_id: str) -> subprocess.CompletedProcess:
    return _run([sys.executable, "-m", "src.integrity.registry", "approve",
                 str(events_json),
                 "--proposal", proposal_id,
                 "--customer", customer,
                 "--state-dir", str(STATE_ROOT)])


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
for k, v in [("last_data_health", None), ("last_identity_events", None),
             ("last_out_dir", None), ("last_customer", None), ("logs", [])]:
    if k not in st.session_state:
        st.session_state[k] = v


def log(msg: str):
    st.session_state.logs.append(msg)


# --------------------------------------------------------------------------
# Sidebar — customer + state controls
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("1. Customer")
    customer = st.text_input("Customer name", value="demo",
                             help="Per-customer state directory. Use 'demo' for the fixtures.")

    st.divider()
    st.header("2. History state")
    if state_exists(customer):
        summary = state_summary(customer)
        st.success(f"State present · {summary['days_in_history']} days in history")
        if summary["baseline"]:
            st.caption(f"Baseline: {summary['baseline'].get('generated_from_days','?')} days · "
                       f"{len(summary['baseline'].get('queues',{}))} queues profiled")
    else:
        st.warning("No state yet — warm it before running.")

    warmup_source = st.radio("Warmup source",
                             ["fixtures/avaya_30d (22 healthy days)", "Pick a folder"],
                             help="The default fixture is the 22-day synthetic Avaya history.")
    if warmup_source == "Pick a folder":
        custom_warmup = st.text_input("Path (relative to project root)",
                                       value="fixtures/avaya_30d")
        warmup_root = ROOT / custom_warmup
    else:
        warmup_root = DEFAULT_WARMUP_FIXTURE

    col_w1, col_w2 = st.columns(2)
    if col_w1.button("Warmup", type="primary", use_container_width=True):
        with st.spinner(f"Warming state for '{customer}' from {warmup_root.name}…"):
            r = warmup(customer, warmup_root)
        if r.returncode == 0:
            log(r.stderr.strip() or "warmup ok")
            st.success("Warmup complete.")
            st.rerun()
        else:
            st.error(f"Warmup failed:\n{r.stderr}")

    if col_w2.button("Reset state", use_container_width=True):
        reset_customer_state(customer)
        for k in ("last_data_health", "last_identity_events", "last_out_dir"):
            st.session_state[k] = None
        st.warning(f"State cleared for '{customer}'.")
        st.rerun()

    st.divider()
    st.header("3. Interval data")
    input_mode = st.radio("Provide day data as",
                          ["Pick a scenario fixture", "Upload 3 CSVs"])

    day_folder: pathlib.Path | None = None
    run_date_default = "2025-07-14"

    if input_mode == "Pick a scenario fixture":
        scenarios = []
        if SCENARIOS_ROOT.exists():
            for scen in sorted(SCENARIOS_ROOT.iterdir()):
                if scen.is_dir():
                    for day in sorted(scen.iterdir()):
                        if day.is_dir():
                            scenarios.append((f"{scen.name}/{day.name}", day))
        if not scenarios:
            st.info("No scenario fixtures found under fixtures/avaya_30d_scenarios/.")
        else:
            labels = [s[0] for s in scenarios]
            chosen = st.selectbox("Scenario", labels)
            day_folder = dict(scenarios)[chosen]
            run_date_default = day_folder.name
    else:
        st.caption("Upload all three CSVs for the same day.")
        up_queue = st.file_uploader("queue.csv", type=["csv"], key="up_queue")
        up_aq    = st.file_uploader("agentqueue.csv", type=["csv"], key="up_aq")
        up_as    = st.file_uploader("agentsystem.csv", type=["csv"], key="up_as")
        if up_queue and up_aq and up_as:
            tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="lexicon_integrity_"))
            day_folder = tmpdir / run_date_default
            day_folder.mkdir(parents=True)
            (day_folder / "queue.csv").write_bytes(up_queue.getvalue())
            (day_folder / "agentqueue.csv").write_bytes(up_aq.getvalue())
            (day_folder / "agentsystem.csv").write_bytes(up_as.getvalue())

    run_date = st.text_input("Run date (YYYY-MM-DD)", value=run_date_default)

    st.divider()
    can_run = day_folder is not None and state_exists(customer)
    run_hint = None
    if not state_exists(customer):
        run_hint = "Warm state first."
    elif day_folder is None:
        run_hint = "Provide a day folder."
    if run_hint:
        st.caption(f"⚠ {run_hint}")
    run_clicked = st.button("Run integrity pass", type="primary", disabled=not can_run,
                            use_container_width=True)


# --------------------------------------------------------------------------
# Run action
# --------------------------------------------------------------------------
if run_clicked and day_folder and state_exists(customer):
    out_dir = OUT_ROOT / f"ui-{customer}-{run_date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    with st.spinner("Running integrity pass…"):
        r = run_integrity(customer, day_folder, run_date, out_dir)
    if r.returncode != 0:
        st.error(f"Run failed:\n{r.stderr}")
    else:
        log(r.stderr.strip())
        try:
            dh = json.loads((out_dir / "data_health.json").read_text())
            ie = json.loads((out_dir / "identity_events.json").read_text())
        except FileNotFoundError as e:
            st.error(f"Sidecar missing: {e}")
        else:
            st.session_state.last_data_health = dh
            st.session_state.last_identity_events = ie
            st.session_state.last_out_dir = str(out_dir)
            st.session_state.last_customer = customer
            st.success("Integrity pass complete.")


# --------------------------------------------------------------------------
# Main area — Results tabs
# --------------------------------------------------------------------------
dh = st.session_state.last_data_health
ie = st.session_state.last_identity_events

if not dh and not ie:
    st.info("👈 Warm state, provide a day folder, and click **Run integrity pass**.")

    # Show a preview of current state even before running.
    if state_exists(customer):
        st.subheader("Current state snapshot")
        summary = state_summary(customer)
        c1, c2, c3 = st.columns(3)
        c1.metric("Days in history", summary["days_in_history"])
        c2.metric("Queues profiled", len(summary["baseline"].get("queues", {})) if summary["baseline"] else 0)
        c3.metric("Registry entries", len(summary["registry"].get("queues", [])) if summary["registry"] else 0)
        if summary["registry"]:
            with st.expander("Queue registry"):
                st.json(summary["registry"], expanded=False)
    st.stop()


# Summary strip
c1, c2, c3, c4 = st.columns(4)
c1.metric("Findings (Feature A)", dh["summary"]["findings_count"] if dh else 0)
c2.metric("Proposals (Feature B)", ie["summary"]["proposals_count"] if ie else 0)
c3.metric("Intervals checked", dh["summary"]["intervals_checked"] if dh else 0)
c4.metric("Cold start?", "yes" if (dh and dh["summary"]["cold_start"]) else "no")

tab_health, tab_identity, tab_registry, tab_raw = st.tabs(
    ["🩺 Data Health (A)", "🔀 Identity Events (B)", "📇 Registry", "📄 Raw JSON"]
)

# --- Feature A tab ---
with tab_health:
    if not dh or not dh["findings"]:
        st.success("✅ No integrity findings — feed is healthy.")
    else:
        rows = []
        for f in dh["findings"]:
            rows.append({
                "Interval": f["interval"],
                "Queue": f.get("queue") or "—",
                "Classification": f["classification"],
                "Severity": f["severity"],
                "Expected": f.get("expected_contacts"),
                "Observed": f.get("observed_contacts"),
                "z-score": f.get("z_score"),
                "Staffed agents": ", ".join(f["evidence"].get("agents_staffed", []) or []),
                "Ready sec": f["evidence"].get("ready_time_seconds_total"),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
        with st.expander("Evidence details"):
            for f in dh["findings"]:
                st.markdown(f"**{f['id']}** — {f['classification']} @ {f['interval']} queue={f.get('queue')}")
                st.json(f["evidence"])

# --- Feature B tab ---
with tab_identity:
    proposals = (ie or {}).get("proposals", [])
    new_qs = (ie or {}).get("new_queues", [])

    if not proposals and not new_qs:
        st.success("✅ No queue identity events — no renumbers detected.")
    else:
        if proposals:
            st.subheader("Merge proposals")
            rows = []
            for p in proposals:
                rows.append({
                    "Proposal ID": p["id"],
                    "Disappeared": p["disappeared_key"],
                    "New key": p["new_key"],
                    "Maps to": p["canonical_id"],
                    "Confidence": p["confidence"],
                    "Agent overlap": p["score_breakdown"]["agent_overlap"],
                    "Volume shape": p["score_breakdown"]["volume_shape"],
                    "Hours overlap": p["score_breakdown"]["hours_overlap"],
                    "Shared agents": ", ".join(p["evidence"].get("shared_agents", [])),
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

            st.divider()
            st.markdown("**Ratify a proposal** — appends the new alias to its canonical queue in the registry.")
            for p in proposals:
                cols = st.columns([3, 2, 1])
                cols[0].text(f"{p['id']}  ·  {p['disappeared_key']} → {p['new_key']}  ·  {p['canonical_id']}  ·  conf {p['confidence']}")
                if p.get("status") == "ratified":
                    cols[2].markdown("✅ ratified")
                else:
                    if cols[2].button("Ratify", key=f"ratify_{p['id']}"):
                        events_path = pathlib.Path(st.session_state.last_out_dir) / "identity_events.json"
                        r = ratify_proposal(customer, events_path, p["id"])
                        if r.returncode == 0:
                            p["status"] = "ratified"
                            st.session_state.last_identity_events = ie
                            st.success(r.stdout.strip() or "Ratified.")
                            st.rerun()
                        else:
                            st.error(r.stderr)
        if new_qs:
            st.subheader("New queues (below merge threshold)")
            st.dataframe(
                [{"Vendor key": q["vendor_key"], "First seen": q["first_seen"],
                  "Agents": ", ".join(q["provisional_fingerprint"].get("agent_set", []))}
                 for q in new_qs],
                use_container_width=True, hide_index=True,
            )

# --- Registry tab ---
with tab_registry:
    summary = state_summary(customer)
    if not summary["registry"]:
        st.info("Registry is empty.")
    else:
        for q in summary["registry"].get("queues", []):
            st.markdown(f"### `{q['canonical_id']}`")
            st.text(f"aliases: {', '.join(q.get('aliases', []))}")
            st.text(f"last seen: {q.get('last_seen')}")
            if q.get("fingerprint", {}).get("agent_set"):
                st.text(f"agents: {', '.join(q['fingerprint']['agent_set'])}")
            st.divider()

# --- Raw JSON tab ---
with tab_raw:
    if dh:
        st.markdown("**data_health.json**")
        st.json(dh, expanded=False)
    if ie:
        st.markdown("**identity_events.json**")
        st.json(ie, expanded=False)
    if st.session_state.last_out_dir:
        st.caption(f"Location on disk: {st.session_state.last_out_dir}")
