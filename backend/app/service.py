from __future__ import annotations

import json
from typing import Any, Protocol

import pandas as pd
from pydantic import ValidationError

from .analysis import (
    ANALYSIS_REQUEST_ADAPTER,
    AnalysisRequest,
    AnalysisValidationError,
    ContributionRequest,
    PeriodCompareRequest,
    run_analysis,
    validate_analysis_request,
)
from .executor import PlanExecutionError, dataframe_page, execute_plan
from .llm_client import LLMError
from .narration import (
    NARRATION_SCHEMA,
    build_narration_prompt,
    fallback_narration,
    grounded_or_fallback,
    parse_narration,
)
from .plan import QueryPlan
from .prompts import build_prompt, build_repair_prompt
from .viz import choose_viz


class LLMClient(Protocol):
    def generate(self, prompt: str, response_schema: dict[str, Any] | None = None) -> str: ...


class QueryService:
    def __init__(self, df: pd.DataFrame, schema: list[dict[str, Any]], client: LLMClient) -> None:
        self._df = df
        self._schema = schema
        self._client = client

    @staticmethod
    def _parse(raw: str) -> QueryPlan | AnalysisRequest:
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
            if isinstance(payload, dict) and payload.get("mode") == "analysis":
                return ANALYSIS_REQUEST_ADAPTER.validate_python(payload)
            return QueryPlan.model_validate(payload)
        except ValidationError as exc:
            details = json.dumps(exc.errors(include_url=False, include_input=False), ensure_ascii=False)
            raise ValueError(f"Model output did not match the query or analysis schema: {details}") from exc

    def _follow_ups(self, request: PeriodCompareRequest | ContributionRequest) -> list[str]:
        params = request.params
        excluded = {params.metric, getattr(params, "dimension", None)}
        dimensions = [
            item["name"]
            for item in self._schema
            if item["name"] not in excluded
            and ("allowed_values" in item or any(token in item["type"].lower() for token in ("object", "string", "category")))
        ]
        suggestions = [
            f"Break the {params.metric} change down by {dimension}"
            for dimension in dimensions[:2]
        ]
        if isinstance(request, ContributionRequest):
            suggestions.append(
                f"Compare {params.metric} in {params.period.label} with {params.baseline.label}"
            )
        else:
            suggestions.append(f"Show the underlying rows for {params.period.label}")
        if len(suggestions) < 2:
            suggestions.append(f"Show {params.metric} over time")
        return suggestions[:3]

    def _narrate(
        self,
        question: str,
        request: PeriodCompareRequest | ContributionRequest,
        findings: Any,
    ) -> Any:
        try:
            raw = self._client.generate(
                build_narration_prompt(question, findings, self._schema),
                response_schema=NARRATION_SCHEMA,
            )
            return grounded_or_fallback(parse_narration(raw), findings)
        except (LLMError, ValueError):
            return fallback_narration(findings)

    def _run_analysis(
        self,
        question: str,
        request: PeriodCompareRequest | ContributionRequest,
    ) -> dict[str, Any]:
        validate_analysis_request(self._df, request)
        result = run_analysis(self._df, request)
        narration = self._narrate(question, request, result.findings)
        return {
            "plan": request.model_dump(mode="json"),
            "columns": result.columns,
            "rows": result.rows,
            "row_count": len(result.rows),
            "truncated": False,
            "viz": result.viz,
            "answer": narration.headline,
            "insights": narration.insights,
            "findings": result.findings.model_dump(mode="json"),
            "follow_ups": self._follow_ups(request),
        }

    def _run(self, raw: str, question: str) -> dict[str, Any]:
        plan = self._parse(raw)
        if isinstance(plan, (PeriodCompareRequest, ContributionRequest)):
            return self._run_analysis(question, plan)
        if plan.clarify:
            return {"clarify": plan.clarify}
        result = execute_plan(self._df, plan)
        viz = choose_viz(result.dataframe, plan)
        if viz["type"] == "bar" and not plan.sort_by:
            result = dataframe_page(
                result.dataframe.sort_values(viz["y"][0], ascending=False, kind="stable"),
                limit=plan.limit,
            )
        return {
            "plan": plan.model_dump(mode="json"),
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "viz": viz,
        }

    def query(self, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        raw = self._client.generate(build_prompt(question, self._schema, history))
        try:
            return self._run(raw, question)
        except (ValueError, PlanExecutionError, AnalysisValidationError) as first_error:
            repair_prompt = build_repair_prompt(question, self._schema, raw, str(first_error), history)
            repaired = self._client.generate(repair_prompt)
            try:
                return self._run(repaired, question)
            except (ValueError, PlanExecutionError, AnalysisValidationError) as second_error:
                raise ValueError("Unable to produce a valid query plan after one repair attempt.") from second_error
