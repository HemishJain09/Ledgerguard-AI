# Synthetic Data Overview

This dataset simulates a real-world financial pipeline where money moves from a customer sale to a bank account. It consists of three CSV files, containing around 75 transactions, designed to test a reconciliation engine.

## The Three Files

1. **`erp_export.csv` (The Source of Truth):** 
   Represents internal sales records. This is what the business *expects* to receive.
2. **`razorpay_recon.csv` (The Gateway):** 
   Represents the payment processor. It shows the money collected from the customer, minus processing fees and taxes.
3. **`bank_statement.csv` (The Destination):** 
   Represents the actual cash that arrived in the corporate bank account.

## How to use it

To successfully reconcile this data, your engine must link rows using the **Order ID** (ERP $\leftrightarrow$ Razorpay) and the **UTR Number** (Razorpay $\leftrightarrow$ Bank). 

## Intentional "Errors" (Edge Cases)

While ~50 transactions match perfectly across all three files, we intentionally injected 2 specific instances of each of the following real-world anomalies to test the system's robustness:

*   **Timing Issues (Weekend Lag):** 
    *   *What we faked:* 2 transactions were generated on a Friday (`2026-08-14`) in the ERP and Gateway, but the Bank statement (`Txn Date` and `Value Date`) shows them arriving on Tuesday (`2026-08-18`).
*   **Amount Discrepancies (Auth vs Settled):** 
    *   *What we faked:* 2 ERP orders expect exactly `$100.00` more than what was actually authorized and settled by Razorpay.
*   **Structural Complexities:** 
    *   *Many-to-Many Aggregation:* 2 instances where two separate ERP orders (one for $1000, one for $2000) are grouped together by Razorpay into a single combined UTR deposit in the Bank statement.
    *   *Partial Payments & Splits:* 2 instances where a single large ERP order for $5000 is split into two separate Gateway transactions ($2000 and $3000), hitting the Bank as two distinct credits.
*   **Data Corruption:** 
    *   *Truncated Metadata:* 2 Bank statement rows have their `Ref No.` truncated (e.g., `HDFC10...`), meaning a simple string match against the Razorpay `settlement_utr` will fail.
    *   *Transposed Digits:* 2 ERP orders expect a gross total of exactly `$1019.00`, but the Gateway processed exactly `$1091.00`.
    *   *Duplicate Ingestion:* 2 ERP orders are perfectly duplicated (appearing twice in the `erp_export.csv` file) to test idempotency.
*   **Hidden Math / Adjustments:** 
    *   *Silent Deductions:* 2 Bank statement deposits are exactly `$50.00` less than the expected net credit from Razorpay, simulating a hidden bank fee.
    *   *FX Rounding:* 2 Gateway transactions are exactly `$0.05` higher than the ERP expected amount due to simulated exchange rate shifts during processing.
    *   *Unrecorded Refunds:* 2 refunds appear in the Gateway data and as a `Debit` in the Bank statement, but the operations team never recorded them in the ERP.
*   **The Human-in-the-Loop Trap:** 
    *   *What we faked:* For 2 transactions, the Razorpay `fee` is artificially inflated by exactly `$100.00` while the `amount` and `credit` remain untouched. This breaks the mathematical invariant (`Gross - Fee - Tax == Net Credit`), specifically designed to force your LangGraph state machine to halt and trigger the React UI for correction.
