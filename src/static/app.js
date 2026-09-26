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
  toggleAdd: document.getElementById("toggle-add"),
  addForm: document.getElementById("add-form"),
  addAccount: document.getElementById("add-account"),
  addDate: document.getElementById("add-date"),
  addAmount: document.getElementById("add-amount"),
  addDescription: document.getElementById("add-description"),
  addCategory: document.getElementById("add-category"),
  addShared: document.getElementById("add-shared"),
  addSubmit: document.getElementById("add-submit"),
  addStatus: document.getElementById("add-status"),
  addResult: document.getElementById("add-result"),
};

// Cached so the inline per-row edit dropdown and the "add transaction"
// form's category dropdown don't each need their own fetch.
let knownCategories = [];

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

  knownCategories = categories;

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

  // "Add transaction" form's category dropdown - keep the leading
  // "Auto-categorise" option, repopulate the rest.
  els.addCategory.length = 1;
  for (const cat of categories) {
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = cat;
    els.addCategory.appendChild(opt);
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

function renderCategoryCell(txn) {
  if (txn.category) {
    const { bg, text } = categoryColor(txn.category);
    return `<span class="category-chip" data-value="${txn.category}" style="background:${bg};color:${text}">${txn.category}</span>`;
  }
  return `<span class="category-chip uncategorized" data-value="">uncategorized</span>`;
}

function renderSharedCell(txn) {
  if (txn.is_shared === true) return `<span class="badge shared" data-value="true">Shared</span>`;
  if (txn.is_shared === false) return `<span class="badge personal" data-value="false">Personal</span>`;
  return `<span class="badge undecided" data-value="">Undecided</span>`;
}

function renderRows(items) {
  els.body.innerHTML = "";
  for (const txn of items) {
    const tr = document.createElement("tr");
    tr.dataset.id = txn._id;

    tr.innerHTML = `
      <td>${txn.date ?? ""}</td>
      <td>${txn.description_raw ?? ""}</td>
      <td>${txn.account_id ?? ""}</td>
      <td class="cat-cell">${renderCategoryCell(txn)}</td>
      <td class="shared-cell">${renderSharedCell(txn)}</td>
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

// --- inline edit: category chip + shared badge --------------------------

async function patchTransaction(id, fields) {
  try {
    const res = await fetch(`/api/transactions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      alert(body.detail || "Failed to update transaction.");
      return false;
    }
    return true;
  } catch (err) {
    alert("Couldn't reach the server.");
    return false;
  }
}

function editCategoryCell(tr, id, currentValue) {
  const cell = tr.querySelector(".cat-cell");
  const select = document.createElement("select");
  select.className = "cell-edit-select";

  const blankOpt = document.createElement("option");
  blankOpt.value = "";
  blankOpt.textContent = "Uncategorised";
  select.appendChild(blankOpt);

  for (const cat of knownCategories) {
    const opt = document.createElement("option");
    opt.value = cat;
    opt.textContent = cat;
    select.appendChild(opt);
  }
  select.value = currentValue || "";

  cell.innerHTML = "";
  cell.appendChild(select);
  select.focus();

  let committed = false;

  select.addEventListener("change", async () => {
    committed = true;
    const newValue = select.value;
    if (newValue === (currentValue || "")) {
      loadTransactions();
      return;
    }
    const ok = await patchTransaction(id, { category: newValue || null });
    loadTransactions(); // re-render the chip either way - reverts on failure
    if (!ok) return;
  });

  select.addEventListener("blur", () => {
    // Change already handled the save case; this just cancels back to
    // the chip if the user clicked away without picking anything new.
    if (!committed) loadTransactions();
  });
}

async function cycleSharedCell(tr, id, currentValue) {
  const next = currentValue === "" ? "true" : currentValue === "true" ? "false" : "";
  const ok = await patchTransaction(id, { is_shared: next === "" ? null : next === "true" });
  if (ok) loadTransactions();
}

els.body.addEventListener("click", (e) => {
  const tr = e.target.closest("tr");
  if (!tr) return;
  const id = tr.dataset.id;

  const chip = e.target.closest(".category-chip");
  if (chip && !tr.querySelector(".cell-edit-select")) {
    editCategoryCell(tr, id, chip.dataset.value);
    return;
  }

  const badge = e.target.closest(".badge");
  if (badge) {
    cycleSharedCell(tr, id, badge.dataset.value);
  }
});

// --- add transaction manually --------------------------------------------

els.toggleAdd.addEventListener("click", () => {
  const showing = !els.addForm.hidden;
  els.addForm.hidden = showing;
  els.toggleAdd.textContent = showing ? "Show" : "Hide";
});

function renderAddResult(summary, isError) {
  els.addResult.hidden = false;
  els.addResult.className = `upload-result ${isError ? "error" : "success"}`;

  if (isError) {
    els.addResult.textContent = summary;
    return;
  }

  const sharedLabel =
    summary.is_shared === true ? "Shared" : summary.is_shared === false ? "Personal" : "Undecided";

  els.addResult.innerHTML = `
    <div>Added: ${summary.description_raw} (${formatAmount(summary.amount)})</div>
    <div>Category: ${summary.category ?? "uncategorised"} - ${sharedLabel}</div>
  `;
}

els.addForm.addEventListener("submit", async (e) => {
  e.preventDefault();

  els.addSubmit.disabled = true;
  els.addStatus.textContent = "Adding\u2026";
  els.addResult.hidden = true;

  const payload = {
    account_id: els.addAccount.value,
    date: els.addDate.value,
    amount: parseFloat(els.addAmount.value),
    description_raw: els.addDescription.value,
  };
  if (els.addCategory.value) payload.category = els.addCategory.value;
  if (els.addShared.value) payload.is_shared = els.addShared.value === "true";

  try {
    const res = await fetch("/api/transactions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();

    if (!res.ok) {
      renderAddResult(body.detail ?? "Couldn't add the transaction.", true);
    } else {
      renderAddResult(body, false);
      els.addForm.reset();
      await loadFilters();
      resetAndReload();
    }
  } catch (err) {
    renderAddResult("Couldn't reach the server.", true);
  } finally {
    els.addSubmit.disabled = false;
    els.addStatus.textContent = "";
  }
});

