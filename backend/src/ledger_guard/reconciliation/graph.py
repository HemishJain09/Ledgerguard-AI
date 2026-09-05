import networkx as nx
from typing import List, Dict, Any
from .models import FinancialEvent, ReconEdge

def build_and_cluster_graph(events: List[FinancialEvent], edges: List[ReconEdge]) -> List[Dict[str, Any]]:
    """
    Builds a NetworkX graph from the events and edges, and returns disjoint clusters.
    This effectively groups all interrelated events into isolated subgraphs for the solver.
    """
    G = nx.Graph()
    
    # Add all events as nodes
    for event in events:
        G.add_node(
            event.id, 
            type=event.event_type, 
            amount=float(event.amount), 
            date=event.transaction_date.isoformat(),
            description=event.description
        )
        
    # Add edges that survived the funnel
    for edge in edges:
        G.add_edge(
            edge.source_event_id, 
            edge.target_event_id, 
            weight=edge.match_score,
            amount_diff=float(edge.amount_diff),
            match_reason=edge.match_reason
        )
        
    # Extract connected components (disjoint subgraphs)
    clusters = []
    for comp in nx.connected_components(G):
        subgraph = G.subgraph(comp)
        
        # Only keep clusters that have at least one edge (meaning at least 2 nodes connected)
        # If a node is completely isolated, it couldn't find any candidates in the funnel.
        if subgraph.number_of_nodes() > 1:
            clusters.append({
                "nodes": list(subgraph.nodes(data=True)),
                "edges": list(subgraph.edges(data=True)),
                "node_count": subgraph.number_of_nodes(),
                "edge_count": subgraph.number_of_edges()
            })
            
    # Sort clusters by size (largest first) to prioritize complex reconciliations
    clusters.sort(key=lambda x: x["node_count"], reverse=True)
            
    return clusters
