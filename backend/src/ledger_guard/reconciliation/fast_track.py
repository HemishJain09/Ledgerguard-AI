import uuid
from typing import List
from sqlalchemy.orm import Session

from ledger_guard.reconciliation.models import FinancialEvent

def execute_fast_track(events: List[FinancialEvent], db: Session) -> List[FinancialEvent]:
    """
    Tier 1: 1:1 Deterministic Fast-Track.
    Identifies mathematically perfect 1:1 matches (Exact transaction ID + Exact Amount + Same Currency)
    and instantly commits them, bypassing candidate generation and solver compute entirely.
    """
    # Group events by type
    sales = [e for e in events if e.event_type == "SALE_EVENT"]
    pg_payments = [e for e in events if e.event_type == "PG_PAYMENT_EVENT"]
    pg_payouts = [e for e in events if e.event_type == "PG_PAYOUT_EVENT"]
    bank_settlements = [e for e in events if e.event_type == "BANK_SETTLEMENT_EVENT"]
    
    fast_tracked_ids = set()
    matched_pairs = []
    
    # 1. Match Sales to PG Payments (Gross)
    for sale in sales:
        if not sale.transaction_id or sale.transaction_id == "UNKNOWN":
            continue
            
        for pg in pg_payments:
            if pg.id in fast_tracked_ids:
                continue
                
            # Allow for concatenated gateway strings (e.g. txn_123 vs pg_txn_123)
            id_match = (sale.transaction_id in pg.transaction_id) or (sale.transaction_id in pg.description)
                
            if id_match and sale.amount == pg.amount and sale.currency == pg.currency:
                fast_tracked_ids.add(sale.id)
                fast_tracked_ids.add(pg.id)
                
                matched_pairs.append({
                    "source_id": sale.id,
                    "target_id": pg.id,
                    "allocated_amount": float(sale.amount),
                    "match_score": 100,
                    "match_reason": "FAST_TRACK_1_TO_1",
                    "source_fact_ids": sale.fact_ids,
                    "target_fact_ids": pg.fact_ids,
                })
                break
                
    # 2. Match PG Payouts to Bank Settlements (Net)
    for pg in pg_payouts:
        if not pg.transaction_id or pg.transaction_id == "UNKNOWN":
            continue
            
        for bank in bank_settlements:
            if bank.id in fast_tracked_ids:
                continue
                
            # Bank statements often embed the gateway payout UTR inside the description or append it.
            utr_match = (pg.transaction_id in bank.transaction_id) or (pg.transaction_id in bank.description)
                
            if utr_match and pg.amount == bank.amount and pg.currency == bank.currency:
                
                fast_tracked_ids.add(pg.id)
                fast_tracked_ids.add(bank.id)
                
                matched_pairs.append({
                    "source_id": pg.id,
                    "target_id": bank.id,
                    "allocated_amount": float(pg.amount),
                    "match_score": 100,
                    "match_reason": "FAST_TRACK_1_TO_1",
                    "source_fact_ids": pg.fact_ids,
                    "target_fact_ids": bank.fact_ids,
                })
                break
                
    # Commit in a single batch to respect concurrency lexicographical locks
    if matched_pairs:
        from decimal import Decimal
        from ledger_guard.reconciliation.models import ProposedSolution
        from ledger_guard.reconciliation.allocator import commit_decision
        from ledger_guard.reconciliation.verifier import gatekeeper_decision
        
        cluster_id = "fast-track-" + str(uuid.uuid4())[:8]
        for pair in matched_pairs:
            solution = ProposedSolution(
                source_event_ids=[pair["source_id"]],
                target_event_id=pair["target_id"],
                source_fact_ids=pair.get("source_fact_ids", []),
                target_fact_ids=pair.get("target_fact_ids", []),
                allocated_amount=Decimal(str(pair["allocated_amount"])),
                match_reason=pair.get("match_reason", ""),
                cluster_id=cluster_id,
                solver_status="FAST_TRACK"
            )
            b5_decision, b5_logs = gatekeeper_decision(solution, db)
            commit_decision(solution, b5_decision, b5_logs, db)
        
    # Return remaining events
    return [e for e in events if e.id not in fast_tracked_ids]
