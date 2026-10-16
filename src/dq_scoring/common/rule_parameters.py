"""Pure Pydantic parameter schemas for extended quality rules (text, spelling, JSON)."""

import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictParameterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextQualityParameters(StrictParameterModel):
    column: str = Field(min_length=1)
    check: Literal["REPLACEMENT_CHARACTER", "CONTROL_CHARACTER", "MOJIBAKE", "LENGTH"]
    min_length: int | None = Field(default=None, ge=0, strict=True)
    max_length: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def validate_length_bounds(self) -> "TextQualityParameters":
        if self.check == "LENGTH":
            if self.min_length is None and self.max_length is None:
                raise ValueError("At least one of min_length or max_length is required for check='LENGTH'")
            if self.min_length is not None and self.max_length is not None and self.min_length > self.max_length:
                raise ValueError("min_length cannot exceed max_length")
        return self


class SpellingParameters(StrictParameterModel):
    column: str = Field(min_length=1)
    language: Literal["vi", "en", "vi-en"]
    dictionary_revision: str = Field(min_length=1)
    accepted_terms: list[str] = Field(default_factory=list)
    dictionary_digests: dict[str, list[dict[str, str]]] | None = None

    @field_validator("accepted_terms")
    @classmethod
    def validate_accepted_terms(cls, terms: list[str]) -> list[str]:
        if len(terms) > 1000:
            raise ValueError("accepted_terms cannot exceed 1000 items")
        for term in terms:
            if len(term) > 128:
                raise ValueError(f"accepted_term '{term[:20]}...' exceeds 128 characters")
        return terms


class JsonFieldParameters(StrictParameterModel):
    column: str = Field(min_length=1)
    path: str
    check: Literal["NON_NULL", "TYPE", "RANGE", "REGEX", "ALLOWED_VALUES"]
    expected_type: Literal["STRING", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY"] | None = None
    min: str | None = None
    max: str | None = None
    pattern: str | None = None
    allowed_values: list[str] | None = None

    @field_validator("path")
    @classmethod
    def validate_rfc6901_path(cls, path: str) -> str:
        if path != "" and not path.startswith("/"):
            raise ValueError("RFC 6901 JSON Pointer path must be '' (root) or start with '/'")
        if re.search(r"~(?![01])", path):
            raise ValueError("Invalid JSON Pointer escape")
        return path

    @field_validator("pattern")
    @classmethod
    def validate_pattern_length(cls, pattern: str | None) -> str | None:
        if pattern is not None and len(pattern) > 512:
            raise ValueError("pattern cannot exceed 512 characters")
        return pattern

    @model_validator(mode="after")
    def validate_check_payload(self) -> "JsonFieldParameters":
        if self.check == "TYPE":
            if not self.expected_type:
                raise ValueError("expected_type is required when check='TYPE'")
        elif self.check == "RANGE":
            if self.min is None and self.max is None:
                raise ValueError("At least one of min or max is required when check='RANGE'")
            min_dec: Decimal | None = None
            max_dec: Decimal | None = None
            if self.min is not None:
                try:
                    min_dec = Decimal(self.min)
                except InvalidOperation as exc:
                    raise ValueError(f"Invalid decimal string min='{self.min}'") from exc
            if self.max is not None:
                try:
                    max_dec = Decimal(self.max)
                except InvalidOperation as exc:
                    raise ValueError(f"Invalid decimal string max='{self.max}'") from exc
            if any(bound is not None and not bound.is_finite() for bound in (min_dec, max_dec)):
                raise ValueError("RANGE bounds must be finite decimal strings")
            if min_dec is not None and max_dec is not None and min_dec > max_dec:
                raise ValueError(f"min ({self.min}) cannot exceed max ({self.max})")
        elif self.check == "REGEX":
            if not self.pattern:
                raise ValueError("pattern is required when check='REGEX'")
        elif self.check == "ALLOWED_VALUES":
            if not self.allowed_values or len(self.allowed_values) == 0:
                raise ValueError("allowed_values list is required when check='ALLOWED_VALUES'")
            if len(self.allowed_values) > 1000:
                raise ValueError("allowed_values cannot exceed 1000 items")
        return self


class JsonArrayParameters(StrictParameterModel):
    column: str = Field(min_length=1)
    path: str
    min_items: int | None = Field(default=None, ge=0, strict=True)
    max_items: int | None = Field(default=None, ge=0, strict=True)
    unique_items: bool = False

    @field_validator("path")
    @classmethod
    def validate_rfc6901_path(cls, path: str) -> str:
        if path != "" and not path.startswith("/"):
            raise ValueError("RFC 6901 JSON Pointer path must be '' (root) or start with '/'")
        if re.search(r"~(?![01])", path):
            raise ValueError("Invalid JSON Pointer escape")
        return path

    @model_validator(mode="after")
    def validate_array_bounds(self) -> "JsonArrayParameters":
        if self.min_items is None and self.max_items is None and not self.unique_items:
            raise ValueError("At least one of min_items, max_items, or unique_items=True must be configured")
        if self.min_items is not None and self.max_items is not None and self.min_items > self.max_items:
            raise ValueError("min_items cannot exceed max_items")
        return self
