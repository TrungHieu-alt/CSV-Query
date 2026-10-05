import re

import pandas as pd
import streamlit as st

from client import ask_llm
from prompt_wrapper import build_prompt, build_retry_prompt


# =========================
# PAGE CONFIG
# =========================

st.set_page_config(
    page_title="CSV Q&A Demo",
    page_icon="📊",
    layout="wide"
)


# =========================
# LOAD CSV
# =========================

CSV_FILE = "data/sales_data.csv"


@st.cache_data
def load_data():
    df = pd.read_csv(CSV_FILE)

    # Convert order_date from text to datetime
    df["order_date"] = pd.to_datetime(df["order_date"])

    return df


df = load_data()


# =========================
# HELPERS: parse & safely run the LLM's pandas query
# =========================

# Model được yêu cầu output đúng 1 trong 2 dạng:
#   QUERY: <expr>
#   CLARIFY: <question>
QUERY_RE = re.compile(r"QUERY:\s*(.+)", re.IGNORECASE)
CLARIFY_RE = re.compile(r"CLARIFY:\s*(.+)", re.IGNORECASE)
CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)

# very small denylist so the demo doesn't eval something dangerous
FORBIDDEN_RE = re.compile(
    r"__|import\s|exec\s*\(|eval\s*\(|open\s*\(|os\.|sys\.|subprocess|\bdel\b"
)


def parse_llm_response(llm_response: str):
    """
    Parse phản hồi của Gemini theo contract QUERY:/CLARIFY:.
    Trả về (query, clarification) — đúng một trong hai sẽ có giá trị.
    Fallback: nếu model không tuân thủ format (vẫn có thể xảy ra),
    cố gắng bóc code block hoặc dòng cuối như phiên bản cũ.
    """

    text = llm_response.strip()

    query_match = QUERY_RE.search(text)
    if query_match:
        query = query_match.group(1).strip()
        # bỏ code fence nếu model lỡ bọc thêm
        query = query.strip("`").strip()
        return query, None

    clarify_match = CLARIFY_RE.search(text)
    if clarify_match:
        return None, clarify_match.group(1).strip()

    # --- fallback cho trường hợp model không theo format ---
    block_match = CODE_BLOCK_RE.search(text)
    candidate = block_match.group(1).strip() if block_match else text

    if "df" in candidate:
        lines = [line.strip() for line in candidate.splitlines() if line.strip()]
        if lines:
            return lines[-1], None

    return None, text


def run_query(query: str):
    """Evaluate the pandas query with only df/pd exposed."""

    if FORBIDDEN_RE.search(query):
        raise ValueError("Query bị chặn vì chứa từ khoá không an toàn.")

    return eval(query, {"df": df, "pd": pd}, {})


def render_result(container, result):
    if isinstance(result, (pd.DataFrame, pd.Series)):
        container.dataframe(result, use_container_width=True)
    else:
        container.write(result)


def answer_question(question: str):
    """
    Chạy full pipeline cho 1 câu hỏi, có tự retry 1 lần khi query
    sinh ra bị lỗi lúc eval (gửi lỗi ngược lại cho Gemini để tự sửa).
    Trả về dict turn.
    """

    raw_response = ""
    query = None
    clarification = None
    result = None
    error = None
    retried = False

    try:
        prompt = build_prompt(question)
        raw_response = ask_llm(prompt)
    except Exception as exc:
        error = f"Không gọi được Gemini: {exc}"
        return {
            "question": question, "raw": raw_response, "query": query,
            "clarification": clarification, "result": result,
            "error": error, "retried": retried,
        }

    query, clarification = parse_llm_response(raw_response)

    if query:
        try:
            result = run_query(query)
        except Exception as exc:
            first_error = str(exc)

            # Tự sửa 1 lần: gửi query lỗi + thông báo lỗi thật cho Gemini
            try:
                retry_prompt = build_retry_prompt(question, query, first_error)
                retry_raw = ask_llm(retry_prompt)
                retried = True

                retry_query, retry_clarification = parse_llm_response(retry_raw)

                if retry_query:
                    query = retry_query
                    result = run_query(query)
                elif retry_clarification:
                    query = None
                    clarification = retry_clarification
                else:
                    error = f"Lỗi khi chạy query: {first_error}"
            except Exception as retry_exc:
                error = f"Lỗi khi chạy query: {first_error} (retry cũng lỗi: {retry_exc})"

    return {
        "question": question,
        "raw": raw_response,
        "query": query,
        "clarification": clarification,
        "result": result,
        "error": error,
        "retried": retried,
    }


# =========================
# PAGE TITLE
# =========================

st.title("📊 Sales Data Q&A")

st.write(
    "Hỏi bằng ngôn ngữ tự nhiên về dữ liệu bán hàng. "
    "Mô hình **Gemini** sẽ sinh câu truy vấn Pandas tương ứng."
)


# =========================
# DATASET OVERVIEW (thu gọn để nhường chỗ cho khung chat)
# =========================

with st.expander("📁 Xem tổng quan dữ liệu", expanded=False):

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Orders", f"{len(df):,}")
    col2.metric("Total Revenue", f"${df['revenue'].sum():,.2f}")
    col3.metric("Products", df["product"].nunique())

    st.subheader("Data Preview")
    st.dataframe(df.head(20), use_container_width=True)

    st.subheader("Data Schema")
    schema_df = pd.DataFrame(
        {
            "Column": df.columns,
            "Data Type": [str(dtype) for dtype in df.dtypes],
            "Missing Values": [
                int(df[column].isnull().sum()) for column in df.columns
            ],
        }
    )
    st.dataframe(schema_df, use_container_width=True)


# =========================
# CHAT STATE
# =========================

if "messages" not in st.session_state:
    # each item: {question, raw, query, clarification, result, error, retried}
    st.session_state.messages = []


def render_turn(container, turn):
    with container:
        if turn["error"]:
            if turn["query"]:
                st.markdown("**🔎 Pandas Query**")
                st.code(turn["query"], language="python")
            st.error(turn["error"])

        elif turn["query"]:
            if turn.get("retried"):
                st.caption("⚙️ Query lỗi ở lần đầu, đã tự sửa lại.")
            st.markdown("**🔎 Pandas Query**")
            st.code(turn["query"], language="python")

            st.markdown("**💬 Trả lời**")
            render_result(st, turn["result"])

        elif turn["clarification"]:
            st.markdown("**💬 Cần làm rõ**")
            st.write(turn["clarification"])

        else:
            st.markdown("**💬 Trả lời**")
            st.write(turn["raw"])


# =========================
# RENDER CHAT HISTORY
# =========================

for turn in st.session_state.messages:
    with st.chat_message("user"):
        st.write(turn["question"])

    with st.chat_message("assistant"):
        render_turn(st.container(), turn)


# =========================
# CHAT INPUT
# =========================

question = st.chat_input("Đặt câu hỏi về dữ liệu bán hàng...")

if question:

    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Đang hỏi Gemini..."):
            turn = answer_question(question)

        render_turn(st.container(), turn)

    st.session_state.messages.append(turn)