#!/usr/bin/env python3
"""Check that the bounded parity triage has one disposition per cluster."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "census" / "parity-decision-triage.md"
DISPOSITIONS = ROOT / "docs" / "parity" / "dispositions.md"
MATRIX = ROOT / "census" / "parity-matrix.md"
EXPECTED_BUCKETS = Counter({"A": 18, "B": 13, "C": 8, "D": 3})
EXPECTED_DISPOSITIONS = Counter({"keep": 14, "migrate": 15, "retire": 2, "hold": 11})
EXPECTED_CLUSTER_COUNT = 42
EXPECTED_ID_COUNT = 47
EXPECTED_STATUS = "Status: 31 executable clusters decided; 11 clusters deliberately held"
EXPECTED_CLUSTER_DISPOSITIONS = {
    ("DT-C4",): "migrate",
    ("DT-U2",): "keep",
    ("DM-R2", "DM-U2"): "migrate",
    ("DM-N3",): "keep",
    ("DM-C2",): "migrate",
    ("DM-C3",): "keep",
    ("MW-U1",): "migrate",
    ("MW-S1",): "migrate",
    ("NP-U1",): "migrate",
    ("NP-S1",): "keep",
    ("OR-C3",): "migrate",
    ("PA-C1", "PA-R1"): "keep",
    ("PA-U1",): "keep",
    ("PA-C3",): "migrate",
    ("PB-R1",): "migrate",
    ("PB-A2", "PB-C2", "PB-R2", "PB-U6"): "migrate",
    ("PB-A3",): "migrate",
    ("PB-A5",): "migrate",
    ("DT-N1",): "keep",
    ("DT-C2",): "keep",
    ("CS-C4",): "retire",
    ("MW-C1",): "keep",
    ("MW-C3",): "retire",
    ("NP-U2",): "keep",
    ("NP-U4",): "keep",
    ("PB-A6",): "migrate",
    ("PB-A7",): "migrate",
    ("PB-U4",): "keep",
    ("PB-U5",): "keep",
    ("PB-S2",): "migrate",
    ("PB-S3",): "keep",
    ("DT-A1",): "hold",
    ("MW-R2",): "hold",
    ("MW-S2",): "hold",
    ("PA-N3",): "hold",
    ("PA-N5",): "hold",
    ("PA-N6",): "hold",
    ("PA-C2",): "hold",
    ("PB-A4",): "hold",
    ("DT-R1",): "hold",
    ("OR-C4",): "hold",
    ("OR-S4",): "hold",
}


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def id_key(value: str) -> tuple[str, ...]:
    return tuple(sorted(part.strip() for part in value.split(",") if part.strip()))


def read_triage() -> dict[tuple[str, ...], tuple[str, str]]:
    result: dict[tuple[str, ...], tuple[str, str]] = {}
    in_table = False
    for line in TRIAGE.read_text().splitlines():
        if line.startswith("| Cluster | Related matrix IDs | Bucket |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            break
        row = cells(line)
        key = id_key(row[1])
        if key in result:
            raise SystemExit(f"duplicate triage IDs: {key}")
        result[key] = (row[0], row[2])
    return result


def read_dispositions() -> dict[tuple[str, ...], tuple[str, str, str]]:
    result: dict[tuple[str, ...], tuple[str, str, str]] = {}
    section = ""
    table_kind = ""
    for line in DISPOSITIONS.read_text().splitlines():
        if line.startswith("## A "):
            section = "A"
        elif line.startswith("## B "):
            section = "B"
        elif line.startswith("## Held "):
            section = "held"

        if line.startswith("| Cluster | Matrix IDs | Disposition |"):
            table_kind = "decision"
            continue
        if line.startswith("| Bucket | Cluster | Matrix IDs | Disposition |"):
            table_kind = "held"
            continue
        if line.startswith("|---"):
            continue
        if not line.startswith("|"):
            table_kind = ""
            continue

        row = cells(line)
        if table_kind == "decision":
            bucket, cluster, ids, disposition = section, row[0], row[1], row[2]
        elif table_kind == "held":
            bucket, cluster, ids, disposition = row[0], row[1], row[2], row[3]
        else:
            continue

        key = id_key(ids)
        if key in result:
            raise SystemExit(f"duplicate disposition IDs: {key}")
        result[key] = (cluster, bucket, disposition)
    return result


def matrix_ids() -> set[str]:
    result = set()
    for line in MATRIX.read_text().splitlines():
        if line.startswith("|"):
            first = cells(line)[0]
            if re.fullmatch(r"[A-Z]{2}-[A-Z]\d+", first):
                result.add(first)
    return result


def main() -> None:
    triage = read_triage()
    dispositions = read_dispositions()
    if triage.keys() != dispositions.keys():
        missing = sorted(triage.keys() - dispositions.keys())
        extra = sorted(dispositions.keys() - triage.keys())
        raise SystemExit(f"disposition coverage mismatch: missing={missing} extra={extra}")

    actual_cluster_dispositions = {
        key: disposition for key, (_, _, disposition) in dispositions.items()
    }
    if actual_cluster_dispositions != EXPECTED_CLUSTER_DISPOSITIONS:
        drift = {
            key: (EXPECTED_CLUSTER_DISPOSITIONS.get(key), actual_cluster_dispositions.get(key))
            for key in sorted(
                EXPECTED_CLUSTER_DISPOSITIONS.keys() | actual_cluster_dispositions.keys()
            )
            if EXPECTED_CLUSTER_DISPOSITIONS.get(key) != actual_cluster_dispositions.get(key)
        }
        raise SystemExit(f"cluster disposition drift: {drift}")

    known_matrix_ids = matrix_ids()
    used_ids = Counter(matrix_id for key in triage for matrix_id in key)
    reused_ids = sorted(matrix_id for matrix_id, count in used_ids.items() if count != 1)
    if reused_ids:
        raise SystemExit(f"matrix IDs must appear in exactly one cluster: {reused_ids}")
    for key, (triage_cluster, triage_bucket) in triage.items():
        cluster, bucket, disposition = dispositions[key]
        if cluster != triage_cluster:
            raise SystemExit(f"cluster drift for {key}: {cluster!r} != {triage_cluster!r}")
        if bucket != triage_bucket:
            raise SystemExit(f"bucket drift for {key}: {bucket} != {triage_bucket}")
        allowed = {"keep", "migrate", "retire", "hold"} if bucket == "A" else {"keep", "migrate", "retire"}
        if bucket in {"C", "D"}:
            allowed = {"hold"}
        if disposition not in allowed:
            raise SystemExit(f"invalid disposition for {key}: {bucket}/{disposition}")
        unknown = set(key) - known_matrix_ids
        if unknown:
            raise SystemExit(f"unknown matrix IDs in {key}: {sorted(unknown)}")

    bucket_counts = Counter(bucket for _, bucket in triage.values())
    disposition_counts = Counter(value[2] for value in dispositions.values())
    status = DISPOSITIONS.read_text().splitlines()[2]
    if len(triage) != EXPECTED_CLUSTER_COUNT or sum(len(key) for key in triage) != EXPECTED_ID_COUNT:
        raise SystemExit(
            f"triage cardinality drift: clusters={len(triage)} IDs={sum(len(key) for key in triage)}"
        )
    if bucket_counts != EXPECTED_BUCKETS:
        raise SystemExit(f"triage bucket drift: {bucket_counts} != {EXPECTED_BUCKETS}")
    if disposition_counts != EXPECTED_DISPOSITIONS:
        raise SystemExit(
            f"disposition count drift: {disposition_counts} != {EXPECTED_DISPOSITIONS}"
        )
    if status != EXPECTED_STATUS:
        raise SystemExit(f"status drift: {status!r} != {EXPECTED_STATUS!r}")
    print(f"ok: {len(triage)} clusters / {sum(len(key) for key in triage)} matrix IDs")
    print("buckets:", " ".join(f"{key}={bucket_counts[key]}" for key in "ABCD"))
    print(
        "dispositions:",
        " ".join(
            f"{key}={disposition_counts[key]}"
            for key in ("keep", "migrate", "retire", "hold")
        ),
    )


if __name__ == "__main__":
    main()
