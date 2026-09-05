from decimal import Decimal
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from ledger_guard.db.models import FactLedger
from ledger_guard.reconciliation.models import ProposedSolution

def gatekeeper_decision(solution: ProposedSolution, db: Session) -> Tuple[str, Dict[str, Any]]:
    """
    Block 5: The Deterministic Verifier & Decision Engine Router
    Enforces 3 strict checks before allowing a case to proceed.
    Returns (decision_status, verifier_logs)
    """
    logs = {
        "provenance": "PENDING",
        "source_authority": "PENDING",
        "completeness": "PENDING",
        "residual": "0.00",
        "error_message": None
    }
    
    # Check 1: Provenance & Validity
    # Cross-reference every fact ID against active FactLedger
    all_fact_ids = set(solution.source_fact_ids + solution.target_fact_ids)
    if not all_fact_ids:
        logs["provenance"] = "FAILED"
        logs["error_message"] = "No facts provided in solution"
        return "ABSTAIN", logs
        
    facts = db.query(FactLedger).filter(FactLedger.id.in_(all_fact_ids)).all()
    fact_map = {f.id: f for f in facts}
    
    missing_facts = all_fact_ids - set(fact_map.keys())
    if missing_facts:
        logs["provenance"] = "FAILED"
        logs["error_message"] = f"Hallucinated or missing facts: {missing_facts}"
        return "ESCALATE", logs
        
    for fid, fact in fact_map.items():
        if fact.remaining_amount is None or fact.remaining_amount <= 0:
            logs["provenance"] = "FAILED"
            logs["error_message"] = f"Fact {fid} is already fully consumed (remaining_amount <= 0)"
            return "ESCALATE", logs
            
    logs["provenance"] = "PASSED"
    
    # Check 2 & 3: Source Authority & Completeness Check
    allocated = solution.allocated_amount
    
    # Check if remaining_amount can cover it
    source_remaining_sum = sum(fact_map[fid].remaining_amount for fid in solution.source_fact_ids)
    if source_remaining_sum < allocated:
        logs["completeness"] = "FAILED"
        logs["error_message"] = f"Source facts insufficient total balance: {source_remaining_sum} < {allocated}"
        return "ESCALATE", logs
        
    target_remaining_sum = sum(fact_map[fid].remaining_amount for fid in solution.target_fact_ids)
    if target_remaining_sum < allocated:
        logs["completeness"] = "FAILED"
        logs["error_message"] = f"Target facts insufficient total balance: {target_remaining_sum} < {allocated}"
        return "ESCALATE", logs

    # Re-enforce Source Authority: Strict Decimal Arithmetic (Gateway overrides ERP)
    # The allocated_amount from the proposed solution must mathematically balance.
    # Gateway (Gross - Fees) vs ERP (Net).
    source_net = sum(fact_map[fid].amount if fact_map[fid].direction == 'CREDIT' else -fact_map[fid].amount for fid in solution.source_fact_ids)
    target_net = sum(fact_map[fid].amount if fact_map[fid].direction == 'CREDIT' else -fact_map[fid].amount for fid in solution.target_fact_ids)
    
    residual = target_net - source_net
    logs["residual"] = str(residual)
    
    if abs(residual) > Decimal("0.001"):
        logs["completeness"] = "FAILED"
        logs["source_authority"] = "FAILED"
        logs["error_message"] = f"Residual break of {residual} remains. Gateway math contradicts ERP or data missing."
        return "ESCALATE", logs
        
    logs["completeness"] = "PASSED"
    logs["source_authority"] = "PASSED"
    
    # Decision Engine
    if solution.solver_status == "AMBIGUOUS":
        return "REVIEW", logs
        
    return "AUTO_RESOLVE", logs
