# LedgerGuard AI

LedgerGuard AI is an autonomous financial reconciliation engine designed to automatically match and reconcile high-volume financial events across multiple sources (e.g., ERP sales, Payment Gateways, and Bank Settlements) with extreme precision. 

When discrepancies occur (such as missing transactions, orphaned events, or data quality errors), LedgerGuard AI utilizes a built-in AI Investigator powered by Gemini 2.5 Flash to automatically dissect the financial graph, propose an economic hypothesis for the anomaly, and present it to human operators in a streamlined "Forensic Queue" for one-click manual resolution.

## Architecture & Pipeline Blocks

LedgerGuard AI is composed of 5 distinct orchestration blocks that run sequentially to guarantee data integrity and deterministic outcomes.

### Block 1: Data Ingestion & Extraction
Responsible for extracting raw, messy financial data and normalizing it into a strict canonical format using deterministic math assertions and LLM schema discovery.

```mermaid
graph TD
    A([Raw Files: CSV / PDF / XLSX]) --> B[1. File & Row Extraction<br>Polars / pdfplumber]
    B --> C{2. Hash Validation<br>SHA-256 Check}
    C -- Hash Exists --> D[Drop Duplicate<br>Idempotency]
    C -- New Hash --> E[3. LLM Schema Discovery<br>Gemini 2.5 Flash]
    E -. Logs Trace To .-> F[LangSmith Observability<br>Trace Logging]
    E -- Outputs Pydantic Mapping --> G{4. Invariant Probes<br>Python Math Assertions}
    G -- Probes FAIL --> H[5. Human-in-the-Loop<br>LangGraph Routing & React UI]
    H -- Human Corrects Schema --> G
    G -- Probes PASS --> I[6. Data Normalization<br>Decimal / ISO-8601 Cast]
    I --> J[(Fact Ledger DB<br>CanonicalRecord)]
```

### Block 2: Candidate Generation Funnel
Responsible for shrinking the massive search space. It creates small, high-probability bipartite graphs between candidate source events and target deposit events.

```mermaid
graph TD
    A[(Fact Ledger DB)] --> B[Financial Event Builder<br>Map Facts to Events]
    B --> C[Job & Policy Scope<br>Define Batch Limits]
    C --> D{Candidate Generation Funnel}
    D --> E[1. Merchant & Currency Partition]
    E --> F[2. Temporal Window Pruning]
    F --> G[3. Token & Amount Evidence]
    G --> H[Multi-Signal Resolution<br>Create Edges]
```

### Block 3: Mathematical MILP Solver
Executes Mixed-Integer Linear Programming against the candidate graphs to mathematically prove 1:1, 1:N, or N:M matches without hallucination.

```mermaid
graph TD
    A([Candidate Graph from Block 2<br>e.g., 72 Candidates]) --> B[1. Mathematical Formulation<br>Formulate Objective & Constraints]
    B --> C[2. MILP Solver Execution<br>Google OR-Tools / SciPy]
    C -- Success --> D[3. Deterministic Proof & Ambiguity Check<br>Evaluate Uniqueness]
    C -- Break/Discrepancy --> E[Route to AI Investigator<br>Block 4]
    C -- Timeout/Unproven --> F[Emit ABSTAIN]
    D --> G{Multiple Equivalent Subsets?}
    G -- Unique --> H[4. Transactional Allocation<br>Commit Atomic Allocation]
    G -- Ambiguous --> I[Route to HUMAN_REVIEW]
    H --> J[(Allocation Ledger DB)]
    H --> K([Proven Allocation Graph<br>Ready for Block 5])
```

### Block 4: AI Investigator
An autonomous Agent (Gemini 2.5 Flash) that analyzes unresolved solver cases, hypothesizes economic anomalies (like missing fees or orphaned records), and writes a deterministic Program-of-Thought DSL to prove its hypothesis.

```mermaid
graph TD
    A([Unresolved Solver Case<br>from Block 3]) --> B[1. Evidence Retrieval<br>Dynamic Bundle Assembly]
    B --> C[2. AI Investigator Agent<br>Gemini 2.5 Flash]
    C --> D{3. Generates Structured Output<br>Hypothesis & DSL Program}
    D --> E[4. Deterministic PoT Executor<br>Python Dispatch Loop]
    E --> F{5. Math Verification<br>Does Result = Target?}
    F -- False --> G[Route to ESCALATE / REVIEW<br>Verification Failed]
    F -- True --> H([Proven AI Case<br>Ready for Block 5 Verifier])
```

