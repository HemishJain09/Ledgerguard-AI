# Ledger Guard: Phase 1 (Ingestion & Normalization)

## Overview
Phase 1 of Ledger Guard implements a robust, fault-tolerant ingestion pipeline that transforms chaotic, unpredictable financial data (from Payment Gateways, ERPs, and Banks) into a mathematically sound, standardized canonical format. 

This phase is critical because downstream reconciliation (Phase 2) requires absolutely perfect, standardized data to function correctly.

## Architecture & Data Flow

The ingestion engine is powered by **LangGraph**, representing the flow as a state machine. It consists of several distinct blocks:

### Block 1: Extraction & Idempotency
- **Goal:** Read the raw CSV file and ensure we never process the same file twice.
- **Mechanism:** Calculates the SHA-256 hash of the file contents. If the hash exists in the database, the pipeline halts immediately (`DROPPED`). Otherwise, the file is loaded into a Polars DataFrame.

### Block 2: Schema Discovery (LLM)
- **Goal:** Dynamically map unfamiliar column headers to our strict `CanonicalTransaction` schema.
- **Mechanism:** A sample of the data is sent to **Qwen 3.8-27b** (via Langchain/Groq). The LLM acts as an autonomous data engineer, analyzing the raw headers and sample data, and outputting a strict Pydantic `SchemaMapping`.
- **Why this matters:** We don't need to write hardcoded parsers for every new payment gateway or bank. The system adapts automatically.

### Block 3: Deterministic Probes (Math Invariants)
- **Goal:** Validate that the LLM's mapping makes mathematical sense. LLMs can hallucinate; math does not.
- **Mechanism:** We apply the LLM's mapping to a sample of the data and run strict math assertions. 
  - For PG/Bank: `Gross - Fee - Tax == Net`
  - For ERP: `Item Total + Tax == Invoice Total`
- **Why this matters:** If the LLM maps a decoy column (e.g., a legacy 'Final Payable' or 'estimated_fee' column), the math fails. Instead of polluting our database, the pipeline throws an `InvariantProbeError` and pauses execution.

### Block 4: Human-in-the-Loop (Exceptions Queue)
- **Goal:** Allow a human operator to correct LLM hallucinations safely and efficiently.
- **Mechanism:** When the math probe fails, LangGraph **interrupts** the state machine. The frontend React UI dynamically renders the LLM's attempted mapping alongside the actual headers from the uploaded CSV. The human operator can override the incorrect column mapping.
- **Resumption:** Once submitted, the new mapping is injected back into the LangGraph state. The pipeline resumes, loops back to the Math Probes to verify the human's fix, and proceeds.

### Block 5: The Fact Ledger
- **Goal:** Persist the perfectly mapped, mathematically verified data into a standardized database table.
- **Mechanism:** We apply the verified schema mapping to the *entire* dataset. The raw data is transformed into `CanonicalTransaction` models and stored in the `fact_ledger` SQLite table.
- **Why this matters:** The Fact Ledger is the single source of truth. Every record in it is guaranteed to have a `gross_amount`, `fee_amount`, `tax_amount`, and `net_amount` that mathematically balance.

## Conclusion
With Phase 1 complete, Ledger Guard has a bulletproof ingestion engine. It leverages the flexibility of LLMs for schema discovery, but relies on deterministic math and Human-in-the-Loop verification to guarantee 100% data integrity. We are now ready to build the MILP Solver for Phase 2 reconciliation!
