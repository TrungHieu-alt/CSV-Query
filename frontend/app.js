const UI = Object.freeze({
  pageTitle: "CSV Data Studio",
  pageDescription: "Explore CSV files and ask natural-language questions.",
  eyebrow: "CSV DATA STUDIO",
  heading: "Explore any CSV. Ask anything.",
  subtitle: "Browse your rows in a clean table, then use natural language to analyze the active dataset.",
  chatTab: "Ask data",
  dataTab: "Explore rows",
  upload: "Upload CSV",
  bundledDataset: "Bundled sales data",
  welcome: (name) => `You are asking about “${name}”. What would you like to know?`,
  placeholder: "Ask a question about the active dataset",
  send: "Ask",
  loading: "Analyzing the data…",
  uploading: "Validating and loading your CSV…",
  uploadSuccess: (name) => `“${name}” is ready.`,
  errorPrefix: "Sorry, that request could not be completed: ",
  networkError: "The API is unavailable. Check that the backend is running.",
  generatedPlan: "Generated plan",
  noRows: "No matching rows.",
  truncated: "Showing the first 500 rows.",
  rowCount: (count) => `${count.toLocaleString()} result${count === 1 ? "" : "s"}`,
  dataKicker: "Active dataset",
  dataTitle: "Data explorer",
  dataSummary: (rows, columns) => `${rows.toLocaleString()} rows · ${columns} columns`,
  previous: "Previous",
  next: "Next",
  page: (current, total) => `Page ${current} of ${total}`,
  loadingRows: "Loading rows…",
  csvOnly: "Choose a CSV file encoded as UTF-8.",
});

const apiBaseUrl = (window.APP_CONFIG?.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const elements = {
  messages: document.querySelector("#messages"),
  examples: document.querySelector("#examples"),
  form: document.querySelector("#chat-form"),
  input: document.querySelector("#question-input"),
  send: document.querySelector("#send-button"),
  status: document.querySelector("#status"),
  chatTab: document.querySelector("#chat-tab"),
  dataTab: document.querySelector("#data-tab"),
  chatPanel: document.querySelector("#chat-panel"),
  dataPanel: document.querySelector("#data-panel"),
  datasetSelect: document.querySelector("#dataset-select"),
  upload: document.querySelector("#upload-button"),
  file: document.querySelector("#file-input"),
  dataKicker: document.querySelector("#data-kicker"),
  dataTitle: document.querySelector("#data-title"),
  dataSummary: document.querySelector("#data-summary"),
  schemaCards: document.querySelector("#schema-cards"),
  dataTable: document.querySelector("#data-table"),
  dataStatus: document.querySelector("#data-status"),
  previous: document.querySelector("#previous-page"),
  next: document.querySelector("#next-page"),
  pageStatus: document.querySelector("#page-status"),
};

const history = [];
const datasets = new Map([["default", UI.bundledDataset]]);
let activeDatasetId = "default";
let activeSchema = [];
let currentOffset = 0;
const pageSize = 50;

document.title = UI.pageTitle;
document.querySelector("#page-description").content = UI.pageDescription;
document.querySelector("#eyebrow").textContent = UI.eyebrow;
document.querySelector("#heading").textContent = UI.heading;
document.querySelector("#subtitle").textContent = UI.subtitle;
elements.chatTab.textContent = UI.chatTab;
elements.dataTab.textContent = UI.dataTab;
elements.upload.textContent = UI.upload;
elements.input.placeholder = UI.placeholder;
elements.send.textContent = UI.send;
elements.dataKicker.textContent = UI.dataKicker;
elements.dataTitle.textContent = UI.dataTitle;
elements.previous.textContent = UI.previous;
elements.next.textContent = UI.next;

function appendMessage(role, text, isError = false) {
  const message = document.createElement("article");
  message.classList.add("message", role);
  if (isError) message.classList.add("error");
  const content = document.createElement("div");
  content.textContent = text;
  message.append(content);
  elements.messages.append(message);
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return message;
}

function appendPlan(container, plan) {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = UI.generatedPlan;
  const code = document.createElement("pre");
  code.textContent = JSON.stringify(plan, null, 2);
  details.append(summary, code);
  container.append(details);
}

function createTable(columns, rows) {
  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = document.createElement("table");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = column;
    headRow.append(cell);
  });
  const head = document.createElement("thead");
  head.append(headRow);
  const body = document.createElement("tbody");
  rows.forEach((row) => {
    const tableRow = document.createElement("tr");
    columns.forEach((column) => {
      const cell = document.createElement("td");
      cell.textContent = row[column] === null ? "—" : String(row[column]);
      tableRow.append(cell);
    });
    body.append(tableRow);
  });
  table.append(head, body);
  wrapper.append(table);
  return wrapper;
}

function setLoading(loading) {
  elements.input.disabled = loading;
  elements.send.disabled = loading;
  elements.status.textContent = loading ? UI.loading : "";
}

function updateDatasetSelector() {
  elements.datasetSelect.replaceChildren();
  datasets.forEach((name, id) => {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = name;
    option.selected = id === activeDatasetId;
    elements.datasetSelect.append(option);
  });
}

function resetConversation() {
  history.splice(0);
  elements.messages.replaceChildren();
  appendMessage("assistant", UI.welcome(datasets.get(activeDatasetId)));
}

