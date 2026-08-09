"""CRM/vendor-neutrality gate for the discovery framework.

Same idea as tests/lexicon/blueprints/test_crm_neutrality.py — no vendor
slug or vendor-specific field name should appear in framework code. The
semantic-tag keyword lexicon lives at ontology/discover_lexicon.yaml and
is loaded at runtime, so framework Python files should be clean.

This test COMPLEMENTS the blueprint neutrality test. Both must pass.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK_DIR = ROOT / "src" / "lexicon" / "discover"

# Vendor slugs (case-insensitive) and vendor-specific field/object names
# (case-sensitive) that must not appear in framework code.
FORBIDDEN_SLUGS = ["five9", "amazonconnect", "salesforce", "genesys", "dynamics365"]
FORBIDDEN_FIELD_NAMES = [
    "acdtime", "acwtime", "holdtime", "anstime", "acdcalls",
    "AgentWork", "PendingServiceRouting", "UserServicePresence",
    "AFTER_CONTACT_WORK_TIME", "SUM_HANDLE_TIME",
    "tTalk", "tHeld", "tAcw", "tHandle",
]
# "avaya" is a very common substring (Avaya) — check case-insensitive as a slug
FORBIDDEN_SLUGS.append("avaya")


def test_framework_code_does_not_reference_specific_crms():
    py_files = [p for p in FRAMEWORK_DIR.rglob("*.py")
                if p.name != "__init__.py"]
    violations: list[tuple[Path, str, int]] = []
    for path in py_files:
        text = path.read_text()
        for term in FORBIDDEN_SLUGS:
            pat = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)
            for m in pat.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                violations.append((path, term, line))
        for term in FORBIDDEN_FIELD_NAMES:
            pat = re.compile(re.escape(term))
            for m in pat.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                violations.append((path, term, line))
    assert violations == [], (
        "Framework code contains vendor-specific terms (violates neutrality):\n"
        + "\n".join(
            f"  {p.relative_to(ROOT)}:{ln}  contains {t!r}"
            for p, t, ln in violations
        )
    )
