"""Normative-consistency checks for the M6F ACL materialization contract.

These guard the network boundary the later M6F stages depend on: the offline
stages must never be documented as calling Confluence, while the M6F-C1 capture
carve-out must stay explicit. A blanket "M6F never calls Confluence" would make
C1 either implemented wrongly or reviewed wrongly.
"""

from __future__ import annotations

from pathlib import Path

_SPEC_PATH = (
    Path(__file__).resolve().parents[3]
    / "contracts"
    / "foundation"
    / "ACL_MATERIALIZATION_SPEC.md"
)


def _normalized_spec() -> str:
    return " ".join(_SPEC_PATH.read_text(encoding="utf-8").split())


def test_spec_scopes_the_network_boundary_per_stage() -> None:
    spec = _normalized_spec()

    assert "M6F-A, M6F-B, and M6F-C2 never perform any network request" in spec
    assert "ACL materialization itself never calls Confluence" in spec


def test_spec_keeps_the_c1_live_capture_carve_out() -> None:
    spec = _normalized_spec()

    assert (
        "M6F-C1, which may invoke the approved M6B read-only collection path "
        "only during a separately authorized controlled live capture"
    ) in spec
    # §10 must still authorize exactly one controlled live read-only M6B run.
    assert (
        "separately authorized controlled live read-only M6B run is allowed"
        in spec
    )


def test_spec_has_no_blanket_no_confluence_contradiction() -> None:
    spec = _normalized_spec()

    # The retired wording bundled the Confluence claim into an unqualified
    # conjunction; it must not reappear and re-introduce the contradiction.
    assert "and never calls Confluence" not in spec
