"""
LLM module — Multi-provider NL→SQL pipeline
Primary:  Google Gemini 1.5 Flash (free tier)
Fallback: Groq llama-3.1-70b (free tier)
Strategy: NL → SQL → Execute → NL Answer (grounded in real data)
"""

import os
import json
import re
import httpx
import asyncio
import sqlite3
from typing import AsyncGenerator

from db import execute_query, DB_PATH

# Provider config
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY    = os.environ.get("GROQ_API_KEY", "")
OPENROUTER_KEY  = os.environ.get("OPENROUTER_API_KEY", "")

GEMINI_URL      = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GROQ_URL        = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL  = "https://openrouter.ai/api/v1/chat/completions"

def _active_provider() -> str:
    if GEMINI_API_KEY:    return "gemini"
    if GROQ_API_KEY:      return "groq"
    if OPENROUTER_KEY:    return "openrouter"
    return "offline"

def _get_optional_tables_schema() -> str:
    """Dynamically add schema for optional tables that exist in the DB."""
    extra = ""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        conn.close()
        if "sales_order_headers" in tables:
            extra += """
TABLE: sales_order_headers
  salesOrder TEXT (PK) — sales order number
  salesOrderType TEXT — e.g. 'OR' = standard order
  soldToParty TEXT — FK to customers.customer
  totalNetAmount TEXT — CAST AS REAL for math
  overallDeliveryStatus TEXT — A=not started B=partial C=complete
  overallBillingStatus TEXT  — A=not started B=partial C=complete
  creationDate TEXT, requestedDeliveryDate TEXT
"""
        if "payments" in tables:
            extra += """
TABLE: payments
  companyCode TEXT, fiscalYear TEXT, accountingDocument TEXT, accountingDocumentItem TEXT (PK composite)
  customer TEXT — FK to customers.customer
  amountInTransactionCurrency TEXT — CAST AS REAL
  transactionCurrency TEXT, postingDate TEXT, clearingDate TEXT
"""
        if "billing_cancellations" in tables:
            extra += """
TABLE: billing_cancellations
  billingDocument TEXT (PK), cancelledBillingDocument TEXT
  cancellationDate TEXT, soldToParty TEXT, totalNetAmount TEXT
"""
    except Exception:
        pass
    return extra

