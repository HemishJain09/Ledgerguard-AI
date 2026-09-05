import polars as pl
from decimal import Decimal, InvalidOperation

class InvariantProbeError(Exception):
    """Raised when the strict math assertions fail on the sample rows."""
    pass

def run_deterministic_probes(sample_df: pl.DataFrame) -> bool:
    """
    Takes a sample of the mapped Polars DataFrame.
    Asserts strict mathematical realities: Gross - Fee - Tax = Net.
    Raises InvariantProbeError if any row fails, which halts the pipeline.
    """
    # Convert to a list of dicts for pure Python precise Decimal math
    rows = sample_df.to_dicts()
    
    for i, row in enumerate(rows):
        try:
            # We strictly parse strings to Decimal. 
            # If the LLM mapped a date column to 'net_amount', this will explode.
            gross = Decimal(str(row.get('gross_amount') or '0.00').replace(',', '').strip())
            fee = Decimal(str(row.get('fee_amount') or '0.00').replace(',', '').strip())
            tax = Decimal(str(row.get('tax_amount') or '0.00').replace(',', '').strip())
            net = Decimal(str(row.get('net_amount') or '0.00').replace(',', '').strip())
            
        except InvalidOperation as e:
            raise InvariantProbeError(f"Type assertion failed at row {i}. LLM mapped non-numeric string to Decimal. Error: {e}")
            
        # The core math invariant for a payment record
        record_type = str(row.get('type') or '').upper()
        
        # ERP (Sales) usually Add Tax to Gross to get the final Net
        if 'ERP' in record_type or 'SALE' in record_type:
            expected_net = gross + tax
            diff = abs(expected_net - net)
            if diff > Decimal('0.10'):
                raise InvariantProbeError(f"Math invariant failed at row {i}. (Gross: {gross} + Tax: {tax}) != Net: {net}. Difference: {diff}")
        
        # Payment Gateways / Settlements usually Deduct Fee and Tax from Gross
        else:
            expected_net = gross - fee - tax
            diff = abs(expected_net - net)
            if diff > Decimal('0.10'):
                raise InvariantProbeError(f"Math invariant failed at row {i}. (Gross: {gross} - Fee: {fee} - Tax: {tax}) != Net: {net}. Difference: {diff}")

    # If it survived, the mapping is solid.
    return True
