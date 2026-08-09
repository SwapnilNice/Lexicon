"""
Derive canonical records from raw vendor CSVs by reusing the engine's compute_fields.

This is a library wrapper — no XML, no side effects. Keeps the History Store
vendor-neutral, obeying guides/inferential/QUEUE_glossary.md.
"""
import pathlib
from typing import Iterable

from src import engine


_CONTACTS_RECEIVED_PARTS = ("HandledLong", "HandledShort", "AbandonedLong", "AbandonedShort")


def _fill_contacts_received(canon: dict) -> None:
    """QUEUE-glossary identity: ContactsReceived = handled + abandoned (short + long).

    Applied when a vendor mapping doesn't emit ContactsReceived directly (e.g. Avaya
    hsplit exposes the parts but not the sum). Downstream — baselines, completeness —
    uses ContactsReceived, so we materialize it here to keep the store vendor-neutral.
    """
    if "ContactsReceived" in canon:
        return
    if any(k in canon for k in _CONTACTS_RECEIVED_PARTS):
        canon["ContactsReceived"] = sum(int(canon.get(k, 0)) for k in _CONTACTS_RECEIVED_PARTS)


def derive_row(mapping: dict, row: dict) -> dict:
    """One vendor row -> one dict of canonical fields (no interval/day metadata)."""
    canon = engine.compute_fields(mapping, row)
    _fill_contacts_received(canon)
    return canon


def _parse_interval_start(s: str) -> tuple[str, str]:
    """'20250602T0900' -> ('2025-06-02', '09:00')."""
    day = f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    interval = f"{s[9:11]}:{s[11:13]}"
    return day, interval


def derive_from_csv(mapping: dict, csv_path: pathlib.Path) -> list[dict]:
    """Load a vendor CSV and produce canonical records with (day, interval) metadata attached."""
    rows, _dt, _period = engine.load_csv(str(csv_path))
    out = []
    for r in rows:
        day, interval = _parse_interval_start(r["INTERVAL_START"])
        canon = derive_row(mapping, r)
        canon.update({"day": day, "interval": interval})
        out.append(canon)
    return out


def derive_day_folder(mappings: dict[str, dict], day_folder: pathlib.Path) -> dict[str, list[dict]]:
    """
    Read a day folder (queue.csv, agentqueue.csv, agentsystem.csv) and return
    {report_name: [canonical_records]}.

    `mappings` is keyed by report name: 'queue', 'agentqueue', 'agentsystem'.
    """
    result = {}
    for report, filename in [("queue", "queue.csv"),
                             ("agentqueue", "agentqueue.csv"),
                             ("agentsystem", "agentsystem.csv")]:
        path = day_folder / filename
        if not path.exists():
            result[report] = []
            continue
        result[report] = derive_from_csv(mappings[report], path)
    return result
