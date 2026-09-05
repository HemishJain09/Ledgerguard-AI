from decimal import Decimal
import datetime
from typing import Dict, Any, List
from .models import DslOperation, EvidenceBundle

class ExecutorError(Exception):
    pass

def execute_pot_program(bundle: EvidenceBundle, program: List[DslOperation]) -> Dict[str, Any]:
    """
    Step 4: Deterministic PoT Executor
    A sandbox that loops sequentially over the DSL operations.
    Raises ValueError or KeyError on hallucinated variables to trigger the LangGraph self-correction loop.
    """
    # Clone variables and attach initial lineage (just the variable name itself)
    variables = {k: (v, {k}) for k, v in bundle.variables.items()}
    
    def get_val(operand: str) -> Any:
        # If operand is a numeric literal
        try:
            return (Decimal(operand), set())
        except Exception:
            pass
            
        if operand not in variables:
            raise KeyError(f"Hallucinated variable or missing fact attribute: '{operand}'")
        return variables[operand]

    for op in program:
        a_val, a_lineage = get_val(op.a)
        
        b_val, b_lineage = None, set()
        if op.b is not None:
            b_val, b_lineage = get_val(op.b)
            
        result = None
        new_lineage = a_lineage | b_lineage | {op.result_var}
        
        try:
            match op.op:
                case "SUBTRACT":
                    if not isinstance(a_val, Decimal) or not isinstance(b_val, Decimal):
                        raise ValueError(f"SUBTRACT requires Decimal operands, got {type(a_val)} and {type(b_val)}")
                    result = a_val - b_val
                    
                case "ADD":
                    if not isinstance(a_val, Decimal) or not isinstance(b_val, Decimal):
                        raise ValueError(f"ADD requires Decimal operands, got {type(a_val)} and {type(b_val)}")
                    result = a_val + b_val
                    
                case "MULTIPLY":
                    if not isinstance(a_val, Decimal) or not isinstance(b_val, Decimal):
                        raise ValueError(f"MULTIPLY requires Decimal operands, got {type(a_val)} and {type(b_val)}")
                    result = a_val * b_val
                    
                case "COMPARE":
                    result = Decimal("1") if a_val == b_val else Decimal("0")
                    
                case "DATE_DIFF":
                    if not isinstance(a_val, datetime.datetime) or not isinstance(b_val, datetime.datetime):
                        raise ValueError("DATE_DIFF requires datetime operands")
                    result = Decimal((a_val - b_val).days)
                    
                case "RULE_LOOKUP":
                    result = a_val
                    
                case _:
                    raise ValueError(f"Unknown operation: {op.op}")
                    
            variables[op.result_var] = (result, new_lineage)
            
        except Exception as e:
            if isinstance(e, (KeyError, ValueError, ExecutorError)):
                raise e
            raise ExecutorError(f"Error executing {op.op}: {str(e)}")
            
    return variables
