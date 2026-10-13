"""文件说明：配套资料v2分类型字段；案例十列、图片三字段，未知字段拒绝。"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class BaseFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)


class CaseFields(BaseFields):
    person_category: str = Field(default="", max_length=1000)
    position: str = Field(default="", max_length=1000)
    rank: str = Field(default="", max_length=1000)
    political_status: str = Field(default="", max_length=1000)
    age: str = Field(default="", max_length=1000)
    domains: list[str] = Field(default_factory=list, max_length=10)
    problem_types: list[str] = Field(default_factory=list, max_length=20)
    outcome: str = Field(default="", max_length=10000)
    original: str = Field(min_length=1, max_length=30000)

    @field_validator("domains", "problem_types")
    @classmethod
    def clean_values(cls, values):
        values = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        if any(len(v) > 100 or ";" in v or "；" in v for v in values):
            raise ValueError("每项最多100字，单项不能包含分号")
        return values


class ImageFields(BaseFields):
    tags: list[str] = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=10000)

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values):
        values = CaseFields.clean_values(values)
        if not values:
            raise ValueError("至少填写一个标签")
        return values


class SaveMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    fields: CaseFields | ImageFields


class MaterialAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=36)
    expected_version: int = Field(ge=1)


class BatchAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["PUBLISH", "OFFLINE"]
    items: list[MaterialAction] = Field(min_length=1, max_length=100)
