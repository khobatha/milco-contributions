# MILCO Contributions Analytics Portal

This repository contains a **fully automated, open-source system** for:
- Ingesting monthly contribution CSV reports
- Cleaning and validating member contribution data
- Aggregating contributions by member and period
- Publishing a **static Admin Dashboard** and **Member Portal** via GitHub Pages

## Features

- Automated CSV ingestion and cleaning (Python + Pandas)
- Robust aggregation logic with verification checks
- Static admin dashboard (Chart.js)
- Zero-cost hosting via GitHub Pages
- Designed for cooperatives and transparency

## Folder Structure

pipeline/ # Python ingestion + aggregation scripts
docs/ # GitHub Pages site (admin dashboard & portal)
outputs/ # Generated clean & aggregated datasets
data/raw/ # (Ignored) raw CSV uploads


## Getting Started (Local)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r pipeline/requirements.txt

python pipeline/ingest_clean.py
python pipeline/aggregate.py

Publishing the Admin Dashboard

The admin dashboard is served from /docs using GitHub Pages.

After pushing to GitHub:

Enable Pages → Source: main → Folder: /docs

Access dashboard at:
https://<username>.github.io/milco-contributions/admin.html

Security Note

Raw contribution CSV files are not committed to this repository.
Only aggregated, non-editable outputs are published.


