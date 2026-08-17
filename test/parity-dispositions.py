#!/usr/bin/env python3
"""Check that every parity-matrix ID has one pinned cluster disposition."""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TRIAGE = ROOT / "census" / "parity-decision-triage.md"
DISPOSITIONS = ROOT / "docs" / "parity" / "dispositions.md"
MATRIX = ROOT / "census" / "parity-matrix.md"
EXPECTED_BUCKETS = Counter({"A": 18, "B": 13, "C": 8, "D": 3, "E": 66})
EXPECTED_DISPOSITIONS = Counter({"keep": 63, "migrate": 39, "retire": 3, "hold": 3})
EXPECTED_CLUSTER_COUNT = 108
EXPECTED_ID_COUNT = 134
EXPECTED_STATUS = "Status: 105 executable clusters decided; 3 clusters deliberately held"
EXPECTED_TRIAGE_SHA256 = "6b3499bd292f02d25dff0562ddada6a3fe13689dc46aac043a6dafa8c249e625"
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
    ("DT-A1",): "keep",
    ("MW-R2",): "migrate",
    ("MW-S2",): "migrate",
    ("PA-N3",): "migrate",
    ("PA-N5",): "keep",
    ("PA-N6",): "keep",
    ("PA-C2",): "keep",
    ("PB-A4",): "keep",
    ("DT-R1",): "hold",
    ("OR-C4",): "hold",
    ("OR-S4",): "hold",
    ("DT-R2",): "migrate",
    ("DT-A2",): "migrate",
    ("DT-N2",): "keep",
    ("DT-N3",): "keep",
    ("DT-C1", "DT-C3"): "keep",
    ("DT-S1",): "keep",
    ("DT-S2",): "migrate",
    ("DM-R1", "DM-A2", "DM-U3", "DM-N1", "DM-C1", "DM-S2"): "keep",
    ("DM-A1", "DM-U4", "DM-S3"): "keep",
    ("DM-U1",): "migrate",
    ("DM-N2",): "keep",
    ("DM-S1",): "keep",
    ("DM-S4",): "keep",
    ("DM-S5",): "migrate",
    ("CS-A1", "CS-U1", "CS-C1"): "keep",
    ("CS-N1",): "keep",
    ("CS-N2",): "keep",
    ("CS-N3",): "keep",
    ("CS-C2",): "keep",
    ("CS-C3",): "keep",
    ("CS-S1", "CS-S2"): "migrate",
    ("FB-R1", "FB-A1", "FB-A2", "FB-A3", "FB-N1", "FB-C1", "FB-C2"): "keep",
    ("MW-R1",): "migrate",
    ("MW-R3",): "keep",
    ("MW-U2",): "keep",
    ("MW-N1",): "keep",
    ("MW-N2",): "migrate",
    ("MW-N3",): "keep",
    ("MW-C2",): "keep",
    ("MW-S3",): "migrate",
    ("NP-R1",): "migrate",
    ("NP-A1",): "keep",
    ("NP-U3",): "keep",
    ("NP-N1", "NP-C1"): "keep",
    ("OR-N1",): "keep",
    ("OR-N2",): "keep",
    ("OR-N3", "OR-S2"): "migrate",
    ("OR-N4",): "migrate",
    ("OR-C1",): "keep",
    ("OR-C2",): "keep",
    ("OR-S1",): "keep",
    ("OR-S3",): "migrate",
    ("PA-R2",): "migrate",
    ("PA-N1",): "keep",
    ("PA-N2",): "keep",
    ("PA-N4",): "migrate",
    ("PA-N7",): "migrate",
    ("PA-N8",): "keep",
    ("PA-N9",): "keep",
    ("PA-C4",): "keep",
    ("PA-C5", "PA-C6"): "keep",
    ("PA-C7",): "retire",
    ("PA-S1",): "keep",
    ("PA-S2",): "keep",
    ("PA-S3",): "migrate",
    ("PB-A1",): "migrate",
    ("PB-A8", "PB-U8"): "keep",
    ("PB-U1",): "keep",
    ("PB-U2",): "migrate",
    ("PB-U3",): "keep",
    ("PB-U7",): "migrate",
    ("PB-U9",): "migrate",
    ("PB-N1",): "keep",
    ("PB-N2",): "keep",
    ("PB-C1",): "keep",
    ("PB-S1",): "keep",
}
EXPECTED_CLUSTER_DISPOSITIONS = {
    tuple(sorted(key)): value for key, value in EXPECTED_CLUSTER_DISPOSITIONS.items()
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
            in_table = False
            continue
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
        elif line.startswith("## C "):
            section = "C"
        elif line.startswith("## E "):
            section = "E"
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


def matrix_ids() -> list[str]:
    result = []
    for line in MATRIX.read_text().splitlines():
        if line.startswith("|"):
            first = cells(line)[0]
            if re.fullmatch(r"[A-Z]{2}-[A-Z]\d+", first):
                result.append(first)
    return result


def triage_digest(triage: dict[tuple[str, ...], tuple[str, str]]) -> str:
    canonical = "\n".join(
        f"{','.join(key)}\t{cluster}\t{bucket}"
        for key, (cluster, bucket) in sorted(triage.items())
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def main() -> None:
    subprocess.run(
        [sys.executable, ROOT / "test" / "parity-c-measurement.py"], check=True
    )
    triage = read_triage()
    dispositions = read_dispositions()
    if triage.keys() != dispositions.keys():
        missing = sorted(triage.keys() - dispositions.keys())
        extra = sorted(dispositions.keys() - triage.keys())
        raise SystemExit(f"disposition coverage mismatch: missing={missing} extra={extra}")

    actual_triage_sha256 = triage_digest(triage)
    if actual_triage_sha256 != EXPECTED_TRIAGE_SHA256:
        raise SystemExit(
            "triage mapping drift: "
            f"{actual_triage_sha256} != {EXPECTED_TRIAGE_SHA256}"
        )

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

    matrix_rows = matrix_ids()
    matrix_counts = Counter(matrix_rows)
    duplicate_matrix_ids = sorted(
        matrix_id for matrix_id, count in matrix_counts.items() if count != 1
    )
    if duplicate_matrix_ids:
        raise SystemExit(f"matrix IDs must be unique: {duplicate_matrix_ids}")
    known_matrix_ids = set(matrix_rows)
    used_ids = Counter(matrix_id for key in triage for matrix_id in key)
    reused_ids = sorted(matrix_id for matrix_id, count in used_ids.items() if count != 1)
    if reused_ids:
        raise SystemExit(f"matrix IDs must appear in exactly one cluster: {reused_ids}")
    if set(used_ids) != known_matrix_ids:
        missing = sorted(known_matrix_ids - set(used_ids))
        extra = sorted(set(used_ids) - known_matrix_ids)
        raise SystemExit(f"matrix coverage mismatch: missing={missing} extra={extra}")
    for key, (triage_cluster, triage_bucket) in triage.items():
        cluster, bucket, disposition = dispositions[key]
        if cluster != triage_cluster:
            raise SystemExit(f"cluster drift for {key}: {cluster!r} != {triage_cluster!r}")
        if bucket != triage_bucket:
            raise SystemExit(f"bucket drift for {key}: {bucket} != {triage_bucket}")
        allowed = {"hold"} if bucket == "D" else {"keep", "migrate", "retire"}
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
    print("buckets:", " ".join(f"{key}={bucket_counts[key]}" for key in "ABCDE"))
    print(
        "dispositions:",
        " ".join(
            f"{key}={disposition_counts[key]}"
            for key in ("keep", "migrate", "retire", "hold")
        ),
    )


if __name__ == "__main__":
    main()
