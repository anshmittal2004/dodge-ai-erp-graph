# Dodge AI — ERP Graph Intelligence System

> **Graph-Based Data Modeling and Query System**  
> Forward Deployed Engineer Assessment — Dodge AI

A production-grade system that ingests a fragmented SAP ERP dataset, unifies it into a graph of interconnected business entities, visualizes the graph interactively, and lets users query the entire dataset using natural language — powered by Google Gemini with a strict ERP-domain guardrail layer.

---

## Live Demo

🔗 **[Demo Link — add after deploying]**  
📁 **[GitHub Repo — add your URL]**

---

## Screenshots

| Graph View | Chat Query | Broken Flow Detection |
|---|---|---|
| _Interactive node-edge graph_ | _NL → SQL → Answer_ | _Highlighted broken flows_ |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Browser)                       │
│                                                                  │
│   ┌──────────────────────────────┐  ┌────────────────────────┐  │
│   │   Graph Panel (Cytoscape.js) │  │  Chat Panel            │  │
│   │   • 555 nodes, 750+ edges    │  │  • NL input            │  │
│   │   • Node type filtering      │  │  • SQL accordion        │  │
│   │   • Click-to-inspect         │  │  • Raw data table       │  │
│   │   • Highlight from chat      │  │  • Node highlights      │  │
│   └──────────────────────────────┘  └────────────────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼──────────────────────────────────────┐
│                    Backend (FastAPI / Python)                     │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐  │
│  │  /api/graph │  │  /api/chat   │  │  /api/chat/stream      │  │
│  │  Graph JSON │  │  NL→SQL→Run  │  │  SSE streaming         │  │
│  └─────────────┘  └──────┬───────┘  └────────────────────────┘  │
│                           │                                       │
│  ┌────────────────────────▼───────────────────────────────────┐  │
│  │                    LLM Pipeline                             │  │
│  │  1. Guardrails (pattern + keyword check)                    │  │
│  │  2. System prompt with full DB schema                       │  │
│  │  3. Gemini 1.5 Flash → JSON {thought, sql, explanation}     │  │
│  │  4. Execute SQL against SQLite                              │  │
│  │  5. Self-heal loop if SQL errors                            │  │
│  │  6. Return answer + highlighted node IDs                    │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    SQLite Database (erp.db)                  │ │
│  │  12 core tables + 6 optional tables (when data available)   │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Choice — SQLite

**Why SQLite, not Neo4j or PostgreSQL?**

| Concern | Decision |
|---|---|
| Zero-dependency deployment | SQLite ships with Python stdlib — no server to run |
| Dataset size (~1000 rows) | SQLite handles millions; overkill not needed |
| Complex joins | SQL joins are faster than graph traversal for this data volume |
| Demo portability | Single `.db` file, runs anywhere |
| Graph visualization | Handled in-memory by the graph builder — the DB doesn't need to be a graph DB |

The graph is **constructed at query time** from relational data using Python (`graph.py`). This is the correct architectural choice: the data *is* relational, and the graph is a *view* of that relational data — not a separate storage model.

If the dataset grew to millions of documents and traversal queries dominated (e.g., multi-hop "find all customers reachable from plant X"), migrating to Neo4j would make sense. At this scale, SQLite + in-memory graph is faster and simpler.

---

## LLM Prompting Strategy

### Model: Google Gemini 1.5 Flash (free tier)

### Prompt Architecture

```
SYSTEM PROMPT (static, injected once per session)
├── Full SQLite schema for all 12 tables
├── Column-level documentation (types, semantics, SAP meanings)
├── Key foreign key relationships spelled out explicitly
│     e.g. "billing_header.accountingDocument = journal_entries.accountingDocument"
├── Business rules
│     e.g. "overallGoodsMovementStatus: A=not started, B=partial, C=complete"
├── Output format: strict JSON {thought, sql, explanation, highlighted_node_ids}
└── SQLite-specific rules (use LIMIT not TOP, CAST for numeric columns)

USER TURN
└── Natural language question (already guardrail-checked)

ASSISTANT TURN
└── JSON {thought, sql, explanation, highlighted_node_ids}
     ↓
     Execute SQL against SQLite
     ↓ (if error)
     Self-heal: append error + original SQL, ask LLM to fix
     ↓
     Format human-readable answer
```

