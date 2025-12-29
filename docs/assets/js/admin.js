// docs/assets/js/admin.js
// MiLCo Admin Dashboard JS (null-safe + SUCCESS vs FAIL aware)

let totalsChart = null;
let topChart = null;

function $(id) { return document.getElementById(id); }

function setText(id, value) {
  const el = $(id);
  if (!el) return false;
  el.textContent = value;
  return true;
}

function fmtNumber(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(n);
}

function fmtPct(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const val = Number(n);
  const sign = val > 0 ? "+" : "";
  return `${sign}${val.toFixed(2)}%`;
}

async function loadSummary() {
  const url = `./data/summary_stats.json?v=${Date.now()}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load summary_stats.json (${res.status})`);
  return await res.json();
}

// Backward compatibility helpers
function getPeriodSuccessTotal(r) {
  if (r && r.success_total != null) return Number(r.success_total) || 0;
  if (r && r.total != null) return Number(r.total) || 0; // old schema fallback
  return 0;
}
function getPeriodFailTotal(r) {
  if (r && r.fail_total != null) return Number(r.fail_total) || 0;
  return 0;
}
function getSuccessGrowth(r) {
  if (!r) return null;
  if (r.success_growth_pct != null) return r.success_growth_pct;
  if (r.growth_pct != null) return r.growth_pct;
  return null;
}
function getFailGrowth(r) {
  if (!r) return null;
  if (r.fail_growth_pct != null) return r.fail_growth_pct;
  return null;
}

function renderKPIs(summary) {
  const members = Number(summary.distinct_members ?? 0) || 0;
  const periods = Number(summary.distinct_periods ?? 0) || 0;
  const records = Number(summary.total_records_clean ?? 0) || 0;

  const grandSuccess =
    summary.grand_total_success != null ? Number(summary.grand_total_success) || 0 :
    (summary.grand_total != null ? Number(summary.grand_total) || 0 : 0);

  const grandFail =
    summary.grand_total_fail != null ? Number(summary.grand_total_fail) || 0 : 0;

  // New IDs (preferred)
  setText("kpiGrandTotalSuccess", fmtNumber(grandSuccess));
  setText("kpiGrandTotalFail", fmtNumber(grandFail));
  setText("kpiMembers", fmtNumber(members));
  setText("kpiPeriods", fmtNumber(periods));
  setText("kpiRecords", fmtNumber(records));

  const avgSuccess = members > 0 ? (grandSuccess / members) : 0;
  const avgFail = members > 0 ? (grandFail / members) : 0;

  setText("kpiAvgPerMemberSuccess", fmtNumber(avgSuccess));
  setText("kpiAvgPerMemberFail", fmtNumber(avgFail));

  // Old IDs (fallback if you still have the old admin.html)
  // If these elements exist, populate them too.
  setText("kpiGrandTotal", fmtNumber(grandSuccess)); // old page had single total
  setText("kpiAvgPerMember", fmtNumber(avgSuccess));
  setText("kpiPeriods", fmtNumber(periods)); // already set above, safe

  setText("lastUpdated", `Updated: ${new Date().toLocaleString()}`);
}

function renderPeriodTable(summary) {
  const tbody = $("tblPeriods");
  if (!tbody) return;

  tbody.innerHTML = "";

  const rows = summary.totals_by_period ?? [];
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5">No period data found.</td></tr>`;
    return;
  }

  // Detect whether table is new (5 cols) or old (3 cols)
  // If old header exists, we output 3 cols. Otherwise output 5.
  // (We infer by checking the first header row cell count.)
  const table = tbody.closest("table");
  const thCount = table?.querySelectorAll("thead th")?.length ?? 5;
  const isOld3Col = thCount <= 3;

  for (const r of rows) {
    const period = r.period ?? "";
    const successTotal = getPeriodSuccessTotal(r);
    const failTotal = getPeriodFailTotal(r);
    const successGrowth = getSuccessGrowth(r);
    const failGrowth = getFailGrowth(r);

    const tr = document.createElement("tr");
    if (isOld3Col) {
      tr.innerHTML = `
        <td>${period}</td>
        <td>${fmtNumber(successTotal)}</td>
        <td>${fmtPct(successGrowth)}</td>
      `;
    } else {
      tr.innerHTML = `
        <td>${period}</td>
        <td>${fmtNumber(successTotal)}</td>
        <td>${fmtNumber(failTotal)}</td>
        <td>${fmtPct(successGrowth)}</td>
        <td>${fmtPct(failGrowth)}</td>
      `;
    }
    tbody.appendChild(tr);
  }
}

function renderTotalsChart(summary) {
  const ctxEl = $("chartTotals");
  if (!ctxEl) return;

  const rows = summary.totals_by_period ?? [];
  const labels = rows.map(r => r.period);
  const successTotals = rows.map(r => getPeriodSuccessTotal(r));
  const failTotals = rows.map(r => getPeriodFailTotal(r));

  if (totalsChart) totalsChart.destroy();
  totalsChart = new Chart(ctxEl, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "SUCCESS Total (LSL)", data: successTotals, tension: 0.25 },
        { label: "FAIL Total (LSL)", data: failTotals, tension: 0.25 }
      ]
    },
    options: {
      responsive: true,
      plugins: {
        tooltip: {
          callbacks: {
            label: (item) => ` ${item.dataset.label}: ${fmtNumber(item.raw)} LSL`
          }
        }
      },
      scales: { y: { ticks: { callback: (v) => fmtNumber(v) } } }
    }
  });
}

function renderTopChart(summary) {
  const ctxEl = $("chartTop");
  if (!ctxEl) return;

  const topArr = summary.top_contributors_success ?? summary.top_contributors ?? [];
  const top = (topArr || []).slice(0, 10);

  const labels = top.map(r => r.member_name || r.member_key || "Unknown");
  const values = top.map(r => {
    if (r.total_success_to_date != null) return Number(r.total_success_to_date) || 0;
    if (r.total_to_date != null) return Number(r.total_to_date) || 0;
    return 0;
  });

  if (topChart) topChart.destroy();
  topChart = new Chart(ctxEl, {
    type: "bar",
    data: { labels, datasets: [{ label: "Total to date (SUCCESS only) – LSL", data: values }] },
    options: {
      responsive: true,
      indexAxis: "y",
      plugins: {
        tooltip: { callbacks: { label: (item) => ` ${fmtNumber(item.raw)} LSL` } }
      },
      scales: { x: { ticks: { callback: (v) => fmtNumber(v) } } }
    }
  });
}

function showError(msg) {
  const box = $("errBox");
  if (!box) return;
  box.style.display = "block";
  box.textContent = msg;
}

function clearError() {
  const box = $("errBox");
  if (!box) return;
  box.style.display = "none";
  box.textContent = "";
}

async function run() {
  clearError();
  try {
    const summary = await loadSummary();
    renderKPIs(summary);
    renderTotalsChart(summary);
    renderTopChart(summary);
    renderPeriodTable(summary);
  } catch (e) {
    showError(e.message || String(e));
    console.error(e);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const btn = $("btnReload");
  if (btn) btn.addEventListener("click", run);
  run();
});
