const state = {
  skip: 0,
  limit: 50,
};

const els = {
  account: document.getElementById("account"),
  category: document.getElementById("category"),
  shared: document.getElementById("shared"),
  start: document.getElementById("start"),
  end: document.getElementById("end"),
  search: document.getElementById("search"),
  clearFilters: document.getElementById("clear-filters"),
  body: document.getElementById("results-body"),
  table: document.getElementById("results-table"),
  emptyState: document.getElementById("empty-state"),
  loadingState: document.getElementById("loading-state"),
  count: document.getElementById("results-count"),
  pageInfo: document.getElementById("page-info"),
  prevBtn: document.getElementById("prev-page"),
  nextBtn: document.getElementById("next-page"),
  toggleUpload: document.getElementById("toggle-upload"),
  uploadForm: document.getElementById("upload-form"),
  uploadFile: document.getElementById("upload-file"),
  uploadAccount: document.getElementById("upload-account"),
  uploadMapping: document.getElementById("upload-mapping"),
  uploadSource: document.getElementById("upload-source"),
  uploadSubmit: document.getElementById("upload-submit"),
  uploadStatus: document.getElementById("upload-status"),
  uploadResult: document.getElementById("upload-result"),
};

function buildQuery() {
  const params = new URLSearchParams();
  if (els.account.value) params.set("account_id", els.account.value);
  if (els.category.value) params.set("category", els.category.value);
  if (els.shared.value) params.set("is_shared", els.shared.value);
  if (els.start.value) params.set("start", els.start.value);
  if (els.end.value) params.set("end", els.end.value);
  if (els.search.value) params.set("search", els.search.value);
  params.set("skip", state.skip);
  params.set("limit", state.limit);
  return params.toString();
}

async function loadFilters() {
  const [accounts, categories] = await Promise.all([
    fetch("/api/accounts").then((r) => r.json()),
    fetch("/api/categories").then((r) => r.json()),
  ]);

  // Clear everything but the "All ..." default option, so this can be
  // safely re-called (e.g. after an upload adds a new account/category)
  // without duplicating entries.
  els.account.length = 1;
  els.category.length = 1;

  for (const acc of accounts) {
    const opt = document.createElement("option");
    opt.value = acc;
    opt.textContent = acc;
    els.account.appendChild(opt);
  }
  for (const cat of categories) {
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = cat;
    els.category.appendChild(opt);
  }
}

async function loadMappings() {
  const mappings = await fetch("/api/mappings").then((r) => r.json());
  els.uploadMapping.innerHTML = "";
  for (const name of mappings) {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    els.uploadMapping.appendChild(opt);
  }
}

function formatAmount(amount) {
  const abs = Math.abs(amount).toFixed(2);
  return amount < 0 ? `-\u00a3${abs}` : `+\u00a3${abs}`;
}

// Deterministic pastel colour per category name, so new categories added
// to category_rules.yaml automatically get a (stable, readable) colour
// without needing a hand-maintained palette here.
function categoryColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const hue = Math.abs(hash) % 360;
  return {
    bg: `hsl(${hue}, 55%, 93%)`,
    text: `hsl(${hue}, 45%, 30%)`,
  };
}

function renderRows(items) {
  els.body.innerHTML = "";
  for (const txn of items) {
    const tr = document.createElement("tr");

    const sharedBadge =
      txn.is_shared === true
        ? '<span class="badge shared">Shared</span>'
        : txn.is_shared === false
        ? '<span class="badge personal">Personal</span>'
        : "";

    let categoryHtml;
    if (txn.category) {
      const { bg, text } = categoryColor(txn.category);
      categoryHtml = `<span class="category-chip" style="background:${bg};color:${text}">${txn.category}</span>`;
    } else {
      categoryHtml = '<span class="category-chip uncategorized">uncategorized</span>';
    }

    tr.innerHTML = `
      <td>${txn.date ?? ""}</td>
      <td>${txn.description_raw ?? ""}</td>
      <td>${txn.account_id ?? ""}</td>
      <td>${categoryHtml}</td>
      <td>${sharedBadge}</td>
      <td class="amount-col ${txn.amount < 0 ? "negative" : "positive"}">${formatAmount(txn.amount)}</td>
    `;
    els.body.appendChild(tr);
  }
}

