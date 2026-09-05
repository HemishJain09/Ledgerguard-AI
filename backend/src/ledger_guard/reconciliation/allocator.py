"""
Phase 3, Block 5 — Immutable Audit Trail & Transaction Manager

Safely commits verified solutions to the persistent database.
Uses lexicographically sorted row locks to prevent deadlocks.
"""

from decimal import Decimal
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from ledger_guard.db.models import FactLedger, AllocationRecord, ExceptionRecord, DecisionRecord
from ledger_guard.reconciliation.models import ProposedSolution

def commit_decision(
    solution: ProposedSolution,
    decision_status: str,
    verifier_logs: Dict[str, Any],
    db: Session,
    ast_program: Optional[Dict[str, Any]] = None
) -> DecisionRecord:
    """
    The final Block 5 transaction gate.
    Always appends a DecisionRecord for audit trail.
    If AUTO_RESOLVE, atomically mutates FactLedger using lexicographical row locks.
    """
    try:
        # 1. Create the Immutable Audit Trail entry
        decision = DecisionRecord(
            decision_status=decision_status,
            cluster_id=solution.cluster_id,
            solution_payload=solution.model_dump(mode="json"),
            verifier_logs=verifier_logs,
            ast_program=ast_program
        )
        db.add(decision)
        
        # 2. If not AUTO_RESOLVE, push to Exception Dashboard logic (via ExceptionRecord)
        if decision_status != "AUTO_RESOLVE":
            db.commit()
            return decision

        # 3. For AUTO_RESOLVE, we execute ledger mutation with SELECT ... FOR UPDATE
        all_fact_ids = set(solution.source_fact_ids + solution.target_fact_ids)
        sorted_fact_ids = sorted(list(all_fact_ids))
        
        if sorted_fact_ids:
            locked_facts = (
                db.query(FactLedger)
                .filter(FactLedger.id.in_(sorted_fact_ids))
                .with_for_update()
                .order_by(FactLedger.id)
                .all()
            )
            fact_map = {f.id: f for f in locked_facts}
        else:
            fact_map = {}
            
        allocated_amount = solution.allocated_amount
        
        # Create AllocationRecord
        db.add(AllocationRecord(
            source_event_id=solution.source_event_ids[0] if solution.source_event_ids else "",
            target_event_id=solution.target_event_id,
            allocated_amount=allocated_amount,
            match_reason=solution.match_reason,
            match_score=100,
            solver_status=solution.solver_status,
            cluster_id=solution.cluster_id,
            source_fact_ids=solution.source_fact_ids,
            target_fact_ids=solution.target_fact_ids,
        ))
        
        # Deduct balances
        for fid in all_fact_ids:
            fact = fact_map.get(fid)
            if fact and fact.remaining_amount is not None:
                fact.remaining_amount = max(
                    Decimal("0.00"),
                    fact.remaining_amount - allocated_amount
                )
                if fact.remaining_amount <= Decimal("0.01"):
                    fact.status = "ALLOCATED"
                    
        db.commit()
        return decision
        
    except Exception as e:
        db.rollback()
        raise e


def record_exception(
    result: Dict[str, Any],
    cluster: Dict[str, Any],
    db: Session,
) -> ExceptionRecord:
    """
    Persists a solver exception (ABSTAIN, AMBIGUOUS, INFEASIBLE, OVERSIZED)
    into the exception_records table for human review.
    """
    # Serialize cluster data (convert non-serializable types)
    safe_nodes = []
    for n in cluster.get("nodes", []):
        if isinstance(n, (list, tuple)) and len(n) >= 2:
            amt = n[1].get("amount")
            safe_nodes.append({"id": n[0], "type": n[1].get("type"), "amount": float(amt) if amt is not None else 0.0, "description": n[1].get("description")})
        elif isinstance(n, dict):
            amt = n.get("amount")
            safe_nodes.append({"id": n.get("id"), "type": n.get("type"), "amount": float(amt) if amt is not None else 0.0, "description": n.get("description")})

    safe_edges = []
    for e in cluster.get("edges", []):
        if isinstance(e, (list, tuple)) and len(e) >= 3:
            safe_edges.append({"source": e[0], "target": e[1], "score": e[2].get("weight"), "reason": e[2].get("match_reason")})
        elif isinstance(e, dict):
            safe_edges.append({"source": e.get("source"), "target": e.get("target"), "score": e.get("score"), "reason": e.get("reason")})

    safe_cluster = {
        "node_count": cluster.get("node_count", 0),
        "edge_count": cluster.get("edge_count", 0),
        "nodes": safe_nodes,
        "edges": safe_edges,
    }
    
    record = ExceptionRecord(
        cluster_id=result.get("cluster_id", ""),
        reason=result.get("status", "UNKNOWN"),
        cluster_data=safe_cluster,
        status="PENDING",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