DB_SCHEMA = """
You have access to a SQLite database with the following tables representing an SAP ERP system:

TABLE: customers
  customer TEXT (PK) — customer ID
  fullName TEXT — company/person name
  city TEXT, country TEXT, region TEXT, postalCode TEXT, street TEXT
  paymentTerms TEXT, reconciliationAccount TEXT
  currency TEXT, salesOrganization TEXT, distributionChannel TEXT
  incotermsClassification TEXT

TABLE: products
  product TEXT (PK) — material/product ID
  productDescription TEXT — human-readable name
  language TEXT

TABLE: plants
  plant TEXT (PK) — plant/warehouse ID
  plantName TEXT — human-readable name
  salesOrganization TEXT, distributionChannel TEXT, division TEXT

TABLE: delivery_header
  deliveryDocument TEXT (PK) — outbound delivery ID
  creationDate TEXT, shippingPoint TEXT
  overallGoodsMovementStatus TEXT — 'A'=not started, 'B'=partial, 'C'=complete
  overallPickingStatus TEXT — 'A'=not started, 'B'=partial, 'C'=complete
  deliveryBlockReason TEXT — empty string means not blocked
  headerBillingBlockReason TEXT — empty string means not blocked
  actualGoodsMovementDate TEXT — null if not yet goods-moved

TABLE: delivery_items
  deliveryDocument TEXT, deliveryDocumentItem TEXT (PK composite)
  referenceSdDocument TEXT — links to sales order number
  referenceSdDocumentItem TEXT — sales order line item
  plant TEXT — FK to plants
  storageLocation TEXT
  actualDeliveryQuantity TEXT, deliveryQuantityUnit TEXT
  itemBillingBlockReason TEXT

TABLE: billing_header
  billingDocument TEXT (PK) — invoice/billing doc number
  billingDocumentType TEXT — e.g. 'F2' = invoice, 'S1' = cancellation
  creationDate TEXT, billingDocumentDate TEXT
  billingDocumentIsCancelled INTEGER — 1=yes, 0=no
  cancelledBillingDocument TEXT — references original doc if this is cancellation
  totalNetAmount TEXT — amount as string, cast with CAST(totalNetAmount AS REAL)
  transactionCurrency TEXT
  companyCode TEXT, fiscalYear TEXT
  accountingDocument TEXT — FK to journal_entries.accountingDocument
  soldToParty TEXT — FK to customers.customer

TABLE: billing_items
  billingDocument TEXT, billingDocumentItem TEXT (PK composite)
  material TEXT — FK to products.product
  billingQuantity TEXT, billingQuantityUnit TEXT
  netAmount TEXT — item-level amount
  transactionCurrency TEXT
  referenceSdDocument TEXT — links to delivery document (outbound delivery)
  referenceSdDocumentItem TEXT

TABLE: journal_entries
  companyCode TEXT, fiscalYear TEXT, accountingDocument TEXT, accountingDocumentItem TEXT (PK composite)
  glAccount TEXT — general ledger account
  referenceDocument TEXT — links to billing document number
  costCenter TEXT, profitCenter TEXT
  transactionCurrency TEXT
  amountInTransactionCurrency TEXT
  companyCodeCurrency TEXT, amountInCompanyCodeCurrency TEXT
  postingDate TEXT, documentDate TEXT
  accountingDocumentType TEXT — 'RV'=revenue, 'DZ'=payment
  assignmentReference TEXT
  customer TEXT — FK to customers.customer
  financialAccountType TEXT
  clearingDate TEXT — null if not yet cleared (payment pending)
  clearingAccountingDocument TEXT

TABLE: ar_items
  companyCode TEXT, fiscalYear TEXT, accountingDocument TEXT, accountingDocumentItem TEXT (PK composite)
  clearingDate TEXT — null/empty = not yet paid
  clearingAccountingDocument TEXT
  amountInTransactionCurrency TEXT, transactionCurrency TEXT
  amountInCompanyCodeCurrency TEXT, companyCodeCurrency TEXT
  customer TEXT — FK to customers.customer
  invoiceReference TEXT
  salesDocument TEXT — FK to sales order
  salesDocumentItem TEXT
  postingDate TEXT, documentDate TEXT
  glAccount TEXT, financialAccountType TEXT, profitCenter TEXT

KEY BUSINESS RELATIONSHIPS:
- Sales Order → Delivery: delivery_items.referenceSdDocument = sales order number
- Delivery → Billing: billing_items.referenceSdDocument = delivery_header.deliveryDocument
- Billing → Journal Entry: billing_header.accountingDocument = journal_entries.accountingDocument
  AND journal_entries.referenceDocument = billing_header.billingDocument
- Billing → Customer: billing_header.soldToParty = customers.customer
- Billing Item → Product: billing_items.material = products.product
- Delivery Item → Plant: delivery_items.plant = plants.plant
"""

def _build_system_prompt() -> str:
    optional = _get_optional_tables_schema()
    return f"""You are an ERP data analyst AI for a SAP system. You help users query and understand business data.

{DB_SCHEMA}{optional}

INSTRUCTIONS:
1. When the user asks a question, generate a SQLite SQL query to answer it.
2. Return your response as valid JSON with this exact structure:
{{
  "thought": "brief reasoning about the query",
  "sql": "SELECT ... (valid SQLite SQL)",
  "explanation": "plain English explanation of what the query does",
  "highlighted_node_ids": ["billing_90504248", "cust_320000083"]
}}

3. For highlighted_node_ids, prefix with entity type:
   - customers → "cust_{{customer_id}}"
   - billing → "billing_{{billingDocument}}"
   - delivery → "delivery_{{deliveryDocument}}"
   - products → "prod_{{product_id}}"
   - plants → "plant_{{plant_id}}"
   - sales orders → "so_{{salesOrder}}"
   - journal entries → "je_{{accountingDocument}}"

4. Always use CAST(col AS REAL) when doing math on amount/quantity columns.
5. Limit results to at most 50 rows unless asked for more.
6. For "broken flows" queries: a broken flow means a delivery that has no corresponding billing, or a billing without a journal entry.
7. Always write valid SQLite syntax (no TOP, use LIMIT instead).
8. Do NOT include markdown code fences in your SQL.
9. Return ONLY valid JSON, no preamble text.
"""

