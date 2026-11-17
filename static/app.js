"use strict";

const $ = id => document.getElementById(id);
const input = $("message");
const messages = $("messages");
const groups = {
  all: ["All services", ""],
  accounts: ["Accounts", "≡"],
  transfers: ["Transfers", "→"],
  lending: ["Loans & deposits", "◇"],
  cards: ["Cards", "▤"],
  support: ["Support", "?"],
};
const catalogue = {
  account_balance_enquiry: ["accounts", "See available and ledger balances"],
  transaction_history_request: ["accounts", "Filter recent credits and debits"],
  fund_transfer_initiation: ["transfers", "Send to a registered demo beneficiary"],
  loan_eligibility_enquiry: ["lending", "Estimate an EMI and check sample criteria"],
  loan_emi_query: ["lending", "View your existing repayment details"],
  fixed_deposit_booking: ["lending", "Get a maturity quote and review a booking"],
  fixed_deposit_enquiry: ["lending", "See saved principal and maturity dates"],
  credit_card_statement_request: ["cards", "Open recorded statement entries"],
  credit_card_limit_enquiry: ["cards", "View available credit and reward points"],
  credit_card_payment_due_enquiry: ["cards", "Find the amount and payment date"],
  credit_card_limit_enhancement: ["cards", "Open a credit-limit review request"],
  block_card_request: ["cards", "Review and block the demo card"],
  fraud_alert_report: ["support", "Report an owned transaction"],
  grievance_registration: ["support", "Raise a case for review"],
  case_status_request: ["support", "Look up a case with its reference"],
};
const quickTasks = ["account_balance_enquiry", "fund_transfer_initiation", "fixed_deposit_booking", "case_status_request"];
const noFields = new Set(["account_balance_enquiry", "loan_emi_query", "fixed_deposit_enquiry",
  "credit_card_statement_request", "credit_card_limit_enquiry", "credit_card_payment_due_enquiry", "block_card_request"]);
const changes = new Set(["fund_transfer_initiation", "fixed_deposit_booking", "credit_card_limit_enhancement",
  "block_card_request", "fraud_alert_report", "grievance_registration"]);
const stepNames = {
  menu: "Choose a service", identity: "Choose profile", otp: "Verify code", payee: "Choose beneficiary",
  transfer_amount: "Enter amount", rail: "Choose rail", purpose: "Choose purpose", payee_check: "Check beneficiary",
  confirm: "Review and confirm", range: "Choose period", direction: "Choose direction", min_amount: "Filter amount",
  loan_type: "Choose loan type", loan_amount: "Enter principal", loan_tenure: "Enter tenure",
  fd_amount: "Enter principal", fd_tenure: "Choose tenure", limit_amount: "Enter requested limit",
  transaction_ref: "Choose transaction", description: "Describe issue", category: "Choose category",
  contact: "Choose contact method", case_ref: "Enter case reference",
};
const state = {session: null, reply: null, busy: false, pending: null, selected: null,
  activeProfile: null, group: "all", step: "menu", review: null, stepOptions: [], revision: 0};

function node(tag, text, cls) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (cls) item.className = cls;
  return item;
}

function button(label, cls, click) {
  const item = node("button", label, cls);
  item.type = "button";
  item.addEventListener("click", click);
  return item;
}

function row(parent, key, value) {
  const detail = node("dd");
  if (value instanceof HTMLElement) detail.append(value);
  else detail.textContent = value;
  const item = node("div");
  item.append(node("dt", key), detail);
  parent.append(item);
}

function rows(parent, pairs) {
  if (!pairs?.length) return;
  const list = node("dl", undefined, "rows");
  pairs.forEach(([key, value]) => row(list, key, value));
  parent.append(list);
}

function fill(value) {
  input.value = value;
  input.focus();
}

function appendMessage(who, response) {
  const item = node("div", undefined, "message " + (who === "You" ? "user" : "assistant"));
  item.append(node("span", who, "byline"));
  const bubble = node("div", undefined, "bubble");
  bubble.append(node("p", response.event === "review" ? "The review is ready below." : response.message));
  if (response.title && response.event !== "review") {
    const receipt = node("section", undefined, "receipt");
    receipt.append(node("strong", response.title));
    rows(receipt, response.rows);
    if (response.records?.length) {
      const list = node("ul", undefined, "records");
      response.records.forEach(record => list.append(node("li", record.join(" · "))));
      receipt.append(list);
    }
    bubble.append(receipt);
  }
  item.append(bubble);
  messages.append(item);
  while (messages.children.length > 80) messages.firstChild.remove();
  messages.scrollTop = messages.scrollHeight;
}

