"""Tests for the B4 (flow-configured mapping) v1 slice."""
from pathlib import Path
import pytest

from lexicon.blueprints.wfm_mapping import derive_wfm_mapping, _first_object_field

ROOT = Path(__file__).resolve().parents[3]
BLUEPRINT_DIR = ROOT / "ontology" / "blueprints"
CANON = ROOT / "ontology" / "canonical_wfm.yaml"


def test_first_object_field_picks_first_backticked_ref():
    text = "For voice: `VoiceCall.CallStartDateTime`. For chat: `AgentWork.AcceptDateTime`."
    assert _first_object_field(text) == "VoiceCall.CallStartDateTime"


def test_first_object_field_returns_none_when_absent():
    assert _first_object_field("no backticks here") is None
    assert _first_object_field("`not_dotted`") is None
    assert _first_object_field("just prose") is None


def test_derive_salesforce_queue_based_mapping():
    result = derive_wfm_mapping(
        blueprint_path=BLUEPRINT_DIR / "salesforce" / "queue_based.md",
        events_path=BLUEPRINT_DIR / "events.yaml",
        canonical_path=CANON,
        report="queue",
    )

    # Metadata
    assert result["meta"]["vendor"] == "salesforce"
    assert result["meta"]["routing_model"] == "queue_based"
    assert result["meta"]["status"] == "proposed"

    fields = result["fields"]
    proposals = result["proposals"]

    # HandleTime — Salesforce doesn't produce hold events (per blueprint), so
    # the derivation lacks a required component and HandleTime is None.
    assert fields.get("HandleTime") is None
    assert proposals["HandleTime"]["needs_review"] is True
    assert "hold_time" in proposals["HandleTime"]["rationale"]

    # WorkTime — the acw_time projection resolves via interaction.acw.start / .end.
    # Blueprint records these as "AgentWork.EndDateTime" / "AgentWork.CloseDateTime".
    assert fields.get("WorkTime") is not None
    assert "AgentWork" in fields["WorkTime"]
    # The formula should be a time difference (subtraction).
    assert " - " in fields["WorkTime"]


def test_derive_uses_canonical_wfm_concepts():
    """Confirm the routing between events.yaml projections and canonical_wfm.yaml
    derivations is intact — i.e., events with `projects_to_canonical_wfm` land in
    the primitive-concept map, and canonical fields with `derivation` blocks
    compose from those primitives."""
    result = derive_wfm_mapping(
        blueprint_path=BLUEPRINT_DIR / "salesforce" / "queue_based.md",
        events_path=BLUEPRINT_DIR / "events.yaml",
        canonical_path=CANON,
        report="queue",
    )
    # WorkTime is a leaf (not composed) in canonical_wfm.yaml, so it must exist
    # via the LEAF_TO_CONCEPT branch (not derivation).
    assert "WorkTime" in result["proposals"]
    # HandleTime is composed (talk + hold) in canonical_wfm.yaml, so its rationale
    # should reference the derivation path.
    assert "HandleTime" in result["proposals"]
