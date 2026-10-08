const apiBaseUrl = (window.APP_CONFIG?.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const elements = Object.fromEntries([
  "workspace", "messages", "examples", "chat-form", "question-input", "send-button", "status",
  "chat-panel", "open-chat", "close-chat", "dataset-select", "upload-button", "file-input",
  "data-title", "data-summary", "data-table", "data-status", "row-status", "row-search",
].map((id) => [id, document.getElementById(id)]));
const datasets = new Map([["default", "Bundled sales data"]]);
const history = [];
const charts = new Set();
let activeDatasetId = "default";
let activeSchema = [];
let activeExamples = [];
let datasetVersion = 0;
let datasetController;
let queryController;
let queryPending = false;
let allRows = [];
let filteredRows = [];
let tableColumns = [];
let totalRows = 0;
let sortColumn = null;
let sortDirection = 1;
let bodyElement;
let windowStart = -1;
const rowHeight = 32;
const windowSize = 100;
const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const currencyFormat = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function readableLabel(value) {
  return String(value ?? "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
function isDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}(?:$|T| )/.test(value);
}
function isCurrency(column, schema = activeSchema, plan = null) {
  const aggregation = plan?.aggregations?.find((item) => item.alias === column);
  // Counts remain numbers even when their source column contains money.
  if (aggregation && ["count", "nunique"].includes(aggregation.func)) return false;
  const source = aggregation?.column || column;
  const metadata = schema.find((item) => item.name === source);
  return metadata?.unit === "USD" || /(?:^|_)(revenue|price|sales|income|cost|spend|amount|profit|salary|earnings)(?:_|$)/i.test(source);
}
function formatValue(value, column = "", schema = activeSchema, plan = null) {
  if (value === null || value === undefined || (typeof value === "number" && !Number.isFinite(value))) return "—";
  if (typeof value === "number") return (isCurrency(column, schema, plan) ? currencyFormat : numberFormat).format(value);
  if (isDate(value)) return value.slice(0, 10);
  return String(value);
}
function numericColumn(column, rows, schema = activeSchema) {
  const metadata = schema.find((item) => item.name === column);
  if (metadata) return /^(?:u?int|float|decimal)/i.test(metadata.type);
  return rows.some((row) => typeof row[column] === "number");
}
function node(tag, className, text) {
  const result = document.createElement(tag);
  if (className) result.className = className;
  if (text !== undefined) result.textContent = text;
  return result;
}
function scrollMessages() {
  elements.messages.scrollTop = elements.messages.scrollHeight;
}
function appendMessage(role, text, error = false) {
  const message = node("article", `message ${role}${error ? " error" : ""}`);
  message.append(node("span", "message-label", role === "user" ? "You" : "Data Studio"));
  if (text) message.append(node("div", "message-content", text));
  elements.messages.append(message);
  scrollMessages();
  return message;
}
function createTable(columns, rows, schema = activeSchema, plan = null) {
  const wrapper = node("div", "table-wrap");
  const table = node("table");
  const head = node("thead");
  const header = node("tr");
  const numeric = columns.map((column) => numericColumn(column, rows, schema));
  columns.forEach((column, index) => {
    const cell = node("th", numeric[index] ? "numeric" : "", readableLabel(column));
    cell.scope = "col";
    header.append(cell);
  });
  head.append(header);
  const body = node("tbody");
  rows.forEach((row) => {
    const tr = node("tr");
    columns.forEach((column, index) => tr.append(node("td", numeric[index] ? "numeric" : "", formatValue(row[column], column, schema, plan))));
    body.append(tr);
  });
  table.append(head, body);
  wrapper.append(table);
  return wrapper;
}
function appendThinkingIndicator() {
  const message = node("article", "message thinking");
  message.setAttribute("role", "status");
  message.append(node("span", "message-label", "Data Studio"));
  const indicator = node("div", "thinking-indicator");
  const dots = node("span", "thinking-dots");
  dots.setAttribute("aria-hidden", "true");
  for (let index = 0; index < 3; index++) dots.append(node("span"));
  indicator.append(dots, node("span", "", "Đang suy nghĩ…"));
  message.append(indicator);
  elements.messages.append(message);
  scrollMessages();
  return message;
}
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = node("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function csvCell(value) {
  const cell = value == null ? "" : isDate(value) ? value.slice(0, 10) : String(value);
  return `"${cell.replaceAll('"', '""')}"`;
}
function downloadCsv(data) {
  const lines = [data.columns.map(csvCell).join(","), ...data.rows.map((row) => data.columns.map((column) => csvCell(row[column])).join(","))];
  downloadBlob(new Blob([`\uFEFF${lines.join("\r\n")}`], { type: "text/csv;charset=utf-8" }), "query-result.csv");
}
function actionButton(label, action) {
  const button = node("button", "result-action", label);
  button.type = "button";
  button.addEventListener("click", () => action(button));
  return button;
}
async function copyAnswer(button, text) {
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied";
  } catch {
    button.textContent = "Copy unavailable";
  }
  setTimeout(() => { button.textContent = "Copy"; }, 2000);
}
function resultType(data) {
  if (data.result_type) return data.result_type;
  if (data.rows.length === 1 && data.columns.length === 1) return "value";
  return ({ kpi: "value", bar: "categorical", grouped_bar: "categorical", line: "time_series" })[data.viz?.type] || "table";
}
function chartSpec(data, type) {
  const numeric = data.columns.filter((column) => numericColumn(column, data.rows, []));
  const other = data.columns.filter((column) => !numeric.includes(column));
  return {
    x: data.viz?.x || other[0],
    y: data.viz?.y?.length ? data.viz.y : numeric,
    series: data.viz?.series || (type === "categorical" && other.length === 2 ? other[1] : null),
  };
}
function chartTitle(spec) {
  return `${spec.y.map(readableLabel).join(" & ")} by ${readableLabel(spec.x)}`;
}
function createChart(data, type, schema, container) {
  const spec = chartSpec(data, type);
  const x = spec.x;
  const y = spec.y;
  // ISO dates sort correctly without timezone conversion.
  const rows = type === "time_series" ? [...data.rows].sort((a, b) => String(a[x]).localeCompare(String(b[x]))) : data.rows;
  let labels = [...new Set(rows.map((row) => formatValue(row[x], x, schema, data.plan)))];
  const groups = spec.series ? [...new Set(rows.map((row) => String(row[spec.series] ?? "—")))] : null;
  const chartDatasets = groups ? groups.map((group) => ({
    label: group, sourceColumn: y[0],
    data: labels.map((label) => rows.find((row) => formatValue(row[x], x, schema, data.plan) === label && String(row[spec.series] ?? "—") === group)?.[y[0]] ?? null),
  })) : y.map((column) => ({ label: readableLabel(column), sourceColumn: column, data: rows.map((row) => row[column]) }));
  chartDatasets.forEach((dataset, index) => Object.assign(dataset, {
    backgroundColor: `rgba(55, 107, 74, ${Math.max(.35, .85 - index * .15)})`, borderColor: "#376b4a",
    borderWidth: 2, borderDash: type === "time_series" && index ? [4 + index * 2, 3] : [],
    borderRadius: type === "categorical" ? 3 : 0, pointRadius: 2, tension: .15,
  }));
  const horizontal = type === "categorical" && labels.some((label) => label.length > 16);
  const values = chartDatasets.flatMap((dataset) => dataset.data).filter((value) => typeof value === "number" && Number.isFinite(value));
  const wholeNumbers = values.every(Number.isInteger);
  const title = chartTitle(spec);
  const subtitle = `${readableLabel(x)} · ${labels.length} ${type === "time_series" ? "dates" : "categories"}`;
  const wrapper = node("div", "chart-wrap");
  const canvas = node("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", `${title}. ${subtitle}. Use View as table to read the values.`);
  wrapper.append(canvas);
  container.append(wrapper);
  const numericAxis = {
    beginAtZero: type !== "time_series",
    ticks: { ...(wholeNumbers ? { precision: 0 } : {}), callback: (value) => formatValue(value, y[0], schema, data.plan) },
    grid: { color: "#e4e9df" }, border: { display: false },
  };
  const categoryAxis = { grid: { display: false }, border: { display: false }, ticks: { maxRotation: 0, autoSkip: true, callback: function(value) {
    const label = String(this.getLabelForValue(value));
    return label.length > 22 ? `${label.slice(0, 19)}…` : label;
  } } };
  const chart = new Chart(canvas, {
    type: type === "time_series" ? "line" : "bar",
    data: { labels, datasets: chartDatasets },
    plugins: [{ id: "paperBackground", beforeDraw(instance) {
      const ctx = instance.ctx;
      ctx.save(); ctx.globalCompositeOperation = "destination-over"; ctx.fillStyle = "#f7f8f1";
      ctx.fillRect(0, 0, instance.width, instance.height); ctx.restore();
    } }],
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, indexAxis: horizontal ? "y" : "x",
      plugins: {
        title: { display: true, text: title, align: "start", color: "#17211b", padding: { bottom: 4 }, font: { size: 13 } },
        subtitle: { display: true, text: subtitle, align: "start", color: "#617067", padding: { bottom: 16 }, font: { size: 11 } },
        legend: { display: chartDatasets.length > 1, labels: { boxWidth: 10, color: "#617067" } },
        tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${formatValue(item.raw, item.dataset.sourceColumn, schema, data.plan)}` } },
      },
      scales: { x: horizontal ? numericAxis : categoryAxis, y: horizontal ? categoryAxis : numericAxis },
    },
  });
  charts.add(chart);
  return { wrapper, canvas, chart };
}
function renderResult(message, data, schema) {
  const type = resultType(data);
  const actions = node("div", "result-actions");
  let copyText;
  if (!data.rows.length) {
    copyText = "No matching rows. Try a broader question.";
    message.append(node("div", "message-content", copyText));
  } else if (type === "value") {
    copyText = data.columns.map((column) => `${readableLabel(column)}: ${formatValue(data.rows[0][column], column, schema, data.plan)}`).join("\n");
    message.append(node("div", "message-content", copyText));
  } else {
    copyText = [data.columns.map(readableLabel).join("\t"), ...data.rows.map((row) => data.columns.map((column) => formatValue(row[column], column, schema, data.plan)).join("\t"))].join("\n");
    const table = createTable(data.columns, data.rows, schema, data.plan);
    let visual;
    // Attach first so Chart.js can measure the panel's actual width.
    if (["categorical", "time_series"].includes(type) && typeof Chart !== "undefined") {
      visual = createChart(data, type, schema, message);
      table.hidden = true;
      const toggle = actionButton("View as table", (button) => {
        table.hidden = !table.hidden;
        visual.wrapper.hidden = !table.hidden;
        button.textContent = table.hidden ? "View as table" : "View as chart";
        if (table.hidden) {
          visual.chart.resize(visual.wrapper.clientWidth, visual.wrapper.clientHeight);
          visual.chart.update("none");
        }
      });
      toggle.setAttribute("aria-expanded", "false");
      toggle.addEventListener("click", () => toggle.setAttribute("aria-expanded", String(!table.hidden)));
      actions.append(toggle);
      actions.append(actionButton("Download chart (PNG)", () => {
        // Hidden chart parents report zero size. Supply a size explicitly so
        // exporting also works while viewing the result as a table.
        visual.chart.resize(visual.wrapper.clientWidth || message.clientWidth, 240);
        visual.chart.update("none");
        visual.canvas.toBlob((blob) => {
          if (blob) downloadBlob(blob, "query-chart.png");
        }, "image/png");
      }));
    } else {
      const spec = chartSpec(data, type);
      message.append(node("h3", "result-title", type === "table" ? "Matching rows" : chartTitle(spec)));
      message.append(node("p", "result-subtitle", `${numberFormat.format(data.row_count)} results${type !== "table" ? " · Chart unavailable; showing data" : ""}`));
    }
    message.append(table);
    actions.append(actionButton("Export CSV", () => downloadCsv(data)));
  }
  actions.prepend(actionButton("Copy", (button) => copyAnswer(button, copyText)));
  message.append(actions);
  if (data.pandas_query) {
    const query = node("section", "query-details");
    query.id = `query-plan-${elements.messages.childElementCount}`;
    query.hidden = true;
    query.setAttribute("aria-label", "Query used for this answer");
    query.append(node("p", "query-label", "Pandas query · Python"));
    const code = node("code", "", data.pandas_query);
    const pre = node("pre", "query-code");
    pre.tabIndex = 0;
    pre.append(code);
    query.append(pre);
    const toggle = actionButton("Show query", (button) => {
      query.hidden = !query.hidden;
      button.textContent = query.hidden ? "Show query" : "Hide query";
      button.setAttribute("aria-expanded", String(!query.hidden));
    });
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", query.id);
    actions.append(toggle);
    message.append(query);
  }
  if (data.truncated) message.append(node("p", "truncation-note", `Showing ${numberFormat.format(data.rows.length)} of ${numberFormat.format(data.row_count)} results. CSV export includes these displayed rows.`));
  scrollMessages();
}
function setLoading(loading) {
  queryPending = loading;
  elements["question-input"].disabled = loading;
  elements["send-button"].disabled = loading;
  elements.status.textContent = loading ? "Analyzing your data…" : "";
}
function datasetGuidance() {
  const columns = activeSchema.map((column) => column.name);
  const example = activeExamples.find((question) => question === "Total revenue by region") || activeExamples[0] || "Show the first 20 rows";
  const columnList = columns.length ? ` (columns: ${columns.join(", ")})` : "";
  return `I can only answer questions about this dataset${columnList}. Try something like '${example}'.`;
}
function friendlyError(error, action = "query") {
  if (error.code === "gemini_quota_exhausted") return `All configured Gemini API keys have reached their quota or rate limit.${error.retryAfter ? ` Try again in about ${error.retryAfter} seconds.` : " Please try again later."}`;
  if (error.code === "gemini_connection_error") return "Cannot connect to Gemini. Check the backend’s network connection, then try again.";
  if (error.code === "gemini_not_configured") return "Configure a Gemini API key before asking questions.";
  if (error.name === "TypeError") return "Cannot reach the API. Check that the backend is running, then try again.";
  if (error.status === 429) return "Too many requests. Please try again shortly.";
  if (action === "upload") return error.status === 413 ? "This CSV exceeds the 10 MB upload limit." : "Could not load this file. Use a valid UTF-8 CSV with a header row.";
  if (error.status === 502) return "The question service is unavailable. Please try again shortly.";
  if (action === "query" && error.status === 422) return "I couldn’t build a valid query for that question. Please try again or simplify the question.";
  return action === "query" ? "The query could not be completed. Please try again shortly." : "Could not load the dataset. Try selecting it again.";
}
async function api(path, options = {}) {
  const response = await fetch(`${apiBaseUrl}${path}`, options);
  if (!response.ok) {
    const error = new Error("Request failed");
    error.status = response.status;
    const data = await response.json().catch(() => null);
    error.code = data?.error_code;
    error.retryAfter = Number.isFinite(data?.retry_after) && data.retry_after > 0 ? Math.ceil(data.retry_after) : null;
    throw error;
  }
  return response.json();
}
function updateDatasetSelector() {
  elements["dataset-select"].replaceChildren();
  datasets.forEach((name, id) => {
    const option = node("option", "", name);
    option.value = id;
    option.selected = id === activeDatasetId;
    elements["dataset-select"].append(option);
  });
}
function resetConversation() {
  history.length = 0;
  charts.forEach((chart) => chart.destroy());
  charts.clear();
  elements.messages.replaceChildren();
  elements.examples.hidden = false;
  elements.examples.replaceChildren();
  appendMessage("assistant", `Ask about “${datasets.get(activeDatasetId)}”. Your data stays visible while we explore it.`);
}
function renderExplorer() {
  const table = node("table");
  const head = node("thead");
  const tr = node("tr");
  tableColumns.forEach((column) => {
    const cell = node("th", numericColumn(column, allRows) ? "numeric" : "");
    cell.scope = "col";
    const sorted = sortColumn === column;
    cell.setAttribute("aria-sort", sorted ? (sortDirection === 1 ? "ascending" : "descending") : "none");
    const button = node("button", "sort-button", `${readableLabel(column)}${sorted ? (sortDirection === 1 ? " ↑" : " ↓") : ""}`);
    button.type = "button";
    button.title = `Sort by ${column}`;
    button.setAttribute("aria-label", `Sort by ${column}`);
    button.append(node("span", "column-type", activeSchema.find((item) => item.name === column)?.type || "unknown"));
    button.addEventListener("click", () => {
      sortDirection = sorted ? -sortDirection : 1;
      sortColumn = column;
      filterRows();
      renderExplorer();
      elements["data-table"].querySelectorAll(".sort-button")[tableColumns.indexOf(column)]?.focus({ preventScroll: true });
    });
    cell.append(button);
    tr.append(cell);
  });
  head.append(tr);
  bodyElement = node("tbody");
  table.append(head, bodyElement);
  elements["data-table"].replaceChildren(table);
  elements["data-table"].scrollTop = 0;
  windowStart = -1;
  renderRowWindow();
}
function renderRowWindow() {
  if (!bodyElement) return;
  const start = Math.max(0, Math.min(Math.floor(elements["data-table"].scrollTop / rowHeight) - 10, Math.max(0, filteredRows.length - windowSize)));
  if (start === windowStart) return;
  windowStart = start;
  const end = Math.min(start + windowSize, filteredRows.length);
  const fragment = document.createDocumentFragment();
  const spacer = (height) => {
    if (!height) return;
    const tr = node("tr");
    tr.setAttribute("aria-hidden", "true");
    const cell = node("td");
    cell.colSpan = tableColumns.length;
    cell.style.cssText = `height:${height}px;padding:0;border:0`;
    tr.append(cell);
    fragment.append(tr);
  };
  spacer(start * rowHeight);
  const numeric = tableColumns.map((column) => numericColumn(column, allRows));
  filteredRows.slice(start, end).forEach((row) => {
    const tr = node("tr");
    tableColumns.forEach((column, index) => tr.append(node("td", numeric[index] ? "numeric" : "", formatValue(row[column], column))));
    fragment.append(tr);
  });
  spacer((filteredRows.length - end) * rowHeight);
  if (!filteredRows.length) {
    const tr = node("tr");
    const cell = node("td", "empty-table", "No matching rows.");
    cell.colSpan = tableColumns.length;
    tr.append(cell); fragment.append(tr);
  }
  bodyElement.replaceChildren(fragment);
}
function filterRows() {
  const term = elements["row-search"].value.trim().toLowerCase();
  filteredRows = term ? allRows.filter((row) => tableColumns.some((column) =>
    formatValue(row[column], column).toLowerCase().includes(term) || String(row[column] ?? "").toLowerCase().includes(term))) : [...allRows];
  if (sortColumn) filteredRows.sort((a, b) => {
    const left = a[sortColumn], right = b[sortColumn];
    if (left == null) return right == null ? 0 : 1;
    if (right == null) return -1;
    return sortDirection * (typeof left === "number" && typeof right === "number" ? left - right : String(left).localeCompare(String(right), "en", { numeric: true }));
  });
  elements["row-status"].textContent = `${numberFormat.format(filteredRows.length)}${term ? " matching" : ""} rows${allRows.length < totalRows ? " loaded" : ""}`;
}
async function selectDataset(id) {
  datasetController?.abort();
  queryController?.abort();
  datasetController = new AbortController();
  const signal = datasetController.signal;
  const version = ++datasetVersion;
  activeDatasetId = id;
  activeSchema = [];
  activeExamples = [];
  allRows = []; filteredRows = []; tableColumns = []; totalRows = 0;
  bodyElement = null;
  sortColumn = null; sortDirection = 1;
  elements["row-search"].value = "";
  elements["row-search"].disabled = true;
  elements["data-table"].replaceChildren();
  elements["row-status"].textContent = "";
  elements["data-title"].textContent = datasets.get(id);
  elements["data-summary"].textContent = "Loading dataset…";
  elements["data-status"].textContent = "Loading rows…";
  updateDatasetSelector(); resetConversation(); setLoading(false);
  try {
    const schema = await api(`/api/schema?dataset_id=${encodeURIComponent(id)}`, { signal });
    if (version !== datasetVersion) return;
    activeSchema = schema.columns;
    activeExamples = schema.examples;
    schema.examples.forEach((example) => {
      const chip = node("button", "chip", example);
      chip.type = "button";
      chip.addEventListener("click", () => ask(example));
      elements.examples.append(chip);
    });
    let offset = 0;
    while (true) {
      const data = await api(`/api/datasets/${encodeURIComponent(id)}/rows?offset=${offset}&limit=500`, { signal });
      if (version !== datasetVersion) return;
      tableColumns = data.columns; totalRows = data.row_count;
      allRows.push(...data.rows);
      elements["data-summary"].textContent = `${numberFormat.format(totalRows)} rows · ${tableColumns.length} columns`;
      if (offset === 0) { filterRows(); renderExplorer(); }
      elements["data-status"].textContent = data.has_more ? `Loading rows… ${numberFormat.format(allRows.length)} / ${numberFormat.format(totalRows)}` : "";
      if (!data.has_more || !data.rows.length) break;
      offset += data.rows.length;
    }
    filterRows(); renderExplorer();
    elements["row-search"].disabled = false;
  } catch (error) {
    if (error.name !== "AbortError" && version === datasetVersion) elements["data-status"].textContent = friendlyError(error, "dataset");
  }
}
async function ask(question) {
  if (queryPending || !question.trim()) return;
  const version = datasetVersion;
  const schema = [...activeSchema];
  queryController = new AbortController();
  appendMessage("user", question);
  history.push({ role: "user", content: question });
  elements.examples.hidden = true;
  setLoading(true);
  const thinkingMessage = appendThinkingIndicator();
  try {
    const data = await api("/api/query", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: queryController.signal,
      body: JSON.stringify({ question, history: history.slice(-7, -1), dataset_id: activeDatasetId }),
    });
    if (version !== datasetVersion) return;
    thinkingMessage.remove();
    if (data.clarify || data.out_of_scope) {
      const text = data.out_of_scope ? datasetGuidance() : data.clarify;
      const message = appendMessage("assistant", text);
      const actions = node("div", "result-actions");
      actions.append(actionButton("Copy", (button) => copyAnswer(button, text)));
      message.append(actions);
      history.push({ role: "assistant", content: text });
    } else {
      renderResult(appendMessage("assistant", ""), data, schema);
      history.push({ role: "assistant", content: JSON.stringify({ summary: `${data.row_count} results`, last_plan: data.plan }).slice(0, 1000) });
    }
  } catch (error) {
    thinkingMessage.remove();
    if (error.name !== "AbortError" && version === datasetVersion) {
      const text = friendlyError(error);
      appendMessage("assistant", text, true);
      history.push({ role: "assistant", content: text });
    }
  } finally {
    thinkingMessage.remove();
    if (version === datasetVersion) { setLoading(false); elements["question-input"].focus(); }
  }
}
async function uploadCsv(file) {
  if (!file.name.toLowerCase().endsWith(".csv")) { elements.status.textContent = "Choose a UTF-8 CSV file."; return; }
  elements["upload-button"].disabled = true;
  elements.status.textContent = "Validating and loading your CSV…";
  try {
    const data = await api(`/api/datasets?filename=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "Content-Type": "text/csv" }, body: file });
    datasets.set(data.dataset_id, data.name);
    await selectDataset(data.dataset_id);
    elements.status.textContent = `“${data.name}” is ready.`;
  } catch (error) { elements.status.textContent = friendlyError(error, "upload"); }
  finally { elements["upload-button"].disabled = false; elements["file-input"].value = ""; }
}
function collapseChat(collapsed) {
  elements.workspace.classList.toggle("chat-collapsed", collapsed);
  elements["chat-panel"].hidden = collapsed;
  elements["open-chat"].hidden = !collapsed;
  elements["open-chat"].setAttribute("aria-expanded", String(!collapsed));
  if (collapsed) elements["open-chat"].focus();
  else { charts.forEach((chart) => chart.resize()); elements["question-input"].focus(); }
}
elements["chat-form"].addEventListener("submit", (event) => {
  event.preventDefault();
  const question = elements["question-input"].value.trim();
  if (!question || queryPending) return;
  elements["question-input"].value = "";
  ask(question);
});
elements["question-input"].addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); elements["chat-form"].requestSubmit(); }
});
elements["row-search"].addEventListener("input", () => { filterRows(); renderExplorer(); });
elements["data-table"].addEventListener("scroll", () => requestAnimationFrame(renderRowWindow));
elements["close-chat"].addEventListener("click", () => collapseChat(true));
elements["open-chat"].addEventListener("click", () => collapseChat(false));
elements["upload-button"].addEventListener("click", () => elements["file-input"].click());
elements["file-input"].addEventListener("change", () => { if (elements["file-input"].files[0]) uploadCsv(elements["file-input"].files[0]); });
elements["dataset-select"].addEventListener("change", () => selectDataset(elements["dataset-select"].value));
selectDataset("default");
