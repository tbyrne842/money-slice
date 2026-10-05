const state = {
  skip: 0,
  limit: 50,
};

// Transaction text comes from bank CSVs, and household members can now
// see each other's rows - so everything interpolated into innerHTML is escaped.
function esc(value) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, (c) => map[c]);
}

let currentUser = null;
let household = null;

const els = {
  scope: document.getElementById("scope"),
  sharingHint: document.getElementById("sharing-hint"),
  householdBody: document.getElementById("household-body"),
  settlementPanel: document.getElementById("settlement-panel"),
  settlementBody: document.getElementById("settlement-body"),
  settleStart: document.getElementById("settle-start"),
  settleEnd: document.getElementById("settle-end"),
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
  uploadMapping: document.getElementById("upload-mapping"),
  uploadSource: document.getElementById("upload-source"),
  uploadSubmit: document.getElementById("upload-submit"),
  uploadStatus: document.getElementById("upload-status"),
  uploadResult: document.getElementById("upload-result"),
  toggleAdd: document.getElementById("toggle-add"),
  addForm: document.getElementById("add-form"),
  addDate: document.getElementById("add-date"),
  addAmount: document.getElementById("add-amount"),
  addDescription: document.getElementById("add-description"),
  addCategory: document.getElementById("add-category"),
  addShared: document.getElementById("add-shared"),
  addSubmit: document.getElementById("add-submit"),
  addStatus: document.getElementById("add-status"),
  addResult: document.getElementById("add-result"),
  balanceWidget: document.getElementById("balance-widget"),
};

// Cached so the inline per-row edit dropdown and the "add transaction"
// form's category dropdown don't each need their own fetch.
let knownCategories = [];

function buildQuery() {
  const params = new URLSearchParams();
  // "Mine" narrows the household view down to your own rows; with no
  // household the server already only returns your own.
  if (els.scope.value === "mine") params.set("owner", currentUser);
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
  const categories = await fetch("/api/categories").then((r) => r.json());

  knownCategories = categories;

  // Clear everything but the "All ..." default option, so this can be
  // safely re-called (e.g. after an upload adds a new category)
  // without duplicating entries.
  els.category.length = 1;
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

async function loadBalance() {
  const widget = els.balanceWidget;
  if (!household) {
    widget.className = "balance-widget settled";
    widget.removeAttribute("title");
    els.settlementPanel.hidden = true;
    widget.innerHTML = '<span class="balance-label">No household yet</span><span class="balance-amount">Create or join one</span>';
    return;
  }
  try {
    const settlement = await fetch("/api/settlement").then((r) => {
      if (!r.ok) throw new Error("settlement unavailable");
      return r.json();
    });
    const mine = settlement.balance[currentUser] ?? 0;
    const amount = `\u00a3${Math.abs(mine).toFixed(2)}`;

    let statusClass, label, amountText;
    if (Math.abs(mine) < 0.005) {
      [statusClass, label, amountText] = ["settled", "Household balance", "Settled up"];
    } else if (mine > 0) {
      [statusClass, label, amountText] = ["owed-to-me", "You are owed", amount];
    } else {
      [statusClass, label, amountText] = ["i-owe", "You owe", amount];
    }

    // The widget is always all-time; the breakdown follows the date range.
    if (els.settleStart.value || els.settleEnd.value) loadSettlementPanel();
    else renderSettlement(settlement);

    widget.className = `balance-widget ${statusClass}`;
    widget.title = settlement.settlement_text;
    widget.innerHTML = `
      <span class="balance-label">${label}</span>
      <span class="balance-amount">${amountText}</span>
    `;
  } catch (err) {
    widget.className = "balance-widget settled";
    widget.innerHTML = '<span class="balance-label">Balance unavailable</span>';
  }
}

// --- household panel ---------------------------------------------------

let scopeInitialised = false;

function updateScopeControl() {
  const householdOption = els.scope.querySelector('option[value="household"]');
  householdOption.disabled = !household;
  if (!household) {
    els.scope.value = "mine";
  } else if (!scopeInitialised) {
    els.scope.value = "household"; // default to the shared view once there's one to see
  }
  scopeInitialised = true;
  els.sharingHint.hidden = !!household;
  document.body.classList.toggle("no-household", !household);
}

function money(n) {
  return `${n < 0 ? "-" : ""}\u00a3${Math.abs(n).toFixed(2)}`;
}

function renderSettlement(data) {
  els.settlementPanel.hidden = false;
  const rows = Object.keys(data.shares)
    .map(
      (u) => `<tr>
        <td>${esc(u)}${u === currentUser ? " (you)" : ""}</td>
        <td>${+(data.shares[u] * 100).toFixed(2)}%</td>
        <td>${money(data.paid_by_member[u])}</td>
        <td>${money(data.fair_share[u])}</td>
        <td class="${data.balance[u] < 0 ? "negative" : "positive"}">${money(data.balance[u])}</td>
      </tr>`
    )
    .join("");
  const ignored = data.unattributed_settle_ups
    ? `<p class="household-note">${data.unattributed_settle_ups} settle-up payment(s) ignored: the recipient is unknown in a household of three or more.</p>`
    : "";
  els.settlementBody.innerHTML = `
    <table class="household-table">
      <thead><tr><th>Member</th><th>Share</th><th>Paid</th><th>Fair share</th><th>Balance</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p><strong>${esc(data.settlement_text)}</strong> &middot; total shared spend ${money(data.total_shared)}</p>
    ${ignored}`;
}

async function loadSettlementPanel() {
  if (!household) return;
  const params = new URLSearchParams();
  if (els.settleStart.value) params.set("start", els.settleStart.value);
  if (els.settleEnd.value) params.set("end", els.settleEnd.value);
  const res = await fetch(`/api/settlement?${params}`);
  if (res.ok) renderSettlement(await res.json());
}

function renderHousehold() {
  if (!household) {
    els.householdBody.innerHTML = `
      <p class="household-note">You're not in a household yet. Create one and share its invite code, or join one with a code.</p>
      <div class="filters-grid">
        <form id="household-create" class="household-form">
          <div class="field"><label for="household-name">New household name</label>
            <input type="text" id="household-name" maxlength="50" required /></div>
          <button type="submit">Create</button>
        </form>
        <form id="household-join" class="household-form">
          <div class="field"><label for="household-code">Invite code</label>
            <input type="text" id="household-code" autocomplete="off" required /></div>
          <button type="submit">Join</button>
        </form>
      </div>
      <p id="household-status" class="household-status"></p>`;
    return;
  }
  const rows = household.members
    .map(
      (m) => `<tr><td>${esc(m.username)}${m.username === currentUser ? " (you)" : ""}</td>
        <td><input type="number" class="share-input" data-user="${esc(m.username)}" min="0" max="100" step="any"
          value="${+(m.share * 100).toFixed(6)}" /> %</td></tr>`
    )
    .join("");
  els.householdBody.innerHTML = `
    <p><strong>${esc(household.name)}</strong> &middot; invite code <code class="invite-code">${esc(household.invite_code)}</code></p>
    <table class="household-table"><thead><tr><th>Member</th><th>Share of joint spend</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <div class="upload-actions">
      <button type="button" id="save-shares">Save shares</button>
      <button type="button" id="rotate-code" class="text-btn">New invite code</button>
      <button type="button" id="leave-household" class="text-btn">Leave household</button>
      <span id="household-status" class="household-status"></span>
    </div>`;
}

function householdStatus(message, isError) {
  const el = document.getElementById("household-status");
  if (!el) return;
  el.textContent = message;
  el.className = `household-status${isError ? " error" : ""}`;
}

async function householdRequest(url, method, body) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? "Invalid input." : data.detail;
    householdStatus(detail || "Something went wrong.", true);
    return null;
  }
  return data;
}

