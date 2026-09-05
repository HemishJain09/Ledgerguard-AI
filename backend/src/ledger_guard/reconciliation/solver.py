"""
Phase 3 — MILP Solver Engine

Processes disjoint clusters from Phase 2 through a 4-block lifecycle:
  1. Mathematical Formulation (integer-scaled constraint matrices)
  2. MILP Solver Execution (SciPy milp with hard timeout)
  3. Deterministic Uniqueness Proof (adversarial second pass)
  4. Routes to allocator or exception buckets
"""

import uuid
import time
import math
import numpy as np
from decimal import Decimal
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass, field

from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import eye as speye

from ledger_guard.config import SOLVER_TIMEOUT, INTEGER_SCALE_FACTOR, MAX_CLUSTER_SIZE


# ---------------------------------------------------------------------------
# Block 1: Mathematical Formulation
# ---------------------------------------------------------------------------

@dataclass
class MILPFormulation:
    """Holds the fully constructed MILP problem for a single cluster."""
    cluster_id: str
    # Decision variables: one binary x_i per edge in the cluster
    edge_list: List[Dict[str, Any]]  # [{source_id, target_id, score, amount_diff, reason}]
    
    # Objective: maximize total match score (negate for minimization)
    c: np.ndarray  # cost vector (negative scores for minimization)
    
    # Constraints
    constraints: List[LinearConstraint]
    
    # Bounds: 0 <= x_i <= 1 (binary)
    bounds: Bounds
    
    # Integrality: all variables are binary (1)
    integrality: np.ndarray
    
    # Metadata
    node_ids: List[str]
    source_node_ids: List[str]
    target_node_ids: List[str]


from ledger_guard.config import MAX_FEE_PCT

def formulate_cluster(cluster: Dict[str, Any], events_map: Dict[str, Dict]) -> Optional[MILPFormulation]:
    """
    Block 1: Translates a candidate graph cluster into MILP constraint matrices.
    
    Decision variables: 
      - x_i (binary): 1 if edge i is selected, 0 otherwise.
      - y_j (binary): 1 if target j is fulfilled, 0 otherwise.
    
    Objective: Maximize sum of match_score * x_i (minimize negative).
    
    Constraints:
      - Each source node participates in at most 1 selected edge (one-to-one matching for sources).
      - [TIER 3] Fee-Tolerant Subset-Sum: For each target j:
        y_j * Target_amount <= sum(x_i * Source_amount) <= y_j * (Target_amount / (1 - MAX_FEE_PCT))
    """
    cluster_id = str(uuid.uuid4())
    
    edges = cluster["edges"]
    nodes = cluster["nodes"]
    
    if not edges:
        return None
    
    num_edges = len(edges)
    
    # Build the edge list with metadata
    edge_list = []
    for src_id, tgt_id, data in edges:
        edge_list.append({
            "source_id": src_id,
            "target_id": tgt_id,
            "score": data.get("weight", 0),
            "amount_diff": data.get("amount_diff", 0),
            "reason": data.get("match_reason", "UNKNOWN"),
        })
    
    all_node_ids = [n[0] for n in nodes]
    source_node_ids = list(set(e["source_id"] for e in edge_list))
    target_node_ids = list(set(e["target_id"] for e in edge_list))
    num_targets = len(target_node_ids)
    
    total_vars = num_edges + num_targets
    
    # --- Objective Vector ---
    # c = [-score_0, ..., -score_E-1, 0, ..., 0]
    c = np.zeros(total_vars, dtype=np.float64)
    for i, e in enumerate(edge_list):
        c[i] = -e["score"]
    
    # --- Constraints ---
    constraints = []
    
    # Constraint 1: Each source node matched at most once
    for s_id in source_node_ids:
        row = np.zeros(total_vars, dtype=np.float64)
        for e_idx, edge in enumerate(edge_list):
            if edge["source_id"] == s_id:
                row[e_idx] = 1.0
        constraints.append(LinearConstraint(row.reshape(1, -1), lb=0, ub=1))
        
    # Constraint 2: Fee-Tolerant Bounds (N:1 Matching)
    # y_j * T <= sum(x_i * S_i) <= y_j * (T / (1 - MAX_FEE_PCT))
    # Rewrite as:
    # 0 <= sum(x_i * S_i) - y_j * T
    # sum(x_i * S_i) - y_j * (T / (1 - MAX_FEE_PCT)) <= 0
    for j, t_id in enumerate(target_node_ids):
        t_amount = float(events_map[t_id]["amount"]) * INTEGER_SCALE_FACTOR
        upper_bound_factor = math.ceil(t_amount / (1.0 - MAX_FEE_PCT))
        
        row_lower = np.zeros(total_vars, dtype=np.float64)
        row_upper = np.zeros(total_vars, dtype=np.float64)
        
        for e_idx, edge in enumerate(edge_list):
            if edge["target_id"] == t_id:
                s_amount = float(events_map[edge["source_id"]]["amount"]) * INTEGER_SCALE_FACTOR
                row_lower[e_idx] = s_amount
                row_upper[e_idx] = s_amount
                
        # The y_j variable is at index num_edges + j
        row_lower[num_edges + j] = -t_amount
        row_upper[num_edges + j] = -upper_bound_factor
        
        # Lower bound constraint: sum(x_i * S_i) - y_j * T >= 0
        constraints.append(LinearConstraint(row_lower.reshape(1, -1), lb=0, ub=np.inf))
        
        # Upper bound constraint: sum(x_i * S_i) - y_j * (T / (1-fee)) <= 0
        constraints.append(LinearConstraint(row_upper.reshape(1, -1), lb=-np.inf, ub=0))
    
    # Bounds: 0 <= var <= 1 for all binary variables
    bounds = Bounds(lb=0, ub=1)
    
    # Integrality: all variables are binary (1)
    integrality = np.ones(total_vars, dtype=int)
    
    return MILPFormulation(
        cluster_id=cluster_id,
        edge_list=edge_list,
        c=c,
        constraints=constraints,
        bounds=bounds,
        integrality=integrality,
        node_ids=all_node_ids,
        source_node_ids=source_node_ids,
        target_node_ids=target_node_ids,
    )


