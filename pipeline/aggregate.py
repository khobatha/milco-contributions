#!/usr/bin/env python3
"""
Automated aggregation for cleaned contributions data (with txn_status).

Business rule:
- Keep BOTH SUCCESS and FAIL transactions in each member’s history/report
- BUT only SUM SUCCESS transactions when computing:
  - amount_sum per period
  - total_to_date
  - admin totals_by_period, grand_total, top contributors

Input:
- outputs/clean/all_contributions_clean.csv  (must include txn_status column)

Outputs:
- outputs/aggregated/contributions_long.csv         (SUCCESS-summed per member x period)
- outputs/aggregated/contributions_wide.csv         (pivot of SUCCESS-summed amounts)
- outputs/aggregated/contributions_by_member.json   (history includes success & fail)
- outputs/aggregated/summary_stats.json             (SUCCESS totals only)

Also prints:
- sanity checks based on SUCCESS-only totals
"""

from __future__ import annotations

import json
import os
from typing import Dict, Any

import pandas as pd


INPUT_CLEAN = "outputs/clean/all_contributions_clean.csv"
OUT_DIR = "outputs/aggregated"

OUT_LONG = os.path.join(OUT_DIR, "contributions_long.csv")
OUT_WIDE = os.path.join(OUT_DIR, "contributions_wide.csv")
OUT_BY_MEMBER_JSON = os.path.join(OUT_DIR, "contributions_by_member.json")
OUT_SUMMARY_JSON = os.path.join(OUT_DIR, "summary_stats.json")


def ensure_dirs() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)


def normalize_txn_status(s: Any) -> str:
    """
    Normalize a status into SUCCESS/FAIL. Conservative default = FAIL.
    """
    if s is None:
        return "FAIL"
    t = str(s).strip().lower()
    if not t:
        return "FAIL"

    success_markers = ["success", "successful", "completed", "complete", "paid", "processed", "ok", "approved"]
    fail_markers = ["fail", "failed", "error", "rejected", "returned", "invalid", "declined", "unsuccess"]

    if any(m in t for m in fail_markers):
        return "FAIL"
    if any(m in t for m in success_markers):
        return "SUCCESS"
    return "FAIL"


def load_clean_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"member_code": str}, keep_default_na=False)

    # Normalize key columns
    df["period"] = df.get("period", "").astype(str).str.strip()
    df["member_name"] = df.get("member_name", "").astype(str).str.strip()
    df["member_code"] = df.get("member_code", "").astype(str).str.strip()

    # txn_status (ensure exists)
    if "txn_status" not in df.columns:
        # If older clean files exist without txn_status, assume SUCCESS for backward compatibility
        df["txn_status"] = "SUCCESS"
    df["txn_status"] = df["txn_status"].map(normalize_txn_status)

    # Ensure amount is numeric
    df["amount"] = pd.to_numeric(df.get("amount", None), errors="coerce")
    df = df.dropna(subset=["amount"])
    df = df[df["amount"] > 0]

    # If member_code exists, prefer it as stable ID; otherwise fallback to name
    df["member_key"] = df["member_code"].where(df["member_code"].str.len() > 0, df["member_name"])

    # Drop empties
    df = df[df["member_key"].str.len() > 0]
    df = df[df["period"].str.len() > 0]

    return df


