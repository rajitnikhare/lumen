"use strict";

const $ = (id) => document.getElementById(id);
const labels = {overview: "My day", assistant: "Assistant", saved: "Saved", reminders: "Reminders", research: "Research", settings: "Settings & privacy"};
let csrf = "";
let data = {document: [], note: [], draft: [], reminder: [], chat: [], research: [], mail_message: [], candidate_reminder: []};
let currentPage = "assistant";
let currentSavedTab = "documents";
let pendingApproval = null;
let toastTimer;
let unlocked = false;
let sessionEpoch = 0;
let busy = 0;
let chatMode = "ask";
let sharedFile = null;
let sharedDocument = null;
let voiceTicket = null;
let sharingTicket = null;
let chatInFlight = false;
const compact = new URLSearchParams(window.location.search).get("desktop") === "1";
const nativeBridge = window.webkit?.messageHandlers?.lumen;
if (compact) document.body.classList.add("compact");
$("voice-button").hidden = !nativeBridge;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").className = error ? "error" : "";
  $("toast").hidden = false;
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 10000 : 4500);
}

async function api(path, options = {}) {
  const epoch = sessionEpoch;
  const wasUnlocked = unlocked;
  const headers = {"X-Lumen-CSRF": csrf, ...options.headers};
  if (options.body && typeof options.body === "string") headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers, credentials: "same-origin"});
  let result;
  try { result = await response.json(); }
  catch { throw new Error("The server returned an unreadable response. Check the terminal."); }
  if (!response.ok) {
    if (response.status === 423) showVault();
    const detail = Array.isArray(result.detail) ? result.detail.map((item) => `${item.loc.at(-1)}: ${item.msg}`).join("; ") : result.detail;
    throw new Error(detail || `Request failed (${response.status}).`);
  }
  if (wasUnlocked && epoch !== sessionEpoch) throw new Error("Workspace locked while this request was running.");
  return result;
}

function json(method, body) { return {method, body: JSON.stringify(body)}; }

function showPanel(id, focusId) {
  $(id).hidden = false;
  if (focusId) $(focusId).focus();
}

function hidePanel(id) {
  $(id).hidden = true;
}

function selectSavedTab(tab) {
  currentSavedTab = tab;
  for (const button of document.querySelectorAll(".saved-tabs [data-saved-tab]")) {
    const selected = button.dataset.savedTab === tab;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-selected", String(selected));
  }
  for (const panel of document.querySelectorAll(".saved-panel")) panel.hidden = panel.id !== `saved-${tab}`;
}

function filterText(id) {
  return ($(id)?.value || "").trim().toLowerCase();
}

function showVault() {
  voiceTicket = null;
  sharingTicket = null;
  nativeBridge?.postMessage({action: "voiceShortcutAvailability", enabled: "false"});
  nativeBridge?.postMessage({action: "cancelVoice"});
  unlocked = false;
  sessionEpoch += 1;
  data = {document: [], note: [], draft: [], reminder: [], chat: [], research: [], mail_message: [], candidate_reminder: []};
  pendingApproval = null;
  sharedFile = null;
  sharedDocument = null;
  for (const dialog of document.querySelectorAll("dialog")) dialog.close();
  $("workspace").hidden = true;
  $("vault-screen").hidden = false;
  for (const form of document.querySelectorAll("#workspace form")) form.reset();
  $("inline-draft-form").reset();
  for (const input of document.querySelectorAll("#workspace input[type=hidden]")) input.value = "";
  for (const id of ["document-list", "note-list", "draft-list", "reminder-list", "research-list", "chat-log", "upcoming", "recent", "stats", "detail-body", "detail-title", "approval-payload", "approval-warning", "mail-message-list", "candidate-reminder-list"]) $(id).replaceChildren();
  for (const id of ["upload-form", "note-form", "draft-editor", "reminder-form"]) hidePanel(id);
  for (const id of ["document-search", "note-search", "draft-search", "reminder-search", "mail-search"]) { const node = $(id); if (node) node.value = ""; }
  $("candidate-reminders").hidden = true;
  selectSavedTab("documents");
  $("passphrase").value = "";
  $("passphrase-label").textContent = "Vault passphrase";
  $("unlock-button").textContent = "Unlock my workspace";
  $("vault-hint").textContent = "Unlock to resume. The passphrase is never sent to an AI or search service.";
  $("shared-context").hidden = true;
  $("shared-context").open = false;
  $("shared-file-preview").hidden = true;
  $("chat-tool-feedback").hidden = true;
  $("chat-progress").hidden = true;
  $("model-setup").hidden = true;
  $("shared-file-name").textContent = "";
  $("chat-tool-feedback").textContent = "";
  $("mail-check-status").textContent = "";
}

async function session() {
  const result = await api("/api/session");
  csrf = result.csrf;
  if (result.unlocked) {
    unlocked = true;
    nativeBridge?.postMessage({action: "voiceShortcutAvailability", enabled: "true"});
    $("vault-screen").hidden = true;
    $("workspace").hidden = false;
    await refresh();
    navigate(currentPage);
    await ensureModel();
  } else {
    showVault();
    $("passphrase-label").textContent = result.initialized ? "Vault passphrase" : "Create a vault passphrase";
    $("passphrase").autocomplete = result.initialized ? "current-password" : "new-password";
    $("passphrase").minLength = result.initialized ? 1 : 12;
    $("unlock-button").textContent = result.initialized ? "Unlock my workspace" : "Create my private workspace";
    $("vault-hint").textContent = result.initialized ? "Your workspace is locked. Nothing is available to the assistant until you unlock." : "Choose at least 12 characters. There is no passphrase recovery. Your vault is stored only on this computer.";
  }
}

function navigate(page) {
  currentPage = page;
  for (const section of document.querySelectorAll(".page")) section.hidden = section.id !== `page-${page}`;
  for (const button of document.querySelectorAll(".sidebar [data-page]")) button.classList.toggle("active", button.dataset.page === page);
  $("page-label").textContent = labels[page];
  $("compact-page").value = page;
  if (page === "settings") run($("page-settings"), async () => { await Promise.all([loadSettings(), loadMailAccount()]); });
}

