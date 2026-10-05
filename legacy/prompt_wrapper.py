"""
Prompt wrapper for Gemini.

This module builds a complete prompt using:

- System Prompt
- Dataset Schema
- Business Rules
- Clarification Rules
- Examples (question -> intent -> query mẫu thật)
- User Question

Output contract (bắt buộc model tuân theo, để app.py parse dễ và
ít lỗi hơn so với việc đoán "dòng cuối có chữ df là code"):

    QUERY: <một dòng biểu thức pandas duy nhất, dùng biến df>

hoặc, khi câu hỏi mơ hồ:

    CLARIFY: <một câu hỏi làm rõ>
"""

from schema import (
    SCHEMA,
    BUSINESS_RULES,
    CLARIFICATION_RULES,
    EXAMPLES,
)


SYSTEM_PROMPT = """
You are an expert data analysis assistant.

Your ONLY responsibility is to understand the user's question
and generate a valid single-line Pandas expression for the
provided dataset (a DataFrame called `df`), OR ask for
clarification when the question is ambiguous.

IMPORTANT RULES

- ONLY use columns defined in the dataset schema.
- NEVER invent columns.
- NEVER invent values.
- NEVER use knowledge outside the dataset.
- Read the schema descriptions carefully before answering.
- Use business rules to understand the dataset semantics.
- If the question is ambiguous, DO NOT guess. Ask ONE clarification question.
- Think step by step internally, but only output the final line below.
- The pandas expression MUST be a single line, MUST reference `df`,
  and MUST NOT use import, exec, eval, open, os, sys, subprocess, or del.

OUTPUT FORMAT (STRICT — output exactly one of the two lines, nothing else):

QUERY: <single-line pandas expression using df>
CLARIFY: <one clarification question>

Do NOT add explanations, markdown fences, or extra text before or after
this line. Do NOT output both QUERY and CLARIFY.
""".strip()


def _render_schema() -> str:

    sections = []

    for column in SCHEMA:

        text = [
            f"Column: {column['name']}",
            f"Type: {column['type']}",
            f"Description: {column['description']}"
        ]

        if "unit" in column:
            text.append(f"Unit: {column['unit']}")

        if "format" in column:
            text.append(f"Format: {column['format']}")

        if "formula" in column:
            text.append(f"Formula: {column['formula']}")

        if "allowed_values" in column:
            text.append(
                "Allowed Values: "
                + ", ".join(column["allowed_values"])
            )

        if "examples" in column:
            text.append(
                "Examples: "
                + ", ".join(column["examples"])
            )

        if "synonyms" in column:
            text.append(
                "Synonyms: "
                + ", ".join(column["synonyms"])
            )

        sections.append("\n".join(text))

    return "\n\n".join(sections)


def _render_business_rules():

    return "\n".join(
        f"- {rule}"
        for rule in BUSINESS_RULES
    )


def _render_clarification_rules():

    return "\n".join(
        f"- {rule}"
        for rule in CLARIFICATION_RULES
    )


def _render_examples():

    blocks = []

    for example in EXAMPLES:

        if example.get("query"):
            output_line = f"QUERY: {example['query']}"
        else:
            output_line = f"CLARIFY: {example['intent']}"

        blocks.append(
            f"""
User:
{example['question']}

Intent:
{example['intent']}

Output:
{output_line}
""".strip()
        )

    return "\n\n".join(blocks)


def build_prompt(user_question: str) -> str:

    return f"""
{SYSTEM_PROMPT}

==================================================
DATASET SCHEMA
==================================================

{_render_schema()}

==================================================
BUSINESS RULES
==================================================

{_render_business_rules()}

==================================================
CLARIFICATION RULES
==================================================

{_render_clarification_rules()}

==================================================
EXAMPLES
==================================================

{_render_examples()}

==================================================
USER QUESTION
==================================================

{user_question}

==================================================
YOUR TASK
==================================================

1. Read the schema carefully.
2. Understand the user's intent.
3. Verify that all requested fields exist.
4. Verify the request is unambiguous.
5. Output exactly ONE line following the OUTPUT FORMAT above.
""".strip()


def build_retry_prompt(user_question: str, failed_query: str, error_message: str) -> str:
    """
    Prompt sửa lỗi: gửi lại câu hỏi gốc + query đã sinh ra + lỗi thực tế
    khi eval(), để model tự sửa. Giúp hệ thống "khôn" hơn thay vì chịu
    thua ngay lần đầu chạy lỗi.
    """

    return f"""
{SYSTEM_PROMPT}

==================================================
DATASET SCHEMA
==================================================

{_render_schema()}

==================================================
BUSINESS RULES
==================================================

{_render_business_rules()}

==================================================
CONTEXT
==================================================

The user asked:
{user_question}

You previously generated this pandas expression:
{failed_query}

Running it raised this error:
{error_message}

==================================================
YOUR TASK
==================================================

Fix the expression so it runs successfully against `df` and correctly
answers the user's question. Output exactly ONE line following the
OUTPUT FORMAT below.

QUERY: <single-line pandas expression using df>
CLARIFY: <one clarification question, only if the fix truly requires
more information from the user>
""".strip()