"""
Lexicon mapping ENGINE (report-aware).

Runs an *executable* dialect mapping file (a .map.yaml) to turn vendor rows into
NICE WFM XML, for any of the three interval reports:
    queue        -> QueueNode / QueueData
    agentqueue   -> AgentQueueNode / AgentQueueData
    agentsystem  -> AgentSystemNode / AgentSystemData

The mapping expresses each canonical field as a small arithmetic formula over
vendor columns, e.g.:
    HandleTime: "acdtime + holdtime"              # Avaya
    HandleTime: "(tTalk_ms + tHeld_ms) / 1000"    # Genesys

Units and XML order come from the canonical ontology + the DTD, so a mapping only
has to say WHICH formula, never HOW to format. The report is read from meta.report.
"""
import ast
import csv
import json
import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANON = yaml.safe_load((ROOT / "ontology" / "canonical_wfm.yaml").read_text())

# child element order per report (from HistPlugin.dtd)
QUEUE_ORDER = [
    "QueueValue", "ContactsReceived", "AbandonedShort", "AbandonedLong",
    "HandledShort", "HandledLong", "HandleTime", "HoldTime", "WorkTime",
    "QueueDelayTime", "SvcLvlPct", "BackLog", "BackLogExpired",
    "BackLogNotExpired", "RightPartyContacts", "RightPartyTalkTime",
    "WrongPartyContacts", "WrongPartyTalkTime", "ContactsActive",
]
AGENTQUEUE_ORDER = [
    "QueueValue", "AgentValue", "Handled", "HandleTime", "HoldTime", "WorkTime",
    "RightPartyContacts", "RightPartyTalkTime", "WrongPartyContacts", "WrongPartyTalkTime",
]
AGENTSYSTEM_ORDER = [
    "AgentValue", "InternalContacts", "InternalHandleTime", "ReadyTime",
    "NotReadyTime", "OutboundContacts", "OutboundHandleTime", "LoginTime",
]

REPORTS = {
    "queue":       {"section": "queue",        "node": "QueueNode",       "data": "QueueData",       "order": QUEUE_ORDER},
    "agentqueue":  {"section": "agent_queue",  "node": "AgentQueueNode",  "data": "AgentQueueData",  "order": AGENTQUEUE_ORDER},
    "agentsystem": {"section": "agent_system", "node": "AgentSystemNode", "data": "AgentSystemData", "order": AGENTSYSTEM_ORDER},
}


def report_of(mapping: dict) -> str:
    return mapping.get("meta", {}).get("report", "queue")


def unit_of(field: str, section: str) -> str:
    return CANON[section].get(field, {}).get("unit", "count")


# ---- safe arithmetic evaluator (only + - * / and names/numbers) -----------
def safe_eval(expr: str, row: dict) -> float:
    node = ast.parse(str(expr), mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add): return a + b
            if isinstance(n.op, ast.Sub): return a - b
            if isinstance(n.op, ast.Mult): return a * b
            if isinstance(n.op, ast.Div): return a / b
            raise ValueError("operator not allowed")
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.Constant):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id not in row:
                raise KeyError(n.id)
            return float(row[n.id])
        raise ValueError(f"expression element not allowed: {type(n).__name__}")

    return ev(node)


def _wrap(field: str, value, section: str) -> str:
    u = unit_of(field, section)
    if u == "key":
        return f"<{field}>{value}</{field}>"
    if u == "percentage":
        return f"<{field}><percentage>{value}</percentage></{field}>"
    if u == "duration_seconds":
        return f"<{field}><duration><totalseconds>{int(round(value))}</totalseconds></duration></{field}>"
    return f"<{field}><count>{int(round(value))}</count></{field}>"


def transform(mapping: dict, rows: list, datetime: str, period: str) -> str:
    cfg = REPORTS[report_of(mapping)]
    section, fields = cfg["section"], mapping["fields"]
    out = ['<?xml version="1.0"?>', "<HistPlugin>", "    <DataSourceNode>",
           f"        <Vendor>{mapping['meta']['vendor']}</Vendor>", f"        <{cfg['node']}>",
           f"            <TimePeriod><DateTime>{datetime}</DateTime><period>{period}</period></TimePeriod>"]
    for row in rows:
        out.append(f"            <{cfg['data']}>")
        for field in cfg["order"]:
            if field not in fields:
                continue
            expr = fields[field]
            if unit_of(field, section) == "key":
                val = str(row[expr]) if expr in row else expr
                out.append("                " + _wrap(field, val, section))
            else:
                out.append("                " + _wrap(field, safe_eval(expr, row), section))
        out.append(f"            </{cfg['data']}>")
    out += [f"        </{cfg['node']}>", "    </DataSourceNode>", "</HistPlugin>", ""]
    return "\n".join(out)


def compute_fields(mapping: dict, row: dict) -> dict:
    """Per-field canonical values (used by verify_mapping)."""
    section = REPORTS[report_of(mapping)]["section"]
    result = {}
    for field, expr in mapping["fields"].items():
        if unit_of(field, section) == "key":
            result[field] = str(row[expr]) if expr in row else str(expr)
        else:
            result[field] = int(round(safe_eval(expr, row)))
    return result


# ---- loaders --------------------------------------------------------------
def load_csv(path: str):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k, v in list(r.items()):
            if k == "INTERVAL_START":
                continue
            try:
                r[k] = int(v)
            except (ValueError, TypeError):
                try: r[k] = float(v)
                except (ValueError, TypeError): pass
    return rows, rows[0]["INTERVAL_START"], "PT15M"


def load_genesys(path: str):
    doc = json.loads(pathlib.Path(path).read_text())
    rows = []
    for res in doc["results"]:
        row = {k: v for k, v in res.items() if k != "metrics"}   # queueId, userId, ...
        row.update(res.get("metrics", {}))
        rows.append(row)
    return rows, doc["intervalStart"], doc.get("period", "PT15M")


def load_any(path: str):
    return load_genesys(path) if path.endswith(".json") else load_csv(path)


if __name__ == "__main__":
    import sys
    mp = yaml.safe_load(pathlib.Path(sys.argv[1]).read_text())
    rows, dt, per = load_any(sys.argv[2])
    sys.stdout.write(transform(mp, rows, dt, per))
