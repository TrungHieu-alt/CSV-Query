const UI = Object.freeze({
  subtitle: "Ask questions in everyday language. Your answer is produced by a validated, code-free query plan.",
  welcome: "What would you like to know about the 2025 sales data?",
  placeholder: "e.g. Total revenue by region",
  send: "Ask",
  loading: "Analyzing the data…",
  errorPrefix: "Sorry, that query could not be completed: ",
  networkError: "The API is unavailable. Check that the backend is running.",
  generatedPlan: "Generated plan",
  noRows: "No matching rows.",
  truncated: "Showing the first 500 rows.",
  rowCount: (count) => `${count} result${count === 1 ? "" : "s"}`,
});

const apiBaseUrl = (window.APP_CONFIG?.API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");
const messagesElement = document.querySelector("#messages");
const examplesElement = document.querySelector("#examples");
const form = document.querySelector("#chat-form");
const input = document.querySelector("#question-input");
const sendButton = document.querySelector("#send-button");
const statusElement = document.querySelector("#status");
const history = [];

document.querySelector("#subtitle").textContent = UI.subtitle;
input.placeholder = UI.placeholder;
sendButton.textContent = UI.send;

function appendMessage(role, text, isError = false) {
  const message = document.createElement("article");
  message.classList.add("message", role);
  if (isError) message.classList.add("error");
  const content = document.createElement("div");
  content.textContent = text;
  message.append(content);
  messagesElement.append(message);
  messagesElement.scrollTop = messagesElement.scrollHeight;
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

function appendTable(container, columns, rows) {
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
  container.append(wrapper);
}

function setLoading(loading) {
  input.disabled = loading;
  sendButton.disabled = loading;
  statusElement.textContent = loading ? UI.loading : "";
}

async function ask(question) {
  appendMessage("user", question);
  history.push({ role: "user", content: question });
  setLoading(true);
  try {
    const response = await fetch(`${apiBaseUrl}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: history.slice(-6, -1) }),
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
    if (data.rows?.length) appendTable(message, data.columns, data.rows);
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
    input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = input.value.trim();
  if (!question) return;
  input.value = "";
  ask(question);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

async function loadExamples() {
  try {
    const response = await fetch(`${apiBaseUrl}/api/schema`);
    if (!response.ok) return;
    const data = await response.json();
    data.examples.forEach((example) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = example;
      chip.addEventListener("click", () => ask(example));
      examplesElement.append(chip);
    });
  } catch (_error) {
    // The main query flow displays connection errors; chips are optional.
  }
}

appendMessage("assistant", UI.welcome);
loadExamples();