### Block 5: The Deterministic Verifier
The final safety checkpoint. It accepts proposed matches from the MILP Solver or the AI Investigator, strips away their reasoning, and verifies provenance, source authority, and completeness from scratch.

```mermaid
graph TD
    A([Proposed Solution<br>from Block 3 or 4]) --> B[The Deterministic Verifier]
    B --> C{1. Provenance & Validity<br>Are facts real & active?}
    C -- Pass --> D{2. Source Authority<br>Who owns the truth?}
    D -- Pass --> E{3. Completeness Check<br>Is Residual = 0?}
    C -- Fail --> F[ESCALATE<br>Contradiction/Break]
    D -- Contradiction --> F
    E -- Pass --> G[Decision Engine]
    G --> H{Route Case Status}
    H --> I[AUTO_RESOLVE]
    H --> J[REVIEW]
    H --> K[ABSTAIN]
    E -- Break Remains --> F
    I --> L[(Decision Record DB)]
    J --> L
    K --> L
    F --> L
    L --> M([Exception Dashboard<br>Human Workflow])
```
- **Interactive Forensic Queue**: A beautiful, dynamic React dashboard to visualize orphaned clusters side-by-side, view the AI's hypothesis, and securely push manual adjustments and force-matches to the immutable ledger.
- **Real-Time Insights**: A live dashboard displaying auto-match rates, total reconciled volume, and trailing 7-day trend analysis.

## Repository Structure

- `backend/`: The FastAPI backend, Postgres/SQLite database models, Multi-Agent solver, and API endpoints.
- `frontend/`: The Vite + React dashboard, utilizing `recharts` and `lucide-react`.
- `Testing_data/`: A collection of 444 synthetic financial records across 3 tiers (ERP Export, Razorpay Recon, and Bank Statement) designed to simulate real-world e-commerce accounting.

## Prerequisites

- Python 3.13+ (using `uv` for dependency management)
- Node.js 18+ (for running the Vite React frontend)

## Installation and Setup

### 1. Clone the repository
```bash
git clone https://github.com/HemishJain09/Ledgerguard-AI.git
cd Ledgerguard-AI
```

### 2. Backend Setup
```bash
cd backend
# Install dependencies using uv
uv sync
```

Create a `.env` file in the `backend/` directory with your API keys:
```env
GROQ_API_KEY="your_groq_api_key_here"
LANGCHAIN_API_KEY="your_langchain_api_key_here"
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
LANGCHAIN_PROJECT="LedgerGuard-AI"
GEMINI_API_KEY="your_gemini_api_key_here"
DATABASE_URL="sqlite:///./ledger.db"
```

### 3. Frontend Setup
```bash
cd ../frontend
npm install
```

## Running the Application

You will need two terminal tabs to run both servers concurrently.

**Terminal 1: Start the Backend Server**
```bash
cd backend
uv run uvicorn server:app --reload --port 8000
```
*The API will be available at `http://localhost:8000`*

**Terminal 2: Start the Frontend UI**
```bash
cd frontend
npm run dev
```
*The Dashboard will be available at `http://localhost:5173`*

## Demo Walkthrough

1. Open `http://localhost:5173` in your browser.
2. In the **Dashboard** view, under "Demo Ingestion Sources", click the ingest buttons sequentially:
   - **Ingest ERP Export**
   - **Ingest Razorpay Recon**
   - **Ingest Bank Statement**
3. Once all files are ingested, click **Run Auto-Reconciliation Engine**. The background solver will execute the MILP algorithms and allocate the matches.
4. Navigate to the **AI Forensic Queue** in the sidebar.
5. You will see mathematically orphaned clusters that failed automatic resolution. The AI Investigator will present its hypothesis for *why* the records failed to match (e.g., "Missing Record" or "Data Quality Error").
6. Check the candidate boxes you wish to map, enter an adjustment if needed, and click **Force Match & Clear** to manually resolve the anomaly.

## License
MIT License
