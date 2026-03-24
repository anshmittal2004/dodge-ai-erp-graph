"""
Graph construction module
Builds nodes + edges from the ERP SQLite database
"""

from db import execute_query, get_db_connection
from typing import Optional


NODE_COLORS = {
    "customer":        "#6366f1",  # indigo
    "delivery":        "#10b981",  # emerald
    "billing":         "#f59e0b",  # amber
    "journal_entry":   "#8b5cf6",  # violet
    "product":         "#ec4899",  # pink
    "plant":           "#14b8a6",  # teal
    "sales_order":     "#3b82f6",  # blue
    "ar_item":         "#ef4444",  # red
}


def build_graph_data(center_node_type: Optional[str] = None,
                     center_node_id: Optional[str] = None,
                     depth: int = 1):
    """Build full or neighbourhood graph"""
    nodes = {}
    edges = []
    edge_set = set()

    def add_node(node_id, node_type, label, data=None):
        if node_id not in nodes:
            nodes[node_id] = {
                "id": node_id,
                "type": node_type,
                "label": label,
                "color": NODE_COLORS.get(node_type, "#94a3b8"),
                "data": data or {},
                "size": _node_size(node_type),
            }

    def add_edge(src, tgt, label, edge_type="default"):
        key = f"{src}→{tgt}→{label}"
        if key not in edge_set and src in nodes and tgt in nodes:
            edge_set.add(key)
            edges.append({
                "id": key,
                "source": src,
                "target": tgt,
                "label": label,
                "type": edge_type,
            })

    conn = get_db_connection()
    cur = conn.cursor()

    # ── CUSTOMERS ──────────────────────────────────────────────────────────
    cur.execute("SELECT * FROM customers")
    for c in cur.fetchall():
        cid = f"cust_{c['customer']}"
        add_node(cid, "customer", c["fullName"] or c["customer"], {
            "customer_id": c["customer"],
            "city": c["city"],
            "country": c["country"],
            "currency": c["currency"],
            "paymentTerms": c["paymentTerms"],
        })

    # ── PRODUCTS ────────────────────────────────────────────────────────────
    cur.execute("SELECT * FROM products")
    for p in cur.fetchall():
        pid = f"prod_{p['product']}"
        add_node(pid, "product", p["productDescription"] or p["product"], {
            "product_id": p["product"],
            "description": p["productDescription"],
        })

    # ── PLANTS ──────────────────────────────────────────────────────────────
    cur.execute("SELECT * FROM plants LIMIT 20")
    for p in cur.fetchall():
        plid = f"plant_{p['plant']}"
        add_node(plid, "plant", p["plantName"] or p["plant"], {
            "plant_id": p["plant"],
            "salesOrg": p["salesOrganization"],
        })

    # ── BILLING HEADERS ─────────────────────────────────────────────────────
    cur.execute("""
        SELECT bh.*, c.fullName as customerName
        FROM billing_header bh
        LEFT JOIN customers c ON c.customer = bh.soldToParty
    """)
    for b in cur.fetchall():
        bid = f"billing_{b['billingDocument']}"
        add_node(bid, "billing", f"Billing {b['billingDocument']}", {
            "billingDocument": b["billingDocument"],
            "type": b["billingDocumentType"],
            "totalNetAmount": b["totalNetAmount"],
            "currency": b["transactionCurrency"],
            "date": b["billingDocumentDate"],
            "isCancelled": b["billingDocumentIsCancelled"],
            "soldToParty": b["soldToParty"],
            "customerName": b["customerName"],
            "accountingDocument": b["accountingDocument"],
        })
        # billing → customer edge
        cid = f"cust_{b['soldToParty']}"
        if cid in nodes:
            add_edge(cid, bid, "has_billing", "has_billing")

    # ── BILLING ITEMS (→ products, → deliveries via referenceSdDocument) ───
    cur.execute("SELECT * FROM billing_items")
    for bi in cur.fetchall():
        bid = f"billing_{bi['billingDocument']}"
        pid = f"prod_{bi['material']}"
        if bid in nodes and pid in nodes:
            add_edge(bid, pid, "includes_product", "includes_product")

        # billing item references delivery document
        ref_del = f"delivery_{bi['referenceSdDocument']}"
        if ref_del in nodes:
            add_edge(bid, ref_del, "billed_from_delivery", "billed_from_delivery")

    # ── DELIVERY HEADERS ────────────────────────────────────────────────────
    cur.execute("SELECT * FROM delivery_header")
    for d in cur.fetchall():
        did = f"delivery_{d['deliveryDocument']}"
        status = "✅" if d["overallGoodsMovementStatus"] == "C" else "🔄"
        add_node(did, "delivery", f"Delivery {d['deliveryDocument']} {status}", {
            "deliveryDocument": d["deliveryDocument"],
            "goodsMovementStatus": d["overallGoodsMovementStatus"],
            "pickingStatus": d["overallPickingStatus"],
            "shippingPoint": d["shippingPoint"],
            "creationDate": d["creationDate"],
            "blockReason": d["deliveryBlockReason"],
        })

    # ── DELIVERY ITEMS (→ sales orders, → plants, → products) ──────────────
    cur.execute("SELECT * FROM delivery_items")
    for di in cur.fetchall():
        did = f"delivery_{di['deliveryDocument']}"
        # delivery → sales order (referenceSdDocument = sales order)
        so_id = di["referenceSdDocument"]
        if so_id:
            soid = f"so_{so_id}"
            add_node(soid, "sales_order", f"SO {so_id}", {
                "salesOrder": so_id,
            })
            add_edge(soid, did, "fulfilled_by", "fulfilled_by")

        # delivery → plant
        plid = f"plant_{di['plant']}"
        if plid in nodes and did in nodes:
            add_edge(did, plid, "ships_from", "ships_from")

    # billing items → sales order (link via referenceSdDocument)
    cur.execute("SELECT DISTINCT referenceSdDocument, billingDocument FROM billing_items WHERE referenceSdDocument IS NOT NULL")
    for bi in cur.fetchall():
        bid = f"billing_{bi['billingDocument']}"
        soid = f"so_{bi['referenceSdDocument']}"
        if bid in nodes and soid in nodes:
            add_edge(soid, bid, "billed_as", "billed_as")

    # ── JOURNAL ENTRIES ─────────────────────────────────────────────────────
    cur.execute("""
        SELECT DISTINCT accountingDocument, referenceDocument, postingDate,
               amountInTransactionCurrency, transactionCurrency, companyCode,
               fiscalYear, accountingDocumentType, customer
        FROM journal_entries
    """)
    for j in cur.fetchall():
        jid = f"je_{j['accountingDocument']}"
        add_node(jid, "journal_entry", f"JE {j['accountingDocument']}", {
            "accountingDocument": j["accountingDocument"],
            "referenceDocument": j["referenceDocument"],
            "postingDate": j["postingDate"],
            "amount": j["amountInTransactionCurrency"],
            "currency": j["transactionCurrency"],
            "type": j["accountingDocumentType"],
        })
        # billing → journal entry (billing header links via accountingDocument)
        bid = f"billing_{j['referenceDocument']}"
        if bid in nodes:
            add_edge(bid, jid, "posted_to_journal", "posted_to_journal")

        # customer → journal entry
        if j["customer"]:
            cid = f"cust_{j['customer']}"
            if cid in nodes:
                add_edge(cid, jid, "customer_entry", "customer_entry")

    conn.close()

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_types": _count_by_type(nodes),
        }
    }


def _node_size(node_type: str) -> int:
    sizes = {
        "customer": 30,
        "billing": 20,
        "delivery": 20,
        "journal_entry": 16,
        "product": 18,
        "plant": 18,
        "sales_order": 22,
        "ar_item": 14,
    }
    return sizes.get(node_type, 16)


def _count_by_type(nodes: dict) -> dict:
    counts = {}
    for n in nodes.values():
        t = n["type"]
        counts[t] = counts.get(t, 0) + 1
    return counts
