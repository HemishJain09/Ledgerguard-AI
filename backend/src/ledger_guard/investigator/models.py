from pydantic import BaseModel, Field
from typing import List, Literal, Any, Dict
from enum import Enum

class DslOperationType(str, Enum):
    SUBTRACT = "SUBTRACT"
    ADD = "ADD"
    MULTIPLY = "MULTIPLY"
    COMPARE = "COMPARE"
    DATE_DIFF = "DATE_DIFF"
    RULE_LOOKUP = "RULE_LOOKUP"

class DslOperation(BaseModel):
    op: DslOperationType = Field(description="The atomic operation to execute")
    a: str = Field(description="The first operand. Usually a variable name or fact_id attribute (e.g. EVT_1.gross) or string literal for numbers")
    b: str | None = Field(description="The second operand. Usually a variable name, string literal, or None for unary operations")
    result_var: str = Field(description="The name of the variable to store the result in the execution sandbox")

class InvestigationResult(BaseModel):
    classification: Literal[
        "TIMING_DIFFERENCE", 
        "EXPECTED_FEE", 
        "EXPECTED_ADJUSTMENT", 
        "SOURCE_CONTRADICTION",
        "UNRESOLVED",
        "MISSING_RECORD",
        "AMOUNT_VARIANCE",
        "DATA_QUALITY_ERROR"
    ] = Field(description="The semantic classification of the discrepancy")
    hypothesis: str = Field(description="A human-readable economic explanation of the discrepancy")
    facts_used: List[str] = Field(default_factory=list, description="List of fact/event IDs cited in the hypothesis")
    dsl_program: List[DslOperation] = Field(default_factory=list, description="The PoT operations to execute and prove the hypothesis")

class EvidenceBundle(BaseModel):
    cluster_id: str
    variables: Dict[str, Any] = Field(description="Pre-loaded variables mapping strings (e.g. EVT_1.gross) to Decimal or date values")
    target_event_id: str = Field(description="The ID of the target bank deposit to reconcile against")
    policy: Dict[str, Any] = Field(description="Policy boundaries, such as max_fee_pct or max_backward_adjustment_days")
    candidate_relationships: List[str] = Field(default_factory=list, description="IDs of related events provided to solve the case")
    global_context: str = Field(default="", description="Provenance metadata and raw file logs for isolation analysis")