async function loadHousehold() {
  const res = await fetch("/api/households/me");
  household = res.ok ? await res.json() : null;
  renderHousehold();
  updateScopeControl();
  loadBalance();
}

els.householdBody.addEventListener("submit", async (e) => {
  e.preventDefault();
  let result = null;
  if (e.target.id === "household-create") {
    result = await householdRequest("/api/households", "POST", { name: document.getElementById("household-name").value });
  } else if (e.target.id === "household-join") {
    result = await householdRequest("/api/households/join", "POST", { invite_code: document.getElementById("household-code").value });
  }
  if (result) location.reload(); // membership changes what's visible everywhere
});

els.householdBody.addEventListener("click", async (e) => {
  if (e.target.id === "save-shares") {
    const shares = {};
    for (const input of els.householdBody.querySelectorAll(".share-input")) {
      shares[input.dataset.user] = Number(input.value) / 100;
    }
    const total = Object.values(shares).reduce((a, b) => a + b, 0);
    if (Math.abs(total - 1) > 1e-6) {
      householdStatus(`Shares add up to ${(total * 100).toFixed(2)}% - they need to make 100%.`, true);
      return;
    }
    if (await householdRequest("/api/households/me/shares", "PUT", { shares })) {
      await loadHousehold();
      householdStatus("Shares saved.", false);
    }
  } else if (e.target.id === "rotate-code") {
    if (!confirm("Replace the invite code? The old one will stop working.")) return;
    if (await householdRequest("/api/households/me/invite-code", "POST")) await loadHousehold();
  } else if (e.target.id === "leave-household") {
    if (!confirm("Leave this household? You'll stop seeing each other's transactions.")) return;
    if (await householdRequest("/api/households/me/leave", "POST")) location.reload();
  }
});

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
    return `<span class="category-chip" data-value="${esc(txn.category)}" style="background:${bg};color:${text}">${esc(txn.category)}</span>`;
  }
  return `<span class="category-chip uncategorized" data-value="">uncategorized</span>`;
}

