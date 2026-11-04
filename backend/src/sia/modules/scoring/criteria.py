"""The ideal customer profile (ICP): which criteria matter and how much.

Stored as JSON and validated with this schema on every read and write. A discriminated union
(`kind`) keeps each criterion type's fields strict; one criterion per kind.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from sia.modules.enrichment.extraction import BusinessModel

Importance = Annotated[int, Field(ge=1, le=5, description="1 = minor ... 5 = critical")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=50)]

IMPORTANCE_LABELS = {1: "Minor", 2: "Low", 3: "Medium", 4: "High", 5: "Critical"}


class _Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    importance: Importance = 3
    must_have: bool = Field(default=False, description="Failing it disqualifies the company")


class IndustryCriterion(_Criterion):
    kind: Literal["industry"] = "industry"
    industries: list[Label] = Field(min_length=1, max_length=30)


class SizeCriterion(_Criterion):
    kind: Literal["size"] = "size"
    min_employees: int | None = Field(default=None, ge=0)
    max_employees: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _bounds(self) -> Self:
        if self.min_employees is None and self.max_employees is None:
            raise ValueError("Set a minimum or a maximum number of employees.")
        if (
            self.min_employees is not None
            and self.max_employees is not None
            and self.min_employees > self.max_employees
        ):
            raise ValueError("The minimum is larger than the maximum.")
        return self


class CountryCriterion(_Criterion):
    kind: Literal["country"] = "country"
    countries: list[Label] = Field(min_length=1, max_length=50)


class BusinessModelCriterion(_Criterion):
    kind: Literal["business_model"] = "business_model"
    models: list[BusinessModel] = Field(min_length=1, max_length=4)


class KeywordCriterion(_Criterion):
    kind: Literal["keywords"] = "keywords"
    keywords: list[Keyword] = Field(min_length=1, max_length=20)


class ContactsCriterion(_Criterion):
    kind: Literal["has_contacts"] = "has_contacts"
    min_contacts: int = Field(default=1, ge=1, le=1000)


Criterion = Annotated[
    IndustryCriterion
    | SizeCriterion
    | CountryCriterion
    | BusinessModelCriterion
    | KeywordCriterion
    | ContactsCriterion,
    Field(discriminator="kind"),
]


class ICPDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criteria: list[Criterion] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def _one_per_kind(self) -> Self:
        kinds = [c.kind for c in self.criteria]
        if len(kinds) != len(set(kinds)):
            raise ValueError("Each kind of criterion can be used only once.")
        return self
