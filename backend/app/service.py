from __future__ import annotations

import json
from typing import Any, Protocol

import pandas as pd
from pydantic import ValidationError

from .executor import PlanExecutionError, execute_plan
from .plan import QueryPlan
from .prompts import build_prompt, build_repair_prompt


class LLMClient(Protocol):
    def generate(self, prompt: str) -> str: ...


class QueryService:
    def __init__(self, df: pd.DataFrame, schema: list[dict[str, Any]], client: LLMClient) -> None:
        self._df = df
        self._schema = schema
        self._client = client

    @staticmethod
    def _parse(raw: str) -> QueryPlan:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Model output was not valid JSON.") from exc
        try:
            return QueryPlan.model_validate(payload)
        except ValidationError as exc:
            raise ValueError("Model output did not match the query-plan schema.") from exc

    def _run(self, raw: str) -> dict[str, Any]:
        plan = self._parse(raw)
        if plan.clarify:
            return {"clarify": plan.clarify}
        result = execute_plan(self._df, plan)
        return {
            "plan": plan.model_dump(mode="json"),
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
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