function selected() {
  return state.session?.demo_records.find(profile => profile.id === state.selected);
}

function renderProfile() {
  const profile = selected();
  const active = state.activeProfile;
  for (const id of ["profile", "assistant-profile"]) $(id).value = active?.id || state.selected || "";
  $("profile-badge").textContent = state.reply?.verified ? "Verified" : "Guest";
  $("profile-badge").classList.toggle("verified", Boolean(state.reply?.verified));
  $("profile-summary").textContent = active ? active.name + " · Savings •••• " + active.suffix :
    state.reply?.verified ? "The current demo profile is verified." : "Choose a sample customer to get started.";
  $("profile-action").textContent = state.reply?.verified ? "Check balance" : "Verify & check balance";
  $("switch-profile").hidden = !state.reply?.verified;
  const record = $("record");
  record.replaceChildren();
  if (!profile) return;
  row(record, "Customer ID", button(profile.id, "small-action", () => fill(profile.id)));
  row(record, "Demo mobile", button(profile.mobile, "small-action", () => fill(profile.mobile)));
  row(record, "Account suffix", profile.account.slice(-4));
  row(record, "Card suffix", profile.card);
}

function drawNavigation(view, focus = true) {
  $("overview-view").hidden = view !== "overview";
  $("assistant-view").hidden = view !== "assistant";
  document.querySelectorAll("nav [data-view]").forEach(control => {
    if (control.dataset.view === view) control.setAttribute("aria-current", "page");
    else control.removeAttribute("aria-current");
  });
  if (focus) (view === "overview" ? $("overview-title") : $("assistant-title")).focus();
  messages.scrollTop = messages.scrollHeight;
}

function renderServices() {
  const grid = $("service-grid");
  const filters = $("filters");
  grid.replaceChildren();
  filters.replaceChildren();
  if (!state.session) return;
  const matching = Object.entries(state.session.services).filter(([key]) =>
    state.group === "all" || catalogue[key]?.[0] === state.group);
  $("service-count").textContent = matching.length + (matching.length === 1 ? " service" : " services");
  for (const [key, [label]] of Object.entries(groups)) {
    const filter = button(label, "filter", () => {
      state.group = key;
      renderServices();
      $("filters").children[Object.keys(groups).indexOf(key)].focus();
    });
    filter.setAttribute("aria-pressed", String(key === state.group));
    filters.append(filter);
  }
  for (const [key, label] of matching) {
    const [group, description] = catalogue[key] || ["accounts", ""];
    const control = button(undefined, "service", () => startTask(key));
    control.setAttribute("aria-label", label);
    const icon = node("span", groups[group][1], "service-icon " + group);
    const text = node("span");
    const arrow = node("b", "→");
    icon.setAttribute("aria-hidden", "true");
    arrow.setAttribute("aria-hidden", "true");
    text.append(node("strong", label), node("small", description));
    control.append(icon, text, arrow);
    grid.append(control);
  }
  syncButtons();
}

function shortcuts(text) {
  return Object.keys(state.session.services).find(key => state.session.services[key] === text);
}

function renderChoices() {
  const choices = $("choices");
  choices.replaceChildren();
  if (!state.session) return;
  let options;
  if (state.step === "menu") {
    options = quickTasks.map(task => state.session.services[task]);
  } else {
    options = (state.review?.options || state.stepOptions).filter(label => !shortcuts(label));
    if (!options.includes("Cancel")) options.push("Cancel");
  }
  for (const label of options) {
    const cls = "choice" + (label === "Confirm" ? " confirm" : "");
    choices.append(button(label, cls, () => submit(label, state.step === "menu" ? shortcuts(label) : null)));
  }
  if (state.step === "identity" && selected()) {
    const id = selected().id;
    choices.prepend(button("Use " + id, "choice", () => submit(id)));
  }
  input.placeholder = state.step === "otp" ? "Enter six-digit demo code" : "Type a banking request";
  input.inputMode = ["otp", "payee_check"].includes(state.step) ? "numeric" : "text";
  syncButtons();
}