const NO_HOUSEHOLD_TITLE = "Takes effect once you join a household";

function renderSharedCell(txn) {
  const title = household ? "" : ` title="${NO_HOUSEHOLD_TITLE}"`;
  if (txn.is_shared === true) return `<span class="badge shared" data-value="true"${title}>Shared</span>`;
  if (txn.is_shared === false) return `<span class="badge personal" data-value="false"${title}>Personal</span>`;
  return `<span class="badge undecided" data-value=""${title}>Undecided</span>`;
}

function renderRows(items) {
  els.body.innerHTML = "";
  for (const txn of items) {
    const tr = document.createElement("tr");
    tr.dataset.id = txn._id;
    // Household members can view each other's rows but only edit their own.
    if (txn.owner !== currentUser) tr.classList.add("readonly");

    tr.innerHTML = `
      <td>${esc(txn.date)}</td>
      <td>${esc(txn.description_raw)}</td>
      <td>${esc(txn.owner)}</td>
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

for (const el of [els.scope, els.category, els.shared, els.start, els.end]) {
  el.addEventListener("change", resetAndReload);
}

els.clearFilters.addEventListener("click", () => {
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

// --- sign-in -----------------------------------------------------------

const authEls = {
  overlay: document.getElementById("auth-overlay"),
  form: document.getElementById("auth-form"),
  title: document.getElementById("auth-title"),
  username: document.getElementById("auth-username"),
  password: document.getElementById("auth-password"),
  error: document.getElementById("auth-error"),
  submit: document.getElementById("auth-submit"),
  toggle: document.getElementById("auth-toggle"),
  userMenu: document.getElementById("user-menu"),
  userName: document.getElementById("user-name"),
  logout: document.getElementById("logout-btn"),
};

let registering = false;

function showLogin() {
  authEls.overlay.hidden = false;
}

function setAuthMode(isRegister) {
  registering = isRegister;
  authEls.title.textContent = isRegister ? "Create an account" : "Sign in";
  authEls.submit.textContent = isRegister ? "Create account" : "Sign in";
  authEls.toggle.textContent = isRegister ? "I already have an account" : "Create an account";
  authEls.password.autocomplete = isRegister ? "new-password" : "current-password";
  authEls.error.hidden = true;
}

authEls.toggle.addEventListener("click", () => setAuthMode(!registering));

authEls.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  authEls.submit.disabled = true;
  authEls.error.hidden = true;
  try {
    const res = await fetch(registering ? "/api/auth/register" : "/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: authEls.username.value,
        password: authEls.password.value,
      }),
    });
    if (res.ok) {
      location.reload(); // simplest way to guarantee no stale data from before sign-in
      return;
    }
    const body = await res.json().catch(() => ({}));
    authEls.error.textContent = body.detail ?? "Couldn't sign in.";
    authEls.error.hidden = false;
  } catch (err) {
    authEls.error.textContent = "Couldn't reach the server.";
    authEls.error.hidden = false;
  } finally {
    authEls.submit.disabled = false;
  }
});

authEls.logout.addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  location.reload();
});

// An expired session mid-use shows the sign-in screen instead of failing silently.
const rawFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const res = await rawFetch(input, init);
  if (res.status === 401 && !String(input).startsWith("/api/auth/")) showLogin();
  return res;
};

async function startApp() {
  const res = await fetch("/api/auth/me");
  if (!res.ok) {
    showLogin();
    return;
  }
  const { username } = await res.json();
  currentUser = username;
  authEls.userName.textContent = username;
  authEls.userMenu.hidden = false;
  loadMappings();
  // The household decides the default view, so it loads before the table does.
  await loadHousehold();
  loadFilters().then(loadTransactions);
}

startApp();

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
      loadBalance();
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
    // category/is_shared edits can change the settlement math - keep
    // the always-visible balance in sync with every inline edit, not
    // just uploads and manual adds.
    loadBalance();
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
  if (!tr || tr.classList.contains("readonly")) return;
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
      loadBalance();
    }
  } catch (err) {
    renderAddResult("Couldn't reach the server.", true);
  } finally {
    els.addSubmit.disabled = false;
    els.addStatus.textContent = "";
  }
});


// --- tabs and settlement controls ------------------------------------------

function showTab(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.tab === name);
  }
  document.getElementById("tab-transactions").hidden = name !== "transactions";
  document.getElementById("tab-household").hidden = name !== "household";
}

document.querySelector(".tabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab");
  if (tab) showTab(tab.dataset.tab);
});

els.balanceWidget.addEventListener("click", () => showTab("household"));

for (const el of [els.settleStart, els.settleEnd]) {
  el.addEventListener("change", loadSettlementPanel);
}
