from typing import TypedDict, Optional, List, Any
import os
import json
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from langgraph.graph import StateGraph, END
from pydantic import BaseModel
from decimal import Decimal

from .models import EvidenceBundle, InvestigationResult
from .executor import execute_pot_program, ExecutorError
from .verifier import verify_resolution

class AgentState(TypedDict):
    bundle: EvidenceBundle
    messages: List[BaseMessage]
    result: Optional[InvestigationResult]
    decision: Optional[str]
    retries: int

# System prompt outlining the DSL and rules
SYSTEM_PROMPT = """You are the LedgerGuard AI Investigator.
Your job is to resolve discrepancies between financial events (e.g. ERP sales vs Bank deposits).
You will be provided with an EvidenceBundle containing variables representing the amounts and timestamps of the events.

Your goal is to formulate an economic hypothesis for the discrepancy (e.g. gateway fees, tax deductions, chargebacks) 
and prove it by generating a Program-of-Thought (PoT) using EXACTLY these 6 atomic operations:

1. SUBTRACT (a, b, result_var): variables[result_var] = a - b
2. ADD (a, b, result_var): variables[result_var] = a + b
3. MULTIPLY (a, b, result_var): variables[result_var] = a * b
4. COMPARE (a, b, result_var): variables[result_var] = 1 if a == b else 0
5. DATE_DIFF (a, b, result_var): variables[result_var] = (a - b).days
6. RULE_LOOKUP (a, None, result_var): variables[result_var] = variables[a]

RULES:
- ONLY use variables that are pre-loaded in the EvidenceBundle.
- The FINAL operation MUST be a COMPARE checking your computed net amount against the target bank deposit amount, 
  storing the boolean (1 or 0) in 'final_match'.
- Output strictly in the requested JSON format.
- CONDITIONAL OVERRIDE: If candidate_relationships is empty, this is an isolated orphan. Do not attempt mathematical closure. Classify the root cause of the isolation using the provided taxonomy (MISSING_RECORD, AMOUNT_VARIANCE, DATA_QUALITY_ERROR). You MUST output an empty operations array `[]` for the dsl_program.
"""

def build_investigator_graph():
    # Initialize Gemini model to handle large token contexts
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0, max_tokens=800)
    structured_llm = llm.with_structured_output(InvestigationResult)

    def generate_node(state: AgentState):
        bundle = state["bundle"]
        
        if not state["messages"]:
            # Initial prompt
            bundle_str = bundle.model_dump_json(indent=2)
            msg = HumanMessage(content=f"Please analyze the following EvidenceBundle and generate a PoT program:\n{bundle_str}")
            messages = [SystemMessage(content=SYSTEM_PROMPT), msg]
        else:
            messages = state["messages"]

        result = structured_llm.invoke(messages)
        
        # Add the AI's output to the history in case we need to retry
        new_messages = messages + [AIMessage(content=result.model_dump_json(indent=2))]
        return {"result": result, "messages": new_messages}

    def execute_node(state: AgentState):
        bundle = state["bundle"]
        result = state["result"]
        retries = state.get("retries", 0)
        
        try:
            # 1. Run Executor
            variables_out = execute_pot_program(bundle, result.dsl_program)
            
            # 2. Run Verifier
            is_proven, decision = verify_resolution(bundle, variables_out, result)
            
            if is_proven:
                return {"decision": "PROVEN_AI_CASE", "messages": state["messages"]}
            else:
                return {"decision": decision, "messages": state["messages"]}
                
        except ExecutorError as e:
            # The execution failed (e.g. KeyError on hallucinated variable)
            if retries >= 2:
                # Max retries hit, escalate
                return {"decision": "ESCALATE_MAX_RETRIES", "messages": state["messages"]}
            
            # Feed the error back to the LLM
            error_msg = HumanMessage(content=f"ExecutorError: {str(e)}\nPlease fix your DSL program and try again.")
            new_messages = state["messages"] + [error_msg]
            
            return {"messages": new_messages, "retries": retries + 1, "decision": "RETRY"}

    def route_decision(state: AgentState):
        decision = state.get("decision")
        if decision == "RETRY":
            return "generate"
        return END

    workflow = StateGraph(AgentState)
    workflow.add_node("generate", generate_node)
    workflow.add_node("execute", execute_node)

    workflow.set_entry_point("generate")
    workflow.add_edge("generate", "execute")
    workflow.add_conditional_edges("execute", route_decision)

    return workflow.compile()

def run_investigation(bundle: EvidenceBundle) -> AgentState:
    graph = build_investigator_graph()
    
    initial_state = {
        "bundle": bundle,
        "messages": [],
        "result": None,
        "decision": None,
        "retries": 0
    }
    
    final_state = graph.invoke(initial_state)
    return final_state