async function loadTransactions() {
  els.loadingState.hidden = false;
  els.emptyState.hidden = true;
  els.table.style.display = "none";

  const res = await fetch(`/api/transactions?${buildQuery()}`);
  const data = await res.json();

  els.loadingState.hidden = true;

  if (data.total === 0) {
    els.emptyState.hidden = false;
    els.table.style.display = "none";
    els.body.innerHTML = "";
  } else {
    els.table.style.display = "";
    renderRows(data.items);
  }

  const from = data.total === 0 ? 0 : data.skip + 1;
  const to = Math.min(data.skip + data.limit, data.total);
  els.count.textContent = `Showing ${from}-${to} of ${data.total}`;
  els.pageInfo.textContent = `Page ${Math.floor(data.skip / data.limit) + 1}`;

  els.prevBtn.disabled = data.skip === 0;
  els.nextBtn.disabled = data.skip + data.limit >= data.total;
}

function resetAndReload() {
  state.skip = 0;
  loadTransactions();
}

let searchDebounce;
els.search.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(resetAndReload, 300);
});

for (const el of [els.account, els.category, els.shared, els.start, els.end]) {
  el.addEventListener("change", resetAndReload);
}

els.clearFilters.addEventListener("click", () => {
  els.account.value = "";
  els.category.value = "";
  els.shared.value = "";
  els.start.value = "";
  els.end.value = "";
  els.search.value = "";
  resetAndReload();
});

els.prevBtn.addEventListener("click", () => {
  state.skip = Math.max(0, state.skip - state.limit);
  loadTransactions();
});

els.nextBtn.addEventListener("click", () => {
  state.skip += state.limit;
  loadTransactions();
});

loadFilters().then(loadTransactions);
loadMappings();

els.toggleUpload.addEventListener("click", () => {
  const showing = !els.uploadForm.hidden;
  els.uploadForm.hidden = showing;
  els.toggleUpload.textContent = showing ? "Show" : "Hide";
});

function renderUploadResult(summary, isError) {
  els.uploadResult.hidden = false;
  els.uploadResult.className = `upload-result ${isError ? "error" : "success"}`;

  if (isError) {
    els.uploadResult.textContent = summary;
    return;
  }

  els.uploadResult.innerHTML = `
    <div>${summary.inserted} inserted, ${summary.duplicates} duplicates skipped</div>
    <div>${summary.categorised} categorised, ${summary.still_uncategorised} still uncategorised</div>
  `;
}

els.uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();

  const file = els.uploadFile.files[0];
  if (!file) return;

  els.uploadSubmit.disabled = true;
  els.uploadStatus.textContent = "Uploading\u2026";
  els.uploadResult.hidden = true;

  const formData = new FormData();
  formData.append("file", file);
  formData.append("account_id", els.uploadAccount.value);
  formData.append("mapping", els.uploadMapping.value);
  formData.append("source", els.uploadSource.value || "csv");

  try {
    const res = await fetch("/api/import", { method: "POST", body: formData });
    const body = await res.json();

    if (!res.ok) {
      renderUploadResult(body.detail ?? "Upload failed.", true);
    } else {
      renderUploadResult(body, false);
      els.uploadForm.reset();
      els.uploadSource.value = "csv";
      await loadMappings();
      await loadFilters();
      resetAndReload();
    }
  } catch (err) {
    renderUploadResult("Upload failed - couldn't reach the server.", true);
  } finally {
    els.uploadSubmit.disabled = false;
    els.uploadStatus.textContent = "";
  }
});