async function ensureModel() {
  if (!unlocked) return;
  try {
    const settings = await api("/api/settings");
    const {models} = await api("/api/models");
    if (settings.model) {
      if (!models.includes(settings.model)) throw new Error(`The configured model ${settings.model} is unavailable. Open Ollama or choose an installed model in Settings.`);
      $("model-setup").hidden = true;
      return;
    }
    if (!models.length) throw new Error("No local model is installed. Open Ollama and download a model, then try again.");
    const preferred = ["qwen3:4b", "llama3.2:3b", "llama3:latest", "qwen3:8b"];
    const model = preferred.find((name) => models.includes(name)) || models[0];
    await api("/api/settings", json("PUT", {model}));
    $("model-setup").hidden = true;
    toast(`Ready to help using ${model}, on your Mac.`);
  } catch (error) {
    if (!unlocked) return;
    $("model-setup-text").textContent = `Local AI isn't ready: ${error.message} Notes and reminders still work without it. `;
    $("model-setup").hidden = false;
    $("open-ollama").hidden = !nativeBridge;
  }
}

function changeChatMode(mode) {
  chatMode = mode;
  $("chat-form").dataset.mode = mode;
  for (const button of document.querySelectorAll("[data-chat-mode]")) {
    button.classList.toggle("selected", button.dataset.chatMode === mode);
    button.setAttribute("aria-pressed", String(button.dataset.chatMode === mode));
  }
  $("inline-reminder").hidden = mode !== "reminder";
  $("inline-due").required = mode === "reminder";
  $("inline-draft").hidden = mode !== "draft";
  $("inline-note").hidden = mode !== "note";
  $("shared-file-consent").required = mode === "ask" && Boolean(sharedFile) && !sharedDocument;
  $("chat-message").maxLength = mode === "reminder" ? 4000 : 8000;
  $("use-history").disabled = mode !== "ask";
  $("chat-message-label").textContent = {ask: "What is on your mind?", note: "What would you like to save?", reminder: "What should I remind you about?", draft: "What would you like the email to say?"}[mode];
  $("chat-message").placeholder = {ask: "Help me organize this in Notes, or suggest my next step...", note: "A thought, a plan, something to keep...", reminder: "Call the dentist, finish a project, pack for a trip...", draft: "Tell me the purpose, key details, and tone..."}[mode];
  $("chat-submit").textContent = {ask: "Ask Lumen", note: "Save note", reminder: "Save reminder", draft: "Create draft"}[mode];
  $("chat-tool-feedback").hidden = true;
}

function feedback(text) {
  $("chat-tool-feedback").textContent = text;
  $("chat-tool-feedback").hidden = false;
}

function setSharedFile(file) {
  if (!unlocked) throw new Error("Unlock your workspace before sharing a file.");
  if (!file.size || file.size > 12 * 1024 * 1024) throw new Error("Choose a nonempty file no larger than 12 MiB.");
  sharedFile = file;
  sharedDocument = null;
  changeChatMode("ask");
  $("shared-context").hidden = false;
  $("shared-context").open = true;
  $("shared-file-preview").hidden = false;
  $("shared-file-name").textContent = `Selected file: ${file.name}. It is not imported or sent to AI until you allow access and ask.`;
  $("shared-file-consent").checked = false;
  $("shared-file-consent").required = true;
  $("shared-file-consent").disabled = false;
  $("file-consent-label").hidden = false;
  if (!$("chat-message").value.trim()) $("chat-message").value = "Suggest how I can use or organize this file.";
}

function clearSharedContext() {
  const hadSavedDocument = Boolean(sharedDocument);
  $("shared-text").value = "";
  $("shared-app").value = "";
  $("chat-file").value = "";
  $("shared-file-consent").checked = false;
  $("shared-file-consent").required = false;
  sharedFile = null;
  sharedDocument = null;
  $("shared-context").hidden = true;
  $("shared-context").open = false;
  $("shared-file-preview").hidden = true;
  if (hadSavedDocument) toast("Removed from this request. The library copy remains; revoke access or delete it in Documents.");
}

async function run(element, operation) {
  const controls = element ? [...element.querySelectorAll("button")] : [];
  if (element?.tagName === "BUTTON") controls.push(element);
  const enabled = controls.filter((control) => !control.disabled);
  enabled.forEach((control) => { control.disabled = true; });
  busy += 1;
  try { await operation(); }
  catch (error) { toast(error.message || "Something went wrong. Check the server terminal.", true); }
  finally { busy -= 1; enabled.forEach((control) => { control.disabled = false; }); }
}

async function refresh() {
  const epoch = sessionEpoch;
  const result = await api("/api/dashboard");
  if (epoch !== sessionEpoch || !unlocked) return;
  data = result;
  render();
}

function empty(container, title, subtitle) {
  const block = el("div", "empty");
  block.append(el("div", "empty-icon", "\u2727"), el("strong", "", title), el("span", "", subtitle));
  container.append(block);
}

function chatEmptyState(container) {
  const block = el("div", "empty");
  block.append(el("div", "empty-icon", "\u2727"), el("strong", "", "A calm place to think."), el("span", "", "Ask about an authorized document, a saved note, or a general question."));
  const quick = el("div", "quick-actions");
  for (const [label, mode] of [["Ask a question", "ask"], ["Save a note", "note"], ["Set a reminder", "reminder"]]) {
    quick.append(action(label, () => { changeChatMode(mode); $("chat-message").focus(); }));
  }
  block.append(quick);
  container.append(block);
}

