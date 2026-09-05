import uuid
from typing import List, Dict, Tuple
from collections import defaultdict
from ledger_guard.db.models import FactLedger
from .models import FinancialEvent

def build_financial_events(fact_records: List[FactLedger]) -> List[FinancialEvent]:
    """
    Transforms atomic FactLedger rows into high-level FinancialEvents.
    Groups by (transaction_id, source_file_hash) to reconstruct the full context.
    """
    # Group facts
    grouped_facts: Dict[Tuple[str, str], List[FactLedger]] = defaultdict(list)
    for fact in fact_records:
        if fact.status == "UNALLOCATED":
            grouped_facts[(fact.transaction_id, fact.source_file_hash)].append(fact)
            
    events = []
    
    for (txn_id, file_hash), facts in grouped_facts.items():
        if not facts:
            continue
            
        base_type_hint = facts[0].type.upper()
        
        # Calculate totals for the group
        gross_val = sum(f.amount for f in facts if "_GROSS" in f.type and f.direction == "CREDIT") - \
                    sum(f.amount for f in facts if "_GROSS" in f.type and f.direction == "DEBIT")
        
        fee_val = sum(f.amount for f in facts if "_FEE" in f.type and f.direction == "DEBIT")
        tax_val = sum(f.amount for f in facts if "_TAX" in f.type and f.direction == "DEBIT")
        
        net_val = sum(f.amount for f in facts if "_NET" in f.type and f.direction == "CREDIT") - \
                  sum(f.amount for f in facts if "_NET" in f.type and f.direction == "DEBIT")
                  
        # If no explicit NET record, calculate from gross/fee/tax
        if net_val == 0 and gross_val != 0:
            if "ERP" in base_type_hint or "SALE" in base_type_hint:
                # For sales/ERP, tax is usually added to gross to get net invoice total
                net_val = gross_val + tax_val
            else:
                # For gateways, fee and tax are deducted from gross
                net_val = gross_val - fee_val - tax_val

        # Representative metadata
        primary_date = facts[0].transaction_date
        currency = facts[0].currency
        desc = facts[0].description
        fact_ids = [f.id for f in facts]
        
        # 1. ERP Export -> SALE_EVENT (Needs to match against PG Gross)
        if "ERP" in base_type_hint or "SALE" in base_type_hint:
            events.append(FinancialEvent(
                id=str(uuid.uuid4()),
                fact_ids=fact_ids,
                event_type="SALE_EVENT",
                # PG Gross = ERP Net (Invoice Total)
                amount=abs(net_val),
                currency=currency,
                transaction_date=primary_date,
                description=desc or "",
                transaction_id=txn_id or ""
            ))
            
        # 2. Bank Statement -> BANK_SETTLEMENT_EVENT (Needs to match against PG Net)
        elif "BANK" in base_type_hint:
            events.append(FinancialEvent(
                id=str(uuid.uuid4()),
                fact_ids=fact_ids,
                event_type="BANK_SETTLEMENT_EVENT",
                amount=abs(net_val) if net_val != 0 else abs(gross_val),
                currency=currency,
                transaction_date=primary_date,
                description=desc or "",
                transaction_id=txn_id or ""
            ))
            
        # 3. Payment Gateway -> Produces TWO events! 
        # One to match the ERP (Gross), one to match the Bank (Net)
        else:
            # Match with ERP
            events.append(FinancialEvent(
                id=str(uuid.uuid4()),
                fact_ids=fact_ids,
                event_type="PG_PAYMENT_EVENT",
                amount=abs(gross_val),
                currency=currency,
                transaction_date=primary_date,
                description=desc or "",
                transaction_id=txn_id or ""
            ))
            # Match with Bank
            events.append(FinancialEvent(
                id=str(uuid.uuid4()),
                fact_ids=fact_ids,
                event_type="PG_PAYOUT_EVENT",
                amount=abs(net_val),
                currency=currency,
                transaction_date=primary_date,
                description=desc or "",
                transaction_id=txn_id or ""
            ))
            
    return events