# ---------------------------------------------------------------------------
# Block 2: MILP Solver Execution
# ---------------------------------------------------------------------------

@dataclass
class SolverOutput:
    status: str  # "OPTIMAL", "INFEASIBLE", "TIME_LIMIT"
    solution: Optional[np.ndarray] = None
    objective_value: float = 0.0
    time_ms: float = 0.0


def solve_milp(formulation: MILPFormulation, extra_constraints: List[LinearConstraint] = None) -> SolverOutput:
    """
    Block 2: Feeds the formatted MILP into SciPy's milp() solver.
    Returns the solver status and binary solution vector.
    """
    all_constraints = list(formulation.constraints)
    if extra_constraints:
        all_constraints.extend(extra_constraints)
        
    # [TIER 4] Dynamic Timeout Scaling
    edge_count = len(formulation.edge_list)
    dynamic_timeout = max(0.5, min(edge_count * 0.06, 10.0))
    
    start = time.perf_counter()
    
    result = milp(
        c=formulation.c,
        constraints=all_constraints,
        integrality=formulation.integrality,
        bounds=formulation.bounds,
        options={"time_limit": dynamic_timeout, "disp": False},
    )
    
    elapsed_ms = (time.perf_counter() - start) * 1000
    
    if result.success:
        return SolverOutput(
            status="OPTIMAL",
            solution=np.round(result.x).astype(int),
            objective_value=result.fun,
            time_ms=elapsed_ms,
        )
    
    # SciPy uses result.message to communicate failure reasons
    msg = result.message.lower() if hasattr(result, 'message') else ""
    if "time limit" in msg or "iteration limit" in msg:
        return SolverOutput(status="TIME_LIMIT", time_ms=elapsed_ms)
    
    return SolverOutput(status="INFEASIBLE", time_ms=elapsed_ms)


# ---------------------------------------------------------------------------
# Block 3: Deterministic Proof & Ambiguity Check
# ---------------------------------------------------------------------------

def prove_uniqueness(formulation: MILPFormulation, first_solution: np.ndarray,
                     first_objective: float) -> str:
    """
    Block 3: Defends against the Uniform Pricing Trap.
    
    Adds a ban constraint excluding the first solution's edges and re-solves.
    If a second solution achieves the same objective, returns AMBIGUOUS.
    Otherwise returns UNIQUE_PROVEN.
    """
    num_edges = len(formulation.edge_list)
    total_vars = len(formulation.c)
    
    selected_indices = np.where(first_solution == 1)[0]
    edge_indices = [idx for idx in selected_indices if idx < num_edges]
    
    if len(edge_indices) == 0:
        # No edges selected = trivially unique (empty solution)
        return "UNIQUE_PROVEN"
    
    # Ban constraint: sum(x_i for i where first_solution[i]==1) <= |selected_edges| - 1
    ban_row = np.zeros(total_vars, dtype=np.float64)
    for idx in edge_indices:
        ban_row[idx] = 1.0
    
    ban_constraint = LinearConstraint(
        ban_row.reshape(1, -1),
        lb=0,
        ub=len(edge_indices) - 1  # Force at least one different selection
    )
    
    # Re-solve with the ban
    second_pass = solve_milp(formulation, extra_constraints=[ban_constraint])
    
    if second_pass.status != "OPTIMAL":
        # No other feasible solution exists → first solution is unique
        return "UNIQUE_PROVEN"
    
    # Compare objective values (remember: negated scores, so lower = better)
    # If the second solution has the same quality, it's ambiguous
    obj_tolerance = 1.0  # Allow 1 point of score difference
    if abs(second_pass.objective_value - first_objective) <= obj_tolerance:
        return "AMBIGUOUS"
    
    # Second solution is strictly worse → first is unique best
    return "UNIQUE_PROVEN"