function dateLabel(date) {
  return new Date(date).toLocaleString(undefined, {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
}

function localDate(date) {
  const value = new Date(date);
  const adjusted = new Date(value.getTime() - value.getTimezoneOffset() * 60000);
  return adjusted.toISOString().slice(0, 16);
}

function action(label, callback, danger = false) {
  const button = el("button", `secondary${danger ? " danger-button" : ""}`, label);
  button.type = "button";
  button.addEventListener("click", () => run(button, callback));
  return button;
}

function card(title, meta, preview, badge, off = false) {
  const node = el("article", "record-card");
  const top = el("div", "record-top");
  const copy = el("div");
  copy.append(el("h3", "", title), el("div", "meta", meta));
  top.append(copy);
  if (badge) top.append(el("span", `permission-pill${off ? " off" : ""}`, badge));
  node.append(top);
  if (preview) node.append(el("div", "record-preview", preview));
  const actions = el("div", "record-actions");
  node.append(actions);
  return {node, actions};
}

function sourceChips(sources, container) {
  const list = el("div", "source-list");
  for (const source of sources) {
    const label = `[${source.citation}] ${source.title}${source.location ? " - " + source.location : ""}`;
    if (source.url) {
      const link = el("a", "source-chip", label);
      const parsed = new URL(source.url);
      if (!["http:", "https:"].includes(parsed.protocol)) continue;
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.title = "Open external website (this contacts the source website)";
      list.append(link);
    } else {
      const button = action(label, () => showSource(source));
      button.className = "source-chip";
      list.append(button);
    }
  }
  if (sources.length) container.append(list);
}

function detail(title, text, sources = []) {
  $("detail-title").textContent = title;
  $("detail-body").replaceChildren(el("div", "detail-text", text));
  sourceChips(sources, $("detail-body"));
  $("detail-dialog").showModal();
}

async function showSource(source) {
  const kind = source.kind || "document";
  const item = await api(`/api/items/${kind}/${source.record_id}`);
  const text = kind === "document" ? item.chunks.map((chunk) => `${chunk.location}\n${chunk.text}`).join("\n\n") : item.body;
  detail(item.title, text);
}

function renderOverview() {
  $("stats").replaceChildren();
  const stats = [
    ["Documents", data.document.length, "\u25a4"],
    ["Saved notes", data.note.length, "\u270e"],
    ["Email drafts", data.draft.length, "\u2709"],
    ["Open reminders", data.reminder.filter((item) => !item.done).length, "\u25f7"]
  ];
  for (const [label, count, icon] of stats) {
    const node = el("div", "stat-card");
    const copy = el("div");
    copy.append(el("div", "stat-label", label), el("div", "stat-value", String(count).padStart(2, "0")));
    node.append(copy, el("span", "stat-icon", icon));
    $("stats").append(node);
  }
  $("upcoming").replaceChildren();
  const upcoming = data.reminder.filter((item) => !item.done).sort((a, b) => new Date(a.due_at) - new Date(b.due_at)).slice(0, 4);
  if (!upcoming.length) empty($("upcoming"), "A little breathing room.", "Your next reminders will show up here.");
  for (const item of upcoming) {
    const row = el("div", "row-item");
    const copy = el("div", "row-copy");
    const overdue = new Date(item.due_at) <= new Date();
    copy.append(el("strong", "", item.title), el("span", "", `${overdue ? "Due - " : ""}${dateLabel(item.due_at)}`));
    row.append(el("span", "row-symbol", "\u25f7"), copy);
    $("upcoming").append(row);
  }
  $("recent").replaceChildren();
  const recent = [...data.note.map((item) => ({...item, type: "Note"})), ...data.document.map((item) => ({...item, type: "Document"}))]
    .sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4);
  if (!recent.length) empty($("recent"), "A fresh page.", "Add a document or save your first thought.");
  for (const item of recent) {
    const row = el("div", "row-item");
    const copy = el("div", "row-copy");
    copy.append(el("strong", "", item.title), el("span", "", `${item.type} - ${item.authorized ? "AI access allowed" : "Private storage only"}`));
    row.append(el("span", "row-symbol", item.type === "Note" ? "\u270e" : "\u25a4"), copy);
    $("recent").append(row);
  }
}

function render() {
  renderOverview();
  const documentFilter = filterText("document-search");
  $("document-list").replaceChildren();
  const documents = data.document.filter((item) => item.title.toLowerCase().includes(documentFilter));
  if (!documents.length) empty($("document-list"), data.document.length ? "No matching documents." : "Your library starts with a choice.", data.document.length ? "Try a different search term." : "Add a document above. AI access is off unless you enable it.");
  for (const item of documents) {
    const {node, actions} = card(item.title, `${item.characters.toLocaleString()} indexed characters (includes overlap) - ${dateLabel(item.created_at)}`, item.summary ? item.summary.slice(0, 450) : "Ready when you are. Summarize locally after authorizing access.", item.authorized ? "AI access allowed" : "Private storage only", !item.authorized);
    actions.append(action("View extracted text", async () => showSource({record_id: item.id, kind: "document"})));
    actions.append(action(item.authorized ? "Revoke AI access" : "Authorize AI access", () => changeAccess("document", item)));
    if (item.authorized) actions.append(action("Summarize / refocus", () => summaryDialog(item)));
    if (item.summary) actions.append(action("Read summary", () => detail(item.title, item.summary, item.summary_sources)));
    actions.append(action("Delete", () => deletion("document", item.id), true));
    $("document-list").append(node);
  }
  const noteFilter = filterText("note-search");
  $("note-list").replaceChildren();
  const notes = data.note.filter((item) => item.title.toLowerCase().includes(noteFilter) || item.body.toLowerCase().includes(noteFilter));
  if (!notes.length) empty($("note-list"), data.note.length ? "No matching notes." : "Keep something useful.", data.note.length ? "Try a different search term." : "Preferences are ordinary notes you can inspect, change, or delete.");
  for (const item of notes) {
    const {node, actions} = card(item.title, `${item.category === "preference" ? "Preference / correction" : "Personal note"} - ${dateLabel(item.updated_at)}`, item.body.slice(0, 500), item.authorized ? "In Lumen's memory" : "Private storage only", !item.authorized);
    actions.append(action("Edit", () => { editNote(item); showPanel("note-form", "note-title"); }), action(item.authorized ? "Revoke AI access" : "Authorize AI access", () => changeAccess("note", item)), action("Delete", () => deletion("note", item.id), true));
    $("note-list").append(node);
  }
  const draftFilter = filterText("draft-search");
  $("draft-list").replaceChildren();
  const drafts = data.draft.filter((item) => (item.subject || "").toLowerCase().includes(draftFilter) || (item.recipient || "").toLowerCase().includes(draftFilter));
  if (!drafts.length) empty($("draft-list"), data.draft.length ? "No matching drafts." : "The right words are a draft away.", data.draft.length ? "Try a different search term." : "Use the local AI or write one yourself. Nothing is sent.");
  for (const item of drafts) {
    const {node, actions} = card(item.subject || "Untitled email", `To: ${item.recipient || "Not specified"} - ${dateLabel(item.updated_at)}`, item.body.slice(0, 450), "Draft only");
    actions.append(action("Edit draft", () => { editDraft(item); showPanel("draft-editor", "draft-recipient"); }), action("Copy reviewed text", async () => { await navigator.clipboard.writeText(`To: ${item.recipient}\nSubject: ${item.subject}\n\n${item.body}`); toast("Copied to your system clipboard. Other apps may access clipboard contents."); }), action("Delete", () => deletion("draft", item.id), true));
    $("draft-list").append(node);
  }
  const candidates = data.candidate_reminder || [];
  $("candidate-reminders").hidden = candidates.length === 0;
  $("candidate-reminder-list").replaceChildren();
  for (const item of candidates) {
    const {node, actions} = card(item.title, dateLabel(item.due_at), item.details, "Suggested from email");
    actions.append(
      action("Accept", async () => {
        await api(`/api/candidate-reminders/${item.id}/accept`, json("POST", {}));
        await refresh();
        toast(`Reminder "${item.title}" saved.`);
      }),
      action("Edit before accepting", () => {
        editReminder({candidateId: item.id, title: item.title, due_at: item.due_at, details: item.details});
        showPanel("reminder-form", "reminder-title");
      }),
      action("Discard", async () => {
        await api(`/api/candidate-reminders/${item.id}`, {method: "DELETE"});
        await refresh();
        toast("Suggestion discarded.");
      }, true)
    );
    $("candidate-reminder-list").append(node);
  }
  const reminderFilter = filterText("reminder-search");
  $("reminder-list").replaceChildren();
  const reminders = [...data.reminder].filter((item) => item.title.toLowerCase().includes(reminderFilter)).sort((a, b) => Number(a.done) - Number(b.done) || new Date(a.due_at) - new Date(b.due_at));
  if (!reminders.length) empty($("reminder-list"), data.reminder.length ? "No matching reminders." : "One less thing to hold in your head.", data.reminder.length ? "Try a different search term." : "Add a reminder with an exact date and time.");
  for (const item of reminders) {
    const due = new Date(item.due_at) <= new Date();
    const {node, actions} = card(item.title, dateLabel(item.due_at), item.details, item.done ? "Completed" : due ? "Due now" : "Upcoming");
    actions.append(action("Edit", () => { editReminder(item); showPanel("reminder-form", "reminder-title"); }), action(item.done ? "Reopen" : "Mark complete", async () => { await api(`/api/reminders/${item.id}`, json("PUT", {...reminderFields(item), done: !item.done})); await refresh(); toast(item.done ? "Reminder reopened." : "Reminder completed."); }), action("Delete", () => deletion("reminder", item.id), true));
    $("reminder-list").append(node);
  }
  const mailFilter = filterText("mail-search");
  $("mail-message-list").replaceChildren();
  const mails = data.mail_message.filter((item) => item.subject.toLowerCase().includes(mailFilter) || item.sender.toLowerCase().includes(mailFilter));
  if (!mails.length) empty($("mail-message-list"), data.mail_message.length ? "No matching mail." : "No mail imported yet.", data.mail_message.length ? "Try a different search term." : "Connect a Gmail account in Settings, then click Check for new mail.");
  for (const item of mails) {
    const {node, actions} = card(item.subject, `From ${item.sender || "unknown sender"} - ${dateLabel(item.received_at)}`, item.preview ? item.preview.slice(0, 300) : "", item.authorized ? "AI access allowed" : "Private storage only", !item.authorized);
    actions.append(action("Read message", async () => showSource({record_id: item.id, kind: "mail_message"})));
    actions.append(action(item.authorized ? "Revoke AI access" : "Authorize AI access", () => changeAccess("mail_message", item)));
    actions.append(action("Delete", () => deletion("mail_message", item.id), true));
    $("mail-message-list").append(node);
  }
  renderChat();
  $("research-list").replaceChildren();
  if (!data.research.length) empty($("research-list"), "A wider view, on your terms.", "An external request happens only after you approve the exact query.");
  for (const item of data.research) {
    const {node, actions} = card(item.query, `Brave search snippets - ${dateLabel(item.created_at)}`, item.summary || item.error || "Sources retrieved; no local summary completed.", item.status === "complete" ? "Snippet comparison" : "Summary incomplete");
    sourceChips(item.sources, node);
    if (item.summary) actions.append(action("Save selected findings", () => { editNote({id: "", title: item.query, body: `${item.summary}\n\nReferences:\n${item.sources.map((source) => `[${source.citation}] ${source.url}`).join("\n")}`, authorized: false, category: "note"}); navigate("saved"); selectSavedTab("notes"); showPanel("note-form", "note-title"); }));
    actions.append(action("Delete", () => deletion("research", item.id), true));
    $("research-list").append(node);
  }
}

function renderChat() {
  $("chat-log").replaceChildren();
  if (!data.chat.length) chatEmptyState($("chat-log"));
  for (const item of [...data.chat].reverse()) {
    const turn = el("div", "chat-turn");
    turn.append(el("div", "chat-user", item.message));
    if (item.shared_text || item.app_name) {
      const context = el("details", "chat-shared");
      context.append(el("summary", "", `Context you shared${item.app_name ? " for " + item.app_name : ""}`), el("div", "detail-text", item.shared_text || "App name only."));
      turn.append(context);
    }
    const answer = el("div", "chat-answer");
    answer.append(el("span", "assistant-label", "LUMEN"), el("span", "", item.answer));
    if (item.retrieval) answer.append(el("p", "small muted", `${item.retrieval.method === "semantic" ? "Semantic" : "Keyword"} retrieval: ${item.retrieval.count} source excerpt(s)${item.retrieval.model ? " using " + item.retrieval.model : ""}.`));
    sourceChips(item.sources, answer);
    const controls = el("div", "record-actions");
    controls.append(action("Save selected text as a note", () => { editNote({id: "", title: item.message.slice(0, 200), body: item.answer, authorized: false, category: "note"}); navigate("saved"); selectSavedTab("notes"); showPanel("note-form", "note-title"); }), action("Delete turn", () => deletion("chat", item.id), true));
    answer.append(controls);
    turn.append(answer);
    $("chat-log").append(turn);
  }
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
}

async function changeAccess(kind, item) {
  await api(`/api/access/${kind}/${item.id}`, json("PUT", {authorized: !item.authorized}));
  await refresh();
  toast(item.authorized ? "AI access revoked. Previously saved summaries and conversations remain inspectable." : "Local AI access enabled.");
}

function editNote(item) {
  $("note-id").value = item.id || "";
  $("note-title").value = item.title || "";
  $("note-body").value = item.body || "";
  $("note-category").value = item.category || "note";
  $("note-authorized").checked = Boolean(item.authorized);
  $("note-title").focus();
}

function editDraft(item) {
  $("draft-id").value = item.id || "";
  $("draft-recipient").value = item.recipient || "";
  $("draft-subject").value = item.subject || "";
  $("draft-body").value = item.body || "";
  $("draft-body").focus();
}

function editReminder(item) {
  $("reminder-id").value = item.id || "";
  $("candidate-accept-id").value = item.candidateId || "";
  $("reminder-title").value = item.title || "";
  $("reminder-due").value = item.due_at ? localDate(item.due_at) : "";
  $("reminder-details").value = item.details || "";
  $("reminder-done").checked = Boolean(item.done);
  $("reminder-title").focus();
}

function reminderFields(item) {
  return {title: item.title, due_at: item.due_at, details: item.details, done: item.done};
}

function summaryDialog(item) {
  $("detail-title").textContent = `Summarize: ${item.title}`;
  const form = el("form");
  const label = el("label", "", "What should Lumen focus on?");
  label.htmlFor = "summary-focus";
  const input = el("textarea");
  input.id = "summary-focus";
  input.maxLength = 2000;
  input.rows = 3;
  input.value = "Key points, dates, decisions, and action items";
  const button = el("button", "primary", "Summarize locally");
  button.type = "submit";
  const hint = el("p", "small muted", "Long documents are summarized in sections. This can take several minutes.");
  form.append(label, input, hint, button);
  form.addEventListener("submit", (event) => { event.preventDefault(); run(form, async () => {
    const epoch = sessionEpoch;
    const result = await api(`/api/documents/${item.id}/summary`, json("POST", {focus: input.value}));
    if (epoch !== sessionEpoch || !unlocked) return;
    $("detail-body").replaceChildren(el("div", "detail-text", result.summary));
    sourceChips(result.sources, $("detail-body"));
    await refresh();
    toast("Summary saved locally. Check important points against the source.");
  }); });
  $("detail-body").replaceChildren(form);
  $("detail-dialog").showModal();
}

async function deletion(kind, id) {
  const approval = await api(`/api/delete/${kind}/${id}/preview`, {method: "POST"});
  showApproval(approval);
}

function showApproval(approval) {
  pendingApproval = approval;
  $("approval-title").textContent = approval.action === "search" ? "Approve this external search?" : "Delete this saved item?";
  $("approval-warning").textContent = approval.action === "search" ? approval.disclosure : "This removes the record from your local workspace. This is not secure erasure of disk blocks. Copies saved in other notes or conversations are not removed.";
  $("approval-payload").textContent = approval.action === "search" ? `Destination: ${approval.destination}\n\nExact public query:\n${approval.query}` : `${approval.kind}: ${approval.title}`;
  $("approval-confirm").textContent = approval.action === "search" ? "Approve & search" : "Approve deletion";
  $("approval-dialog").showModal();
}

async function cancelApproval() {
  const approval = pendingApproval;
  pendingApproval = null;
  $("approval-dialog").close();
  if (approval && unlocked) await api(`/api/approvals/${approval.id}`, {method: "DELETE"});
}

async function loadSettings() {
  const epoch = sessionEpoch;
  const settings = await api("/api/settings");
  if (epoch !== sessionEpoch || !unlocked) return;
  $("model-select").replaceChildren(el("option", "", settings.model || "Refresh to choose a model"));
  $("model-select").firstChild.value = settings.model;
  $("embedding-model").value = settings.embedding_model || "";
  $("brave-status").textContent = settings.brave_configured ? "An API key is saved in the encrypted vault. It is never returned to the browser." : "No key configured. Research is disabled until you save one.";
}

async function loadMailAccount() {
  const epoch = sessionEpoch;
  const account = await api("/api/mail/account");
  if (epoch !== sessionEpoch || !unlocked) return;
  $("mail-username").value = account.username || "";
  $("mail-account-status").textContent = account.configured
    ? `Connected as ${account.username}. The app password is saved encrypted and never returned to the browser.`
    : "No mail account connected. Imported mail and email-based reminder suggestions are off until you connect one.";
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-page]");
  if (button) {
    navigate(button.dataset.page);
    if (button.dataset.savedTab) selectSavedTab(button.dataset.savedTab);
  }
  const tab = event.target.closest(".saved-tabs [data-saved-tab]");
  if (tab) selectSavedTab(tab.dataset.savedTab);
  const tool = event.target.closest("[data-chat-mode]");
  if (tool) changeChatMode(tool.dataset.chatMode);
});
$("compact-page").addEventListener("change", () => navigate($("compact-page").value));
for (const id of ["document-search", "note-search", "draft-search", "reminder-search", "mail-search"]) {
  $(id)?.addEventListener("input", () => render());
}