### Why this works better than RAG or vector search

- The data is **structured**, not unstructured. SQL is the right query language.
- The schema is small enough to fit entirely in the context window (~2000 tokens).
- Providing **explicit column semantics** (not just names) dramatically reduces hallucination.
- The **self-heal loop** handles the ~10% of queries where the first SQL attempt has a minor syntax issue.
- **`highlighted_node_ids`** in the response lets the UI visually link the chat answer back to the graph.

### Temperature = 0.1

Low temperature is intentional. We want deterministic, accurate SQL — not creative variation.

---

## Guardrails

Three-layer defense against off-topic queries:

### Layer 1: Prompt Injection Detection (hard block)
Regex patterns catching: `ignore previous instructions`, `jailbreak`, `act as`, `you are now`, `DAN mode`, etc.

### Layer 2: Absolute Block Signals (hard block regardless of domain overlap)
Patterns that definitively indicate non-ERP intent:
- Creative writing: `poem`, `haiku`, `write a story about...`
- General knowledge: `capital of`, `machine learning`, `who is Elon Musk`
- Media generation: `generate an image`, `translate this text`

### Layer 3: Domain Keyword Check (soft block)
Queries with zero ERP domain keywords (orders, billing, delivery, customer, plant, revenue, etc.) are blocked unless they contain a SAP-style document ID.

**Test results: 19/19 cases correctly classified** (see `guardrails.py` for full test suite).

**Example rejection response:**
```
⚠️ Out of scope. This system is designed to answer questions about the ERP 
dataset only — covering Sales Orders, Deliveries, Billing Documents, 
Journal Entries, Customers, Products, and Plants.
```

---

## Graph Model

### Nodes (7 types)

| Type | Color | Count | Key Attribute |
|---|---|---|---|
| `customer` | Indigo | 8 | `customer_id`, `fullName`, `city` |
| `billing` | Amber | 163 | `billingDocument`, `totalNetAmount` |
| `delivery` | Emerald | 86 | `deliveryDocument`, `goodsMovementStatus` |
| `sales_order` | Blue | 86 | `salesOrder` |
| `journal_entry` | Violet | 123 | `accountingDocument`, `amount` |
| `product` | Pink | 69 | `product_id`, `productDescription` |
| `plant` | Teal | 20 | `plant_id`, `plantName` |

### Edges (relationship types)

```
customer ──has_billing──► billing
billing ──includes_product──► product
billing ──billed_from_delivery──► delivery
sales_order ──fulfilled_by──► delivery
delivery ──ships_from──► plant
billing ──posted_to_journal──► journal_entry
customer ──customer_entry──► journal_entry
sales_order ──billed_as──► billing
```

### Key Design Decision: Sales Order as Bridge Node

The `referenceSdDocument` field in `delivery_items` links to a **Sales Order** number (not to another delivery). This is the critical SAP data model insight: the SO→Delivery→Billing chain is connected via document reference numbers, not foreign keys. The graph builder explicitly resolves this.

---

## Project Structure

```
dodge-ai-erp/
├── backend/
│   ├── main.py          — FastAPI app, routes
│   ├── db.py            — SQLite init, schema, query execution
│   ├── graph.py         — Graph construction from DB
│   ├── llm.py           — Gemini integration, NL→SQL pipeline
│   ├── guardrails.py    — 3-layer query validation
│   ├── data_loader.py   — Ingests raw JSONL folders → data/*.json
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── index.html       — Single-file React app (Cytoscape + chat)
│   ├── Dockerfile
│   └── nginx.conf
├── data/                — Processed JSON files (gitignored if large)
│   ├── billing_header.json
│   ├── delivery_header.json
│   └── ... (12 files)
├── raw_data/            — Paste your Google Drive folders here
│   ├── billing_document_headers/
│   ├── sales_order_headers/      ← paste when available
│   └── ...
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Setup & Running Locally

### Prerequisites
- Python 3.11+
- Node.js (optional — frontend is a single HTML file)
- Google Gemini API key (free at https://ai.google.dev)

### 1. Clone & Setup

```bash
git clone https://github.com/YOUR_USERNAME/dodge-ai-erp-graph.git
cd dodge-ai-erp-graph

