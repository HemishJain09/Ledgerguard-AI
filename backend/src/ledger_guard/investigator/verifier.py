from decimal import Decimal
from typing import Dict, Any, Tuple
from .models import InvestigationResult, EvidenceBundle

def verify_resolution(bundle: EvidenceBundle, variables: Dict[str, Any], result: InvestigationResult) -> Tuple[bool, str]:
    """
    Step 5: Math Verification Gate (Stateless)
    Checks if the PoT program proved the resolution.
    Returns (is_proven, reason_or_decision).
    """
    if not result.dsl_program:
        if not bundle.candidate_relationships:
            valid_orphan_classes = {"MISSING_RECORD", "DATA_QUALITY_ERROR", "AMOUNT_VARIANCE"}
            if result.classification in valid_orphan_classes:
                return False, "ESCALATE" # Safely exit with valid forensic classification
            else:
                from ledger_guard.investigator.executor import ExecutorError
                raise ExecutorError(f"Contradiction: AI output empty AST for orphan but classified as {result.classification}. Must be one of {valid_orphan_classes}")
        return False, "No DSL program provided"
        
    # The architecture assumes the final operation is a COMPARE that produces 'final_match'
    # or at least that the very last operation evaluates to Decimal("1")
    last_op = result.dsl_program[-1]
    
    if last_op.op != "COMPARE":
        return False, "Final operation must be a COMPARE against the target bank deposit"
        
    final_result_var = last_op.result_var
    if final_result_var not in variables:
        return False, f"Final result variable {final_result_var} not found in execution state"
        
    final_val, final_lineage = variables[final_result_var]
    
    if final_val != Decimal("1"):
        return False, "ESCALATE - Math verification failed, result != 1"
        
    # Lineage Continuity Check
    target_event_id = bundle.target_event_id
    
    # Check if target event ID is in lineage
    has_target = any(target_event_id in item for item in final_lineage)
    
    # Check if at least one other non-policy, non-target event is in lineage
    has_source = False
    for item in final_lineage:
        # e.g., EVT_1.gross -> item is "EVT_1.gross"
        if item.startswith("policy.") or item == final_result_var or last_op.a == item or last_op.b == item:
            continue
            
        if target_event_id not in item and "." in item:
            has_source = True
            break
            
    if not has_target or not has_source:
        return False, "ESCALATE - Math verification passed but lineage continuity failed. The LLM generated a disconnected dummy comparison."
        
    return True, "PROVEN_AI_CASE"
