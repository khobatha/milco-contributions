#!/usr/bin/env python3
"""
Automated ingestion + cleaning for contribution CSV reports.

Supports:
1) "Column F / Column I" CSV format (member name in column F, amount in column I, period in G2)
2) Bank batch export format with record types SB/SC/SD:
   - Period found as an 8-digit YYYYMMDD somewhere in first rows
   - Member name and amount found in SD rows (name field ~ index 5, amount field ~ index 8)

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

# In "F/I format", F is 6th col -> index 5, I is 9th col -> index 8
FI_NAME_COL_INDEX = 5
FI_AMOUNT_COL_INDEX = 8

# Bank export "SD" row expected mapping (based on your sample files)
BANK_SD_NAME_INDEX = 5
BANK_SD_REF_INDEX = 7
BANK_SD_AMOUNT_INDEX = 8

YYYYMMDD_RE = re.compile(r"\b(20\d{6})\b")


# -----------------------------
# Helpers
# -----------------------------
def ensure_dirs() -> None:
    os.makedirs(os.path.dirname(OUTPUT_CLEAN_CSV), exist_ok=True)
    os.makedirs(os.path.dirname(OUTPUT_AUDIT_CSV), exist_ok=True)


def clean_member_name(name: str) -> str:
    if name is None:
        return ""
    # normalize whitespace
    name = re.sub(r"\s+", " ", str(name)).strip()
    # title case (safe for most names)
    name = name.title()
    return name


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
    # remove currency codes and symbols, commas, spaces
    s = s.replace(",", "")
    s = re.sub(r"(?i)\bLSL\b", "", s)
    s = re.sub(r"[^\d.\-]", "", s).strip()
    if s in ("", "-", ".", "-.", ".-"):
        return None
    try:
        amt = float(s)
        # reject obviously invalid values
        if amt == 0:
            # depending on your business rules, you may allow zero; here we treat as invalid
            return None
        return amt
    except ValueError:
        return None


def extract_period_from_cells(cells: List[str]) -> Optional[date]:
    """
    Find first 8-digit YYYYMMDD in a list of cell strings.
    """
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
    """
    Read first rows of CSV and try to locate a YYYYMMDD date anywhere.
    Works for bank export and many other “header style” CSVs.
    """
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
    """
    Detect if file contains SD record lines typical of bank export.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i > 30:
                    break
                if row and row[0].strip() in ("SB", "SC", "SD"):
                    # more confidence if we see SD early
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
    row_type: str = ""
    row_num: int = -1


# -----------------------------
# Parsers
# -----------------------------
def parse_bank_export(path: str) -> Tuple[pd.DataFrame, List[AuditIssue]]:
    """
    Parse bank export CSV with SB/SC/SD record types.
    We only extract contributions from SD rows.
    """
    issues: List[AuditIssue] = []
    records: List[Dict[str, Any]] = []

    period = extract_period_from_file_head(path)  # usually found in top rows
    if period is None:
        issues.append(AuditIssue(source_file=path, reason="Could not extract period/date from header"))
        # We'll still parse; period will be blank

    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.reader(f)
        for row_num, row in enumerate(reader, start=1):
            if not row:
                continue

            row_type = row[0].strip() if row else ""
            if row_type != "SD":
                continue

            # defensive indexing
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

            # Optional: extract member code like M120 from "M120 Milco Shares"
            member_code = ""
            m = re.search(r"\b(M0*\d+)\b", raw_ref, flags=re.IGNORECASE)
            if m:
                member_code = m.group(1).upper()

            records.append({
                "period": period.isoformat() if period else "",
                "member_name": name,
                "member_code": member_code,
                "amount": amt,
                "source_file": os.path.basename(path),
                "source_format": "bank_export_sd"
            })

    df = pd.DataFrame.from_records(records)
    return df, issues