function renderTask(response) {
  const intent = response.trace?.intent;
  const task = state.session.services[intent];
  $("resume-banner").hidden = state.step === "menu";
  $("resume-title").textContent = task || "Request in progress";
  $("task-name").textContent = task || "Choose a service";
  const progress = $("request-steps");
  progress.replaceChildren();
  if (!task || (state.step === "menu" && !response.title)) return;
  const stages = ["Verify profile"];
  if (!noFields.has(intent)) stages.push("Enter details");
  if (changes.has(intent)) stages.push("Review & confirm");
  const logged = state.step === "menu";
  const active = logged ? stages.length : ["identity", "otp"].includes(state.step) ? 0 :
    state.step === "confirm" ? stages.length - 1 : 1;
  stages.forEach((stage, i) => {
    const step = node("li", undefined, i < active ? "done" : undefined);
    const mark = node("i", i < active ? "✓" : String(i + 1));
    mark.setAttribute("aria-hidden", "true");
    if (i === active) step.setAttribute("aria-current", "step");
    if (i < active && response.verified) step.setAttribute("aria-label", stage + " complete");
    step.append(mark, node("span", stage));
    progress.append(step);
  });
}

function renderTrace(response) {
  const trace = $("trace");
  trace.replaceChildren();
  if (!response.trace) return;
  const {intent, source, confidence, elapsed_ms} = response.trace;
  row(trace, "Intent", intent.replaceAll("_", " "));
  row(trace, "Routing", source);
  if (confidence !== null) row(trace, "Model score", (confidence * 100).toFixed(1) + "%");
  row(trace, "Event", response.event.replaceAll("_", " "));
  row(trace, "Server turn", elapsed_ms.toFixed(2) + " ms");
}

function renderReview() {
  const review = $("review");
  const draft = state.review;
  review.hidden = !draft;
  review.replaceChildren();
  if (!draft) return;
  review.append(node("h3", draft.title));
  rows(review, draft.rows);
}

function applyReply(response) {
  const nextStep = response.step || "menu";
  if (state.step !== nextStep || response.event !== "invalid_field") state.stepOptions = response.options;
  state.reply = response;
  if (!response.verified) state.activeProfile = null;
  state.step = nextStep;
  if (response.event === "review") state.review = response;
  else if (state.step !== "confirm" || !response.verified) state.review = null;
  $("step").textContent = stepNames[state.step] || state.step.replaceAll("_", " ");
  $("step").classList.toggle("verified", Boolean(response.verified));
  $("identity-panel").hidden = !["identity", "otp"].includes(state.step);
  $("inbox").hidden = state.step !== "otp";
  renderProfile();
  renderTask(response);
  renderChoices();
  renderReview();
  renderTrace(response);
}

function syncButtons() {
  input.disabled = state.busy || !state.session;
  $("send").disabled = input.disabled;
  $("retry").disabled = state.busy;
  $("reset").disabled = state.busy || !state.session;
  $("switch-profile").disabled = state.busy;
  $("code").disabled = state.busy;
  for (const id of ["profile", "assistant-profile"]) $(id).disabled =
    state.busy || !state.session || Boolean(state.reply?.verified);
  for (const area of ["choices", "service-grid"]) {
    $(area).querySelectorAll("button").forEach(item => { item.disabled = state.busy; });
  }
  document.querySelectorAll("[data-service]").forEach(item => { item.disabled = state.busy || !state.session; });
}

async function request(path, payload) {
  const options = payload === undefined ? {} : {method: "POST",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)};
  const result = await fetch(path, options);
  const body = await result.json();
  if (!result.ok) {
    const problem = new Error(body.error || "The local request could not be completed.");
    problem.status = result.status;
    throw problem;
  }
  return body;
}

function showError(text, retry = false) {
  $("error").textContent = text;
  $("error").hidden = !text;
  $("retry").hidden = !retry;
}

function startTask(key) {
  if (!state.session || state.busy) return;
  drawNavigation("assistant");
  if (state.step !== "menu") {
    showError("Finish the current request or choose Cancel to start another.");
    return;
  }
  return submit(state.session.services[key], key);
}

async function submit(text, shortcut = null, reuse = false) {
  if (state.busy || !text.trim() || !state.session) return;
  state.busy = true;
  state.revision++;
  syncButtons();
  showError("");
  if (!reuse) state.pending = {text, shortcut, request_id: crypto.randomUUID()};
  try {
    const response = await request("/api/chat", state.pending);
    const wasVerified = Boolean(state.reply?.verified);
    input.value = "";
    state.pending = null;
    if (wasVerified && !response.verified) messages.replaceChildren();
    appendMessage("You", {message: response.echo});
    appendMessage("Assistant", response);
    applyReply(response);
    if (response.verified && !state.activeProfile) {
      try {
        const snapshot = await request("/api/session");
        if (snapshot.active_profile) {
          state.activeProfile = snapshot.active_profile;
          state.selected = state.activeProfile.id;
          renderProfile();
        } else if (!snapshot.reply.verified) {
          replaceConversation(snapshot);
        }
      } catch {
        // The completed turn and its receipt remain visible if the profile refresh fails.
      }
    }
  } catch (problem) {
    const retry = Boolean(state.pending && (!problem.status || problem.status >= 500));
    showError(problem.message, retry);
    if (!retry) state.pending = null;
  } finally {
    state.busy = false;
    syncButtons();
    refreshInbox();
  }
}

