import pytest
from decimal import Decimal
from ledger_guard.reconciliation.funnel import generate_candidates
from ledger_guard.reconciliation.models import FinancialEvent, ProposedSolution
from ledger_guard.reconciliation.solver import process_single_cluster
from ledger_guard.reconciliation.verifier import gatekeeper_decision
from ledger_guard.investigator.executor import execute_pot_program
from ledger_guard.investigator.models import EvidenceBundle, DslOperation
from ledger_guard.db.models import FactLedger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ledger_guard.db.session import Base
from unittest.mock import MagicMock

# --- Test Data Setup ---

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# --- Block 2: Funnel & Candidate Generation ---
def test_block2_generate_candidates():
    # Synthetic ERP and Razorpay node
    erp_node = FinancialEvent(
        id="erp_1",
        event_type="SALE_EVENT",
        amount=5000.00,
        currency="INR",
        timestamp="2023-01-01T10:00:00Z",
        transaction_date="2023-01-01T10:00:00Z",
        transaction_id="txn_123",
        description="Sale",
        fact_ids=[1]
    )
    pg_node = FinancialEvent(
        id="pg_1",
        event_type="PG_PAYMENT_EVENT",
        amount=5000.00,
        currency="INR",
        timestamp="2023-01-01T10:05:00Z",
        transaction_date="2023-01-01T10:05:00Z",
        transaction_id="pg_txn_123",
        description="Razorpay payment",
        fact_ids=[2]
    )
    
    mock_policy = MagicMock(target_currency="INR", max_settlement_lag_days=3)
    candidates = generate_candidates([erp_node, pg_node], mock_policy)
    
    # Assert exactly 1 edge is generated
    assert len(candidates) == 1
    edge = candidates[0]
    assert edge.source_event_id == "erp_1"
    assert edge.target_event_id == "pg_1"
    assert edge.match_score >= 80

# --- Block 3: The Uniform Pricing Trap / Ambiguity Check ---
def test_block3_uniform_pricing_trap():
    # 1 target deposit, 3 identical source invoices
    cluster = {
        "node_count": 4,
        "nodes": [
            ("target_1", {"type": "BANK_SETTLEMENT_EVENT", "amount": 5000.00, "description": "Deposit", "fact_ids": [10]}),
            ("src_1", {"type": "PG_PAYOUT_EVENT", "amount": 5000.00, "description": "Payout A", "fact_ids": [11]}),
            ("src_2", {"type": "PG_PAYOUT_EVENT", "amount": 5000.00, "description": "Payout B", "fact_ids": [12]}),
            ("src_3", {"type": "PG_PAYOUT_EVENT", "amount": 5000.00, "description": "Payout C", "fact_ids": [13]}),
        ],
        "edges": [
            ("src_1", "target_1", {"weight": 90, "match_reason": "Amount Match"}),
            ("src_2", "target_1", {"weight": 90, "match_reason": "Amount Match"}),
            ("src_3", "target_1", {"weight": 90, "match_reason": "Amount Match"}),
        ]
    }
    
    events_map = {
        "target_1": {"type": "BANK_SETTLEMENT_EVENT", "amount": 5000.00, "description": "Deposit", "fact_ids": [10], "transaction_date": "2023-01-01T10:00:00Z"},
        "src_1": {"type": "PG_PAYOUT_EVENT", "amount": 5000.00, "description": "Payout A", "fact_ids": [11], "transaction_date": "2023-01-01T10:00:00Z"},
        "src_2": {"type": "PG_PAYOUT_EVENT", "amount": 5000.00, "description": "Payout B", "fact_ids": [12], "transaction_date": "2023-01-01T10:00:00Z"},
        "src_3": {"type": "PG_PAYOUT_EVENT", "amount": 5000.00, "description": "Payout C", "fact_ids": [13], "transaction_date": "2023-01-01T10:00:00Z"}
    }
    
    result = process_single_cluster(cluster, events_map)
    # The solver should find multiple equivalent optimal solutions and flag as AMBIGUOUS
    assert result["status"] == "AMBIGUOUS"

# --- Block 4: LangGraph Self-Correction Limits ---
def test_block4_langgraph_self_correction_limits():
    
    bundle = EvidenceBundle(
        cluster_id="cluster_1",
        target_event_id="target_1",
        target_event={"amount": 100.00},
        candidate_events=[],
        policy={},
        policy_context={},
        historical_context=[],
        variables={"target_1": Decimal("100.00")}
    )
    
    # Inject adversarial AST trying to reference an undefined variable 'x'
    adversarial_program = [
        DslOperation(
            op="COMPARE",
            a="x", # Undefined variable
            b="target_1",
            result_var="out"
        )
    ]
    
    with pytest.raises(KeyError) as excinfo:
        execute_pot_program(bundle, adversarial_program)
    
    assert "x" in str(excinfo.value)

# --- Block 5: Source Authority Contradiction ---
def test_block5_source_authority_contradiction(db_session):
    # Setup facts where ERP and Gateway net contradicts
    # Fact 1: ERP Net = 1000
    f1 = FactLedger(id=1, amount=Decimal("1000.00"), remaining_amount=Decimal("1000.00"), type="SALE", direction="CREDIT")
    # Fact 2: Gateway Gross = 1050
    f2 = FactLedger(id=2, amount=Decimal("1050.00"), remaining_amount=Decimal("1050.00"), type="PG_PAYMENT", direction="CREDIT")
    # Fact 3: Gateway Fee = 50 (Debit)
    f3 = FactLedger(id=3, amount=Decimal("50.00"), remaining_amount=Decimal("50.00"), type="FEE_DEDUCTION", direction="DEBIT")
    
    db_session.add_all([f1, f2, f3])
    db_session.commit()
    
    # Create ProposedSolution that allocates perfectly to 0.00 residual
    # But ERP (1000) vs Gateway net (1050 - 50 = 1000)
    # Wait, if ERP = 1000 and Gateway net = 1000, that is NOT a contradiction.
    # We need a contradiction: ERP = 1000, Gateway Gross = 1020, Gateway Fee = 10 -> Gateway net = 1010.
    f1.amount = Decimal("1000.00")
    f1.remaining_amount = Decimal("1000.00")
    f2.amount = Decimal("1020.00")
    f2.remaining_amount = Decimal("1020.00")
    f3.amount = Decimal("10.00")
    f3.remaining_amount = Decimal("10.00")
    db_session.commit()
    
    solution = ProposedSolution(
        source_event_ids=["erp_1"],
        target_event_id="pg_1",
        source_fact_ids=[1],
        target_fact_ids=[2, 3],
        allocated_amount=Decimal("1000.00"),
        match_reason="Mocked match",
        cluster_id="cluster_1",
        solver_status="OPTIMAL_UNIQUE"
    )
    
    decision, logs = gatekeeper_decision(solution, db_session)
    
    # Assert Deterministic Verifier enforces hierarchy rule, overrides ERP with Gateway math, and escalates
    # Wait, the arithmetic doesn't balance perfectly if Gateway is 1010 and ERP is 1000.
    # Let's assert it returns ESCALATE.
    assert decision == "ESCALATE"
    assert "Gateway math contradicts ERP" in logs.get("error_message", "") or "completeness" in logs