def aggregate(df_all: pd.DataFrame) -> Dict[str, Any]:
    """
    Returns:
    - long_df: SUCCESS-only aggregated member_key, member_name, member_code, period, amount_sum
    - wide_df: pivot of SUCCESS-only long_df
    - by_member_json: nested dict keyed by member_key, history includes BOTH SUCCESS and FAIL rows
    - summary_stats_json: SUCCESS-only totals per period, top contributors, etc.
    """

    # Separate success-only for sums
    df_success = df_all[df_all["txn_status"] == "SUCCESS"].copy()

    # 1) SUCCESS Contributions by Member x Period
    long_df = (
        df_success.groupby(["member_key", "member_name", "member_code", "period"], as_index=False)["amount"]
        .sum()
        .rename(columns={"amount": "amount_sum"})
    )

    # 2) SUCCESS Total contributions per Member (all time)
    totals_df = (
        long_df.groupby(["member_key"], as_index=False)["amount_sum"]
        .sum()
        .rename(columns={"amount_sum": "total_to_date"})
    )

    # 3) Pivot (wide) – members as rows, periods as columns (SUCCESS-only)
    wide_df = (
        long_df.pivot_table(
            index=["member_key"],
            columns="period",
            values="amount_sum",
            aggfunc="sum",
            fill_value=0.0,
        )
        .reset_index()
    )

    # 4) Display maps (from ALL rows, so names/codes still appear even if only failed)
    name_map = (
        df_all.groupby(["member_key"])["member_name"]
        .agg(lambda s: s.value_counts().index[0])
        .to_dict()
    )

    code_map = (
        df_all.groupby(["member_key"])["member_code"]
        .agg(lambda s: s.value_counts().index[0] if (s.astype(str).str.len() > 0).any() else "")
        .to_dict()
    )

    totals_map = dict(zip(totals_df["member_key"], totals_df["total_to_date"]))

    # 5) Build member history INCLUDING BOTH SUCCESS and FAIL
    # We store per period a list of transactions, plus per-period success_total
    by_member: Dict[str, Any] = {}

    # Ensure chronological stability
    df_hist = df_all.sort_values(["member_key", "period"]).copy()

    for _, row in df_hist.iterrows():
        mk = row["member_key"]
        period = row["period"]
        amt = float(row["amount"])
        st = row["txn_status"]

        if mk not in by_member:
            by_member[mk] = {
                "member_key": mk,
                "member_code": code_map.get(mk, ""),
                "member_name": name_map.get(mk, mk),
                "total": float(totals_map.get(mk, 0.0)),  # SUCCESS-only total
                "history": {},  # period -> {success_total, transactions:[{amount,status}]}
            }

        if period not in by_member[mk]["history"]:
            by_member[mk]["history"][period] = {
                "success_total": 0.0,
                "transactions": []
            }

        # record the transaction
        by_member[mk]["history"][period]["transactions"].append({
            "amount": round(amt, 2),
            "txn_status": st
        })

        # increment success_total only if success
        if st == "SUCCESS":
            by_member[mk]["history"][period]["success_total"] = round(
                by_member[mk]["history"][period]["success_total"] + amt, 2
            )

    # 6) Admin summary stats (SUCCESS-only)
    totals_by_period = (
        long_df.groupby("period", as_index=False)["amount_sum"]
        .sum()
        .sort_values("period")
    )

    totals_by_period["growth_pct"] = totals_by_period["amount_sum"].pct_change() * 100

    top_contributors = (
        totals_df.sort_values("total_to_date", ascending=False)
        .head(20)
        .assign(member_name=lambda d: d["member_key"].map(name_map).fillna(d["member_key"]))
        .to_dict(orient="records")
    )

    # Count totals of success vs fail transactions (records, not sums)
    counts_by_status = (
        df_all["txn_status"].value_counts().to_dict()
    )

    summary = {
        "total_records_clean": int(len(df_all)),
        "total_records_success": int(len(df_success)),
        "total_records_fail": int(len(df_all) - len(df_success)),
        "counts_by_status": {k: int(v) for k, v in counts_by_status.items()},
        "distinct_members": int(df_all["member_key"].nunique()),
        "distinct_periods": int(df_all["period"].nunique()),

        # SUCCESS-only grand total
        "grand_total": float(df_success["amount"].sum()),

        "totals_by_period": [
            {
                "period": r["period"],
                "total": float(r["amount_sum"]),
                "growth_pct": None if pd.isna(r["growth_pct"]) else float(r["growth_pct"]),
            }
            for _, r in totals_by_period.iterrows()
        ],
        "top_contributors": top_contributors,
    }

    return {
        "long_df": long_df,
        "wide_df": wide_df,
        "by_member": by_member,
        "summary": summary,
        "df_success": df_success,   # useful for verification
    }


def verify(df_success: pd.DataFrame, long_df: pd.DataFrame) -> None:
    """
    Verification checks (SUCCESS-only):
    1) Sum of SUCCESS raw amounts equals sum of aggregated long SUCCESS amounts
    2) Period totals (SUCCESS-only) match
    """
    raw_total = float(df_success["amount"].sum())
    agg_total = float(long_df["amount_sum"].sum())

    print("---- Verification (SUCCESS-only) ----")
    print(f"Raw SUCCESS total amount:       {raw_total:,.2f}")
    print(f"Aggregated SUCCESS total amount:{agg_total:,.2f}")

    if abs(raw_total - agg_total) > 0.01:
        print("❌ WARNING: SUCCESS totals do not match! Check ingestion/cleaning or parsing.")
    else:
        print("✅ SUCCESS totals match.")

    raw_by_period = df_success.groupby("period")["amount"].sum().sort_index()
    agg_by_period = long_df.groupby("period")["amount_sum"].sum().sort_index()

    mismatches = (raw_by_period - agg_by_period).abs()
    bad = mismatches[mismatches > 0.01]
    if len(bad) > 0:
        print("❌ WARNING: Period-level SUCCESS mismatches found:")
        for period, diff in bad.items():
            print(f"  - {period}: difference={diff:,.2f}")
    else:
        print("✅ Period-level SUCCESS totals match.")


def main() -> None:
    ensure_dirs()

    if not os.path.exists(INPUT_CLEAN):
        raise SystemExit(f"Missing input file: {INPUT_CLEAN}. Run ingest_clean.py first.")

    df_all = load_clean_data(INPUT_CLEAN)
    results = aggregate(df_all)

    long_df: pd.DataFrame = results["long_df"]
    wide_df: pd.DataFrame = results["wide_df"]
    by_member: Dict[str, Any] = results["by_member"]
    summary: Dict[str, Any] = results["summary"]
    df_success: pd.DataFrame = results["df_success"]

    # Write outputs
    long_df.to_csv(OUT_LONG, index=False)
    wide_df.to_csv(OUT_WIDE, index=False)

    with open(OUT_BY_MEMBER_JSON, "w", encoding="utf-8") as f:
        json.dump(by_member, f, ensure_ascii=False, indent=2)

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Verification
    verify(df_success, long_df)

    # Quick view: Top 5 contributors
    print("\n---- Top 5 Contributors (SUCCESS totals) ----")
    top5 = summary["top_contributors"][:5]
    for i, row in enumerate(top5, start=1):
        print(f"{i}. {row.get('member_name', row['member_key'])}: {row['total_to_date']:,.2f}")

    print("\n✅ Aggregation complete.")
    print(f" - {OUT_LONG}")
    print(f" - {OUT_WIDE}")
    print(f" - {OUT_BY_MEMBER_JSON}")
    print(f" - {OUT_SUMMARY_JSON}")


if __name__ == "__main__":
    main()