async function loadSchema() {
  const response = await fetch(`${apiBaseUrl}/api/schema?dataset_id=${encodeURIComponent(activeDatasetId)}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  activeSchema = data.columns;
  elements.examples.replaceChildren();
  data.examples.forEach((example) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = example;
    chip.addEventListener("click", () => ask(example));
    elements.examples.append(chip);
  });
  renderSchemaCards();
}

function renderSchemaCards() {
  elements.schemaCards.replaceChildren();
  activeSchema.forEach((column) => {
    const card = document.createElement("article");
    card.className = "schema-card";
    const name = document.createElement("p");
    name.className = "schema-name";
    name.textContent = column.name;
    name.title = column.name;
    const type = document.createElement("p");
    type.className = "schema-type";
    type.textContent = column.type;
    card.append(name, type);
    elements.schemaCards.append(card);
  });
}

async function selectDataset(datasetId) {
  activeDatasetId = datasetId;
  currentOffset = 0;
  updateDatasetSelector();
  resetConversation();
  try {
    await loadSchema();
    if (!elements.dataPanel.hidden) await loadRows();
  } catch (error) {
    appendMessage("assistant", `${UI.errorPrefix}${error.message}`, true);
  }
}

async function ask(question) {
  appendMessage("user", question);
  history.push({ role: "user", content: question });
  setLoading(true);
  try {
    const response = await fetch(`${apiBaseUrl}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: history.slice(-6, -1), dataset_id: activeDatasetId }),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    if (data.clarify) {
      appendMessage("assistant", data.clarify);
      history.push({ role: "assistant", content: data.clarify });
      return;
    }
    const label = data.row_count === 0 ? UI.noRows : UI.rowCount(data.row_count);
    const message = appendMessage("assistant", label);
    if (data.rows?.length) message.append(createTable(data.columns, data.rows));
    if (data.truncated) {
      const note = document.createElement("p");
      note.textContent = UI.truncated;
      message.append(note);
    }
    appendPlan(message, data.plan);
    history.push({ role: "assistant", content: label });
  } catch (error) {
    const text = error instanceof TypeError ? UI.networkError : `${UI.errorPrefix}${error.message}`;
    appendMessage("assistant", text, true);
    history.push({ role: "assistant", content: text });
  } finally {
    setLoading(false);
    elements.input.focus();
  }
}

async function uploadCsv(file) {
  if (!file.name.toLowerCase().endsWith(".csv")) {
    elements.status.textContent = UI.csvOnly;
    return;
  }
  elements.upload.disabled = true;
  elements.status.textContent = UI.uploading;
  try {
    const response = await fetch(`${apiBaseUrl}/api/datasets?filename=${encodeURIComponent(file.name)}`, {
      method: "POST",
      headers: { "Content-Type": "text/csv" },
      body: file,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    datasets.set(data.dataset_id, data.name);
    await selectDataset(data.dataset_id);
    elements.status.textContent = UI.uploadSuccess(data.name);
    showPanel("data");
  } catch (error) {
    elements.status.textContent = `${UI.errorPrefix}${error.message}`;
  } finally {
    elements.upload.disabled = false;
    elements.file.value = "";
  }
}

async function loadRows() {
  elements.dataStatus.textContent = UI.loadingRows;
  try {
    const response = await fetch(`${apiBaseUrl}/api/datasets/${encodeURIComponent(activeDatasetId)}/rows?offset=${currentOffset}&limit=${pageSize}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    elements.dataTable.replaceChildren(createTable(data.columns, data.rows));
    elements.dataSummary.textContent = UI.dataSummary(data.row_count, data.columns.length);
    const totalPages = Math.max(1, Math.ceil(data.row_count / pageSize));
    const currentPage = Math.floor(currentOffset / pageSize) + 1;
    elements.pageStatus.textContent = UI.page(currentPage, totalPages);
    elements.previous.disabled = currentOffset === 0;
    elements.next.disabled = !data.has_more;
    elements.dataStatus.textContent = "";
  } catch (error) {
    elements.dataStatus.textContent = `${UI.errorPrefix}${error.message}`;
  }
}

function showPanel(name) {
  const showChat = name === "chat";
  elements.chatPanel.hidden = !showChat;
  elements.dataPanel.hidden = showChat;
  elements.chatTab.classList.toggle("active", showChat);
  elements.dataTab.classList.toggle("active", !showChat);
  if (!showChat) loadRows();
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = elements.input.value.trim();
  if (!question) return;
  elements.input.value = "";
  ask(question);
});
elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});
elements.chatTab.addEventListener("click", () => showPanel("chat"));
elements.dataTab.addEventListener("click", () => showPanel("data"));
elements.upload.addEventListener("click", () => elements.file.click());
elements.file.addEventListener("change", () => {
  if (elements.file.files[0]) uploadCsv(elements.file.files[0]);
});
elements.datasetSelect.addEventListener("change", () => selectDataset(elements.datasetSelect.value));
elements.previous.addEventListener("click", () => {
  currentOffset = Math.max(0, currentOffset - pageSize);
  loadRows();
});
elements.next.addEventListener("click", () => {
  currentOffset += pageSize;
  loadRows();
});

updateDatasetSelector();
resetConversation();
loadSchema().catch(() => {
  elements.status.textContent = UI.networkError;
});
