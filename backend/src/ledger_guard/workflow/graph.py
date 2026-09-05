import polars as pl
from typing import TypedDict, Optional, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from ledger_guard.ingestion.extractor import extract_file
from ledger_guard.ingestion.schema_discovery import discover_schema, apply_mapping, SchemaMapping
from ledger_guard.ingestion.probes import run_deterministic_probes, InvariantProbeError
from ledger_guard.ingestion.idempotency import check_and_register_file, calculate_sha256
from ledger_guard.db.session import SessionLocal
from ledger_guard.ingestion.normalizer import batch_normalize_and_save

class PipelineState(TypedDict):
    file_path: str
    source_hint: str
    raw_df: Optional[list] # List of dicts (JSON serializable)
    schema_mapping: Optional[SchemaMapping]
    mapped_sample_df: Optional[list] # List of dicts
    error_message: Optional[str]
    status: str

def extraction_node(state: PipelineState):
    print(f"-> Extracting {state['file_path']}")
    # 1. Idempotency Check (Block 2)
    db = SessionLocal()
    try:
        is_new = check_and_register_file(state['file_path'], db)
        if not is_new:
            return {"status": "DROPPED"}
    finally:
        db.close()
        
    # 2. Extract Data (Block 1)
    df = extract_file(state['file_path'])
    return {"raw_df": df.to_dicts(), "status": "EXTRACTED"}

def discovery_node(state: PipelineState):
    print("-> Discovering Schema (Block 3)")
    df = pl.DataFrame(state["raw_df"])
    # We pass the source hint to LLM (e.g., 'Razorpay Settlement CSV')
    mapping = discover_schema(df, state["source_hint"])
    
    # Apply mapping to a sample for the probes
    mapped_sample = apply_mapping(df.head(10), mapping)
    
    return {"schema_mapping": mapping, "mapped_sample_df": mapped_sample.to_dicts(), "status": "MAPPED"}

def probes_node(state: PipelineState):
    print("-> Running Invariant Probes (Block 4)")
    try:
        sample_df = pl.DataFrame(state["mapped_sample_df"])
        run_deterministic_probes(sample_df)
        return {"error_message": None, "status": "PROBES_PASSED"}
    except InvariantProbeError as e:
        print(f"!!! PROBES FAILED !!! {e}")
        return {"error_message": str(e), "status": "PROBES_FAILED"}

def human_review_node(state: PipelineState):
    """
    This node represents the React UI. 
    When LangGraph interrupts execution, the thread stops BEFORE running this node.
    The human operator will submit an updated 'schema_mapping' via the state update,
    and then resume the graph.
    """
    print("-> Human Review Complete. Applying new mapping...")
    df = pl.DataFrame(state["raw_df"])
    new_mapping = state["schema_mapping"]
    mapped_sample = apply_mapping(df.head(10), new_mapping)
    return {"mapped_sample_df": mapped_sample.to_dicts(), "status": "MAPPED"}

def persist_node(state: PipelineState):
    print("-> Normalizing & Persisting (Block 6)")
    # Apply mapping to entire dataset now that it's safe
    full_mapped_df = apply_mapping(pl.DataFrame(state["raw_df"]), state["schema_mapping"])
    file_hash = calculate_sha256(state["file_path"])
    batch_normalize_and_save(full_mapped_df, file_hash)
    return {"status": "COMPLETED"}

def should_drop(state: PipelineState):
    if state["status"] == "DROPPED":
        return "end"
    return "discover"

def route_probes(state: PipelineState):
    if state["status"] == "PROBES_FAILED":
        return "human_review"
    return "persist"


# Build the Graph
workflow = StateGraph(PipelineState)

# Add nodes
workflow.add_node("extract", extraction_node)
workflow.add_node("discover", discovery_node)
workflow.add_node("probes", probes_node)
workflow.add_node("human_review", human_review_node)
workflow.add_node("persist", persist_node)

# Set Entry Point
workflow.set_entry_point("extract")

# Edges
workflow.add_conditional_edges("extract", should_drop, {"end": END, "discover": "discover"})
workflow.add_edge("discover", "probes")
workflow.add_conditional_edges("probes", route_probes, {"human_review": "human_review", "persist": "persist"})

# Loop back to probes after human review
workflow.add_edge("human_review", "probes")

workflow.add_edge("persist", END)

# We use a memory saver to enable breakpoints (interrupts)
memory = MemorySaver()
graph = workflow.compile(checkpointer=memory, interrupt_before=["human_review"])
