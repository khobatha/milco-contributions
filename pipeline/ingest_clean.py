#!/usr/bin/env python3
"""
Automated ingestion + cleaning for contribution CSV reports.

Supports:
1) "Column F / Column I" CSV format (member name in column F, amount in column I, period in G2)
   + Transaction status in column L -> cleaned to txn_status: SUCCESS / FAIL
   Rule: if column L == "Processed Successfully" (case-insensitive, trimmed) => SUCCESS, else FAIL
2) Bank batch export format with record types SB/SC/SD:
   - Period found as an 8-digit YYYYMMDD somewhere in first rows
   - Member name and amount found in SD rows (name field ~ index 5, amount field ~ index 8)
   - If bank export has NO status field, we mark included SD rows as SUCCESS (since they represent posted records)

Outputs:
- outputs/clean/all_contributions_clean.csv
- outputs/logs/ingest_audit.csv (dropped/invalid rows + reasons)
"""

from __future__ import annotations

import csv
import glob
import os
import re
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Tuple

import pandas as pd
from dateutil.parser import parse as dt_parse


# -----------------------------
# Configuration
# -----------------------------
DEFAULT_RAW_GLOB = "data/raw/*.csv"
OUTPUT_CLEAN_CSV = "outputs/clean/all_contributions_clean.csv"
OUTPUT_AUDIT_CSV = "outputs/logs/ingest_audit.csv"

# In "F/I/L format", F is 6th col -> index 5, I is 9th col -> index 8, L is 12th col -> index 11
FI_NAME_COL_INDEX = 5
FI_AMOUNT_COL_INDEX = 8
FI_STATUS_COL_INDEX = 11  # Column L

# Bank export "SD" row expected mapping (based on your sample files)
BANK_SD_NAME_INDEX = 5
BANK_SD_REF_INDEX = 7
BANK_SD_AMOUNT_INDEX = 8

YYYYMMDD_RE = re.compile(r"\b(20\d{6})\b")

# Exact-success marker (per your instruction)
FI_SUCCESS_TEXT = "processed successfully"


# -----------------------------
# Helpers
# -----------------------------
def ensure_dirs() -> None:
    os.makedirs(os.path.dirname(OUTPUT_CLEAN_CSV), exist_ok=True)
    os.makedirs(os.path.dirname(OUTPUT_AUDIT_CSV), exist_ok=True)


def clean_member_name(name: str) -> str:
    if name is None:
        return ""
    name = re.sub(r"\s+", " ", str(name)).strip()
    return name.title()


