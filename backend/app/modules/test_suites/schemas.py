from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.test_suites.models import VariableExtractionSource


class VariableExtractionInput(BaseModel):
    variable_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    source: VariableExtractionSource
    expression: str | None = Field(default=None, max_length=512)

    @field_validator("expression")
    @classmethod
    def validate_expression(cls, value: str | None, info: object) -> str | None:
        source = getattr(info, "data", {}).get("source")
        if source == VariableExtractionSource.STATUS_CODE:
            if value is not None:
                raise ValueError("状态码提取不需要 expression")
            return value
        if value is None or not value.strip():
            raise ValueError("该提取方式需要 expression")
        return value.strip()


class TestSuiteStepInput(BaseModel):
    test_case_id: UUID
    request_override: dict[str, object] = Field(default_factory=dict)
    variable_extractions: list[VariableExtractionInput] = Field(default_factory=list, max_length=20)


class TestSuiteCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    stop_on_failure: bool = True
    steps: list[TestSuiteStepInput] = Field(min_length=1, max_length=100)


class TestSuiteUpdateRequest(TestSuiteCreateRequest):
    pass


class VariableExtractionResponse(VariableExtractionInput):
    id: UUID


class TestSuiteStepResponse(BaseModel):
    id: UUID
    test_case_id: UUID
    position: int
    request_override: dict[str, object]
    variable_extractions: list[VariableExtractionResponse]


class TestSuiteResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: str | None
    stop_on_failure: bool
    created_at: datetime
    updated_at: datetime
    steps: list[TestSuiteStepResponse] = Field(default_factory=list)


class TestSuiteRunRequest(BaseModel):
    environment_id: UUID
    write_confirmed: bool = False
    confirmed_host: str | None = Field(default=None, max_length=2048)
