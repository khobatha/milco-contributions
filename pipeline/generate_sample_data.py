#!/usr/bin/env python3
"""
Generate SAFE SAMPLE DATA for public GitHub publishing.

- No real names
- No real amounts
- Same schema as real outputs
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

OUT_DIR = Path("docs/data")
OUT_DIR.mkdir(parents=True, exist_ok=True)

NUM_MEMBERS = 18
NUM_PERIODS = 6

random.seed(42)

# --- Generate periods (monthly) ---
start_date = date(2025, 1, 1)
periods = [(start_date + timedelta(days=30*i)).isoformat() for i in range(NUM_PERIODS)]

# --- Generate members ---
members = []
for i in range(1, NUM_MEMBERS + 1):
    members.append({
        "member_key": f"SAMPLE_M{i:03d}",
        "member_code": f"M{i:03d}",
        "member_name": f"Sample Member {i}"
    })

# --- Generate contributions ---
contributions_by_member = {}
totals_by_period = {p: 0 for p in periods}

for m in members:
    history = {}
    total = 0

    for p in periods:
        if random.random() < 0.85:  # most members contribute most periods
            amount = random.choice([100, 150, 200, 250, 300])
            history[p] = amount
            total += amount
            totals_by_period[p] += amount

    contributions_by_member[m["member_key"]] = {
        "member_key": m["member_key"],
        "member_code": m["member_code"],
        "member_name": m["member_name"],
        "total": total,
        "history": history
    }

# --- Build summary stats ---
totals_by_period_list = []
prev_total = None
for p in periods:
    total = totals_by_period[p]
    growth = None if prev_total is None else ((total - prev_total) / prev_total * 100 if prev_total else 0)
    totals_by_period_list.append({
        "period": p,
        "total": total,
        "growth_pct": growth
    })
    prev_total = total

summary_stats = {
    "total_records_clean": sum(len(m["history"]) for m in contributions_by_member.values()),
    "distinct_members": len(members),
    "distinct_periods": len(periods),
    "grand_total": sum(totals_by_period.values()),
    "totals_by_period": totals_by_period_list,
    "top_contributors": sorted(
        [
            {
                "member_key": m["member_key"],
                "member_name": m["member_name"],
                "total_to_date": m["total"]
            }
            for m in contributions_by_member.values()
        ],
        key=lambda x: x["total_to_date"],
        reverse=True
    )[:10]
}

# --- Write files ---
with open(OUT_DIR / "contributions_by_member.json", "w", encoding="utf-8") as f:
    json.dump(contributions_by_member, f, indent=2)

with open(OUT_DIR / "summary_stats.json", "w", encoding="utf-8") as f:
    json.dump(summary_stats, f, indent=2)

print("✅ Sample dataset generated safely in docs/data/")
