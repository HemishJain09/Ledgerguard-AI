import os
import json
import polars as pl
from pydantic import BaseModel, Field
from typing import Dict, Any, List
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langsmith import traceable

# The strict schema we want to normalize everything into
class CanonicalTransaction(BaseModel):
    transaction_id: str = Field(description="Primary identifier for the transaction (Order ID or Settlement ID/UTR)")
    transaction_date: str = Field(description="Date of the transaction")
    gross_amount: str = Field(description="The total gross amount before deductions")
    fee_amount: str = Field(description="Any processing fee deducted (default '0.00' if none)")
    tax_amount: str = Field(description="Any tax on the fee (default '0.00' if none)")
    net_amount: str = Field(description="The final net amount settled or credited/debited")
    currency: str = Field(description="Currency code for the transaction (default 'INR' if none)")
    description: str = Field(description="Additional details or counterparty name")
    type: str = Field(description="Type of record: e.g., 'ERP_SALE', 'PG_SETTLEMENT', 'BANK_CREDIT'")

class SchemaMapping(BaseModel):
    mapping: Dict[str, str] = Field(
        description="A dictionary mapping the CanonicalTransaction field names to the exact raw column names from the input file."
    )
    fixed_values: Dict[str, str] = Field(
        description="If a Canonical field doesn't exist in the raw data, provide a hardcoded default value for it (e.g., {'fee_amount': '0.00', 'type': 'ERP_SALE'})"
    )

# @traceable enables asynchronous logging to LangSmith for observability
@traceable(name="Discover Schema with LLM")
def discover_schema(raw_df: pl.DataFrame, source_hint: str) -> SchemaMapping:
    """
    Takes a sample of extracted rows and sends them to Gemini 3.1 Pro to map 
    the unfamiliar raw column headers to the strict Pydantic schema.
    """
    # Initialize the Groq model using Langchain
    # It requires GROQ_API_KEY to be set in the environment
    llm = ChatGroq(
        model="qwen/qwen3.8-27b",
        max_tokens=500,
        temperature=0.0
    )
    
    # We use Langchain's with_structured_output to force Pydantic schema return
    structured_llm = llm.with_structured_output(SchemaMapping)
    
    # Take a small sample to save tokens
    sample_size = min(5, len(raw_df))
    sample_data = raw_df.head(sample_size).to_dicts()
    raw_columns = raw_df.columns
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a master financial data engineer. Your job is to map raw data columns from an unknown financial system ({source_hint}) into our strict Canonical Schema.
        
        Available Canonical Fields:
        - transaction_id
        - transaction_date
        - gross_amount
        - fee_amount
        - tax_amount
        - net_amount
        - currency
        - description
        - type
        
        Analyze the provided raw column names and the sample data rows.
        Return a mapping from the Canonical Field names to the Raw Column names.
        If a Canonical field is fundamentally missing (like 'fee_amount' in an ERP export or 'currency'), map it in `fixed_values` instead of `mapping`. For `type`, assign a sensible string based on the {source_hint}."""),
        ("human", "Raw Columns: {raw_columns}\n\nSample Data: {sample_data}\n\nProvide the SchemaMapping.")
    ])
    
    chain = prompt | structured_llm
    
    result: SchemaMapping = chain.invoke({
        "source_hint": source_hint,
        "raw_columns": raw_columns,
        "sample_data": json.dumps(sample_data, indent=2, default=str)
    })
    
    return result

def apply_mapping(raw_df: pl.DataFrame, schema_mapping: SchemaMapping) -> pl.DataFrame:
    """
    Applies the discovered mapping to the Polars DataFrame.
    """
    exprs = []
    
    # 1. Map columns that exist
    for target_col, source_col in schema_mapping.mapping.items():
        if source_col in raw_df.columns:
            exprs.append(pl.col(source_col).alias(target_col).cast(pl.Utf8))
        else:
            print(f"Warning: LLM hallucinated column {source_col}")
            
    # 2. Add fixed/default values
    for target_col, fixed_val in schema_mapping.fixed_values.items():
        exprs.append(pl.lit(fixed_val).alias(target_col))
        
    mapped_df = raw_df.select(exprs)
    
    # Ensure all canonical columns exist, fill missing with None/Null
    canonical_cols = list(CanonicalTransaction.__annotations__.keys())
    for col in canonical_cols:
        if col not in mapped_df.columns:
             mapped_df = mapped_df.with_columns(pl.lit(None).alias(col))
             
    return mapped_df.select(canonical_cols)