def parse_fi_format(path: str) -> Tuple[pd.DataFrame, List[AuditIssue]]:
    """
    Parse a generic CSV where:
    - member name is in column F (index 5)
    - amount is in column I (index 8)
    - period is in cell G2 (row 2, column G -> index 6)
    Because CSV exports vary, this parser tries a best-effort approach:
    - loads all rows with pandas (no header)
    - reads period from row 1, col 6 if available
    - extracts name/amount from each subsequent row where both exist
    """
    issues: List[AuditIssue] = []
    records: List[Dict[str, Any]] = []

    # read without header; keep everything as string
    try:
        raw = pd.read_csv(path, header=None, dtype=str, engine="python")
    except Exception as e:
        issues.append(AuditIssue(source_file=path, reason=f"Could not read CSV: {e}"))
        return pd.DataFrame(), issues

    # period from G2 (row index 1, col index 6)
    period = None
    try:
        g2 = raw.iat[1, 6]  # row 2 col G
        if pd.notna(g2):
            # try YYYYMMDD first, else dateutil parse
            m = YYYYMMDD_RE.search(str(g2))
            if m:
                period = datetime.strptime(m.group(1), "%Y%m%d").date()
            else:
                period = dt_parse(str(g2), dayfirst=False).date()
    except Exception:
        pass

    if period is None:
        # fall back to scanning head
        period = extract_period_from_file_head(path)

    if period is None:
        issues.append(AuditIssue(source_file=path, reason="Could not extract period/date (G2/head scan)"))

    # now iterate rows and pick out name/amount
    for r in range(len(raw)):
        raw_name = raw.iat[r, FI_NAME_COL_INDEX] if raw.shape[1] > FI_NAME_COL_INDEX else None
        raw_amt = raw.iat[r, FI_AMOUNT_COL_INDEX] if raw.shape[1] > FI_AMOUNT_COL_INDEX else None

        name = clean_member_name(raw_name) if raw_name is not None else ""
        amt = clean_amount(raw_amt)

        # skip empty rows
        if not name and (raw_amt is None or str(raw_amt).strip() == ""):
            continue

        # drop likely header/metadata rows
        # (if amount can't be parsed, treat as not a contribution line)
        if not name or amt is None:
            issues.append(AuditIssue(
                source_file=path, row_num=r+1, row_type="FI",
                reason="Row skipped (missing name or invalid amount)",
                raw_name=str(raw_name) if raw_name is not None else "",
                raw_amount=str(raw_amt) if raw_amt is not None else ""
            ))
            continue

        records.append({
            "period": period.isoformat() if period else "",
            "member_name": name,
            "member_code": "",  # unknown in FI format unless you add logic
            "amount": amt,
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

    # Final cleanup: drop obvious empties and enforce types
    if not combined.empty:
        combined["member_name"] = combined["member_name"].fillna("").map(clean_member_name)
        combined["amount"] = pd.to_numeric(combined["amount"], errors="coerce")
        combined = combined.dropna(subset=["amount"])
        combined = combined[combined["member_name"].str.len() > 0]
        # Optional: remove negative amounts unless you expect refunds
        combined = combined[combined["amount"] > 0]

        # sort for easier auditing
        combined = combined.sort_values(["period", "member_name"], ascending=[True, True])

    # Write outputs
    combined.to_csv(OUTPUT_CLEAN_CSV, index=False)

    audit_df = pd.DataFrame([{
        "source_file": i.source_file,
        "row_num": i.row_num,
        "row_type": i.row_type,
        "reason": i.reason,
        "raw_name": i.raw_name,
        "raw_amount": i.raw_amount
    } for i in all_issues])
    audit_df.to_csv(OUTPUT_AUDIT_CSV, index=False)

    print(f"✅ Clean output:  {OUTPUT_CLEAN_CSV}  ({len(combined)} rows)")
    print(f"⚠️  Audit output: {OUTPUT_AUDIT_CSV}  ({len(audit_df)} issues)")
    print(f"📦 Processed files: {len(all_files)}")


if __name__ == "__main__":
    ingest_all()
