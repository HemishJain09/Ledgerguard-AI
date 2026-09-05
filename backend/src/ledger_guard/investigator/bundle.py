import datetime
from decimal import Decimal
from typing import Dict, Any, List, Tuple
from .models import EvidenceBundle

def assemble_bundle(cluster_id: str, cluster_data: Dict[str, Any], policy: Dict[str, Any]) -> EvidenceBundle:
    """
    Step 1: Dynamic Bundle Assembly.
    Extracts numerical and temporal values from a failed cluster and binds them 
    to a variables dictionary for the deterministic PoT executor.
    """
    nodes = cluster_data.get("nodes", [])
    
    variables: Dict[str, Any] = {}
    
    # Pre-load policy constants
    for k, v in policy.items():
        variables[f"policy.{k}"] = Decimal(str(v)) if isinstance(v, (int, float, Decimal)) else v
        
    target_event_id = None
        
    for node in nodes:
        # Check if node is a tuple [id, attrs] or a dict {'id': ..., ...}
        if isinstance(node, list) and len(node) == 2:
            event_id = node[0]
            event = node[1]
        elif isinstance(node, dict):
            event_id = node.get("id", "UNKNOWN")
            event = node
        else:
            continue
            
        # Determine if this is a target bank event
        is_target = "PAYOUT" in event.get("type", "") or "SETTLEMENT" in event.get("type", "") or "BANK" in event.get("type", "")
        if is_target:
            target_event_id = event_id
        
        # Load standard amounts as Decimal
        variables[f"{event_id}.gross"] = Decimal(str(event.get("gross_amount", 0.0)))
        variables[f"{event_id}.fee"] = Decimal(str(event.get("fee_amount", 0.0)))
        variables[f"{event_id}.net"] = Decimal(str(event.get("amount", 0.0)))
        
        # Load timestamp
        ts = event.get("timestamp")
        if isinstance(ts, str):
            try:
                variables[f"{event_id}.timestamp"] = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                variables[f"{event_id}.timestamp"] = None
        elif isinstance(ts, datetime.datetime):
            variables[f"{event_id}.timestamp"] = ts
        else:
            variables[f"{event_id}.timestamp"] = None

    if not target_event_id and nodes:
        # Fallback to the first node if no explicit target found
        target_event_id = nodes[0][0] if isinstance(nodes[0], list) else nodes[0].get("id")
        
    # Build candidate relationships (all node IDs except target)
    candidate_rels = []
    for node in nodes:
        n_id = node[0] if isinstance(node, list) else node.get("id")
        if n_id and n_id != target_event_id:
            candidate_rels.append(n_id)
            
    # If ORPHANED (i.e. only 1 node in cluster_data), extract provenance for global context
    global_context = ""
    if len(nodes) == 1:
        n = nodes[0][1] if isinstance(nodes[0], list) else nodes[0]
        # Assuming the description holds the raw JSON or provenance details
        desc = n.get("description", "")
        global_context = f"Provenance metadata (raw source file row): {desc}"
        
    return EvidenceBundle(
        cluster_id=cluster_id,
        variables=variables,
        target_event_id=target_event_id or "UNKNOWN",
        policy=policy,
        candidate_relationships=candidate_rels,
        global_context=global_context
    )
