import pytest
from decimal import Decimal
from unittest.mock import MagicMock
from ledger_guard.reconciliation.models import FinancialEvent, ProposedSolution
from ledger_guard.reconciliation.funnel import generate_candidates
from ledger_guard.reconciliation.graph import build_and_cluster_graph
from ledger_guard.reconciliation.solver import process_single_cluster
from ledger_guard.investigator.models import EvidenceBundle, DslOperation
from ledger_guard.reconciliation.verifier import gatekeeper_decision
from ledger_guard.investigator.executor import execute_pot_program
from ledger_guard.db.models import FactLedger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ledger_guard.db.session import Base
import threading
import time

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_integration_graph_to_solver_handoff():
    """
    Test that the output of build_and_cluster_graph() (Block 2) can be directly 
    deserialized and ingested by process_single_cluster() (Block 3) without type errors.
    """
    erp_node = FinancialEvent(
        id="erp_1", event_type="SALE_EVENT", amount=5000.00, currency="INR",
        timestamp="2023-01-01T10:00:00Z", transaction_date="2023-01-01T10:00:00Z",
        transaction_id="txn_123", description="Sale", fact_ids=[1]
    )
    pg_node = FinancialEvent(
        id="pg_1", event_type="PG_PAYMENT_EVENT", amount=5000.00, currency="INR",
        timestamp="2023-01-01T10:05:00Z", transaction_date="2023-01-01T10:05:00Z",
        transaction_id="pg_txn_123", description="Razorpay payment", fact_ids=[2]
    )
    mock_policy = MagicMock(target_currency="INR", max_settlement_lag_days=3)
    
    # Block 2
    edges = generate_candidates([erp_node, pg_node], mock_policy)
    clusters = build_and_cluster_graph([erp_node, pg_node], edges)
    
    assert len(clusters) == 1
    cluster = clusters[0]
    
    events_map = {
        "erp_1": {"amount": 5000.00, "fact_ids": [1], "transaction_date": "2023-01-01T10:00:00Z"},
        "pg_1": {"amount": 5000.00, "fact_ids": [2], "transaction_date": "2023-01-01T10:05:00Z"}
    }
    
    # Block 3 handoff
    result = process_single_cluster(cluster, events_map)
    assert result["status"] == "OPTIMAL_UNIQUE"
    assert len(result["matched_pairs"]) == 1


def test_integration_ai_to_verifier_handoff(db_session):
    """
    Test that when the LangGraph agent constructs a proven AST (PROVEN_AI_CASE), 
    the ProposedSolution schema matches exactly what the Block 5 gatekeeper_decision expects.
    """
    bundle = EvidenceBundle(
        cluster_id="cluster_ai",
        target_event_id="pg_1",
        target_event={"amount": 5000.00, "fact_ids": [2], "type": "PG_PAYMENT_EVENT"},
        candidate_events=[{"id": "erp_1", "amount": 5000.00, "fact_ids": [1], "type": "SALE_EVENT"}],
        policy={},
        policy_context={},
        historical_context=[],
        variables={"erp_1": Decimal("5000.00"), "pg_1": Decimal("5000.00")}
    )
    
    # Mocking what the AI generates
    ast = [
        DslOperation(op="COMPARE", a="erp_1", b="pg_1", result_var="final_match")
    ]
    
    # Block 4 Execution
    out_vars = execute_pot_program(bundle, ast)
    assert out_vars["final_match"][0] == Decimal("1")
    
    # AI forms ProposedSolution
    solution = ProposedSolution(
        source_event_ids=["erp_1"],
        target_event_id="pg_1",
        source_fact_ids=[1],
        target_fact_ids=[2],
        allocated_amount=Decimal("5000.00"),
        match_reason="AI proven match",
        cluster_id="cluster_ai",
        solver_status="PROVEN_AI_CASE"
    )
    
    # Set up DB facts
    f1 = FactLedger(id=1, amount=Decimal("5000.00"), remaining_amount=Decimal("5000.00"), type="SALE", direction="CREDIT")
    f2 = FactLedger(id=2, amount=Decimal("5000.00"), remaining_amount=Decimal("5000.00"), type="PG_PAYMENT", direction="CREDIT")
    db_session.add_all([f1, f2])
    db_session.commit()
    
    # Block 5 handoff
    decision, logs = gatekeeper_decision(solution, db_session)
    assert decision == "AUTO_RESOLVE"
    assert logs["completeness"] == "PASSED"

# For PostgreSQL double-spend, we skip it locally if PG is not available, but test the SQLAlchemy logic 
# using a threading simulation on SQLite (SQLite in-memory supports threading if check_same_thread=False).
def test_integration_concurrent_double_spend():
    try:
        engine = create_engine("postgresql://ledgerguard:securepassword@localhost:5432/ledgerguard")
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        pytest.skip("PostgreSQL not available for concurrency test")
        
    Session = sessionmaker(bind=engine)
    
    # Setup initial fact
    db = Session()
    f1 = FactLedger(id=99, amount=Decimal("100.00"), remaining_amount=Decimal("100.00"), type="SALE", direction="CREDIT")
    db.add(f1)
    db.commit()
    db.close()
    
    def worker(worker_id, results):
        session = Session()
        try:
            # Emulate Block 5 Allocator with_for_update lock logic
            # SQLite doesn't natively block with FOR UPDATE in the same way, but it will throw OperationalError on concurrent writes
            fact = session.query(FactLedger).with_for_update().filter(FactLedger.id == 99).first()
            if fact.remaining_amount >= Decimal("100.00"):
                time.sleep(0.5) # Force race condition window
                fact.remaining_amount -= Decimal("100.00")
                session.commit()
                results.append(f"Worker {worker_id}: SUCCESS")
            else:
                results.append(f"Worker {worker_id}: FAILED_NSF")
        except Exception as e:
            session.rollback()
            results.append(f"Worker {worker_id}: LOCKED_OR_FAILED")
        finally:
            session.close()
            
    results = []
    t1 = threading.Thread(target=worker, args=(1, results))
    t2 = threading.Thread(target=worker, args=(2, results))
    
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    # Exactly one should succeed, the other should fail or lock out
    successes = [r for r in results if "SUCCESS" in r]
    assert len(successes) == 1, f"Expected exactly 1 success, got: {results}"
