# Block 3: MILP Solver Engine (Phase 3)

This document outlines the architecture and execution flow for Phase 3: the MILP (Mixed Integer Linear Programming) Solver Engine.

## Pipeline Stage & Core Function

The MILP solver acts as the final decision engine. It takes the highly pruned, isolated clusters generated in Phase 2 and attempts to find a **provably correct and unique** matching subset.

To drastically reduce compute load and volume to the AI investigator without sacrificing compliance, the engine employs a deterministic **4-Tier Interceptor Architecture**.

### Tier 1: The Fast-Track (1:1 Deterministic Intercept)
- **What it does:** Runs completely isolated from the solver engine. It intercepts trivial 1:1 matches that have perfectly matching amounts and deterministic identifiers (e.g., Gateway UTR found directly within the Bank Statement string).
- **Why it matters:** These pairs are immediately locked in a single atomic database commit and ripped out of the graph *before* candidate generation, instantly shattering the O(N*M) density of the downstream clusters.

### Tier 1.5: High-Entropy Amount Anchors (The Zipper)
- **What it does:** Scans the remaining cluster before matrix formulation for perfect, unique amount correlations that satisfy the fee boundary. If there is exactly one source for ₹4,192.18 and exactly one target for ₹4,108.33, it locks them.
- **Why it matters:** Rips high-cardinality isolated pairs out of dense clusters instantly, drastically shrinking the graph before the solver boots up.

### Tier 2: Algorithmic Bulk Resolution (Symmetry Bypass)
- **What it does:** If an N:N cluster contains perfectly symmetrical, mathematically identical metadata (same day, same amount, perfectly identical descriptions), it skips the solver entirely.
- **Why it matters:** It greedily pairs them up to bypass the "Uniform Pricing" trap. This prevents the solver from wasting compute cycles resolving indistinguishable N:N blocks and safely avoids unnecessary `AMBIGUOUS` exception routing.

### Tier 3: Mathematical Formulation (Fee-Tolerant Subset Sum)
- **What it does:** Translates a disjoint cluster of events into a formal, bounded subset-sum optimization problem.
- **Floating-Point Mitigation:** All `Decimal` currencies are scaled by a factor (e.g., `10000`) and converted to integers (`np.float64` under the hood) before entering the solver matrix. 
- **Inequality Constraints:** 
  - To handle variable gateway fees, strict 1:1 equalities are disabled. Instead, the solver matrix strictly enforces the following mathematical bound on the selected subset of gross events:
  - $\text{Target Amount} \le \sum (\text{Sources}) \le \text{Target Amount} / (1 - \text{max\_fee\_pct})$
  - A `math.ceil` is applied to the upper bound to ensure integer truncation never accidentally rejects a valid fee-adjusted combination.

### Tier 4: The Rolling MILP (Chronological Sub-Batching)
- **What it does:** Never feeds a massive target array to the solver. Instead, it groups target nodes by `transaction_date` and boots SciPy in a `while` loop, processing strictly Day 1 targets against available sources, committing matches, and rolling the leftover sources to Day 2.
- **Why it matters:** Drops the constraint matrix dimensions exponentially. A dense 72x74 cluster is chunked into rolling 15x15 subsets, completely eliminating the risk of `ABSTAIN_TIMEOUT` on realistic enterprise ledgers.
- **Dynamic Timeout Trap:** Each daily sub-batch is assigned a dynamic timeout: `timeout = max(0.5, min(edge_count * 0.06, 10.0))` seconds to prevent infinite optimization loops.

---

## Post-Solver Validation

### 1. Deterministic Uniqueness Proof
- **The "Uniform Pricing" Trap:** If the engine finds an optimal match, it must prove it is the *only* mathematically viable combination.
- **Adversarial Second Pass:** We take the first optimal solution, add a rigid constraint mathematically banning its specific combination of edges, and force the solver to run again.
- **Ambiguity Detection:** If the second pass finds a different subset that achieves the exact same optimal score, we flag the cluster as `AMBIGUOUS` and route it to `HUMAN_REVIEW`. It is only marked as `UNIQUE_PROVEN` if the second pass fails or returns a strictly worse score.

### 2. Transactional Allocation (DB Commit)
- **What it does:** Commits the proven matches to the `AllocationRecord` table and deducts the balances from the atomic `FactLedger` rows.
- **Deadlock Prevention:** Before committing, the engine collects all `FactLedger` IDs involved, sorts them lexicographically, and acquires row locks (`SELECT ... FOR UPDATE`) in order. This guarantees that multiple concurrent celery workers will never deadlock on each other when processing adjacent clusters.

## Expected Outputs & Exceptions
- `OPTIMAL_UNIQUE`: Written to `AllocationRecord`. Facts are marked `ALLOCATED`.
- `ABSTAIN_TIMEOUT`: Solver hit the dynamic timeout. Logged to `ExceptionRecord`.
- `AMBIGUOUS`: Multiple identical solutions exist. Logged to `ExceptionRecord` for human review.
- `INFEASIBLE`: No valid combination works within the fee bounds. Logged to `ExceptionRecord`.
- `OVERSIZED`: Cluster node count exceeds `max_cluster_size` (e.g. 500). Skipped and logged for manual resolution.
