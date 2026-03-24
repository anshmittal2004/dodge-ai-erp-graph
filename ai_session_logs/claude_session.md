# Claude AI Coding Session Log
**Tool:** Claude (claude.ai / API)  
**Task:** Dodge AI FDE Assessment — ERP Graph Intelligence System  
**Date:** March 2026

---

## Session Overview

This log documents the AI-assisted development session for the ERP Graph Query System. The session covered dataset analysis, architecture design, full backend + frontend implementation, and iterative debugging.

---

## Prompt 1 — Dataset Exploration

**User prompt:**
> "Analyze the uploaded JSONL files and tell me what tables/entities we have"

**Claude's approach:**
- Listed all 20 files with sizes
- Ran `head -1` on each file, parsed keys to identify entity types
- Grouped files by schema similarity (delivery items split across 2 files, billing header across 3, etc.)
- Identified key join fields: `referenceSdDocument`, `accountingDocument`, `soldToParty`

**Key insight surfaced:**
> "The `referenceSdDocument` in `delivery_items` links to a Sales Order number — not to another delivery. This is the critical SAP chain: SO → Delivery → Billing → Journal"

---

## Prompt 2 — Architecture Decision

**User prompt:**
> "Design the architecture for this system"

**Claude's reasoning:**
```
Q: Graph DB (Neo4j) or Relational (SQLite/Postgres)?
A: SQLite — dataset is ~1000 rows, SQL joins are faster than graph 
   traversal at this scale, zero deployment overhead, ships with Python.
   The "graph" is a VIEW of relational data, not a storage primitive.

Q: Which LLM provider?
A: Gemini 1.5 Flash — free tier, 1M token context window (fits full 
   schema + conversation history), good SQL generation quality.

Q: React SPA or single HTML file?
A: Single HTML file — zero build step, instantly deployable, judges 
   can open it directly. React + Babel in-browser for interactivity.

Q: Graph visualization library?
A: Cytoscape.js — handles 500+ nodes, force-directed layout, 
   click events, programmatic highlighting. D3 would require more 
   custom code for the same result.
```

---

## Prompt 3 — DB Schema Design

**User prompt:**
> "Build the SQLite schema and data loader"

**Iteration 1:** Basic schema, flat columns
**Issue found:** Numeric columns stored as strings in source (SAP exports `"533.05"` not `533.05`)
**Fix:** Added `CAST(col AS REAL)` guidance in LLM system prompt + documented in schema comments

**Iteration 2:** Added compound primary keys for item-level tables
**Issue found:** Duplicate rows when merging multiple JSONL part files
**Fix:** Used `INSERT OR REPLACE` consistently

**Key data model decision:**
```sql
-- delivery_items.referenceSdDocument → links to SALES ORDER (not another delivery)
-- billing_items.referenceSdDocument  → links to DELIVERY DOCUMENT
-- This asymmetry is the core SAP document chain
```

---

## Prompt 4 — Graph Builder

**User prompt:**
> "Build the graph construction module"

**Design decisions:**
- Nodes: one per unique business entity with color-coded type
- Edges: derived from FK relationships at graph-build time
- Node IDs prefixed with type: `billing_90504248`, `cust_320000083` (enables direct UI highlight from chat)
- Size variation by node type: customer (30px) > billing/sales_order (20px) > journal_entry (14px)

**Performance consideration:**
```python
# Edge deduplication via set — prevents duplicate edges from multiple billing items
# pointing to the same delivery document
edge_set = set()
key = f"{src}→{tgt}→{label}"
if key not in edge_set:
    edge_set.add(key)
    edges.append(...)
```

---

## Prompt 5 — LLM Pipeline

**User prompt:**
> "Build the NL → SQL → Answer pipeline with Gemini"

**Prompting strategy iteration:**

**v1 prompt:** "Convert this to SQL"  
**Problem:** LLM didn't know column names, kept hallucinating table structures

**v2 prompt:** Added full schema  
**Problem:** LLM used `TOP N` syntax (SQL Server) instead of `LIMIT N` (SQLite)

**v3 prompt (final):** Added:
- Column-level semantics (what each value means, e.g. status codes)
- Explicit FK relationship documentation  
- SQLite-specific rules (LIMIT, CAST, no window functions in old versions)
- Output format as strict JSON with `highlighted_node_ids` field
- Temperature = 0.1 for deterministic SQL

