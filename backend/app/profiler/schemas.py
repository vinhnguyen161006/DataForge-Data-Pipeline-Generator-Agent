from pydantic import BaseModel, ConfigDict, Field


class ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ColumnProfile(ProfileModel):
    name: str
    inferred_type: str
    row_count: int = Field(ge=0, strict=True)
    null_ratio: float = Field(ge=0, le=1)
    distinct_count: int = Field(ge=0, strict=True)
    min_value: str | None = None
    max_value: str | None = None
    sample_values: list[str] = Field(default_factory=list, max_length=5)
    has_leading_zeros: bool = False


class KeyCandidate(ProfileModel):
    table: str
    columns: list[str]
    is_unique_in_batch: bool
    null_count: int = Field(ge=0, strict=True)


class RelationshipCandidate(ProfileModel):
    child_table: str
    child_columns: list[str]
    parent_table: str
    parent_columns: list[str]
    match_ratio: float = Field(ge=0, le=1)
    orphan_count: int = Field(ge=0, strict=True)
    parent_key_unique: bool
    fanout_warning: bool
    max_parent_matches: int = Field(ge=0, strict=True)


class TableProfile(ProfileModel):
    name: str
    source_file: str
    row_count: int = Field(ge=0, strict=True)
    columns: list[ColumnProfile]


class DataProfile(ProfileModel):
    """The only data description ever sent to the LLM. Never add raw rows here."""

    tables: list[TableProfile]
    key_candidates: list[KeyCandidate]
    relationship_candidates: list[RelationshipCandidate]
    notes: list[str] = Field(default_factory=list)


class LoadedTable(ProfileModel):
    """A materialized source table; no source filesystem access is needed for profiling."""

    name: str
    source_file: str
