import polars as pl
from datetime import datetime
from decimal import Decimal
import pytz
from ledger_guard.db.session import SessionLocal
from ledger_guard.db.models import FactLedger
from ledger_guard.ingestion.idempotency import mark_file_completed

def normalize_date(date_str: str) -> datetime:
    """Aggressively scrub text and enforce ISO-8601 UTC timestamps."""
    if not date_str:
        return None
    # For a real system, you'd use a robust date parser (like dateutil)
    # Since this is a demo, we handle the known synthetic formats
    try:
        # ISO format
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        # DD/MM/YYYY format
        else:
            dt = datetime.strptime(date_str, "%d/%m/%Y")
            # Assume local TZ (Asia/Kolkata for INR), convert to UTC
            local_tz = pytz.timezone("Asia/Kolkata")
            dt = local_tz.localize(dt).astimezone(pytz.UTC)
        return dt
    except ValueError:
        return None

import re
from typing import Tuple

def parse_amount_and_currency(val_str: str, default_curr: str) -> Tuple[Decimal, str]:
    if not val_str:
        return Decimal("0.00"), default_curr
        
    s = str(val_str).replace(",", "").strip()
    
    # Detect currency symbols
    detected_curr = default_curr
    if "₹" in s or "Rs" in s or "INR" in s:
        detected_curr = "INR"
    elif "$" in s or "USD" in s:
        detected_curr = "USD"
    elif "€" in s or "EUR" in s:
        detected_curr = "EUR"
    elif "£" in s or "GBP" in s:
        detected_curr = "GBP"
        
    # Strip everything except numbers, decimals, and minus sign
    clean_num = re.sub(r'[^\d\.\-]', '', s)
    if not clean_num or clean_num == "-" or clean_num == ".":
        return Decimal("0.00"), detected_curr
        
    return Decimal(clean_num), detected_curr

from ledger_guard.config import RECONCILIATION_CONFIG
def batch_normalize_and_save(mapped_df: pl.DataFrame, file_hash: str):
    """
    Processes the entire file, enforces data types, and persists 
    atomic rows to the PostgreSQL Fact Ledger Database.
    """
    rows = mapped_df.to_dicts()
    db = SessionLocal()
    target_currency = RECONCILIATION_CONFIG.get("target_currency", "USD")
    
    try:
        for row in rows:
            txn_id = row.get("transaction_id")
            txn_date = normalize_date(row.get("transaction_date"))
            
            # The LLM often hallucinates "USD" if the column is missing in the ERP file.
            # We will use the explicit target_currency as the baseline, 
            # and override it ONLY if a real currency symbol (₹, $) is found in the amounts!
            base_curr = target_currency
            
            desc = row.get("description")
            base_type = row.get("type", "UNKNOWN").upper()
            
            gross, curr1 = parse_amount_and_currency(row.get("gross_amount"), base_curr)
            fee, curr2 = parse_amount_and_currency(row.get("fee_amount"), base_curr)
            tax, curr3 = parse_amount_and_currency(row.get("tax_amount"), base_curr)
            net, curr4 = parse_amount_and_currency(row.get("net_amount"), base_curr)
            
            # If any of the amounts explicitly had a currency symbol, use that.
            # Otherwise it falls back to target_currency.
            final_currency = curr1 if curr1 != target_currency else \
                             curr2 if curr2 != target_currency else \
                             curr3 if curr3 != target_currency else \
                             curr4 if curr4 != target_currency else target_currency
            
            # Determine base direction (e.g. refund vs payment)
            # A negative net or explicitly refund type implies the gross is a DEBIT
            is_refund = "REFUND" in base_type or net < 0
            
            # 1. Gross Amount (Atom 1)
            if gross != 0:
                # If we received money, gross is CREDIT. If refund, gross is DEBIT.
                gross_dir = "DEBIT" if is_refund else "CREDIT"
                db.add(FactLedger(
                    transaction_id=txn_id,
                    transaction_date=txn_date,
                    amount=abs(gross),
                    currency=final_currency,
                    direction=gross_dir,
                    type=f"{base_type}_GROSS",
                    remaining_amount=abs(gross),
                    status="UNALLOCATED",
                    description=desc,
                    source_file_hash=file_hash
                ))
            
            # 2. Fee Amount (Atom 2)
            if fee != 0:
                # Fees are normally DEBITs (money taken from us)
                # If it's a fee reversal (refunded fee), it would be a CREDIT
                fee_dir = "CREDIT" if fee < 0 else "DEBIT"
                db.add(FactLedger(
                    transaction_id=txn_id,
                    transaction_date=txn_date,
                    amount=abs(fee),
                    currency=final_currency,
                    direction=fee_dir,
                    type=f"{base_type}_FEE",
                    remaining_amount=abs(fee),
                    status="UNALLOCATED",
                    description=f"{desc} (Fee)",
                    source_file_hash=file_hash
                ))
                
            # 3. Tax Amount (Atom 3)
            if tax != 0:
                tax_dir = "CREDIT" if tax < 0 else "DEBIT"
                db.add(FactLedger(
                    transaction_id=txn_id,
                    transaction_date=txn_date,
                    amount=abs(tax),
                    currency=final_currency,
                    direction=tax_dir,
                    type=f"{base_type}_TAX",
                    remaining_amount=abs(tax),
                    status="UNALLOCATED",
                    description=f"{desc} (Tax)",
                    source_file_hash=file_hash
                ))
                
            # Note: For strict bank statements where gross/fee/tax might be 0 but net is present:
            if gross == 0 and fee == 0 and tax == 0 and net != 0:
                net_dir = "CREDIT" if net > 0 else "DEBIT"
                db.add(FactLedger(
                    transaction_id=txn_id,
                    transaction_date=txn_date,
                    amount=abs(net),
                    currency=final_currency,
                    direction=net_dir,
                    type=f"{base_type}_NET",
                    remaining_amount=abs(net),
                    status="UNALLOCATED",
                    description=desc,
                    source_file_hash=file_hash
                ))

        db.commit()
        # Mark file as completed in Idempotency Log
        mark_file_completed(file_hash, db)
        print(f"Successfully committed exploded atomic records to FactLedger.")
    except Exception as e:
        db.rollback()
        print(f"Failed to persist data: {e}")
        raise e
    finally:
        db.close()
