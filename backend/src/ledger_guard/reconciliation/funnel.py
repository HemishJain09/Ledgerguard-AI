from decimal import Decimal
from typing import List
from thefuzz import fuzz
from .models import FinancialEvent, ReconEdge, ReconJobPolicy
from ledger_guard.config import MATH_TOLERANCE

def generate_candidates(events: List[FinancialEvent], policy: ReconJobPolicy) -> List[ReconEdge]:
    """
    The aggressive deterministic funnel that reduces O(N*M) search space.
    """
    edges = []
    
    # Split by event types to avoid cross-matching apples to oranges
    sales = [e for e in events if e.event_type == "SALE_EVENT"]
    pg_payments = [e for e in events if e.event_type == "PG_PAYMENT_EVENT"]
    
    pg_payouts = [e for e in events if e.event_type == "PG_PAYOUT_EVENT"]
    bank_settlements = [e for e in events if e.event_type == "BANK_SETTLEMENT_EVENT"]
    
    # Funnel 1: Match Sales (ERP) to PG Payments (Gross to Gross)
    for sale in sales:
        for pg in pg_payments:
            # 1. Merchant & Currency Partition
            if sale.currency != pg.currency or sale.currency != policy.target_currency:
                continue
                
            # 2. Temporal Window Pruning
            # Time must strictly flow forward (allowing -1 for cross-timezone UTC/IST boundary)
            t_delta = (pg.transaction_date.date() - sale.transaction_date.date()).days
            if not (-1 <= t_delta <= policy.max_settlement_lag_days):
                continue
                
            # 3. Token & Amount Evidence
            amount_diff = abs(sale.amount - pg.amount)
            
            # Fuzzy match the descriptions and transaction IDs
            score_desc = fuzz.token_set_ratio(str(sale.description), str(pg.description))
            score_id = fuzz.ratio(str(sale.transaction_id), str(pg.transaction_id))
            base_score = max(score_desc, score_id)
            
            # Fractional Temporal Decay: -1 point per day of lag to cleanly break ties across weeks
            # while preserving genuine AMBIGUOUS symmetry for same-day identicals.
            match_score = max(0, base_score - max(0, t_delta))
            
            # Economic Boundary: The parent invoice (Sale) must be large enough to cover the partial PG payment
            # We allow a small 2% variance for rounding/fees.
            economic_bound_met = sale.amount >= pg.amount * Decimal('0.98')
            
            if economic_bound_met or match_score >= policy.fuzzy_match_threshold:
                reason = "ECONOMIC_BOUND" if economic_bound_met else "FUZZY_TOKEN"
                edges.append(ReconEdge(
                    source_event_id=sale.id,
                    target_event_id=pg.id,
                    match_score=match_score,
                    amount_diff=amount_diff,
                    time_delta_days=t_delta,
                    match_reason=reason
                ))
                
    # Funnel 2: Match PG Payouts to Bank Settlements (Net to Net)
    for pg in pg_payouts:
        for bank in bank_settlements:
            # 1. Merchant & Currency Partition
            if bank.currency != pg.currency or bank.currency != policy.target_currency:
                continue
                
            # 2. Temporal Window Pruning
            # Time must flow forward (allowing -1 day for timezone edge cases)
            t_delta = (bank.transaction_date.date() - pg.transaction_date.date()).days
            if not (-1 <= t_delta <= policy.max_settlement_lag_days):
                continue
                
            # 3. Token & Amount Evidence
            amount_diff = abs(bank.amount - pg.amount)
            
            # Fuzzy match descriptions and transaction IDs
            score_desc = fuzz.token_set_ratio(str(bank.description), str(pg.description))
            score_id = fuzz.ratio(str(bank.transaction_id), str(pg.transaction_id))
            base_score = max(score_desc, score_id)
            
            # Fractional Temporal Decay: -1 point per day of lag
            match_score = max(0, base_score - max(0, t_delta))
            
            # Economic Boundary: PG payout (net) must be at least as large as the bank settlement net
            # Allow a small 2% variance for rounding/fees.
            economic_bound_met = pg.amount >= bank.amount * Decimal('0.98')
            
            if economic_bound_met or match_score >= policy.fuzzy_match_threshold:
                reason = "ECONOMIC_BOUND" if economic_bound_met else "FUZZY_TOKEN"
                edges.append(ReconEdge(
                    source_event_id=pg.id,
                    target_event_id=bank.id,
                    match_score=match_score,
                    amount_diff=amount_diff,
                    time_delta_days=t_delta,
                    match_reason=reason
                ))
                
    return edges