$("unlock-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  const passphrase = $("passphrase").value;
  $("passphrase").value = "";
  await api("/api/unlock", json("POST", {passphrase}));
  await session();
  navigate(currentPage);
}); });

async function lockWorkspace() {
  if (!unlocked) return;
  await api("/api/lock", {method: "POST"});
  showVault();
  toast("Workspace locked.");
}
$("lock-button").addEventListener("click", () => run($("lock-button"), lockWorkspace));
$("compact-lock").addEventListener("click", () => run($("compact-lock"), lockWorkspace));

$("chat-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  const epoch = sessionEpoch;
  const message = $("chat-message").value.trim();
  if (!message) throw new Error("Write a message first.");
  const mode = chatMode;
  if (mode !== "ask" && (sharedFile || sharedDocument)) throw new Error("Attached files are used in Ask / suggest. Remove the attachment before using this action.");
  const sharedText = $("shared-text").value.trim();
  const appName = $("shared-app").value.trim();
  const noteBody = message + (sharedText ? `\n\nShared text${appName ? " from " + appName : ""}:\n${sharedText}` : "");
  $("chat-progress").textContent = ["ask", "draft"].includes(mode) ? "Thinking on your Mac..." : "Saving locally...";
  $("chat-progress").hidden = false;
  chatInFlight = true;
  try {
    if (mode === "note") {
      const saved = await api("/api/notes", json("POST", {title: message.split("\n")[0].slice(0, 120), body: noteBody, authorized: $("inline-note-memory").checked}));
      feedback(`Saved "${saved.title}"${saved.authorized ? " with AI memory enabled" : " privately, without AI memory"}.`);
      $("chat-message").value = "";
      clearSharedContext();
      await refresh();
      return;
    }
    if (mode === "reminder") {
      if (noteBody.length > 4000) throw new Error("Keep the reminder and shared text under 4,000 characters. Save longer details as a note.");
      const due = new Date($("inline-due").value);
      if (Number.isNaN(due.getTime())) throw new Error("Choose a date and time for your reminder.");
      const saved = await api("/api/reminders", json("POST", {title: message.split("\n")[0].slice(0, 120), details: noteBody, due_at: due.toISOString()}));
      feedback(`Saved "${saved.title}" for ${dateLabel(saved.due_at)}. Reminders appear in My day while Lumen is open and unlocked.`);
      $("chat-message").value = "";
      clearSharedContext();
      $("inline-due").value = "";
      await refresh();
      return;
    }
    if (mode === "draft") {
      const result = await api("/api/compose", json("POST", {recipient: $("inline-recipient").value, instructions: message, tone: "warm and professional", shared_text: sharedText, app_name: appName}));
      if (epoch !== sessionEpoch || !unlocked) return;
      $("inline-draft-to").value = result.recipient;
      $("inline-draft-subject").value = "";
      $("inline-draft-body").value = result.body;
      $("inline-draft-dialog").showModal();
      return;
    }
    if (sharedFile && !sharedDocument) {
      if (!$("shared-file-consent").checked) throw new Error("Allow local AI access before using the attached file.");
      const params = new URLSearchParams({filename: sharedFile.name, authorized: "true"});
      sharedDocument = await api(`/api/documents?${params}`, {method: "POST", body: sharedFile, headers: {"Content-Type": "application/octet-stream"}});
      $("shared-file-name").textContent = `${sharedFile.name} is now saved in Documents with AI access. Q&A uses selected excerpts.`;
      $("file-consent-label").hidden = true;
      $("shared-file-consent").required = false;
      await refresh();
    }
    const result = await api("/api/chat", json("POST", {message, use_history: $("use-history").checked, shared_text: $("shared-text").value, app_name: $("shared-app").value, document_ids: sharedDocument ? [sharedDocument.id] : []}));
    if (epoch !== sessionEpoch || !unlocked) return;
    $("chat-message").value = "";
    data.chat.unshift(result);
    renderChat();
    $("shared-context").open = false;
  } finally {
    chatInFlight = false;
    $("chat-progress").hidden = true;
  }
}); });