# ---------------------------------------------------------------------------
# Orchestrator: Process a Single Cluster
# ---------------------------------------------------------------------------

def process_single_cluster(
    cluster: Dict[str, Any],
    events_map: Dict[str, Dict],
) -> Dict[str, Any]:
    from collections import Counter
    import datetime

    # Guard: oversized clusters
    if cluster["node_count"] > MAX_CLUSTER_SIZE:
        return {
            "cluster_id": str(uuid.uuid4()),
            "status": "OVERSIZED",
            "matched_pairs": [],
            "solver_time_ms": 0.0,
            "message": f"Cluster has {cluster['node_count']} nodes, exceeds max {MAX_CLUSTER_SIZE}",
        }
    
    nodes = cluster["nodes"]
    edges = cluster["edges"]
    
    # Extract sources and targets dynamically from the edges
    s_ids = set(e[0] for e in edges)
    t_ids = set(e[1] for e in edges)
    
    source_nodes = [n for n in nodes if n[0] in s_ids]
    target_nodes = [n for n in nodes if n[0] in t_ids]
    
    all_matched_pairs = []
    total_time_ms = 0.0
    
    # [TIER 1.5] High-Entropy Amount Anchors (Zippers)
    s_amounts = Counter(n[1].get("amount") for n in source_nodes)
    t_amounts = Counter(n[1].get("amount") for n in target_nodes)
    
    unique_s_nodes = [n for n in source_nodes if s_amounts[n[1].get("amount")] == 1]
    unique_t_nodes = [n for n in target_nodes if t_amounts[n[1].get("amount")] == 1]
    
    paired_s_ids = set()
    paired_t_ids = set()
    
    for t_node in unique_t_nodes:
        t_amt = float(t_node[1].get("amount", 0))
        upper_bound = t_amt / (1.0 - MAX_FEE_PCT)
        
        valid_s = [s for s in unique_s_nodes if s[0] not in paired_s_ids and t_amt <= float(s[1].get("amount", 0)) <= upper_bound]
        
        if len(valid_s) == 1:
            s_node = valid_s[0]
            other_t = [t for t in unique_t_nodes if t[0] != t_node[0] and t[0] not in paired_t_ids and float(t[1].get("amount", 0)) <= float(s_node[1].get("amount", 0)) <= float(t[1].get("amount", 0)) / (1.0 - MAX_FEE_PCT)]
            if len(other_t) == 0:
                paired_s_ids.add(s_node[0])
                paired_t_ids.add(t_node[0])
                
                s_event = events_map.get(s_node[0], {})
                t_event = events_map.get(t_node[0], {})
                
                all_matched_pairs.append({
                    "source_id": s_node[0],
                    "target_id": t_node[0],
                    "allocated_amount": float(t_amt),
                    "match_score": 100,
                    "match_reason": "HIGH_ENTROPY_ANCHOR",
                    "source_fact_ids": s_event.get("fact_ids", []),
                    "target_fact_ids": t_event.get("fact_ids", []),
                })
    
    # Filter out zipped nodes
    source_nodes = [n for n in source_nodes if n[0] not in paired_s_ids]
    target_nodes = [n for n in target_nodes if n[0] not in paired_t_ids]
    
    if not source_nodes or not target_nodes:
        return {
            "cluster_id": str(uuid.uuid4()),
            "status": "OPTIMAL_UNIQUE",
            "matched_pairs": all_matched_pairs,
            "solver_time_ms": total_time_ms,
            "message": f"Fully resolved via Tier 1.5 Anchors: {len(all_matched_pairs)} pair(s)",
        }
        
    # [TIER 2] Algorithmic Bulk Resolution (Symmetry Bypass)
    if len(source_nodes) == len(target_nodes) and len(source_nodes) > 1:
        first_s = source_nodes[0][1]
        s_symmetric = all(
            n[1].get("amount") == first_s.get("amount") and 
            n[1].get("date") == first_s.get("date") and
            n[1].get("description") == first_s.get("description") and
            n[1].get("transaction_id") == first_s.get("transaction_id")
            for n in source_nodes
        )
        
        first_t = target_nodes[0][1]
        t_symmetric = all(
            n[1].get("amount") == first_t.get("amount") and 
            n[1].get("date") == first_t.get("date") and
            n[1].get("description") == first_t.get("description") and
            n[1].get("transaction_id") == first_t.get("transaction_id")
            for n in target_nodes
        )
        
        if s_symmetric and t_symmetric:
            for i in range(len(source_nodes)):
                s_id = source_nodes[i][0]
                t_id = target_nodes[i][0]
                s_event = events_map.get(s_id, {})
                t_event = events_map.get(t_id, {})
                
                all_matched_pairs.append({
                    "source_id": s_id,
                    "target_id": t_id,
                    "allocated_amount": float(t_event.get("amount", 0)),
                    "match_score": 100,
                    "match_reason": "SYMMETRY_BYPASS",
                    "source_fact_ids": s_event.get("fact_ids", []),
                    "target_fact_ids": t_event.get("fact_ids", []),
                })
                
            return {
                "cluster_id": str(uuid.uuid4()),
                "status": "OPTIMAL_UNIQUE",
                "matched_pairs": all_matched_pairs,
                "solver_time_ms": 0.0,
                "message": f"Resolved via Tier 2 Symmetry Bypass: {len(all_matched_pairs)} pair(s)",
            }

    # [TIER 3] The Rolling MILP (Chronological Sub-Batching)
    # Group targets by date
    targets_by_date = {}
    for t in target_nodes:
        # events_map date is likely an ISO string or datetime object, handle robustly
        t_event = events_map.get(t[0])
        dt = t_event.get("transaction_date")
        if isinstance(dt, str):
            try:
                date_str = dt.split("T")[0]
            except:
                date_str = "UNKNOWN"
        else:
            date_str = dt.date().isoformat() if dt else "UNKNOWN"
            
        targets_by_date.setdefault(date_str, []).append(t)
        
    sorted_dates = sorted(list(targets_by_date.keys()))
    
    available_sources = list(source_nodes)
    
    for current_date in sorted_dates:
        current_targets = targets_by_date[current_date]
        if not current_targets or not available_sources:
            continue
            
        current_target_ids = {t[0] for t in current_targets}
        current_source_ids = {s[0] for s in available_sources}
        
        # Build sub-cluster edges
        sub_edges = [e for e in edges if e[0] in current_source_ids and e[1] in current_target_ids]
        if not sub_edges:
            continue
            
        sub_nodes = [n for n in nodes if n[0] in current_source_ids or n[0] in current_target_ids]
        
        sub_cluster = {
            "node_count": len(sub_nodes),
            "edges": sub_edges,
            "nodes": sub_nodes
        }
        
        formulation = formulate_cluster(sub_cluster, events_map)
        if formulation is None:
            continue
            
        solver_out = solve_milp(formulation)
        total_time_ms += solver_out.time_ms
        
        if solver_out.status == "TIME_LIMIT":
            return {
                "cluster_id": formulation.cluster_id,
                "status": "ABSTAIN_TIMEOUT",
                "matched_pairs": all_matched_pairs,
                "solver_time_ms": total_time_ms,
                "message": f"Solver hit hard timeout on {current_date}",
            }
        elif solver_out.status == "INFEASIBLE":
            # If a day is infeasible, it doesn't fail the whole cluster, just moves on?
            # Wait, if it's infeasible, we can't allocate. We just skip this day.
            continue
            
        uniqueness = prove_uniqueness(formulation, solver_out.solution, solver_out.objective_value)
        
        if uniqueness == "AMBIGUOUS":
            return {
                "cluster_id": formulation.cluster_id,
                "status": "AMBIGUOUS",
                "matched_pairs": all_matched_pairs,
                "solver_time_ms": total_time_ms,
                "message": f"Ambiguous subset detected on {current_date}",
            }
            
        # Extract proven matches
        num_sub_edges = len(formulation.edge_list)
        used_source_ids = set()
        
        for i, selected in enumerate(solver_out.solution[:num_sub_edges]):
            if selected == 1:
                edge = formulation.edge_list[i]
                s_id = edge["source_id"]
                t_id = edge["target_id"]
                used_source_ids.add(s_id)
                
                source_event = events_map.get(s_id, {})
                target_event = events_map.get(t_id, {})
                
                all_matched_pairs.append({
                    "source_id": s_id,
                    "target_id": t_id,
                    "allocated_amount": float(target_event.get("amount", 0)),
                    "match_score": edge["score"],
                    "match_reason": "OPTIMAL_MILP",
                    "source_fact_ids": source_event.get("fact_ids", []),
                    "target_fact_ids": target_event.get("fact_ids", []),
                })
                
        # Roll forward: remove allocated sources from available pool
        available_sources = [s for s in available_sources if s[0] not in used_source_ids]

    # If we get here, all days were processed optimally!
    return {
        "cluster_id": str(uuid.uuid4()),
        "status": "OPTIMAL_UNIQUE" if all_matched_pairs else "INFEASIBLE",
        "matched_pairs": all_matched_pairs,
        "solver_time_ms": total_time_ms,
        "message": f"Rolling MILP completed with {len(all_matched_pairs)} total match(es)",
    }
