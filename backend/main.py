"""
Dodge AI ERP Graph Query System - Backend
FastAPI + SQLite + Gemini LLM
"""
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import json
import asyncio

from db import get_db_connection, init_db
from graph import build_graph_data
from llm import query_llm, stream_llm
from guardrails import is_allowed_query

app = FastAPI(title="Dodge AI ERP Graph System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    history: Optional[list] = []


class GraphFilterRequest(BaseModel):
    node_type: Optional[str] = None
    node_id: Optional[str] = None
    depth: Optional[int] = 2


@app.on_event("startup")
async def startup():
    init_db()
    print("✅ Database initialized")


@app.get("/health")
def health():
    return {"status": "ok", "service": "Dodge AI ERP Graph System"}


@app.get("/api/graph")
def get_full_graph():
    """Return the full graph structure for visualization"""
    return build_graph_data()


@app.get("/api/graph/node/{node_type}/{node_id}")
def get_node_neighbors(node_type: str, node_id: str, depth: int = 1):
    """Return neighbors of a specific node"""
    return build_graph_data(center_node_type=node_type, center_node_id=node_id, depth=depth)


@app.get("/api/stats")
def get_stats():
    """Return high-level dataset statistics"""
    conn = get_db_connection()
    cur = conn.cursor()
    stats = {}
    tables = ["delivery_header", "delivery_items", "billing_header",
              "billing_items", "journal_entries", "ar_items",
              "customers", "products", "plants"]
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        stats[t] = cur.fetchone()[0]
    conn.close()
    return stats


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """Main chat endpoint — NL → SQL → answer"""
    user_msg = req.message.strip()

    # Guardrail check
    allowed, reason = is_allowed_query(user_msg)
    if not allowed:
        return {
            "answer": reason,
            "sql": None,
            "data": None,
            "highlighted_nodes": [],
            "guardrail_triggered": True,
        }

    try:
        result = await query_llm(user_msg, req.history or [])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Streaming chat endpoint"""
    user_msg = req.message.strip()

    allowed, reason = is_allowed_query(user_msg)
    if not allowed:
        async def blocked():
            payload = json.dumps({
                "type": "guardrail",
                "content": reason,
                "done": True
            })
            yield f"data: {payload}\n\n"
        return StreamingResponse(blocked(), media_type="text/event-stream")

    async def generate():
        async for chunk in stream_llm(user_msg, req.history or []):
            yield f"data: {json.dumps(chunk)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/schema")
def get_schema():
    """Return DB schema for debugging"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    schema = {}
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        schema[t] = [{"name": r[1], "type": r[2]} for r in cur.fetchall()]
    conn.close()
    return schema


@app.get("/api/insights")
def get_insights():
    """Pre-computed business insights for the dashboard"""
    from db import execute_query

    queries = {
        "top_products_by_billing": """
            SELECT bi.material as product_id, p.productDescription as name,
                   COUNT(DISTINCT bi.billingDocument) as billing_count,
                   SUM(CAST(bi.netAmount AS REAL)) as total_revenue
            FROM billing_items bi
            LEFT JOIN products p ON p.product = bi.material
            GROUP BY bi.material
            ORDER BY billing_count DESC
            LIMIT 10
        """,
        "top_customers_by_revenue": """
            SELECT bh.soldToParty as customer_id, c.fullName as name,
                   COUNT(DISTINCT bh.billingDocument) as invoice_count,
                   SUM(CAST(bh.totalNetAmount AS REAL)) as total_revenue
            FROM billing_header bh
            LEFT JOIN customers c ON c.customer = bh.soldToParty
            GROUP BY bh.soldToParty
            ORDER BY total_revenue DESC
            LIMIT 10
        """,
        "broken_flows": """
            SELECT dh.deliveryDocument,
                   dh.overallGoodsMovementStatus as goods_status,
                   dh.overallPickingStatus as pick_status,
                   dh.creationDate,
                   COUNT(bi.billingDocument) as billing_count
            FROM delivery_header dh
            LEFT JOIN delivery_items di ON di.deliveryDocument = dh.deliveryDocument
            LEFT JOIN billing_items bi ON bi.referenceSdDocument = dh.deliveryDocument
            GROUP BY dh.deliveryDocument
            HAVING billing_count = 0
            ORDER BY dh.creationDate DESC
            LIMIT 20
        """,
        "cancelled_billings": """
            SELECT COUNT(*) as total_cancelled,
                   SUM(CAST(totalNetAmount AS REAL)) as cancelled_value
            FROM billing_header
            WHERE billingDocumentIsCancelled = 1
        """,
        "uncleared_receivables": """
            SELECT COUNT(*) as uncleared_count,
                   SUM(CAST(amountInTransactionCurrency AS REAL)) as uncleared_amount
            FROM journal_entries
            WHERE (clearingDate IS NULL OR clearingDate = \'\')
              AND financialAccountType = \'D\'
        """,
        "billing_by_type": """
            SELECT billingDocumentType, COUNT(*) as count,
                   SUM(CAST(totalNetAmount AS REAL)) as total_value
            FROM billing_header
            WHERE billingDocumentIsCancelled = 0
            GROUP BY billingDocumentType
            ORDER BY count DESC
        """,
        "monthly_revenue": """
            SELECT SUBSTR(billingDocumentDate, 1, 7) as month,
                   COUNT(*) as invoice_count,
                   SUM(CAST(totalNetAmount AS REAL)) as revenue
            FROM billing_header
            WHERE billingDocumentIsCancelled = 0
              AND billingDocumentDate IS NOT NULL
            GROUP BY month
            ORDER BY month
        """,
        "plants_by_delivery_count": """
            SELECT di.plant, p.plantName, COUNT(DISTINCT di.deliveryDocument) as delivery_count
            FROM delivery_items di
            LEFT JOIN plants p ON p.plant = di.plant
            GROUP BY di.plant
            ORDER BY delivery_count DESC
            LIMIT 10
        """,
    }

    result = {}
    for key, sql in queries.items():
        rows, err = execute_query(sql)
        result[key] = rows if not err else []

    return result