async function refreshInbox() {
  if (!state.session || state.step !== "otp" || state.busy) {
    if (state.step !== "otp") $("code").hidden = true;
    return;
  }
  const revision = state.revision;
  try {
    const inbox = await request("/api/demo-inbox");
    if (state.step !== "otp" || revision !== state.revision) return;
    const code = $("code");
    code.hidden = !inbox.code;
    code.textContent = inbox.code || "";
    code.setAttribute("aria-label", inbox.code ? "Use demo code " + inbox.code : "Use demo code");
    $("inbox-status").textContent = inbox.code ? "Select the current code · " + inbox.remaining + "s remaining" :
      "No current code. Check the demo identity or select Resend code.";
  } catch {
    if (revision === state.revision) $("code").hidden = true;
  }
}

function replaceConversation(snapshot) {
  state.activeProfile = snapshot.active_profile;
  if (state.activeProfile) state.selected = state.activeProfile.id;
  state.review = snapshot.review;
  state.stepOptions = [];
  messages.replaceChildren();
  appendMessage("Assistant", snapshot.reply);
  applyReply(snapshot.reply);
}

async function refreshVerification() {
  if (!state.session || !state.reply?.verified || state.busy) return;
  const revision = state.revision;
  try {
    const snapshot = await request("/api/session");
    if (revision !== state.revision || state.busy) return;
    if (!snapshot.reply.verified || (state.activeProfile && snapshot.active_profile?.id !== state.activeProfile.id)) {
      state.pending = null;
      showError("");
      replaceConversation(snapshot);
    } else if (snapshot.active_profile && !state.activeProfile) {
      state.activeProfile = snapshot.active_profile;
      state.selected = state.activeProfile.id;
      renderProfile();
    }
  } catch {
    // A failed status check leaves the service available for a deliberate retry.
  }
}

function setConnection(text, status) {
  const indicator = $("connection");
  indicator.className = "connection " + status;
  const dot = node("i");
  dot.setAttribute("aria-hidden", "true");
  indicator.replaceChildren(dot, node("span", text));
}

async function loadSession(reset = false) {
  if (state.busy) return;
  state.busy = true;
  state.revision++;
  syncButtons();
  showError("");
  $("startup-error").hidden = true;
  $("reconnect").hidden = true;
  try {
    const snapshot = reset ? await request("/api/reset", {}) : await request("/api/session");
    state.session = snapshot;
    state.pending = null;
    state.selected = state.selected || snapshot.demo_records[0]?.id;
    for (const select of [$("profile"), $("assistant-profile")]) {
      select.replaceChildren();
      for (const profile of snapshot.demo_records) {
        const option = node("option", profile.name + " · " + profile.id);
        option.value = profile.id;
        select.append(option);
      }
    }
    $("model-name").textContent = snapshot.model;
    replaceConversation(snapshot);
    renderServices();
    setConnection("Local demo ready", "ready");
    if (!reset && state.step !== "menu") drawNavigation("assistant", false);
  } catch (problem) {
    setConnection("Local connection failed", "offline");
    $("startup-error").textContent = problem.message;
    $("startup-error").hidden = false;
    $("reconnect").hidden = false;
  } finally {
    state.busy = false;
    syncButtons();
    refreshInbox();
  }
}

document.querySelectorAll("[data-view]").forEach(item => {
  item.addEventListener("click", () => drawNavigation(item.dataset.view));
});
document.querySelectorAll("[data-service]").forEach(item => {
  item.addEventListener("click", () => startTask(item.dataset.service));
});
for (const id of ["profile", "assistant-profile"]) {
  $(id).addEventListener("change", event => {
    state.selected = event.currentTarget.value;
    renderProfile();
    if (state.reply) renderChoices();
  });
}
$("composer").addEventListener("submit", event => { event.preventDefault(); submit(input.value); });
$("reset").addEventListener("click", () => loadSession(true));
$("switch-profile").addEventListener("click", async () => { await loadSession(true); $("profile").focus(); });
$("reconnect").addEventListener("click", () => loadSession());
$("retry").addEventListener("click", () => {
  if (state.pending) submit(state.pending.text, state.pending.shortcut, true);
});
$("code").addEventListener("click", () => submit($("code").textContent));
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshVerification(); });
loadSession();
setInterval(refreshInbox, 1000);
setInterval(refreshVerification, 20000);
