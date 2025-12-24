// docs/assets/js/admin.js

let totalsChart = null;
let topChart = null;

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
  // Cache-busting so "Reload" works on GitHub Pages
  const url = `./data/summary_stats.json?v=${Date.now()}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load summary_stats.json (${res.status})`);
  return await res.json();
}

function renderKPIs(summary) {
  const grandTotal = summary.grand_total ?? 0;
  const members = summary.distinct_members ?? 0;
  const periods = summary.distinct_periods ?? 0;

  document.getElementById("kpiGrandTotal").textContent = fmtNumber(grandTotal);
  document.getElementById("kpiMembers").textContent = fmtNumber(members);
  document.getElementById("kpiPeriods").textContent = fmtNumber(periods);

  const avgPerMember = members > 0 ? (grandTotal / members) : 0;
  document.getElementById("kpiAvgPerMember").textContent = fmtNumber(avgPerMember);

  document.getElementById("lastUpdated").textContent =
    `Updated: ${new Date().toLocaleString()}`;
}

function renderPeriodTable(summary) {
  const tbody = document.getElementById("tblPeriods");
  tbody.innerHTML = "";

  const rows = summary.totals_by_period ?? [];
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="3">No period data found.</td></tr>`;
    return;
  }

  for (const r of rows) {
    const tr = document.createElement("tr");
    const period = r.period ?? "";
    const total = r.total ?? 0;
    const growth = r.growth_pct;

    tr.innerHTML = `
      <td>${period}</td>
      <td>${fmtNumber(total)}</td>
      <td>${fmtPct(growth)}</td>
    `;
    tbody.appendChild(tr);
  }
}

function renderTotalsChart(summary) {
  const rows = summary.totals_by_period ?? [];
  const labels = rows.map(r => r.period);
  const totals = rows.map(r => r.total ?? 0);

  const ctx = document.getElementById("chartTotals");

  if (totalsChart) totalsChart.destroy();
  totalsChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Total (LSL)",
        data: totals,
        tension: 0.25
      }]
    },
    options: {
      responsive: true,
      plugins: {
        tooltip: {
          callbacks: {
            label: (item) => ` ${fmtNumber(item.raw)} LSL`
          }
        }
      },
      scales: {
        y: {
          ticks: {
            callback: (v) => fmtNumber(v)
          }
        }
      }
    }
  });
}

function renderTopChart(summary) {
  const top = (summary.top_contributors ?? []).slice(0, 10);

  // Using display name if present; otherwise member_key
  const labels = top.map(r => r.member_name || r.member_key || "Unknown");
  const values = top.map(r => r.total_to_date ?? 0);

  const ctx = document.getElementById("chartTop");

  if (topChart) topChart.destroy();
  topChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Total to date (LSL)",
        data: values
      }]
    },
    options: {
      responsive: true,
      indexAxis: "y",
      plugins: {
        tooltip: {
          callbacks: {
            label: (item) => ` ${fmtNumber(item.raw)} LSL`
          }
        }
      },
      scales: {
        x: {
          ticks: {
            callback: (v) => fmtNumber(v)
          }
        }
      }
    }
  });
}

function showError(msg) {
  const box = document.getElementById("errBox");
  box.style.display = "block";
  box.textContent = msg;
}

function clearError() {
  const box = document.getElementById("errBox");
  box.style.display = "none";
  box.textContent = "";
}

async function main() {
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

document.getElementById("btnReload").addEventListener("click", main);
main();
