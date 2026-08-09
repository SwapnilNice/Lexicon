"""
Rolling per-customer canonical history, one JSONL per report.

Canonical-only: refuses to store records that contain known vendor terms.
"""
import json
import pathlib
from datetime import date

FORBIDDEN_TERMS = frozenset({
    # Avaya
    "acdtime", "holdtime", "acwtime", "split", "logid", "abncalls", "slvlabns",
    "anstime", "acceptable", "acdcalls", "i_stafftime", "i_availtime", "ti_auxtime",
    "da_acdcalls", "da_acdtime", "o_acdcalls", "o_acdtime",
    # Genesys
    "tHandle", "tTalk", "tHeld", "tAcw", "queueId", "userId",
})

REPORTS = ("queue", "agent_queue", "agent_system")


class HistoryStore:
    def __init__(self, root: pathlib.Path, customer: str):
        self.root = pathlib.Path(root)
        self.customer = customer
        self.dir = self.root / "history" / customer
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, report: str) -> pathlib.Path:
        assert report in REPORTS, f"unknown report {report}"
        return self.dir / f"{report}.jsonl"

    def append(self, report: str, records: list[dict]) -> None:
        for r in records:
            leaked = FORBIDDEN_TERMS.intersection(r.keys())
            if leaked:
                raise ValueError(f"vendor term(s) leaked into history: {sorted(leaked)}")
        p = self._path(report)
        with p.open("a") as f:
            for r in records:
                f.write(json.dumps(r, sort_keys=True) + "\n")

    def read(self, report: str):
        p = self._path(report)
        if not p.exists():
            return
        with p.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def prune(self, reference_day: str, retention_days: int = 30) -> None:
        """Remove records with day < (reference_day - retention_days)."""
        ref = date.fromisoformat(reference_day)
        keep_from = ref.toordinal() - retention_days
        for report in REPORTS:
            p = self._path(report)
            if not p.exists():
                continue
            kept = []
            with p.open() as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if date.fromisoformat(rec["day"]).toordinal() >= keep_from:
                        kept.append(line)
            with p.open("w") as f:
                for line in kept:
                    f.write(line + "\n")

    def days_present(self, report: str = "queue") -> set[str]:
        return {r["day"] for r in self.read(report)}
