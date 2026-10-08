from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Protocol

import pandas as pd
from pydantic import ValidationError

from .executor import PlanExecutionError, dataframe_page, execute_plan
from .plan import QueryPlan
from .prompts import build_prompt, build_repair_prompt
from .viz import choose_result_type, choose_viz


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str: ...


class QueryService:
    def __init__(self, df: pd.DataFrame, schema: list[dict[str, Any]], client: LLMClient) -> None:
        self._df = df
        self._schema = schema
        self._client = client

    @staticmethod
    def _parse(raw: str) -> QueryPlan:
        normalized = raw.strip()
        if normalized.startswith("```") and normalized.endswith("```"):
            lines = normalized.splitlines()
            if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```json"} and lines[-1].strip() == "```":
                normalized = "\n".join(lines[1:-1]).strip()
        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise ValueError("Model output was not valid JSON.") from exc
        try:
            return QueryPlan.model_validate(payload)
        except ValidationError as exc:
            details = json.dumps(exc.errors(include_url=False, include_input=False, include_context=False), ensure_ascii=False)
            raise ValueError(f"Model output did not match the query-plan schema: {details}") from exc

    def _run(self, raw: str) -> dict[str, Any]:
        plan = self._parse(raw)
        if plan.out_of_scope:
            return {"out_of_scope": True}
        if plan.clarify:
            return {"clarify": plan.clarify}
        result = execute_plan(self._df, plan)
        viz = choose_viz(result.dataframe, plan)
        if viz["type"] == "bar" and not plan.sort_by:
            steps = result.pandas_steps + [f"result = result.sort_values({viz['y'][0]!r}, ascending=False, kind='stable')"]
            result = dataframe_page(
                result.dataframe.sort_values(viz["y"][0], ascending=False, kind="stable"),
                limit=plan.limit,
            )
            result = replace(result, pandas_steps=steps)
        return {
            "plan": plan.model_dump(mode="json"),
            "pandas_query": "\n".join(["import pandas as pd", "", "# df is the active CSV dataset, with dates already parsed.", *result.pandas_steps, f"result = result.iloc[:{min(plan.limit, 500)}]"]),
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "viz": viz,
            "result_type": choose_result_type(result.dataframe, plan),
        }

    def query(self, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        raw = self._client.generate(build_prompt(question, self._schema, history))
        try:
            return self._run(raw)
        except (ValueError, PlanExecutionError) as first_error:
            repair_prompt = build_repair_prompt(question, self._schema, raw, str(first_error), history)
            repaired = self._client.generate(repair_prompt)
            try:
                return self._run(repaired)
            except (ValueError, PlanExecutionError) as second_error:
                raise ValueError("Unable to produce a valid query plan after one repair attempt.") from second_error