$("share-text").addEventListener("click", () => {
  $("shared-context").hidden = false;
  $("shared-context").open = true;
  $("shared-text").focus();
});
$("share-clipboard").addEventListener("click", () => run($("share-clipboard"), async () => {
  if (nativeBridge) { nativeBridge.postMessage({action: "shareClipboard", mode: chatMode}); return; }
  const mode = chatMode;
  const context = await window.lumenMac.prepareSharing();
  if (!context) throw new Error("Unlock before sharing clipboard text.");
  const text = await navigator.clipboard.readText();
  if (!text) throw new Error("The clipboard has no text. Copy a selection first.");
  if (text.length > 8000) throw new Error("Clipboard text is too long. Copy a smaller selection (up to 8,000 characters).");
  if (!await window.lumenMac.shareText({text, mode}, context)) throw new Error("The sharing session changed. Unlock and share again.");
}));
$("share-file").addEventListener("click", () => $("chat-file").click());
$("chat-file").addEventListener("change", () => run(null, async () => {
  if ($("chat-file").files[0]) setSharedFile($("chat-file").files[0]);
}));
$("shared-file-consent").addEventListener("invalid", () => { $("shared-context").open = true; });
$("remove-shared-file").addEventListener("click", () => {
  const hadSavedDocument = Boolean(sharedDocument);
  sharedFile = null; sharedDocument = null;
  $("chat-file").value = "";
  $("shared-file-consent").required = false;
  $("shared-file-preview").hidden = true;
  if (hadSavedDocument) toast("Attachment removed here. Its authorized copy remains in Documents.");
});
$("clear-shared-context").addEventListener("click", clearSharedContext);
$("setup-model").addEventListener("click", () => run($("setup-model"), ensureModel));
$("open-ollama").addEventListener("click", () => nativeBridge?.postMessage({action: "openOllama"}));
$("voice-button").addEventListener("click", () => nativeBridge?.postMessage({action: "speak"}));
$("inline-draft-cancel").addEventListener("click", () => { $("inline-draft-form").reset(); $("inline-draft-dialog").close(); });
$("inline-draft-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  const saved = await api("/api/drafts", json("POST", {recipient: $("inline-draft-to").value, subject: $("inline-draft-subject").value, body: $("inline-draft-body").value}));
  $("inline-draft-dialog").close();
  $("inline-draft-form").reset();
  feedback(`Draft "${saved.subject || "Untitled email"}" saved. Nothing was sent.`);
  $("chat-message").value = "";
  clearSharedContext();
  await refresh();
}); });