cp .env.example .env
# Edit .env and set GEMINI_API_KEY=your_key_here
```

### 2. Add Data Files

**Option A — Use the uploaded JSONL parts (already processed):**
```bash
# The data/ folder is already populated from the uploaded files
```

**Option B — Add the full Google Drive dataset:**
```bash
mkdir raw_data
# Paste all 20 folders from Google Drive into raw_data/
# e.g. raw_data/sales_order_headers/, raw_data/billing_document_headers/, etc.

cd backend
python data_loader.py   # merges all parts → data/*.json
```

### 3. Run Backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

### 4. Run Frontend

```bash
# Simply open frontend/index.html in a browser
# OR serve it:
cd frontend
python -m http.server 3000
# Open http://localhost:3000
```

### 5. Docker (all-in-one)

```bash
docker-compose up --build
# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
```

---

## Adding the Missing Data Folders

When you download the full dataset from Google Drive, paste these folders into `raw_data/` and run `python backend/data_loader.py`:

| Folder | What it unlocks |
|---|---|
| `sales_order_headers/` | Full SO→Delivery→Billing→Journal trace |
| `sales_order_items/` | Per-line-item delivery and billing status |
| `sales_order_schedule_lines/` | Confirmed delivery dates vs requested |
| `billing_document_cancellations/` | Cancellation flow analysis |
| `payments_accounts_receivable/` | Actual payment matching |
| `product_plants/` | Stock availability per plant |
| `product_storage_locations/` | Storage-level inventory |

---

## Example Queries the System Can Answer

```
Which products are associated with the highest number of billing documents?
→ SQL: SELECT material, COUNT(*) FROM billing_items GROUP BY material ORDER BY 2 DESC

Trace the full flow of billing document 90504248
→ SQL: Multi-join across delivery_items → delivery_header → billing_items → 
       billing_header → journal_entries

Show all sales orders that have been delivered but not billed
→ SQL: LEFT JOIN delivery_items with billing_items on referenceSdDocument,
       HAVING COUNT(billingDocument) = 0

Which customer has the highest total revenue?
→ SQL: SUM(CAST(totalNetAmount AS REAL)) GROUP BY soldToParty

Show uncleared journal entries (outstanding receivables)
→ SQL: WHERE clearingDate IS NULL OR clearingDate = ''

Which deliveries are blocked?
→ SQL: WHERE deliveryBlockReason != '' OR headerBillingBlockReason != ''
```

---

## API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/api/graph` | GET | Full graph (nodes + edges) |
| `/api/graph/node/{type}/{id}` | GET | Neighbourhood of a node |
| `/api/chat` | POST | NL query → answer + SQL + data |
| `/api/chat/stream` | POST | Streaming version (SSE) |
| `/api/stats` | GET | Row counts per table |
| `/api/schema` | GET | Full DB schema |

---

## Technical Decisions Summary

| Decision | Choice | Rationale |
|---|---|---|
| Database | SQLite | Zero-dep, fits dataset, SQL joins efficient at this scale |
| Graph library | Cytoscape.js | Best-in-class for network graphs, handles 500+ nodes |
| LLM | Gemini 1.5 Flash | Free tier, 1M token context, fast, good at SQL gen |
| Backend | FastAPI | Async, auto-docs, minimal boilerplate |
| Frontend | Single HTML file | Zero build step, instantly deployable, fully self-contained |
| Graph storage | In-memory (built from SQL) | No separate graph DB needed at this scale |
| Streaming | SSE (Server-Sent Events) | Simple, works everywhere, no WebSocket setup |

---

## AI Coding Session Logs

See `ai_session_logs/` directory for:
- `claude_code_session.md` — Full Claude Code transcript
- `cursor_session.md` — Cursor composer history (if used)

These logs show prompt quality, debugging workflow, and iteration patterns.

---

## Author

Built for the Dodge AI Forward Deployed Engineer Assessment.