import os
import yaml

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../config.yaml")

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)

config_data = load_config()

INGESTION_CONFIG = config_data.get("ingestion", {})
RECONCILIATION_CONFIG = config_data.get("reconciliation", {})
SOLVER_CONFIG = config_data.get("solver", {})

# Defaults
MATH_TOLERANCE = float(INGESTION_CONFIG.get("math_tolerance_amount", 0.10))
MAX_SETTLEMENT_LAG_DAYS = int(config_data.get("reconciliation", {}).get("max_settlement_lag_days", 3))
FUZZY_MATCH_THRESHOLD = int(RECONCILIATION_CONFIG.get("fuzzy_match_threshold", 75))
MAX_FEE_PCT = float(RECONCILIATION_CONFIG.get("max_fee_pct", 0.03))

# Solver
SOLVER_TIMEOUT = float(SOLVER_CONFIG.get("timeout_seconds", 1.5))
INTEGER_SCALE_FACTOR = int(SOLVER_CONFIG.get("integer_scale_factor", 10000))
MAX_CLUSTER_SIZE = int(SOLVER_CONFIG.get("max_cluster_size", 50))