SYSTEM_PROMPT = _build_system_prompt()


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown fences"""
    text = text.strip()
    # Remove markdown code blocks
    text = re.sub(r"```(?:json)?", "", text).strip()
    text = re.sub(r"```", "", text).strip()
    # Find first { ... }
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON found in LLM response: {text[:200]}")


def _build_answer(question: str, sql: str, rows, explanation: str) -> str:
    """Format a human-readable answer from query results"""
    if not rows:
        return f"No data found for your query. {explanation}"

    count = len(rows)
    cols = list(rows[0].keys()) if rows else []

    # Build a concise text summary
    lines = [f"**{explanation}**\n"]

    if count == 1:
        row = rows[0]
        parts = [f"**{k}**: {v}" for k, v in row.items() if v is not None and v != ""]
        lines.append(" | ".join(parts))
    else:
        lines.append(f"Found **{count} result(s)**:\n")
        for i, row in enumerate(rows[:20], 1):
            parts = []
            for k, v in row.items():
                if v is not None and v != "":
                    if isinstance(v, float):
                        parts.append(f"{k}: {v:,.2f}")
                    else:
                        parts.append(f"{k}: {v}")
            lines.append(f"{i}. " + " | ".join(parts))
        if count > 20:
            lines.append(f"\n*...and {count - 20} more results.*")

    return "\n".join(lines)


async def _call_openai_compat(messages_openai: list, url: str, api_key: str, model: str) -> str:
    """Call any OpenAI-compatible endpoint (Groq, OpenRouter)."""
    payload = {
        "model": model,
        "messages": messages_openai,
        "temperature": 0.1,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


async def _call_gemini(messages_gemini: list, system: str) -> str:
    """Call Gemini API."""
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": messages_gemini,
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
    }
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=payload
        )
        resp.raise_for_status()
        data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def _call_llm(question: str, history: list) -> str:
    """Route to available LLM provider."""
    provider = _active_provider()
    sys_prompt = SYSTEM_PROMPT

    # Build OpenAI-format messages (works for Groq + OpenRouter)
    openai_msgs = [{"role": "system", "content": sys_prompt}]
    for h in history[-6:]:
        openai_msgs.append({"role": h["role"], "content": h.get("content", "")})
    openai_msgs.append({"role": "user", "content": question})

    # Build Gemini-format messages
    gemini_msgs = []
    for h in history[-6:]:
        role = "model" if h["role"] == "assistant" else "user"
        gemini_msgs.append({"role": role, "parts": [{"text": h.get("content", "")}]})
    gemini_msgs.append({"role": "user", "parts": [{"text": question}]})

    if provider == "gemini":
        return await _call_gemini(gemini_msgs, sys_prompt)
    elif provider == "groq":
        return await _call_openai_compat(
            openai_msgs, GROQ_URL, GROQ_API_KEY,
            "llama-3.3-70b-versatile"
        )
    elif provider == "openrouter":
        return await _call_openai_compat(
            openai_msgs, OPENROUTER_URL, OPENROUTER_KEY,
            "google/gemini-flash-1.5"
        )
    raise RuntimeError("No LLM provider configured")


async def query_llm(question: str, history: list) -> dict:
    """Main NL→SQL→Execute→Answer pipeline"""
    if _active_provider() == "offline":
        return _fallback_response(question)

    try:
        raw_text = await _call_llm(question, history)
    except Exception as e:
        return {
            "answer": f"LLM call failed: {e}",
            "sql": None, "data": None, "highlighted_nodes": [], "error": str(e),
        }

    try:
        parsed = _extract_json(raw_text)
    except Exception as e:
        return {
            "answer": f"I couldn't parse the LLM response: {e}\n\nRaw: {raw_text[:300]}",
            "sql": None, "data": None, "highlighted_nodes": [],
            "error": str(e),
        }

    sql = parsed.get("sql", "").strip()
    explanation = parsed.get("explanation", "")
    thought = parsed.get("thought", "")
    highlighted = parsed.get("highlighted_node_ids", [])

    if not sql:
        return {
            "answer": explanation or "I couldn't generate a query for that question.",
            "sql": None, "data": None, "highlighted_nodes": [],
        }

    # Execute the SQL
    rows, error = execute_query(sql)

    if error:
        # Try to self-heal: ask LLM to fix
        fix_msg = f"The SQL returned an error: {error}. The SQL was: {sql}. Please fix it and return corrected JSON."
        messages.append({"role": "model", "parts": [{"text": raw_text}]})
        messages.append({"role": "user", "parts": [{"text": fix_msg}]})
        payload["contents"] = messages

        async with httpx.AsyncClient(timeout=30) as client:
            resp2 = await client.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}",
                json=payload,
            )
            resp2.raise_for_status()
            data2 = resp2.json()

        raw_text2 = data2["candidates"][0]["content"]["parts"][0]["text"]
        try:
            parsed2 = _extract_json(raw_text2)
            sql = parsed2.get("sql", sql)
            explanation = parsed2.get("explanation", explanation)
            highlighted = parsed2.get("highlighted_node_ids", highlighted)
            rows, error = execute_query(sql)
        except Exception:
            pass

    if error:
        return {
            "answer": f"Query error: {error}",
            "sql": sql, "data": None, "highlighted_nodes": [],
            "error": error,
        }

    answer = _build_answer(question, sql, rows, explanation)

    return {
        "answer": answer,
        "sql": sql,
        "thought": thought,
        "data": rows[:50] if rows else [],
        "row_count": len(rows) if rows else 0,
        "highlighted_nodes": highlighted,
        "guardrail_triggered": False,
    }


async def stream_llm(question: str, history: list) -> AsyncGenerator[dict, None]:
    """Streaming version — yields chunks"""
    result = await query_llm(question, history)

    # Simulate streaming by chunking the answer
    answer = result.get("answer", "")
    words = answer.split(" ")
    chunk_size = 5

    # First, yield the SQL and metadata immediately
    yield {
        "type": "metadata",
        "sql": result.get("sql"),
        "thought": result.get("thought"),
        "highlighted_nodes": result.get("highlighted_nodes", []),
        "row_count": result.get("row_count", 0),
        "data": result.get("data", []),
    }

    # Then stream the answer text
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i:i + chunk_size])
        if i + chunk_size < len(words):
            chunk += " "
        yield {"type": "text", "content": chunk, "done": False}
        await asyncio.sleep(0.03)

    yield {"type": "text", "content": "", "done": True}


def _fallback_response(question: str) -> dict:
    """Fallback when no API key — try to answer common questions with direct SQL"""
    q = question.lower()

    if "broken" in q or "incomplete" in q:
        sql = """
            SELECT dh.deliveryDocument, dh.overallGoodsMovementStatus,
                   dh.overallPickingStatus, dh.creationDate,
                   COUNT(bi.billingDocument) as billingCount
            FROM delivery_header dh
            LEFT JOIN delivery_items di ON di.deliveryDocument = dh.deliveryDocument
            LEFT JOIN billing_items bi ON bi.referenceSdDocument = dh.deliveryDocument
            GROUP BY dh.deliveryDocument
            HAVING billingCount = 0
            LIMIT 20
        """
        rows, _ = execute_query(sql)
        return {
            "answer": f"Found **{len(rows)} deliveries with no billing documents** (broken flow):\n\n" +
                      "\n".join([f"- Delivery {r['deliveryDocument']} | Status: {r['overallGoodsMovementStatus']} | Created: {r['creationDate']}" for r in rows[:10]]),
            "sql": sql,
            "data": rows,
            "highlighted_nodes": [f"delivery_{r['deliveryDocument']}" for r in rows[:10]],
            "guardrail_triggered": False,
            "note": "Running in offline mode (no API key set). Set GEMINI_API_KEY for full NL capabilities.",
        }

    # Default fallback
    sql = "SELECT COUNT(*) as total_billing FROM billing_header"
    rows, _ = execute_query(sql)
    return {
        "answer": "⚠️ **No GEMINI_API_KEY configured.** Set the environment variable to enable natural language queries.\n\n"
                  f"Dataset loaded: {rows[0]['total_billing'] if rows else '?'} billing documents available.",
        "sql": sql,
        "data": rows,
        "highlighted_nodes": [],
        "guardrail_triggered": False,
    }