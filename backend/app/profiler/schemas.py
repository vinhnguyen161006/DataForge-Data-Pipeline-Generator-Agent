from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    name: str
    inferred_type: str
    row_count: int
    null_ratio: float
    distinct_count: int
    min_value: str | None = None
    max_value: str | None = None
    sample_values: list[str] = Field(default_factory=list, max_length=5)
    has_leading_zeros: bool = False


class KeyCandidate(BaseModel):
    table: str
    columns: list[str]
    is_unique_in_batch: bool
    null_count: int


class RelationshipCandidate(BaseModel):
    child_table: str
    child_columns: list[str]
    parent_table: str
    parent_columns: list[str]
    match_ratio: float
    orphan_count: int
    parent_key_unique: bool
    fanout_warning: bool
    max_parent_matches: int


class TableProfile(BaseModel):
    name: str
    source_file: str
    row_count: int
    columns: list[ColumnProfile]


class DataProfile(BaseModel):
    """The only data description ever sent to the LLM. Never add raw rows here."""

    tables: list[TableProfile]
    key_candidates: list[KeyCandidate]
    relationship_candidates: list[RelationshipCandidate]
    notes: list[str] = Field(default_factory=list)
