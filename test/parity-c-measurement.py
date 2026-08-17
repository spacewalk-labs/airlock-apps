#!/usr/bin/env python3
"""Validate the sanitized phase-8 measurement and its selected C decisions."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MEASUREMENT = ROOT / "census" / "parity-c-measurement-20260817.json"
EXPECTED_DECISIONS = {
    "DT-A1": "keep",
    "MW-R2": "migrate",
    "MW-S2": "migrate",
    "PA-N3": "migrate",
    "PA-N5": "keep",
    "PA-N6": "keep",
    "PA-C2": "keep",
    "PB-A4": "keep",
}
EXPECTED_MEASUREMENTS = {
    "DT-A1": {"retained_route_requests": 0, "caller_principal": "unknown", "disposition": "keep"},
    "MW-R2": {"exact_split_requests": 20, "disposition": "migrate"},
    "MW-S2": {
        "claude_links": 5,
        "codex_links": 4,
        "claude_alias_requests": 39,
        "codex_alias_requests": 0,
        "disposition": "migrate",
    },
    "PA-N3": {
        "live_no_new_privs_zero": 5,
        "historical_spawned_sudo_failure": True,
        "disposition": "migrate",
    },
    "PA-N5": {
        "finite_container_caps": 4,
        "unbounded_container_caps": 1,
        "unbounded_policy": "explicit-cap-required",
        "memory_limit_events": 0,
        "disposition": "keep",
    },
    "PA-N6": {
        "largest_observed_tasks_peak": 1466,
        "task_limit_events": 0,
        "disposition": "keep",
    },
    "PA-C2": {
        "exact_proxy_host_boxes": 5,
        "incoming_host": "unknown",
        "policy": "no-widening",
        "disposition": "keep",
    },
    "PB-A4": {
        "external_html_candidates": 1031,
        "active_list_items": 28,
        "active_external_html_sources": 13,
        "active_direct_html_sources": 3,
        "active_missing_sources": 12,
        "unavailable_boxes": 1,
        "disposition": "keep",
    },
}


def main() -> None:
    raw = MEASUREMENT.read_text()
    data = json.loads(raw)
    assert data["schema"] == "airlock.public-app-parity.c-measurement/v1"
    assert re.fullmatch(r"2026-08-17T\d{2}:\d{2}:\d{2}Z", data["observed_at"])

    evidence = data["private_evidence"]
    assert evidence == {
        "repository": "TeamSPWK/swk-infra",
        "commit": "e9cd24840f612cc94c2ddeaab70f56fc53987af1",
        "path": (
            "docs/tasks/active/airlock-universal-platform/"
            "04-public-app-parity.task.logs/phase-8-c-measurement.log"
        ),
        "review": "L2 REFUTE PASS",
    }
    assert data["coverage"] == {
        "boxes": 5,
        "nginx_log_files": 75,
        "nginx_request_lines": 374037,
        "raw_records": "private",
    }
    for private_name in ("josh-dev", "henna-dev", "jay-dev", "suri-dev", "sue-dev"):
        assert private_name not in raw

    measured = data["measurements"]
    assert measured == EXPECTED_MEASUREMENTS
    assert {key: value["disposition"] for key, value in measured.items()} == EXPECTED_DECISIONS

    # Unknown caller/Host axes stay unknown. Positive request/link/provenance
    # controls must remain positive so a fixture cannot turn missing telemetry
    # into a false zero and keep the same selected output.
    assert measured["DT-A1"]["caller_principal"] == "unknown"
    assert measured["MW-R2"]["exact_split_requests"] > 0
    assert measured["MW-S2"]["claude_links"] == 5
    assert measured["MW-S2"]["claude_alias_requests"] > 0
    assert measured["PA-N3"]["historical_spawned_sudo_failure"] is True
    assert measured["PA-N5"]["finite_container_caps"] == 4
    assert measured["PA-N5"]["unbounded_container_caps"] == 1
    assert measured["PA-N5"]["unbounded_policy"] == "explicit-cap-required"
    assert measured["PA-N6"]["largest_observed_tasks_peak"] > 0
    assert measured["PA-C2"]["incoming_host"] == "unknown"
    assert measured["PA-C2"]["policy"] == "no-widening"
    publish = measured["PB-A4"]
    assert publish["active_list_items"] == (
        publish["active_external_html_sources"]
        + publish["active_direct_html_sources"]
        + publish["active_missing_sources"]
    )
    assert publish["active_external_html_sources"] > 0
    print("ok: phase-8 measurement 5 boxes / 8 C decisions")


if __name__ == "__main__":
    main()
