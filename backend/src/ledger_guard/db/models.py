from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .session import Base

class FileIngestionLog(Base):
    __tablename__ = "file_ingestion_logs"

    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String, index=True)
    file_hash = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="PROCESSING") # PROCESSING, COMPLETED, FAILED
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship back to FactLedger
    fact_ledger_entries = relationship("FactLedger", back_populates="ingestion_log")


# FactLedger model for Block 6
class FactLedger(Base):
    __tablename__ = "fact_ledger"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(String, index=True)
    transaction_date = Column(DateTime(timezone=True))
    
    amount = Column(Numeric(precision=15, scale=2))
    currency = Column(String, default="INR", index=True)
    direction = Column(String) # 'CREDIT' or 'DEBIT'
    
    type = Column(String) # 'GROSS_PAYMENT', 'FEE_DEDUCTION', 'TAX_DEDUCTION', 'BANK_CREDIT', etc.
    
    remaining_amount = Column(Numeric(precision=15, scale=2))
    status = Column(String, default="UNALLOCATED", index=True)
    
    description = Column(String)
    
    # Foreign key linking back to the ingestion log
    source_file_hash = Column(String, ForeignKey("file_ingestion_logs.file_hash"), index=True)
    ingestion_log = relationship("FileIngestionLog", back_populates="fact_ledger_entries")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AllocationRecord(Base):
    """Stores a provably correct, unique match between two financial events."""
    __tablename__ = "allocation_records"

    id = Column(Integer, primary_key=True, index=True)
    source_event_id = Column(String, index=True)
    target_event_id = Column(String, index=True)
    allocated_amount = Column(Numeric(precision=15, scale=2))
    match_reason = Column(String)
    match_score = Column(Integer)
    solver_status = Column(String)  # OPTIMAL_UNIQUE
    cluster_id = Column(String, index=True)
    source_fact_ids = Column(JSON)
    target_fact_ids = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ExceptionRecord(Base):
    """Stores solver-generated exceptions for human review."""
    __tablename__ = "exception_records"

    id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(String, index=True)
    reason = Column(String)  # ABSTAIN_TIMEOUT, AMBIGUOUS_MULTI_SOLUTION, INFEASIBLE, OVERSIZED
    cluster_data = Column(JSON)
    investigation_result = Column(JSON, nullable=True) # AI hypothesis and classification
    status = Column(String, default="PENDING")  # PENDING, RESOLVED
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class DecisionRecord(Base):
    """
    Block 5 Immutable Audit Trail.
    Stores the final verdict from the Deterministic Verifier & Decision Engine.
    """
    __tablename__ = "decision_records"

    id = Column(Integer, primary_key=True, index=True)
    decision_status = Column(String, index=True) # AUTO_RESOLVE, REVIEW, ESCALATE, ABSTAIN
    cluster_id = Column(String, index=True)
    solution_payload = Column(JSON)
    verifier_logs = Column(JSON, nullable=True)
    ast_program = Column(JSON, nullable=True) # If it came from Block 4
    created_at = Column(DateTime(timezone=True), server_default=func.now())