window.lumenMac = {
  // A cached display hint must never authorize an OS read.
  canShare: () => unlocked,
  prepareSharing: async () => {
    if (!unlocked) return null;
    const epoch = sessionEpoch;
    const identifier = crypto.randomUUID();
    sharingTicket = identifier;
    const receipt = await api("/api/sharing/authorize", {method: "POST"});
    if (!unlocked || epoch !== sessionEpoch || identifier !== sharingTicket) return null;
    return {identifier, epoch, vault_generation: receipt.vault_generation};
  },
  validateSharing: async (context) => {
    if (!context || !unlocked || context.epoch !== sessionEpoch || context.identifier !== sharingTicket) return false;
    const receipt = await api("/api/sharing/authorize", {method: "POST"});
    return unlocked && context.epoch === sessionEpoch && context.identifier === sharingTicket
      && receipt.vault_generation === context.vault_generation;
  },
  openChat: () => navigate("assistant"),
  openSettings: () => navigate("settings"),
  lock: () => run(null, lockWorkspace),
  prepareVoiceCapture: async (identifier) => {
    if (!unlocked || typeof identifier !== "string" || !identifier) return null;
    if (chatInFlight) return {reason: "Wait for the current chat action to finish, then speak again. The microphone has not started."};
    if (document.querySelector("dialog[open]")) return {reason: "Close the current review dialog before speaking. The microphone has not started."};
    const epoch = sessionEpoch;
    voiceTicket = identifier;
    const receipt = await api("/api/voice/authorize", {method: "POST"});
    if (!unlocked || epoch !== sessionEpoch || voiceTicket !== identifier) return null;
    navigate("assistant");
    return {identifier, epoch, vault_generation: receipt.vault_generation, mode: chatMode};
  },
  validateVoiceCapture: async (context) => {
    if (!context || !unlocked || chatInFlight || context.epoch !== sessionEpoch || context.identifier !== voiceTicket) return false;
    const receipt = await api("/api/voice/authorize", {method: "POST"});
    return unlocked && context.epoch === sessionEpoch && context.identifier === voiceTicket
      && receipt.vault_generation === context.vault_generation;
  },
  cancelVoiceCapture: () => { voiceTicket = null; },
  acceptVoiceTranscript: async (payload) => {
    if (!payload || typeof payload.text !== "string" || !payload.text.trim()
        || !["ask", "note", "reminder", "draft"].includes(payload.mode)) {
      return {accepted: false, reason: "No usable transcript was provided."};
    }
    if (!await window.lumenMac.validateVoiceCapture(payload)) {
      return {accepted: false, reason: "The vault or voice session changed. Unlock and speak again."};
    }
    const existing = $("chat-message").value;
    const combined = existing ? `${existing.trimEnd()}\n${payload.text.trim()}` : payload.text.trim();
    const limit = payload.mode === "reminder" ? 4000 : 8000;
    if (combined.length > limit) {
      return {accepted: false, reason: `The transcript plus your typed text exceeds ${limit.toLocaleString()} characters. Your existing draft was preserved; copy the transcript and shorten it before pasting.`};
    }
    navigate("assistant");
    changeChatMode(payload.mode);
    $("chat-message").value = combined;
    voiceTicket = null;
    feedback((payload.partial === true ? "Partial voice transcript ready; it may be incomplete. " : "Voice transcript ready. ")
      + "Review or edit it, then press the action button when you are ready. Nothing was submitted to the assistant or saved.");
    $("chat-message").focus();
    return {accepted: true};
  },
  shareText: async (payload, context = null) => {
    const text = typeof payload === "string" ? payload : payload?.text;
    const mode = typeof payload === "string" ? "ask" : payload?.mode;
    if (!unlocked || typeof text !== "string" || text.length > 8000) return false;
    if (!["ask", "note", "reminder", "draft"].includes(mode)) return false;
    const authorization = context || await window.lumenMac.prepareSharing();
    if (!await window.lumenMac.validateSharing(authorization)) return false;
    sharingTicket = null;
    navigate("assistant"); changeChatMode(mode);
    $("shared-context").hidden = false;
    $("shared-context").open = true;
    $("shared-text").value = text;
    if (mode === "ask" && !$("chat-message").value.trim()) $("chat-message").value = "Suggest a useful next step for this.";
    $("shared-app").focus();
    return true;
  },
  shareFile: async (payload, context = null) => {
    if (!unlocked || !payload || typeof payload.name !== "string" || typeof payload.base64 !== "string") return false;
    const authorization = context || await window.lumenMac.prepareSharing();
    if (!await window.lumenMac.validateSharing(authorization)) return false;
    sharingTicket = null;
    try {
      const bytes = Uint8Array.from(atob(payload.base64), (char) => char.charCodeAt(0));
      setSharedFile(new File([bytes], payload.name));
      navigate("assistant");
      return true;
    } catch (error) { toast(error.message, true); return false; }
  }
};

