"""
Database module — SQLite with all ERP entities loaded from JSON files
"""

import sqlite3
import json
import os
from pathlib import Path

DB_PATH = os.path.join(os.path.dirname(__file__), "erp.db")
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def load_json(name: str):
    path = os.path.join(DATA_DIR, f"{name}.json")
    with open(path) as f:
        return json.load(f)


def safe_str(val):
    if val is None:
        return None
    if isinstance(val, dict):
        return json.dumps(val)
    return str(val)


def init_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = get_db_connection()
    cur = conn.cursor()

    # ── CUSTOMERS ──────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer TEXT PRIMARY KEY,
            businessPartner TEXT,
            fullName TEXT,
            country TEXT,
            city TEXT,
            postalCode TEXT,
            street TEXT,
            region TEXT,
            paymentTerms TEXT,
            reconciliationAccount TEXT,
            currency TEXT,
            salesOrganization TEXT,
            distributionChannel TEXT,
            incotermsClassification TEXT,
            businessPartnerIsBlocked INTEGER DEFAULT 0,
            creationDate TEXT
        )
    """)

    customers = load_json("customers")
    addresses = {r["businessPartner"]: r for r in load_json("addresses")}
    cust_company = {r["customer"]: r for r in load_json("customer_company")}
    cust_sales_raw = load_json("customer_sales")
    cust_sales = {}
    for r in cust_sales_raw:
        cust_sales[r["customer"]] = r  # keep last

    for c in customers:
        cid = c["customer"]
        addr = addresses.get(cid, {})
        cc = cust_company.get(cid, {})
        cs = cust_sales.get(cid, {})
        cur.execute("""
            INSERT OR REPLACE INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            cid,
            c.get("businessPartner"),
            c.get("businessPartnerFullName") or c.get("businessPartnerName"),
            addr.get("country"),
            addr.get("cityName"),
            addr.get("postalCode"),
            addr.get("streetName"),
            addr.get("region"),
            cc.get("paymentTerms") or cs.get("customerPaymentTerms"),
            cc.get("reconciliationAccount"),
            cs.get("currency"),
            cs.get("salesOrganization"),
            cs.get("distributionChannel"),
            cs.get("incotermsClassification"),
            1 if c.get("businessPartnerIsBlocked") else 0,
            safe_str(c.get("creationDate")),
        ))

    # ── PRODUCTS ────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            product TEXT PRIMARY KEY,
            productDescription TEXT,
            language TEXT
        )
    """)
    seen_products = set()
    prod_file = "products" if os.path.exists(os.path.join(DATA_DIR, "products.json")) else "product_master"
    for p in load_json(prod_file):
        pid = p["product"]
        if pid not in seen_products:
            cur.execute("INSERT OR REPLACE INTO products VALUES (?,?,?)", (
                pid, p.get("productDescription"), p.get("language")
            ))
            seen_products.add(pid)

    # ── PLANTS ──────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS plants (
            plant TEXT PRIMARY KEY,
            plantName TEXT,
            salesOrganization TEXT,
            distributionChannel TEXT,
            division TEXT,
            country TEXT,
            language TEXT,
            isMarkedForArchiving INTEGER DEFAULT 0
        )
    """)
    for p in load_json("plants"):
        cur.execute("INSERT OR REPLACE INTO plants VALUES (?,?,?,?,?,?,?,?)", (
            p["plant"], p.get("plantName"), p.get("salesOrganization"),
            p.get("distributionChannel"), p.get("division"),
            None, p.get("language"),
            1 if p.get("isMarkedForArchiving") else 0
        ))

    # ── DELIVERY HEADER ─────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS delivery_header (
            deliveryDocument TEXT PRIMARY KEY,
            creationDate TEXT,
            shippingPoint TEXT,
            overallGoodsMovementStatus TEXT,
            overallPickingStatus TEXT,
            deliveryBlockReason TEXT,
            headerBillingBlockReason TEXT,
            actualGoodsMovementDate TEXT
        )
    """)
    for d in load_json("delivery_header"):
        cur.execute("INSERT OR REPLACE INTO delivery_header VALUES (?,?,?,?,?,?,?,?)", (
            d["deliveryDocument"],
            safe_str(d.get("creationDate")),
            d.get("shippingPoint"),
            d.get("overallGoodsMovementStatus"),
            d.get("overallPickingStatus"),
            d.get("deliveryBlockReason"),
            d.get("headerBillingBlockReason"),
            safe_str(d.get("actualGoodsMovementDate")),
        ))

    # ── DELIVERY ITEMS ──────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS delivery_items (
            deliveryDocument TEXT,
            deliveryDocumentItem TEXT,
            referenceSdDocument TEXT,
            referenceSdDocumentItem TEXT,
            plant TEXT,
            storageLocation TEXT,
            actualDeliveryQuantity TEXT,
            deliveryQuantityUnit TEXT,
            itemBillingBlockReason TEXT,
            PRIMARY KEY (deliveryDocument, deliveryDocumentItem)
        )
    """)
    for d in load_json("delivery_items"):
        cur.execute("INSERT OR REPLACE INTO delivery_items VALUES (?,?,?,?,?,?,?,?,?)", (
            d["deliveryDocument"], d["deliveryDocumentItem"],
            d.get("referenceSdDocument"), d.get("referenceSdDocumentItem"),
            d.get("plant"), d.get("storageLocation"),
            safe_str(d.get("actualDeliveryQuantity")),
            d.get("deliveryQuantityUnit"),
            d.get("itemBillingBlockReason"),
        ))

    # ── BILLING HEADER ──────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS billing_header (
            billingDocument TEXT PRIMARY KEY,
            billingDocumentType TEXT,
            creationDate TEXT,
            billingDocumentDate TEXT,
            billingDocumentIsCancelled INTEGER DEFAULT 0,
            cancelledBillingDocument TEXT,
            totalNetAmount TEXT,
            transactionCurrency TEXT,
            companyCode TEXT,
            fiscalYear TEXT,
            accountingDocument TEXT,
            soldToParty TEXT
        )
    """)
    for b in load_json("billing_header"):
        cur.execute("INSERT OR REPLACE INTO billing_header VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            b["billingDocument"], b.get("billingDocumentType"),
            safe_str(b.get("creationDate")), safe_str(b.get("billingDocumentDate")),
            1 if b.get("billingDocumentIsCancelled") else 0,
            b.get("cancelledBillingDocument"),
            safe_str(b.get("totalNetAmount")),
            b.get("transactionCurrency"), b.get("companyCode"),
            safe_str(b.get("fiscalYear")), b.get("accountingDocument"),
            safe_str(b.get("soldToParty")),
        ))

    # ── BILLING ITEMS ───────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS billing_items (
            billingDocument TEXT,
            billingDocumentItem TEXT,
            material TEXT,
            billingQuantity TEXT,
            billingQuantityUnit TEXT,
            netAmount TEXT,
            transactionCurrency TEXT,
            referenceSdDocument TEXT,
            referenceSdDocumentItem TEXT,
            PRIMARY KEY (billingDocument, billingDocumentItem)
        )
    """)
    for b in load_json("billing_items"):
        cur.execute("INSERT OR REPLACE INTO billing_items VALUES (?,?,?,?,?,?,?,?,?)", (
            b["billingDocument"], b["billingDocumentItem"],
            b.get("material"), safe_str(b.get("billingQuantity")),
            b.get("billingQuantityUnit"), safe_str(b.get("netAmount")),
            b.get("transactionCurrency"), b.get("referenceSdDocument"),
            b.get("referenceSdDocumentItem"),
        ))

    # ── JOURNAL ENTRIES ─────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS journal_entries (
            companyCode TEXT,
            fiscalYear TEXT,
            accountingDocument TEXT,
            accountingDocumentItem TEXT,
            glAccount TEXT,
            referenceDocument TEXT,
            costCenter TEXT,
            profitCenter TEXT,
            transactionCurrency TEXT,
            amountInTransactionCurrency TEXT,
            companyCodeCurrency TEXT,
            amountInCompanyCodeCurrency TEXT,
            postingDate TEXT,
            documentDate TEXT,
            accountingDocumentType TEXT,
            assignmentReference TEXT,
            customer TEXT,
            financialAccountType TEXT,
            clearingDate TEXT,
            clearingAccountingDocument TEXT,
            PRIMARY KEY (companyCode, fiscalYear, accountingDocument, accountingDocumentItem)
        )
    """)
    for j in load_json("journal_entries"):
        cur.execute("INSERT OR REPLACE INTO journal_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            j.get("companyCode"), safe_str(j.get("fiscalYear")),
            j.get("accountingDocument"), safe_str(j.get("accountingDocumentItem")),
            j.get("glAccount"), j.get("referenceDocument"),
            j.get("costCenter"), j.get("profitCenter"),
            j.get("transactionCurrency"), safe_str(j.get("amountInTransactionCurrency")),
            j.get("companyCodeCurrency"), safe_str(j.get("amountInCompanyCodeCurrency")),
            safe_str(j.get("postingDate")), safe_str(j.get("documentDate")),
            j.get("accountingDocumentType"), j.get("assignmentReference"),
            safe_str(j.get("customer")), j.get("financialAccountType"),
            safe_str(j.get("clearingDate")), j.get("clearingAccountingDocument"),
        ))

    # ── AR ITEMS ─────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ar_items (
            companyCode TEXT,
            fiscalYear TEXT,
            accountingDocument TEXT,
            accountingDocumentItem TEXT,
            clearingDate TEXT,
            clearingAccountingDocument TEXT,
            clearingDocFiscalYear TEXT,
            amountInTransactionCurrency TEXT,
            transactionCurrency TEXT,
            amountInCompanyCodeCurrency TEXT,
            companyCodeCurrency TEXT,
            customer TEXT,
            invoiceReference TEXT,
            salesDocument TEXT,
            salesDocumentItem TEXT,
            postingDate TEXT,
            documentDate TEXT,
            glAccount TEXT,
            financialAccountType TEXT,
            profitCenter TEXT,
            PRIMARY KEY (companyCode, fiscalYear, accountingDocument, accountingDocumentItem)
        )
    """)
    ar_file = "payments" if os.path.exists(os.path.join(DATA_DIR, "payments.json")) else "ar_items"
    for a in load_json(ar_file):
        cur.execute("INSERT OR REPLACE INTO ar_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            a.get("companyCode"), safe_str(a.get("fiscalYear")),
            a.get("accountingDocument"), safe_str(a.get("accountingDocumentItem")),
            safe_str(a.get("clearingDate")), a.get("clearingAccountingDocument"),
            safe_str(a.get("clearingDocFiscalYear")),
            safe_str(a.get("amountInTransactionCurrency")), a.get("transactionCurrency"),
            safe_str(a.get("amountInCompanyCodeCurrency")), a.get("companyCodeCurrency"),
            safe_str(a.get("customer")), safe_str(a.get("invoiceReference")),
            safe_str(a.get("salesDocument")), safe_str(a.get("salesDocumentItem")),
            safe_str(a.get("postingDate")), safe_str(a.get("documentDate")),
            a.get("glAccount"), a.get("financialAccountType"), a.get("profitCenter"),
        ))


    # ── OPTIONAL TABLES (only loaded when the JSON files exist) ─────────────

    # SALES ORDER HEADERS
    so_h_path = os.path.join(DATA_DIR, "sales_order_headers.json")
    if os.path.exists(so_h_path):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales_order_headers (
                salesOrder TEXT PRIMARY KEY,
                salesOrderType TEXT, salesOrganization TEXT, distributionChannel TEXT,
                creationDate TEXT, soldToParty TEXT, shipToParty TEXT,
                totalNetAmount TEXT, transactionCurrency TEXT,
                overallDeliveryStatus TEXT, overallBillingStatus TEXT,
                requestedDeliveryDate TEXT, purchaseOrderByCustomer TEXT
            )
        """)
        for s in json.load(open(so_h_path)):
            cur.execute("INSERT OR REPLACE INTO sales_order_headers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                safe_str(s.get("salesOrder")), s.get("salesOrderType"),
                s.get("salesOrganization"), s.get("distributionChannel"),
                safe_str(s.get("creationDate")), safe_str(s.get("soldToParty")),
                safe_str(s.get("shipToParty")), safe_str(s.get("totalNetAmount")),
                s.get("transactionCurrency"), s.get("overallDeliveryStatus"),
                s.get("overallBillingStatus"),
                safe_str(s.get("requestedDeliveryDate")), s.get("purchaseOrderByCustomer"),
            ))
        print("  optional: sales_order_headers loaded")

    # SALES ORDER ITEMS
    so_i_path = os.path.join(DATA_DIR, "sales_order_items.json")
    if os.path.exists(so_i_path):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sales_order_items (
                salesOrder TEXT, salesOrderItem TEXT,
                material TEXT, salesOrderItemText TEXT,
                requestedQuantity TEXT, requestedQuantityUnit TEXT,
                netAmount TEXT, transactionCurrency TEXT,
                plant TEXT, storageLocation TEXT,
                deliveryStatus TEXT, billingStatus TEXT,
                PRIMARY KEY (salesOrder, salesOrderItem)
            )
        """)
        for s in json.load(open(so_i_path)):
            cur.execute("INSERT OR REPLACE INTO sales_order_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                safe_str(s.get("salesOrder")), safe_str(s.get("salesOrderItem")),
                s.get("material"), s.get("salesOrderItemText"),
                safe_str(s.get("requestedQuantity")), s.get("requestedQuantityUnit"),
                safe_str(s.get("netAmount")), s.get("transactionCurrency"),
                s.get("plant"), s.get("storageLocation"),
                s.get("deliveryStatus"), s.get("billingStatus"),
            ))
        print("  optional: sales_order_items loaded")

    # PAYMENTS
    pay_path = os.path.join(DATA_DIR, "payments.json")
    if os.path.exists(pay_path):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                companyCode TEXT, fiscalYear TEXT,
                accountingDocument TEXT, accountingDocumentItem TEXT,
                customer TEXT, amountInTransactionCurrency TEXT,
                transactionCurrency TEXT, postingDate TEXT,
                clearingDate TEXT, assignmentReference TEXT,
                PRIMARY KEY (companyCode, fiscalYear, accountingDocument, accountingDocumentItem)
            )
        """)
        for p in json.load(open(pay_path)):
            cur.execute("INSERT OR REPLACE INTO payments VALUES (?,?,?,?,?,?,?,?,?,?)", (
                p.get("companyCode"), safe_str(p.get("fiscalYear")),
                p.get("accountingDocument"), safe_str(p.get("accountingDocumentItem")),
                safe_str(p.get("customer")), safe_str(p.get("amountInTransactionCurrency")),
                p.get("transactionCurrency"), safe_str(p.get("postingDate")),
                safe_str(p.get("clearingDate")), p.get("assignmentReference"),
            ))
        print("  optional: payments loaded")

    # BILLING CANCELLATIONS
    canc_path = os.path.join(DATA_DIR, "billing_cancellations.json")
    if os.path.exists(canc_path):
        cur.execute("""
            CREATE TABLE IF NOT EXISTS billing_cancellations (
                billingDocument TEXT PRIMARY KEY,
                cancelledBillingDocument TEXT, cancellationDate TEXT,
                companyCode TEXT, soldToParty TEXT,
                totalNetAmount TEXT, transactionCurrency TEXT
            )
        """)
        for c in json.load(open(canc_path)):
            cur.execute("INSERT OR REPLACE INTO billing_cancellations VALUES (?,?,?,?,?,?,?)", (
                c.get("billingDocument"), c.get("cancelledBillingDocument"),
                safe_str(c.get("creationDate") or c.get("cancellationDate")),
                c.get("companyCode"), safe_str(c.get("soldToParty")),
                safe_str(c.get("totalNetAmount")), c.get("transactionCurrency"),
            ))
        print("  optional: billing_cancellations loaded")

    # ── INDEXES ──────────────────────────────────────────────────────────────
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_di_ref ON delivery_items(referenceSdDocument)",
        "CREATE INDEX IF NOT EXISTS idx_bi_ref ON billing_items(referenceSdDocument)",
        "CREATE INDEX IF NOT EXISTS idx_bh_sold ON billing_header(soldToParty)",
        "CREATE INDEX IF NOT EXISTS idx_bh_acc ON billing_header(accountingDocument)",
        "CREATE INDEX IF NOT EXISTS idx_je_ref ON journal_entries(referenceDocument)",
        "CREATE INDEX IF NOT EXISTS idx_je_acc ON journal_entries(accountingDocument)",
        "CREATE INDEX IF NOT EXISTS idx_ar_cust ON ar_items(customer)",
        "CREATE INDEX IF NOT EXISTS idx_bi_mat ON billing_items(material)",
        "CREATE INDEX IF NOT EXISTS idx_di_plant ON delivery_items(plant)",
    ]
    for idx in indexes:
        cur.execute(idx)

    conn.commit()
    conn.close()
    print(f"✅ DB initialized at {DB_PATH}")


def execute_query(sql: str, params=None):
    """Execute a SQL query and return results as list of dicts"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        result = [dict(zip(columns, row)) for row in rows]
        return result, None
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()