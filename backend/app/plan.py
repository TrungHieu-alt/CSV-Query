from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FilterOperator = Literal["==", "!=", ">", ">=", "<", "<=", "in", "contains"]
AggregationFunction = Literal["sum", "mean", "count", "min", "max", "nunique"]


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1)
    op: FilterOperator
    value: Any


class Aggregation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1)
    func: AggregationFunction
    alias: str = Field(min_length=1, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clarify: str | None = None
    filters: list[Filter] = Field(default_factory=list)
    group_by: list[str] = Field(default_factory=list)
    aggregations: list[Aggregation] = Field(default_factory=list)
    select: list[str] = Field(default_factory=list)
    sort_by: str | None = None
    ascending: bool = True
    limit: int = 50

    @field_validator("limit", mode="before")
    @classmethod
    def cap_limit(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("limit must be an integer")
        try:
            return min(int(value), 500)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer") from exc

    @model_validator(mode="after")
    def validate_shape(self) -> QueryPlan:
        if self.limit < 1:
            raise ValueError("limit must be at least 1")
        if self.clarify:
            execution_fields = (
                self.filters,
                self.group_by,
                self.aggregations,
                self.select,
                self.sort_by,
            )
            if any(execution_fields):
                raise ValueError("a clarification plan cannot contain execution fields")
            return self
        if self.group_by and not self.aggregations:
            raise ValueError("group_by requires at least one aggregation")
        aliases = [item.alias for item in self.aggregations]
        if len(aliases) != len(set(aliases)):
            raise ValueError("aggregation aliases must be unique")
        if set(aliases) & set(self.group_by):
            raise ValueError("aggregation aliases cannot duplicate group_by columns")
        return self