def clean_amount(value: Any) -> Optional[float]:
    """
    Convert to numeric amount.
    Accepts strings like "LSL 265", "265", "265.00", "2,650"
    Returns float or None if invalid.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    s = s.replace(",", "")
    s = re.sub(r"(?i)\bLSL\b", "", s)
    s = re.sub(r"[^\d.\-]", "", s).strip()

    if s in ("", "-", ".", "-.", ".-"):
        return None

    try:
        amt = float(s)
        if amt == 0:
            return None
        return amt
    except ValueError:
        return None


def normalize_txn_status_from_L(value: Any) -> str:
    """
    Column L rule (FI format only):
    - If the cell contains exactly "Processed Successfully" (case-insensitive, trimmed) => SUCCESS
    - Else => FAIL
    """
    if value is None:
        return "FAIL"
    s = str(value).strip().lower()
    if s == FI_SUCCESS_TEXT:
        return "SUCCESS"
    return "FAIL"


def normalize_txn_status_generic(value: Any) -> str:
    """
    Generic normalizer for already-present statuses (used in final cleanup if needed).
    Conservative: only 'processed successfully' => SUCCESS, else FAIL.
    """
    return normalize_txn_status_from_L(value)


def extract_period_from_cells(cells: List[str]) -> Optional[date]:
    for c in cells:
        if not c:
            continue
        m = YYYYMMDD_RE.search(str(c))
        if m:
            ymd = m.group(1)
            try:
                return datetime.strptime(ymd, "%Y%m%d").date()
            except ValueError:
                continue
    return None


def extract_period_from_file_head(path: str, max_rows: int = 10) -> Optional[date]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                d = extract_period_from_cells(row)
                if d:
                    return d
    except Exception:
        return None
    return None


def looks_like_bank_export(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i > 30:
                    break
                if row and row[0].strip() in ("SB", "SC", "SD"):
                    if row[0].strip() == "SD":
                        return True
    except Exception:
        return False
    return False


@dataclass
class AuditIssue:
    source_file: str
    reason: str
    raw_name: str = ""
    raw_amount: str = ""
    raw_status: str = ""
    row_type: str = ""
    row_num: int = -1


# -----------------------------
# Parsers
# -----------------------------
def parse_bank_export(path: str) -> Tuple[pd.DataFrame, List[AuditIssue]]:
    """
    Parse bank export CSV with SB/SC/SD record types.
    We only extract contributions from SD rows.

    Note: bank export format typically doesn't carry the same "Processed Successfully" column.
    For included SD rows we mark txn_status=SUCCESS (posted records).
    """
    issues: List[AuditIssue] = []
    records: List[Dict[str, Any]] = []

    period = extract_period_from_file_head(path)
    if period is None:
        issues.append(AuditIssue(source_file=path, reason="Could not extract period/date from header"))

    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        for row_num, row in enumerate(reader, start=1):
            if not row:
                continue

            row_type = row[0].strip() if row else ""
            if row_type != "SD":
                continue

            raw_name = row[BANK_SD_NAME_INDEX].strip() if len(row) > BANK_SD_NAME_INDEX else ""
            raw_ref = row[BANK_SD_REF_INDEX].strip() if len(row) > BANK_SD_REF_INDEX else ""
            raw_amount = row[BANK_SD_AMOUNT_INDEX].strip() if len(row) > BANK_SD_AMOUNT_INDEX else ""

            name = clean_member_name(raw_name)
            amt = clean_amount(raw_amount)

            if not name:
                issues.append(AuditIssue(
                    source_file=path, row_num=row_num, row_type=row_type,
                    reason="Missing/empty member name", raw_name=raw_name, raw_amount=raw_amount
                ))
                continue

            if amt is None:
                issues.append(AuditIssue(
                    source_file=path, row_num=row_num, row_type=row_type,
                    reason="Invalid amount", raw_name=raw_name, raw_amount=raw_amount
                ))
                continue

            member_code = ""
            m = re.search(r"\b(M0*\d+)\b", raw_ref, flags=re.IGNORECASE)
            if m:
                member_code = m.group(1).upper()

            records.append({
                "period": period.isoformat() if period else "",
                "member_name": name,
                "member_code": member_code,
                "amount": amt,
                "txn_status": "SUCCESS",  # bank SD rows treated as posted/success
                "source_file": os.path.basename(path),
                "source_format": "bank_export_sd"
            })

    df = pd.DataFrame.from_records(records)
    return df, issues


def parse_fi_format(path: str) -> Tuple[pd.DataFrame, List[AuditIssue]]:
    """
    Parse a CSV where:
    - member name is in column F (index 5)
    - amount is in column I (index 8)
    - txn status is in column L (index 11) -> SUCCESS only if exactly "Processed Successfully"
    - period is in cell G2 (row 2, column G -> index 6)
    """
    issues: List[AuditIssue] = []
    records: List[Dict[str, Any]] = []

    try:
        raw = pd.read_csv(path, header=None, dtype=str, engine="python")
    except Exception as e:
        issues.append(AuditIssue(source_file=path, reason=f"Could not read CSV: {e}"))
        return pd.DataFrame(), issues

    # period from G2
    period = None
    try:
        g2 = raw.iat[1, 6]
        if pd.notna(g2):
            m = YYYYMMDD_RE.search(str(g2))
            if m:
                period = datetime.strptime(m.group(1), "%Y%m%d").date()
            else:
                period = dt_parse(str(g2), dayfirst=False).date()
    except Exception:
        pass

    if period is None:
        period = extract_period_from_file_head(path)

    if period is None:
        issues.append(AuditIssue(source_file=path, reason="Could not extract period/date (G2/head scan)"))

    for r in range(len(raw)):
        raw_name = raw.iat[r, FI_NAME_COL_INDEX] if raw.shape[1] > FI_NAME_COL_INDEX else None
        raw_amt = raw.iat[r, FI_AMOUNT_COL_INDEX] if raw.shape[1] > FI_AMOUNT_COL_INDEX else None
        raw_status = raw.iat[r, FI_STATUS_COL_INDEX] if raw.shape[1] > FI_STATUS_COL_INDEX else None

        name = clean_member_name(raw_name) if raw_name is not None else ""
        amt = clean_amount(raw_amt)

        # IMPORTANT: do not default to success. Use column L rule.
        txn_status = normalize_txn_status_from_L(raw_status)

        # skip empty rows
        if (
            not name
            and (raw_amt is None or str(raw_amt).strip() == "")
            and (raw_status is None or str(raw_status).strip() == "")
        ):
            continue

        # drop header/metadata rows and invalid amounts
        if not name or amt is None:
            issues.append(AuditIssue(
                source_file=path, row_num=r + 1, row_type="FI",
                reason="Row skipped (missing name or invalid amount)",
                raw_name=str(raw_name) if raw_name is not None else "",
                raw_amount=str(raw_amt) if raw_amt is not None else "",
                raw_status=str(raw_status) if raw_status is not None else "",
            ))
            continue

        records.append({
            "period": period.isoformat() if period else "",
            "member_name": name,
            "member_code": "",  # unknown in FI format unless you add extraction logic
            "amount": amt,
            "txn_status": txn_status,  # SUCCESS only if "Processed Successfully"
            "source_file": os.path.basename(path),
            "source_format": "fi_columns"
        })

    df = pd.DataFrame.from_records(records)
    return df, issues


# -----------------------------
# Main pipeline
# -----------------------------
def ingest_all(input_glob: str = DEFAULT_RAW_GLOB) -> None:
    ensure_dirs()

    all_files = sorted(glob.glob(input_glob))
    if not all_files:
        raise SystemExit(f"No CSV files found matching: {input_glob}")

    all_dfs: List[pd.DataFrame] = []
    all_issues: List[AuditIssue] = []

    for path in all_files:
        if looks_like_bank_export(path):
            df, issues = parse_bank_export(path)
        else:
            df, issues = parse_fi_format(path)

        all_dfs.append(df)
        all_issues.extend(issues)

    combined = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()

    if not combined.empty:
        combined["member_name"] = combined["member_name"].fillna("").map(clean_member_name)

        # Ensure txn_status exists; if missing/blank, treat as FAIL (do NOT default to SUCCESS)
        if "txn_status" not in combined.columns:
            combined["txn_status"] = "FAIL"
        combined["txn_status"] = combined["txn_status"].fillna("").map(normalize_txn_status_generic)

        combined["amount"] = pd.to_numeric(combined["amount"], errors="coerce")
        combined = combined.dropna(subset=["amount"])
        combined = combined[combined["member_name"].str.len() > 0]
        combined = combined[combined["amount"] > 0]

        combined = combined.sort_values(["period", "member_name"], ascending=[True, True])

    combined.to_csv(OUTPUT_CLEAN_CSV, index=False)

    audit_df = pd.DataFrame([{
        "source_file": i.source_file,
        "row_num": i.row_num,
        "row_type": i.row_type,
        "reason": i.reason,
        "raw_name": i.raw_name,
        "raw_amount": i.raw_amount,
        "raw_status": i.raw_status,
    } for i in all_issues])
    audit_df.to_csv(OUTPUT_AUDIT_CSV, index=False)

    print(f"✅ Clean output:  {OUTPUT_CLEAN_CSV}  ({len(combined)} rows)")
    print(f"⚠️  Audit output: {OUTPUT_AUDIT_CSV}  ({len(audit_df)} issues)")
    print(f"📦 Processed files: {len(all_files)}")


if __name__ == "__main__":
    ingest_all()
