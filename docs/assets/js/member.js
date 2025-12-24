// docs/assets/js/member.js
//
// Supports new JSON structure where:
// member.history[period] = {
//   success_total: number,
//   transactions: [{ amount: number, txn_status: "SUCCESS"|"FAIL" }, ...]
// }
//
// UI expectations (from updated index.html):
// - Table columns: Period | SUCCESS Total (LSL) | Transactions (Amount + Status)

let DATA = null;           // raw JSON: object keyed by member_key
let INDEX_BY_CODE = {};    // member_code -> member_key
let INDEX_BY_NAME = {};    // normalized name -> member_key
let currentMember = null;  // last matched member object

function norm(s) {
  return (s || "").toString().trim().replace(/\s+/g, " ").toLowerCase();
}

function fmtNumber(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(n);
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

function showResult() {
  document.getElementById("resultBox").style.display = "block";
}

function hideResult() {
  document.getElementById("resultBox").style.display = "none";
}

function setExportEnabled(enabled) {
  document.getElementById("btnExport").disabled = !enabled;
}

function escapeHtml(s) {
  return (s || "").toString()
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function badgeHtml(status) {
  const st = (status || "").toString().toUpperCase();
  const isOk = st === "SUCCESS";
  const cls = isOk ? "badge badge-success" : "badge badge-fail";
  const label = isOk ? "SUCCESS" : "FAIL";
  return `<span class="${cls}"><span class="badge-dot"></span>${label}</span>`;
}

async function loadData() {
  const status = document.getElementById("dataStatus");
  status.textContent = "Loading data…";

  // Cache-busting so updates reflect quickly
  const url = `./data/contributions_by_member.json?v=${Date.now()}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load contributions_by_member.json (${res.status})`);

  DATA = await res.json();

  // Build indexes
  INDEX_BY_CODE = {};
  INDEX_BY_NAME = {};

  for (const [memberKey, obj] of Object.entries(DATA)) {
    const code = norm(obj.member_code);
    const name = norm(obj.member_name);

    if (code) INDEX_BY_CODE[code] = memberKey;
    if (name) INDEX_BY_NAME[name] = memberKey;
  }

  status.textContent = "Data loaded ✅";
}

function findMember(codeInput, nameInput) {
  const code = norm(codeInput);
  const name = norm(nameInput);

  // Preferred lookup by code
  if (code && INDEX_BY_CODE[code]) {
    const key = INDEX_BY_CODE[code];
    return DATA[key];
  }

  // Fallback to exact name match (case-insensitive)
  if (name && INDEX_BY_NAME[name]) {
    const key = INDEX_BY_NAME[name];
    return DATA[key];
  }

  return null;
}

function renderMember(member) {
  document.getElementById("outName").textContent = member.member_name || "—";
  document.getElementById("outCode").textContent = member.member_code || "—";
  // Total is SUCCESS-only (per your aggregation rule)
  document.getElementById("outTotal").textContent = fmtNumber(member.total || 0);

  const tbody = document.getElementById("tblHistory");
  tbody.innerHTML = "";

  const history = member.history || {};
  const periods = Object.keys(history).sort(); // ISO date sorting

  if (!periods.length) {
    tbody.innerHTML = `<tr><td colspan="3">No contribution history found.</td></tr>`;
    return;
  }

  for (const p of periods) {
    const periodObj = history[p] || {};
    const successTotal = Number(periodObj.success_total || 0);

    const txns = Array.isArray(periodObj.transactions) ? periodObj.transactions : [];
    let txHtml = "";

    if (!txns.length) {
      txHtml = `<span class="pill">No transactions</span>`;
    } else {
      // Render list within one cell
      txHtml = txns.map(t => {
        const amt = fmtNumber(Number(t.amount || 0));
        const st = (t.txn_status || "").toString().toUpperCase();
        return `<div style="display:flex;gap:10px;align-items:center;margin:4px 0;">
                  <span style="min-width:90px;">LSL ${amt}</span>
                  ${badgeHtml(st)}
                </div>`;
      }).join("");
    }

    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(p)}</td>
      <td>${fmtNumber(successTotal)}</td>
      <td>${txHtml}</td>
    `;
    tbody.appendChild(tr);
  }
}

function exportCSV(member) {
  // Export includes both SUCCESS and FAIL lines,
  // with an extra column to reflect txn_status,
  // plus a SUCCESS_total column per period for convenience.

  const history = member.history || {};
  const periods = Object.keys(history).sort();

  const lines = [];
  lines.push("Period,Amount,TxnStatus,PeriodSuccessTotal");

  for (const p of periods) {
    const periodObj = history[p] || {};
    const successTotal = Number(periodObj.success_total || 0);
    const txns = Array.isArray(periodObj.transactions) ? periodObj.transactions : [];

    if (!txns.length) {
      // Still emit a row so the period appears in exports
      lines.push(`${p},,,"${successTotal}"`);
      continue;
    }

    for (const t of txns) {
      const amt = (t.amount === null || t.amount === undefined) ? "" : Number(t.amount);
      const st = (t.txn_status || "").toString().toUpperCase();
      lines.push(`${p},${amt},${st},${successTotal}`);
    }
  }

  const csv = lines.join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });

  const safeName = (member.member_name || "member").replace(/[^a-z0-9]+/gi, "_");
  const filename = `MILCO_Contribution_Statement_${safeName}.csv`;

  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

function clearForm() {
  document.getElementById("inpCode").value = "";
  document.getElementById("inpName").value = "";
  currentMember = null;
  hideResult();
  clearError();
  setExportEnabled(false);
}

async function main() {
  hideResult();
  clearError();
  setExportEnabled(false);

  try {
    await loadData();
  } catch (e) {
    showError(e.message || String(e));
    document.getElementById("dataStatus").textContent = "Data load failed ❌";
    return;
  }

  document.getElementById("btnSearch").addEventListener("click", () => {
    clearError();
    hideResult();
    setExportEnabled(false);

    const code = document.getElementById("inpCode").value;
    const name = document.getElementById("inpName").value;

    if (!norm(code) && !norm(name)) {
      showError("Please enter either Member Code or Full Name.");
      return;
    }

    const member = findMember(code, name);
    if (!member) {
      showError("Record not found. Please check the exact Member Code or Full Name and try again.");
      return;
    }

    currentMember = member;
    renderMember(member);
    showResult();
    setExportEnabled(true);
  });

  document.getElementById("btnClear").addEventListener("click", clearForm);

  document.getElementById("btnExport").addEventListener("click", () => {
    if (!currentMember) return;
    exportCSV(currentMember);
  });

  // Optional: allow Enter key to trigger search
  document.getElementById("inpCode").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("btnSearch").click();
  });
  document.getElementById("inpName").addEventListener("keydown", (e) => {
    if (e.key === "Enter") document.getElementById("btnSearch").click();
  });
}

main();
