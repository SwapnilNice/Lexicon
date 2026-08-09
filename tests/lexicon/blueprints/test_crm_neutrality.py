"""CRM-neutrality gate — framework code must not name any specific CRM.

Spec §11 success criterion #6: `grep -r salesforce src/lexicon/blueprints/`
returns zero hits. Same for other platform names.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK_DIR = ROOT / "src" / "lexicon" / "blueprints"

# Platform slugs from schema.yaml — these must NOT appear in framework code.
FORBIDDEN_TERMS = [
    "salesforce", "dynamics365", "servicenow_cx", "hubspot_service_hub",
    # Not-slug forms that would also indicate coupling:
    "AgentWork", "PendingServiceRouting", "UserServicePresence",
    "Omni-Channel", "Service Cloud",
]


def test_framework_code_does_not_reference_specific_crms():
    """Framework Python files must be platform-neutral."""
    py_files = [p for p in FRAMEWORK_DIR.rglob("*.py") if p.name != "__init__.py"]
    violations: list[tuple[Path, str, int]] = []
    for path in py_files:
        text = path.read_text()
        for term in FORBIDDEN_TERMS:
            # Case-insensitive match for slugs; case-sensitive for object names.
            if term.islower():
                pattern = re.compile(re.escape(term), re.IGNORECASE)
            else:
                pattern = re.compile(re.escape(term))
            for m in pattern.finditer(text):
                line_num = text.count("\n", 0, m.start()) + 1
                violations.append((path, term, line_num))
    assert violations == [], (
        "Framework code contains CRM-specific terms (violates CRM-neutrality):\n" +
        "\n".join(f"  {p}:{ln}  contains {t!r}" for p, t, ln in violations)
    )