$("upload-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  const file = $("document-file").files[0];
  if (!file || file.size > 12 * 1024 * 1024) throw new Error("Choose a document no larger than 12 MiB.");
  const params = new URLSearchParams({filename: file.name, authorized: String($("document-authorized").checked)});
  await api(`/api/documents?${params}`, {method: "POST", body: file, headers: {"Content-Type": "application/octet-stream"}});
  $("upload-form").reset();
  hidePanel("upload-form");
  await refresh();
  toast("Document added to the encrypted vault.");
}); });
$("toggle-upload-form").addEventListener("click", () => {
  if ($("upload-form").hidden) showPanel("upload-form", "document-file");
  else { $("upload-form").reset(); hidePanel("upload-form"); }
});
$("cancel-upload").addEventListener("click", () => { $("upload-form").reset(); hidePanel("upload-form"); });

$("new-note").addEventListener("click", () => { editNote({}); showPanel("note-form", "note-title"); });
$("new-draft").addEventListener("click", () => { editDraft({}); showPanel("draft-editor", "compose-instructions"); });
$("new-reminder").addEventListener("click", () => { editReminder({}); showPanel("reminder-form", "reminder-title"); });
$("cancel-note").addEventListener("click", () => { editNote({}); hidePanel("note-form"); });
$("cancel-draft").addEventListener("click", () => { editDraft({}); hidePanel("draft-editor"); });
$("cancel-reminder").addEventListener("click", () => { editReminder({}); hidePanel("reminder-form"); });

$("note-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  const id = $("note-id").value;
  const fields = {title: $("note-title").value, body: $("note-body").value, authorized: $("note-authorized").checked, category: $("note-category").value};
  await api(id ? `/api/notes/${id}` : "/api/notes", json(id ? "PUT" : "POST", fields));
  editNote({});
  hidePanel("note-form");
  await refresh();
  toast("Note saved.");
}); });

