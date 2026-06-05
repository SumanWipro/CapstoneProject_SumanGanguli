"""
utils/audit.py
==============
Audit record writer for the Loan Approval System.

Responsibilities:
- Write structured JSON audit records to audit/logs/
- One file per day (YYYY-MM-DD.jsonl) in JSON Lines format
- Called exclusively by the Compliance Agent

Design decision: JSON Lines (one JSON object per line) is chosen because
audit files can be streamed, appended atomically, and parsed line-by-line
without loading the entire file into memory. The Observability Dashboard
reads these files directly.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import get_settings
from utils.logger import get_logger

log = get_logger(__name__, component="audit")


# ---------------------------------------------------------------------------
# Public writer
# ---------------------------------------------------------------------------

def write_audit_record(record: dict[str, Any]) -> Path:
    """
    Append a structured audit record to today's JSON Lines audit file.

    The record is augmented with a server-side UTC timestamp before writing.
    The audit directory is created automatically if it does not exist.

    Args:
        record: Dictionary containing all audit fields (case_id, verdict,
                applicant_id, confidence_score, explanation, etc.)

    Returns:
        Path to the audit file that was written to.

    Raises:
        OSError: If the audit directory cannot be created or the file
                 cannot be written.

    Usage:
        from utils.audit import write_audit_record
        write_audit_record({
            "case_id": "CASE-20240101-001",
            "applicant_id": "APP-001",
            "verdict": "APPROVED",
            "confidence_score": 0.87,
            "explanation": "...",
        })
    """
    settings = get_settings()
    audit_dir = Path(settings.audit_log_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    audit_file = audit_dir / f"{today}.jsonl"

    enriched = {
        "server_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        **record,
    }

    with open(audit_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(enriched) + "\n")

    log.info(
        "audit_record_written",
        case_id=record.get("case_id"),
        audit_file=str(audit_file),
    )

    return audit_file


def read_audit_records(date_str: str | None = None) -> list[dict[str, Any]]:
    """
    Read all audit records for a given date (default: today).

    Args:
        date_str: Date in YYYY-MM-DD format. Defaults to today (UTC).

    Returns:
        List of audit record dicts, ordered by write time (oldest first).
        Returns empty list if no file exists for the given date.

    Usage:
        from utils.audit import read_audit_records
        records = read_audit_records("2024-01-01")
    """
    settings = get_settings()
    audit_dir = Path(settings.audit_log_dir)

    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    audit_file = audit_dir / f"{date_str}.jsonl"

    if not audit_file.exists():
        return []

    records: list[dict[str, Any]] = []
    with open(audit_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
