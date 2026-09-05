# Block 4: AI Investigator Agent (Phase 5)

This document outlines the architecture of Block 4: The AI Investigator. This system acts as a neuro-symbolic reasoning engine designed to process complex reconciliation exceptions that the deterministic MILP solver (Block 3) could not resolve (`AMBIGUOUS`, `INFEASIBLE`, etc.).

To eliminate mathematical hallucination, this block utilizes a strict **Program-of-Thought (PoT)** architecture.

## 1. Evidence Retrieval (Dynamic Bundle Assembly)
Before any LLM call, the `assemble_bundle` function builds a compact, isolated context dictionary specific to the broken case.
- **Pre-loads Variables:** Iterates over the raw nodes (ERP invoices, Gateway payouts, Bank lines) and loads their attributes into a flat `variables` dictionary (e.g., `EVT_1.gross`, `EVT_1.timestamp`).
- **Policy Injection:** Attaches boundary policies (like `max_fee_pct`).
- **Context Preservation:** By converting massive raw JSON structures into a flat dictionary, it protects the LLM's context window and prevents token bloat.

## 2. AI Investigator Agent & Structured Output
The core reasoning engine is powered by LangGraph and Langchain.
- **Model Selection:** Utilizes `qwen/qwen3.8-27b` (via Groq or OpenRouter proxy) to ensure a massive context window and top-tier semantic reasoning capable of parsing complex ERP metadata without truncating AST schemas.
- **Structured Generation:** Forces the model to output a strictly validated `InvestigationResult` Pydantic schema containing:
  - `classification`: Semantic category of the discrepancy (e.g., `TIMING_DIFFERENCE`, `EXPECTED_FEE`).
  - `hypothesis`: A human-readable economic explanation.
  - `dsl_program`: A strictly ordered list of atomic operations (AST).
- **LangGraph Self-Correction Loop:** If the downstream Python executor raises a `KeyError` (hallucinated variable) or `ValueError` (invalid math), the graph traps the exception and feeds the error trace back to the LLM for a self-correction pass (capped at 2 retries).

## 3. Deterministic PoT Executor
A Python-based execution sandbox (`executor.py`) completely separates semantic reasoning from arithmetic.
- Loops sequentially over the DSL operations using a pure Python `match/case` dispatcher.
- Operates exclusively using Python's `Decimal` module to prevent floating-point drift.
- **Zero Hallucination:** Uses no `eval()` or `exec()`. If an operation references an undefined variable, it throws a safe exception back to the LangGraph router.

### The Minimal Viable DSL (6 Core Operations)
The agent is restricted to composing exact proofs using only 6 atomic primitives:
1. `SUBTRACT`: Deduct fees, taxes, or chargebacks from gross amounts.
2. `ADD`: Combine multiple source payments or adjustments.
3. `MULTIPLY`: Calculate dynamic percentage-based MDR fees or GST.
4. `COMPARE`: Deterministic terminal check against the target bank deposit.
5. `DATE_DIFF`: Check settlement lag against policy bounds.
6. `RULE_LOOKUP`: Fetch an active policy limit.

## 4. Math Verification Gate (Stateless)
This deterministic gate tests whether the PoT program actually proved the resolution.
- **Equation Match:** Ensures the final operation is a `COMPARE` that evaluates to `Decimal("1")` (True), proving the computed total precisely matches the target bank line down to `0.0000`.
- **Stateless Design:** The verifier returns a strict decision state:
  - `PROVEN_AI_CASE`: The DSL executed flawlessly and the math perfectly matched.
  - `ESCALATE`: The hypothesis failed to prove the math, or the data was corrupted.
- **No Mutation:** This block strictly does not acquire database locks or mutate state. It acts exclusively as an oracle. Database allocation and ledger updates are deferred downstream to Block 5.

## API Integration
The Investigator is integrated into the main application via a synchronous endpoint:
`POST /api/exceptions/{exception_id}/investigate`
This route allows the frontend exception dashboard or background cron jobs to trigger isolated investigations on demand.

## Implementation Watch-Outs

### 1. Lineage Continuity in Step 4
The verifier does not merely check if `COMPARE` evaluated to `Decimal("1")`. It traverses the lineage graph of the final variable to confirm it contains both the target event ID (e.g., the Bank payout) and at least one source event ID (e.g., the ERP payment). This prevents the LLM from cheating the verification by generating a disconnected dummy comparison like `COMPARE(100, 100)`.

### 2. Synchronous Timeout Budget
Because `POST /api/exceptions/{exception_id}/investigate` runs LLM generation synchronously and handles up to 2 self-correction retries, the reverse proxy (e.g., Nginx, Gunicorn, uvicorn) must have an HTTP timeout configured to at least 30–60 seconds. If high concurrency is expected in production, this endpoint should be converted to an asynchronous worker queue (e.g., Celery/Redis).