$("compose-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  const epoch = sessionEpoch;
  const result = await api("/api/compose", json("POST", {recipient: $("compose-recipient").value, instructions: $("compose-instructions").value, tone: $("compose-tone").value}));
  if (epoch !== sessionEpoch || !unlocked) return;
  editDraft({...result, subject: ""});
  toast("Draft generated locally. Edit it, then save when ready.");
}); });

$("draft-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  const id = $("draft-id").value;
  const fields = {recipient: $("draft-recipient").value, subject: $("draft-subject").value, body: $("draft-body").value};
  await api(id ? `/api/drafts/${id}` : "/api/drafts", json(id ? "PUT" : "POST", fields));
  editDraft({});
  hidePanel("draft-editor");
  await refresh();
  toast("Draft saved. No email was sent.");
}); });

$("reminder-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  const due = new Date($("reminder-due").value);
  if (Number.isNaN(due.getTime())) throw new Error("Choose a valid local date and time.");
  const candidateId = $("candidate-accept-id").value;
  if (candidateId) {
    await api(`/api/candidate-reminders/${candidateId}/accept`, json("POST", {
      title: $("reminder-title").value, due_at: due.toISOString(), details: $("reminder-details").value,
    }));
    editReminder({});
    hidePanel("reminder-form");
    await refresh();
    toast("Reminder saved from your email.");
    return;
  }
  const id = $("reminder-id").value;
  const fields = {title: $("reminder-title").value, due_at: due.toISOString(), details: $("reminder-details").value, done: $("reminder-done").checked};
  await api(id ? `/api/reminders/${id}` : "/api/reminders", json(id ? "PUT" : "POST", fields));
  editReminder({});
  hidePanel("reminder-form");
  await refresh();
  toast("Reminder saved. It will appear here when Lumen is open and unlocked.");
}); });

$("research-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  showApproval(await api("/api/research/preview", json("POST", {query: $("research-query").value})));
}); });

$("approval-cancel").addEventListener("click", () => run($("approval-cancel"), cancelApproval));
$("approval-dialog").addEventListener("cancel", (event) => { event.preventDefault(); run(null, cancelApproval); });
$("approval-confirm").addEventListener("click", () => run($("approval-dialog"), async () => {
  if (!pendingApproval) throw new Error("No pending approval.");
  const approval = pendingApproval;
  pendingApproval = null;
  try {
    const result = await api(`/api/approvals/${approval.id}/confirm`, {method: "POST"});
    $("approval-dialog").close();
    await refresh();
    toast(result.action === "delete" ? "Item deleted." : "Research saved with source references.");
  } catch (error) {
    $("approval-dialog").close();
    if (unlocked) await refresh();
    throw error;
  }
}));
$("detail-close").addEventListener("click", () => $("detail-dialog").close());

$("refresh-models").addEventListener("click", () => run($("refresh-models"), async () => {
  const epoch = sessionEpoch;
  const selected = $("model-select").value;
  const result = await api("/api/models");
  if (epoch !== sessionEpoch || !unlocked) return;
  $("model-select").replaceChildren();
  for (const name of result.models) {
    const option = el("option", "", name);
    option.value = name;
    $("model-select").append(option);
  }
  if (result.models.includes(selected)) $("model-select").value = selected;
  if (!result.models.length) throw new Error("No local models found. Download one with Ollama first.");
}));

function requireModelSelected() {
  if (!$("model-select").value) throw new Error("Select and save a local AI model first.");
}

$("model-settings-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  const model = $("model-select").value;
  if (!model) throw new Error("Select an installed local model first. Refresh models if the list is empty.");
  await api("/api/settings", json("PUT", {model}));
  await loadSettings();
  toast("Local AI model saved.");
}); });

$("embedding-settings-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  requireModelSelected();
  const fields = {model: $("model-select").value, embedding_model: $("embedding-model").value.trim()};
  await api("/api/settings", json("PUT", fields));
  await loadSettings();
  toast("Document search setting saved.");
}); });

$("research-settings-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  requireModelSelected();
  const key = $("brave-key").value.trim();
  const fields = {model: $("model-select").value};
  if ($("remove-brave-key").checked) fields.brave_key = "";
  else if (key) fields.brave_key = key;
  $("brave-key").value = "";
  await api("/api/settings", json("PUT", fields));
  $("remove-brave-key").checked = false;
  await loadSettings();
  toast("Web research setting saved.");
}); });

$("mail-settings-form").addEventListener("submit", (event) => { event.preventDefault(); run(event.currentTarget, async () => {
  if ($("disconnect-mail-account").checked) {
    await api("/api/mail/account", json("PUT", {disconnect: true}));
    $("disconnect-mail-account").checked = false;
    await loadMailAccount();
    toast("Mail account disconnected.");
    return;
  }
  const username = $("mail-username").value.trim();
  if (!username) throw new Error("Enter the Gmail address for this account.");
  const password = $("mail-app-password").value.trim();
  const fields = {username};
  if (password) fields.app_password = password;
  $("mail-app-password").value = "";
  await api("/api/mail/account", json("PUT", fields));
  await loadMailAccount();
  toast("Mail account connected.");
}); });

$("check-mail").addEventListener("click", () => run($("check-mail"), async () => {
  $("mail-check-status").textContent = "Checking for new mail...";
  try {
    const result = await api("/api/mail/check", {method: "POST"});
    await refresh();
    const message = `Imported ${result.imported} message(s). Found ${result.candidates} possible reminder(s) to review.`;
    $("mail-check-status").textContent = message;
    toast(message);
  } catch (error) {
    $("mail-check-status").textContent = `Check failed: ${error.message}`;
    throw error;
  }
}));

function updateClock() {
  $("today-label").textContent = new Date().toLocaleDateString(undefined, {weekday: "long", month: "long", day: "numeric"}).toUpperCase();
  const hour = new Date().getHours();
  $("greeting").textContent = hour < 12 ? "Good morning. Make a little room." : hour < 18 ? "Good afternoon. Find your focus." : "Good evening. A little clarity.";
  if (unlocked) renderOverview();
}

updateClock();
changeChatMode("ask");
navigate(currentPage);
run(null, session);
setInterval(() => { updateClock(); if (unlocked) run(null, async () => { const result = await api("/api/session"); csrf = result.csrf; if (!result.unlocked) showVault(); }); }, 15000);
