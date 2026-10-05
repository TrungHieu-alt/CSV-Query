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
  chart: "Chart",
  table: "Table",
  downloadCsv: "Download CSV",
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
      cell.textContent = formatValue(row[column], column);
      tableRow.append(cell);
    });
    body.append(tableRow);
  });
  table.append(head, body);
  wrapper.append(table);
  return wrapper;
}

function readableLabel(value) {
  return String(value ?? "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function axisLabel(column) {
  const label = readableLabel(column);
  if (/revenue|price|sales|income|cost/i.test(column ?? "")) return `${label} (USD)`;
  if (/quantity|units|items/i.test(column ?? "")) return `${label} (items)`;
  return label;
}

function formatValue(value, column = "") {
  if (value === null || value === undefined || (typeof value === "number" && Number.isNaN(value))) return "—";
  if (typeof value === "number") {
    const options = { maximumFractionDigits: Number.isInteger(value) ? 0 : 2 };
    const formatted = value.toLocaleString(undefined, options);
    return /revenue|price|sales|income|cost/i.test(column) ? `$${formatted}` : formatted;
  }
  return String(value);
}

function csvCell(value) {
  const cell = value === null || value === undefined ? "" : String(value);
  return `"${cell.replaceAll('"', '""')}"`;
}

function downloadCsv(data) {
  const lines = [data.columns.map(csvCell).join(",")];
  data.rows.forEach((row) => lines.push(data.columns.map((column) => csvCell(row[column])).join(",")));
  const blob = new Blob([`\uFEFF${lines.join("\r\n")}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "query-result.csv";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function makeActionButton(label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "result-action";
  button.textContent = label;
  button.addEventListener("click", action);
  return button;
}

function chartColors(count) {
  const palette = ["#173f2b", "#ca6b3f", "#5976a5", "#8a5b8e", "#8d792d", "#397f78"];
  return Array.from({ length: count }, (_, index) => palette[index % palette.length]);
}

function truncateLabel(value) {
  const label = String(value ?? "—");
  return label.length > 24 ? `${label.slice(0, 21)}…` : label;
}

function createChart(data) {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-label", `${readableLabel(data.viz.type)} visualization`);
  canvas.setAttribute("role", "img");
  const x = data.viz.x;
  const yColumns = data.viz.y || [];
  let labels = data.rows.map((row) => row[x]);
  let datasets;

  if (data.viz.type === "grouped_bar") {
    const groups = [...new Set(data.rows.map((row) => String(row[data.viz.series] ?? "—")))];
    labels = [...new Set(data.rows.map((row) => String(row[x] ?? "—")))];
    const colors = chartColors(groups.length);
    datasets = groups.map((group, index) => ({
      label: group,
      sourceColumn: yColumns[0],
      data: labels.map((label) => data.rows.find((row) => String(row[x] ?? "—") === label && String(row[data.viz.series] ?? "—") === group)?.[yColumns[0]] ?? null),
      backgroundColor: colors[index],
      borderColor: colors[index],
      borderWidth: 2,
    }));
  } else {
    const colors = chartColors(yColumns.length);
    datasets = yColumns.map((column, index) => ({
      label: readableLabel(column),
      sourceColumn: column,
      data: data.rows.map((row) => row[column]),
      backgroundColor: colors[index],
      borderColor: colors[index],
      borderWidth: 2,
      tension: 0.2,
    }));
  }

  const longLabels = labels.some((label) => String(label ?? "").length > 18);
  const chart = new Chart(canvas, {
    type: data.viz.type === "line" ? "line" : "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: data.viz.type === "bar" && longLabels ? "y" : "x",
      plugins: {
        legend: { display: datasets.length > 1 || data.viz.type === "grouped_bar" },
        tooltip: { callbacks: {
          title: (items) => items.length ? String(labels[items[0].dataIndex] ?? "—") : "",
          label: (item) => `${item.dataset.label}: ${formatValue(item.raw, item.dataset.sourceColumn)}`,
        } },
      },
      scales: {
        x: { ticks: { callback: function(value) { return truncateLabel(this.getLabelForValue(value)); } }, title: { display: true, text: readableLabel(x) } },
        y: { beginAtZero: data.viz.type !== "line", title: { display: true, text: yColumns.map(axisLabel).join(", ") } },
      },
    },
  });
  canvas.chartInstance = chart;
  return canvas;
}

function createKpis(data) {
  const grid = document.createElement("div");
  grid.className = "kpi-grid";
  (data.viz.y || []).forEach((column) => {
    const card = document.createElement("section");
    card.className = "kpi-card";
    const value = document.createElement("strong");
    value.textContent = formatValue(data.rows[0]?.[column], column);
    const label = document.createElement("span");
    label.textContent = readableLabel(column);
    card.append(value, label);
    grid.append(card);
  });
  return grid;
}

function renderResult(message, data) {
  const actions = document.createElement("div");
  actions.className = "result-actions";
  const table = createTable(data.columns, data.rows);
  table.hidden = data.viz?.type !== "table";
  let visual = null;

  if (data.viz?.type === "kpi") {
    visual = createKpis(data);
  } else if (["line", "bar", "grouped_bar"].includes(data.viz?.type) && typeof Chart !== "undefined") {
    const chartWrap = document.createElement("div");
    chartWrap.className = "chart-wrap";
    chartWrap.append(createChart(data));
    visual = chartWrap;
  } else {
    table.hidden = false;
  }

  if (visual) {
    actions.append(
      makeActionButton(UI.chart, () => { visual.hidden = false; table.hidden = true; }),
      makeActionButton(UI.table, () => { visual.hidden = true; table.hidden = false; }),
    );
  }
  actions.append(makeActionButton(UI.downloadCsv, () => downloadCsv(data)));
  message.append(actions);
  if (visual) message.append(visual);
  message.append(table);
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
    renderResult(message, data);
    if (data.truncated) {
      const note = document.createElement("p");
      note.className = "truncation-note";
      note.textContent = `Showing ${data.rows.length.toLocaleString()} of ${data.row_count.toLocaleString()} rows (maximum 500).`;
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
