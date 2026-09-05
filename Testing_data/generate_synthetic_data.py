import pandas as pd
import random
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from faker import Faker
import uuid

fake = Faker()

erp_rows = []
rzp_rows = []
bank_rows = []

running_balance = Decimal('100000.00')
START_INV = 1000
START_ORD = 5000

def get_next_ids():
    global START_INV, START_ORD
    START_INV += 1
    START_ORD += 1
    inv = f"INV-{START_INV}"
    order = f"ORD_{START_ORD}"
    utr = str(random.randint(100000000000, 999999999999))
    setl = f"setl_{uuid.uuid4().hex[:14]}"
    pay = f"pay_{uuid.uuid4().hex[:14]}"
    return inv, order, utr, setl, pay

def add_record(erp, rzp_list, bank):
    global running_balance
    if erp:
        erp_rows.append(erp)
    if rzp_list:
        for r in rzp_list:
            rzp_rows.append(r)
    if bank:
        # Calculate balance if there's credit or debit
        credit = bank.get('Credit', Decimal('0.00'))
        debit = bank.get('Debit', Decimal('0.00'))
        running_balance = running_balance + credit - debit
        bank['Balance'] = running_balance
        bank_rows.append(bank)

def generate_base_transaction(date, amount_val):
    inv, order, utr, setl, pay = get_next_ids()
    
    amount = Decimal(str(amount_val)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    erp_tax = (amount * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total_val = amount + erp_tax
    
    rzp_fee = (total_val * Decimal('0.02')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    rzp_tax = (rzp_fee * Decimal('0.18')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    net_credit = total_val - rzp_fee - rzp_tax
    
    date_str = date.strftime('%Y-%m-%d')
    date_iso = date.isoformat() + "Z"
    
    erp = {
        'Invoice ID': inv,
        'Order ID': order,
        'Customer Name': fake.name(),
        'Item Total': amount,
        'ERP Tax': erp_tax,
        'Invoice Total': total_val, # The true net amount
        # DECOY: Legacy ERP systems often have confusing extra columns.
        # LLM might map net_amount to this, causing Math Invariant to fail.
        'Final Payable (Inclusive)': total_val + Decimal('150.00'), 
        'Payment Status': 'PAID',
        'Invoice Date': date_iso
    }
    
    rzp = {
        'settlement_id': setl,
        'settlement_utr': utr,
        'entity_id': pay,
        'type': 'payment',
        'payment_id': '',
        'order_id': order,
        'amount': total_val,
        # REALISTIC DECOY: LLM will map fee_amount to estimated_fee due to our prompt trap. 
        # But it's inaccurate! This will cause Math Invariant Probes to fail.
        'estimated_fee': rzp_fee + Decimal('25.00'), 
        'actual_gateway_deduction': rzp_fee, # The true fee that balances the equation
        'tax': rzp_tax,
        'credit': net_credit,
        'debit': Decimal('0.00'),
        'created_at': date_iso,
        'settled_at': date_iso
    }
    
    bank = {
        'Txn Date': date.strftime('%d/%m/%Y'),
        'Value Date': date.strftime('%d/%m/%Y'),
        'Description': f"NEFT-RAZORPAY-{setl}-{utr}",
        'Ref No./Cheque No.': utr,
        'Debit': Decimal('0.00'),
        'Credit': net_credit,
        'Balance': Decimal('0.00') # Calculated in add_record
    }
    
    return erp, [rzp], bank


# 11. Baseline (Perfect Match): ~50 records
base_date = datetime(2026, 8, 1)
for i in range(50):
    txn_date = base_date + timedelta(days=i % 15)
    amt = random.uniform(100, 5000)
    erp, rzp, bank = generate_base_transaction(txn_date, amt)
    add_record(erp, rzp, bank)

# 1. Weekend Lag (2 records)
for i in range(2):
    friday = datetime(2026, 8, 14) # A Friday
    tuesday = friday + timedelta(days=4)
    amt = random.uniform(500, 2000)
    erp, rzp, bank = generate_base_transaction(friday, amt)
    # Mutate bank date
    bank['Txn Date'] = tuesday.strftime('%d/%m/%Y')
    bank['Value Date'] = tuesday.strftime('%d/%m/%Y')
    # RZP settled at tuesday
    rzp[0]['settled_at'] = tuesday.isoformat() + "Z"
    add_record(erp, rzp, bank)

# 2. Auth vs Settlement Mismatch (2 records)
for i in range(2):
    txn_date = base_date + timedelta(days=16+i)
    amt = random.uniform(1000, 3000)
    erp, rzp, bank = generate_base_transaction(txn_date, amt)
    
    # Authorized amount was higher by 100, settled for less
    erp['Invoice Total'] += Decimal('100.00')
    erp['Final Payable (Inclusive)'] += Decimal('100.00')
    erp['Item Total'] += Decimal('84.75')
    erp['ERP Tax'] += Decimal('15.25')
    
    add_record(erp, rzp, bank)

# 3. Many-to-Many Aggregation (Split Settlements) (2 instances)
for i in range(2):
    txn_date = base_date + timedelta(days=18+i)
    
    # 3 ERP orders, 3 RZP payments, 1 RZP settlement, 1 Bank Credit
    inv_a, ord_a, _, setl_a, pay_a = get_next_ids()
    inv_b, ord_b, _, _, pay_b = get_next_ids()
    _, _, utr_agg, _, _ = get_next_ids() # 1 shared UTR
    
    # Order A
    amt_a = Decimal('1000.00')
    tot_a = amt_a + Decimal('180.00')
    fee_a = Decimal('23.60')
    tax_a = Decimal('4.25')
    cred_a = tot_a - fee_a - tax_a
    
    erp_a = {'Invoice ID': inv_a, 'Order ID': ord_a, 'Customer Name': fake.name(), 'Item Total': amt_a, 'ERP Tax': Decimal('180.00'), 'Invoice Total': tot_a, 'Final Payable (Inclusive)': tot_a + Decimal('150.00'), 'Payment Status': 'PAID', 'Invoice Date': txn_date.isoformat() + "Z"}
    rzp_a = {'settlement_id': setl_a, 'settlement_utr': utr_agg, 'entity_id': pay_a, 'type': 'payment', 'payment_id': '', 'order_id': ord_a, 'amount': tot_a, 'estimated_fee': fee_a + Decimal('25.00'), 'actual_gateway_deduction': fee_a, 'tax': tax_a, 'credit': cred_a, 'debit': Decimal('0.00'), 'created_at': txn_date.isoformat() + "Z", 'settled_at': txn_date.isoformat() + "Z"}
    
    # Order B
    amt_b = Decimal('2000.00')
    tot_b = amt_b + Decimal('360.00')
    fee_b = Decimal('47.20')
    tax_b = Decimal('8.50')
    cred_b = tot_b - fee_b - tax_b
    
    erp_b = {'Invoice ID': inv_b, 'Order ID': ord_b, 'Customer Name': fake.name(), 'Item Total': amt_b, 'ERP Tax': Decimal('360.00'), 'Invoice Total': tot_b, 'Final Payable (Inclusive)': tot_b + Decimal('150.00'), 'Payment Status': 'PAID', 'Invoice Date': txn_date.isoformat() + "Z"}
    rzp_b = {'settlement_id': setl_a, 'settlement_utr': utr_agg, 'entity_id': pay_b, 'type': 'payment', 'payment_id': '', 'order_id': ord_b, 'amount': tot_b, 'estimated_fee': fee_b + Decimal('25.00'), 'actual_gateway_deduction': fee_b, 'tax': tax_b, 'credit': cred_b, 'debit': Decimal('0.00'), 'created_at': txn_date.isoformat() + "Z", 'settled_at': txn_date.isoformat() + "Z"}
    
    bank_agg = {
        'Txn Date': txn_date.strftime('%d/%m/%Y'),
        'Value Date': txn_date.strftime('%d/%m/%Y'),
        'Description': f"NEFT-RAZORPAY-MULTIPLE-{utr_agg}",
        'Ref No./Cheque No.': utr_agg,
        'Debit': Decimal('0.00'),
        'Credit': cred_a + cred_b,
        'Balance': Decimal('0.00')
    }
    
    add_record(erp_a, [rzp_a], None)
    add_record(erp_b, [rzp_b], bank_agg)

# 4. Partial Payments & Splits (2 instances)
# 1 ERP order paid in 2 RZP payments
for i in range(2):
    txn_date = base_date + timedelta(days=20+i)
    inv, order, utr1, setl1, pay1 = get_next_ids()
    _, _, utr2, setl2, pay2 = get_next_ids()
    
    tot_amt = Decimal('5000.00')
    erp = {'Invoice ID': inv, 'Order ID': order, 'Customer Name': fake.name(), 'Item Total': Decimal('4237.29'), 'ERP Tax': Decimal('762.71'), 'Invoice Total': tot_amt, 'Final Payable (Inclusive)': tot_amt + Decimal('150.00'), 'Payment Status': 'PAID', 'Invoice Date': txn_date.isoformat() + "Z"}
    
    # Pay 1: 2000
    rzp1 = {'settlement_id': setl1, 'settlement_utr': utr1, 'entity_id': pay1, 'type': 'payment', 'payment_id': '', 'order_id': order, 'amount': Decimal('2000.00'), 'estimated_fee': Decimal('65.00'), 'actual_gateway_deduction': Decimal('40.00'), 'tax': Decimal('7.20'), 'credit': Decimal('1952.80'), 'debit': Decimal('0.00'), 'created_at': txn_date.isoformat() + "Z", 'settled_at': txn_date.isoformat() + "Z"}
    bank1 = {'Txn Date': txn_date.strftime('%d/%m/%Y'), 'Value Date': txn_date.strftime('%d/%m/%Y'), 'Description': f"NEFT-RAZP-{utr1}", 'Ref No./Cheque No.': utr1, 'Debit': Decimal('0.00'), 'Credit': Decimal('1952.80'), 'Balance': Decimal('0')}
    
    # Pay 2: 3000
    rzp2 = {'settlement_id': setl2, 'settlement_utr': utr2, 'entity_id': pay2, 'type': 'payment', 'payment_id': '', 'order_id': order, 'amount': Decimal('3000.00'), 'estimated_fee': Decimal('85.00'), 'actual_gateway_deduction': Decimal('60.00'), 'tax': Decimal('10.80'), 'credit': Decimal('2929.20'), 'debit': Decimal('0.00'), 'created_at': txn_date.isoformat() + "Z", 'settled_at': txn_date.isoformat() + "Z"}
    bank2 = {'Txn Date': txn_date.strftime('%d/%m/%Y'), 'Value Date': txn_date.strftime('%d/%m/%Y'), 'Description': f"NEFT-RAZP-{utr2}", 'Ref No./Cheque No.': utr2, 'Debit': Decimal('0.00'), 'Credit': Decimal('2929.20'), 'Balance': Decimal('0')}
    
    add_record(erp, [rzp1, rzp2], bank1)
    add_record(None, None, bank2)

# 5. Truncated Metadata (2 records)
for i in range(2):
    txn_date = base_date + timedelta(days=22+i)
    amt = random.uniform(300, 900)
    erp, rzp, bank = generate_base_transaction(txn_date, amt)
    
    # Truncate UTR in Bank statement
    utr = bank['Ref No./Cheque No.']
    bank['Ref No./Cheque No.'] = utr[:6] + "..." 
    
    add_record(erp, rzp, bank)

# 6. Transposed Digits (2 records)
for i in range(2):
    txn_date = base_date + timedelta(days=24+i)
    # Generate exactly 1091.00 in PG/Bank, but 1019.00 in ERP
    inv, order, utr, setl, pay = get_next_ids()
    pg_tot = Decimal('1091.00')
    erp_tot = Decimal('1019.00')
    
    fee = Decimal('21.82')
    tax = Decimal('3.93')
    cred = pg_tot - fee - tax
    
    erp = {'Invoice ID': inv, 'Order ID': order, 'Customer Name': fake.name(), 'Item Total': Decimal('863.56'), 'ERP Tax': Decimal('155.44'), 'Invoice Total': erp_tot, 'Final Payable (Inclusive)': erp_tot + Decimal('150.00'), 'Payment Status': 'PAID', 'Invoice Date': txn_date.isoformat() + "Z"}
    rzp = [{'settlement_id': setl, 'settlement_utr': utr, 'entity_id': pay, 'type': 'payment', 'payment_id': '', 'order_id': order, 'amount': pg_tot, 'estimated_fee': fee + Decimal('25.00'), 'actual_gateway_deduction': fee, 'tax': tax, 'credit': cred, 'debit': Decimal('0.00'), 'created_at': txn_date.isoformat() + "Z", 'settled_at': txn_date.isoformat() + "Z"}]
    bank = {'Txn Date': txn_date.strftime('%d/%m/%Y'), 'Value Date': txn_date.strftime('%d/%m/%Y'), 'Description': f"NEFT-RAZORPAY-{setl}-{utr}", 'Ref No./Cheque No.': utr, 'Debit': Decimal('0.00'), 'Credit': cred, 'Balance': Decimal('0.00')}
    
    add_record(erp, rzp, bank)

# 7. Duplicate Ingestion (2 records)
for i in range(2):
    txn_date = base_date + timedelta(days=26+i)
    amt = random.uniform(800, 1500)
    erp, rzp, bank = generate_base_transaction(txn_date, amt)
    
    add_record(erp, rzp, bank)
    # Add duplicate to ERP
    add_record(erp.copy(), None, None)

# 8. Silent Deductions (2 records)
for i in range(2):
    txn_date = base_date + timedelta(days=28+i)
    amt = random.uniform(2000, 4000)
    erp, rzp, bank = generate_base_transaction(txn_date, amt)
    
    # Bank quietly deducted 50.00 fee not mentioned in PG
    bank['Credit'] -= Decimal('50.00')
    
    add_record(erp, rzp, bank)

# 9. FX Conversion Rounding (2 records)
for i in range(2):
    txn_date = base_date + timedelta(days=29+i)
    amt = random.uniform(500, 1000)
    erp, rzp, bank = generate_base_transaction(txn_date, amt)
    
    # ERP expects 1000.00
    # PG processed 1000.05 due to exchange rate change mid-transaction
    rzp[0]['amount'] += Decimal('0.05')
    rzp[0]['credit'] += Decimal('0.05')
    bank['Credit'] += Decimal('0.05')
    
    add_record(erp, rzp, bank)

# 10. Unrecorded Discrepancies / Refunds (2 records)
for i in range(2):
    txn_date = base_date + timedelta(days=30+i)
    amt = random.uniform(1500, 2500)
    erp, rzp, bank = generate_base_transaction(txn_date, amt)
    
    # Process original payment
    add_record(erp, rzp, bank)
    
    # Inject a refund via Razorpay that didn't hit ERP
    _, _, refund_utr, refund_setl, refund_pay = get_next_ids()
    refund_amt = rzp[0]['amount']
    
    rzp_refund = {
        'settlement_id': refund_setl,
        'settlement_utr': refund_utr,
        'entity_id': refund_pay,
        'type': 'refund',
        'payment_id': rzp[0]['entity_id'],
        'order_id': rzp[0]['order_id'],
        'amount': refund_amt,
        'estimated_fee': Decimal('0.00'),
        'actual_gateway_deduction': Decimal('0.00'),
        'tax': Decimal('0.00'),
        'credit': Decimal('0.00'),
        'debit': refund_amt,
        'created_at': (txn_date + timedelta(days=2)).isoformat() + "Z",
        'settled_at': (txn_date + timedelta(days=2)).isoformat() + "Z"
    }
    
    bank_refund = {
        'Txn Date': (txn_date + timedelta(days=2)).strftime('%d/%m/%Y'),
        'Value Date': (txn_date + timedelta(days=2)).strftime('%d/%m/%Y'),
        'Description': f"NEFT-REFUND-{refund_setl}-{refund_utr}",
        'Ref No./Cheque No.': refund_utr,
        'Debit': refund_amt,
        'Credit': Decimal('0.00'),
        'Balance': Decimal('0.00')
    }
    
    add_record(None, [rzp_refund], bank_refund)

# Ensure columns match strict schema perfectly
df_erp = pd.DataFrame(erp_rows)
df_erp = df_erp[['Invoice ID', 'Order ID', 'Customer Name', 'Item Total', 'ERP Tax', 'Invoice Total', 'Final Payable (Inclusive)', 'Payment Status', 'Invoice Date']]

df_rzp = pd.DataFrame(rzp_rows)
df_rzp = df_rzp[['settlement_id', 'settlement_utr', 'entity_id', 'type', 'payment_id', 'order_id', 'amount', 'estimated_fee', 'actual_gateway_deduction', 'tax', 'credit', 'debit', 'created_at', 'settled_at']]

df_bank = pd.DataFrame(bank_rows)
df_bank = df_bank[['Txn Date', 'Value Date', 'Description', 'Ref No./Cheque No.', 'Debit', 'Credit', 'Balance']]

# Output to CSV
df_erp.to_csv('erp_export.csv', index=False)
df_rzp.to_csv('razorpay_recon.csv', index=False)
df_bank.to_csv('bank_statement.csv', index=False)

print(f"Generated ERP rows: {len(df_erp)}")
print(f"Generated RZP rows: {len(df_rzp)}")
print(f"Generated Bank rows: {len(df_bank)}")
