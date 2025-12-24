#!/usr/bin/env python3
"""
Automated aggregation for cleaned contributions data.

Input:
- outputs/clean/all_contributions_clean.csv

Outputs:
- outputs/aggregated/contributions_long.csv
- outputs/aggregated/contributions_wide.csv
- outputs/aggregated/contributions_by_member.json
- outputs/aggregated/summary_stats.json

Also prints:
- sanity checks
- top contributors
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


def load_clean_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"member_code": str}, keep_default_na=False)

    # Normalize key columns
    df["period"] = df["period"].astype(str).str.strip()
    df["member_name"] = df["member_name"].astype(str).str.strip()
    df["member_code"] = df.get("member_code", "").astype(str).str.strip()

    # Ensure amount is numeric
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df.dropna(subset=["amount"])
    df = df[df["amount"] > 0]

    # If member_code exists, prefer it as stable ID; otherwise fallback to name
    df["member_key"] = df["member_code"].where(df["member_code"].str.len() > 0, df["member_name"])

    # drop empties
    df = df[df["member_key"].str.len() > 0]
    df = df[df["period"].str.len() > 0]

    return df


def aggregate(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Returns:
    - long_df: member_key, member_name, member_code, period, amount_sum
    - wide_df: pivot of long_df
    - by_member_json: nested dict keyed by member_key
    - summary_stats_json: totals per period, top contributors, etc.
    """

    # 1) Contributions by Member x Period
    long_df = (
        df.groupby(["member_key", "member_name", "member_code", "period"], as_index=False)["amount"]
          .sum()
          .rename(columns={"amount": "amount_sum"})
    )

    # 2) Total contributions per Member (all time)
    totals_df = (
        long_df.groupby(["member_key"], as_index=False)["amount_sum"]
              .sum()
              .rename(columns={"amount_sum": "total_to_date"})
    )

    # 3) Pivot (wide) – members as rows, periods as columns
    wide_df = (
        long_df.pivot_table(
            index=["member_key"],
            columns="period",
            values="amount_sum",
            aggfunc="sum",
            fill_value=0.0
        )
        .reset_index()
    )

    # 4) Build nested JSON for the portal (member_key -> {display_name, total, history{period:amt}})
    # Choose the most frequent (or latest) member_name for display (helps if minor name variance)
    name_map = (
        df.groupby(["member_key"])["member_name"]
          .agg(lambda s: s.value_counts().index[0])
          .to_dict()
    )

    code_map = (
        df.groupby(["member_key"])["member_code"]
          .agg(lambda s: s.value_counts().index[0] if (s.astype(str).str.len() > 0).any() else "")
          .to_dict()
    )

    totals_map = dict(zip(totals_df["member_key"], totals_df["total_to_date"]))

    by_member: Dict[str, Any] = {}
    for _, row in long_df.iterrows():
        mk = row["member_key"]
        period = row["period"]
        amt = float(row["amount_sum"])

        if mk not in by_member:
            by_member[mk] = {
                "member_key": mk,
                "member_code": code_map.get(mk, ""),
                "member_name": name_map.get(mk, mk),
                "total": float(totals_map.get(mk, 0.0)),
                "history": {}
            }

        by_member[mk]["history"][period] = round(amt, 2)

    # 5) Admin summary stats
    totals_by_period = (
        long_df.groupby("period", as_index=False)["amount_sum"]
              .sum()
              .sort_values("period")
    )

    # period-to-period growth %
    totals_by_period["growth_pct"] = totals_by_period["amount_sum"].pct_change() * 100

    top_contributors = (
        totals_df.sort_values("total_to_date", ascending=False)
                 .head(20)
                 .assign(
                     member_name=lambda d: d["member_key"].map(name_map).fillna(d["member_key"])
                 )
                 .to_dict(orient="records")
    )

    summary = {
        "total_records_clean": int(len(df)),
        "distinct_members": int(df["member_key"].nunique()),
        "distinct_periods": int(df["period"].nunique()),
        "grand_total": float(df["amount"].sum()),
        "totals_by_period": [
            {
                "period": r["period"],
                "total": float(r["amount_sum"]),
                "growth_pct": None if pd.isna(r["growth_pct"]) else float(r["growth_pct"])
            }
            for _, r in totals_by_period.iterrows()
        ],
        "top_contributors": top_contributors
    }

    return {
        "long_df": long_df,
        "wide_df": wide_df,
        "by_member": by_member,
        "summary": summary
    }


def verify(df: pd.DataFrame, long_df: pd.DataFrame) -> None:
    """
    Verification checks:
    1) Sum of raw amounts equals sum of aggregated long amounts
    2) Totals per period check
    """
    raw_total = float(df["amount"].sum())
    agg_total = float(long_df["amount_sum"].sum())

    print("---- Verification ----")
    print(f"Raw total amount:       {raw_total:,.2f}")
    print(f"Aggregated total amount:{agg_total:,.2f}")

    if abs(raw_total - agg_total) > 0.01:
        print("❌ WARNING: Totals do not match! Check ingestion/cleaning or parsing.")
    else:
        print("✅ Totals match.")

    # Per-period check (raw vs aggregated)
    raw_by_period = df.groupby("period")["amount"].sum().sort_index()
    agg_by_period = long_df.groupby("period")["amount_sum"].sum().sort_index()

    mismatches = (raw_by_period - agg_by_period).abs()
    bad = mismatches[mismatches > 0.01]
    if len(bad) > 0:
        print("❌ WARNING: Period-level mismatches found:")
        for period, diff in bad.items():
            print(f"  - {period}: difference={diff:,.2f}")
    else:
        print("✅ Period-level totals match.")


def main() -> None:
    ensure_dirs()

    if not os.path.exists(INPUT_CLEAN):
        raise SystemExit(f"Missing input file: {INPUT_CLEAN}. Run ingest_clean.py first.")

    df = load_clean_data(INPUT_CLEAN)
    results = aggregate(df)

    long_df: pd.DataFrame = results["long_df"]
    wide_df: pd.DataFrame = results["wide_df"]
    by_member: Dict[str, Any] = results["by_member"]
    summary: Dict[str, Any] = results["summary"]

    # Write outputs
    long_df.to_csv(OUT_LONG, index=False)
    wide_df.to_csv(OUT_WIDE, index=False)

    with open(OUT_BY_MEMBER_JSON, "w", encoding="utf-8") as f:
        json.dump(by_member, f, ensure_ascii=False, indent=2)

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Verification
    verify(df, long_df)

    # Quick view: Top 5 contributors
    print("\n---- Top 5 Contributors ----")
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