**Self-heal loop:**
```python
# If SQL execution fails, append error + original SQL to conversation
# and ask LLM to fix — handles ~10% of edge cases automatically
```

---

## Prompt 6 — Guardrails

**User prompt:**
> "Build guardrails that block off-topic queries"

**Iteration 1:** Simple keyword blocklist
**Problem:** "What is machine learning?" slipped through because "what" was in domain keywords

**Iteration 2:** Pattern matching with domain keyword override
**Problem:** "Write me a poem about SAP" passed because "SAP" is a domain keyword

**Root cause analysis:**
```
The bug: domain keywords included generic words like "which", "show", "find"
and also brand names like "SAP" that appear in off-topic sentences.

Fix: Two separate lists:
  ABSOLUTE_BLOCK_SIGNALS — fire regardless of domain word presence
  OFF_TOPIC_SIGNALS       — fire only when no domain words present
```

**Final test results: 19/19 cases correctly classified**

---

## Prompt 7 — Frontend

**User prompt:**
> "Build the complete frontend with graph visualization and chat"

**Design choices:**
- Dark theme (`#080c12` base) — appropriate for a data ops tool
- JetBrains Mono for data/code elements, Syne for UI labels
- CSS custom properties throughout for consistency
- Node type filter buttons — lets user focus on one entity type
- SQL accordion in chat — shows the generated query (transparency)
- Raw data table in chat — shows the actual rows returned
- Node inspector panel — click any node to see its metadata
- Highlighted nodes from chat scroll the graph to show them
- Suggestion chips for common queries (reduces friction)

**Cytoscape.js configuration decisions:**
```javascript
// cose layout (compound spring embedder) — best for business entity graphs
// Force parameters tuned for this dataset size:
nodeRepulsion: 450000  // spread nodes apart
idealEdgeLength: 80    // tight enough to see relationships
animate: false          // faster initial render at 500+ nodes
```

---

## Debugging Log

### Bug 1: Graph edges referencing non-existent nodes
```
Symptom: edges array had source/target IDs not in nodes dict
Root cause: billing_items references delivery docs that aren't in delivery_header
Fix: add_edge() checks both src and tgt exist in nodes dict before adding
```

### Bug 2: SQLite "no such table: sales_order_headers"
```
Symptom: certain queries fail when optional tables don't exist
Root cause: LLM generates SQL referencing tables that are optional
Fix: schema prompt only mentions tables that actually exist
     Added check in db.py: only create optional tables if JSON file present
```

### Bug 3: CAST errors on numeric strings
```
Symptom: SUM(totalNetAmount) returns null
Root cause: column stored as TEXT "533.05" not REAL 533.05
Fix: documented in system prompt: "Always CAST(col AS REAL) for amount/quantity columns"
```

### Bug 4: Guardrail regex — "Write me a poem" passing
```
Symptom: pattern r"\b(poem|...)\b" not matching "Write me a poem about SAP"
Root cause: "SAP" in DOMAIN_KEYWORDS, domain_hit_count = 1, blocking condition not met
Fix: Added ABSOLUTE_BLOCK_SIGNALS list that fires regardless of domain keyword presence
Final: 19/19 test cases pass
```

---

## What I Would Do Next (With More Time)

1. **Semantic search layer** — embed entity descriptions with sentence-transformers, enable fuzzy product name matching
2. **Graph clustering** — use community detection (Louvain) to auto-group related nodes
3. **Conversation memory** — store past queries in SQLite, reference them in follow-ups  
4. **Sales order data integration** — the full SO→Delivery→Billing→Journal chain becomes queryable
5. **Anomaly detection** — flag statistically unusual amounts, quantities, or document gaps
6. **Export** — let users download query results as CSV

---

## Token/Cost Summary

- LLM: Gemini 1.5 Flash (free tier, 15 RPM, 1M TPM)
- Estimated tokens per query: ~3,000 input + ~500 output = ~3,500 tokens
- Free tier limit: 1M tokens/day → ~285 queries/day on free tier
- Cost: $0

---

*Session log generated from Claude.ai conversation history*