"""
Guardrails module — ensures queries are ERP/dataset-scoped.

Three-layer defense:
  1. Prompt injection detection (hard block)
  2. Explicit off-topic pattern matching (hard block when no domain overlap)
  3. Domain keyword presence check (soft block for generic queries)
"""

import re
from typing import Tuple

# ── DOMAIN KEYWORDS ─────────────────────────────────────────────────────────
DOMAIN_KEYWORDS = {
    # core ERP entities
    "order", "orders", "sales order", "delivery", "deliveries",
    "billing", "invoice", "invoices", "payment", "payments",
    "journal", "accounting", "journal entry", "ar", "accounts receivable",
    # business objects
    "customer", "customers", "product", "products", "material", "materials",
    "plant", "plants", "vendor", "company", "companycode",
    # SAP-specific
    "sap", "erp", "sd", "fi", "mm", "po", "so", "gr", "gi",
    # analytics verbs
    "amount", "quantity", "revenue", "total", "count", "list",
    "highest", "lowest", "most", "least", "top", "bottom", "average",
    "trace", "flow", "track", "status", "incomplete", "broken", "blocked",
    "cancelled", "cleared", "posted", "fiscal", "document", "reference",
    "which", "how many", "show", "find", "get",
    # temporal
    "date", "month", "year", "quarter", "recent", "latest", "period",
    # financial
    "net amount", "netamount", "currency", "inr", "usd", "transaction",
    "gl account", "profit center", "cost center", "clearing",
}

# ── OFF-TOPIC SIGNAL WORDS (any match = suspect) ────────────────────────────
OFF_TOPIC_SIGNALS = [
    # creative writing signals (flexible word order)
    r"\b(poem|poetry|haiku|sonnet|limerick|lyrics|riddle|fiction|joke|meme|prank)\b",
    r"\btell me (a|an) (joke|story|poem|riddle|fact about)\b",
    r"\bwrite\b.{0,30}\b(story|essay|email|letter|code|script)\b",
    r"\b(story|essay)\b.{0,20}\b(about|on|for)\b",
    # general knowledge / facts
    r"\b(capital of|population of|president of|prime minister of|history of)\b",
    r"\b(who invented|what year did|when was .{1,30} born|where is .{1,30} located)\b",
    r"\bwho is\b.{0,30}\b(musk|bezos|gates|zuckerberg|obama|trump|modi|biden)\b",
    r"\bwho (is|was) [A-Z][a-z]+ [A-Z][a-z]+\b",  # "who is John Doe"
    # entertainment / lifestyle
    r"\b(recipe|cook|bake|ingredient|calorie|nutrition)\b",
    r"\b(movie|film|actress|actor|celebrity|musician|band|album|song title)\b",
    r"\b(sports|cricket|football|soccer|tennis|chess|olympic)\b",
    # tech off-topic
    r"\b(machine learning|deep learning|neural network|large language model|llm|gpt|openai|chatgpt)\b",
    r"\b(python tutorial|javascript syntax|html css|blockchain|web3)\b",
    # weather / geo
    r"\b(weather|temperature|forecast|humidity|rainfall)\b",
    # social / wellbeing
    r"\b(how are you|what'?s up|good morning|good night|hello there)\b",
    r"\b(motivat|inspirat|life advice|mental health|self help)\b",
    # finance off-topic
    r"\b(cryptocurrency|bitcoin|ethereum|nft|stock tip|forex|crypto)\b",
    # politics / news
    r"\b(election|political party|democrat|republican|parliament|senate|congress)\b",
    # image/media generation
    r"\bgenerate\b.{0,20}\b(image|picture|video|audio|music|photo)\b",
    r"\btranslate\b.{0,20}\b(text|sentence|word|phrase|this)\b",
]

REJECTION_MESSAGES = {
    "off_topic": (
        "⚠️ **Out of scope.** This system is designed to answer questions "
        "about the ERP dataset only — covering Sales Orders, Deliveries, "
        "Billing Documents, Journal Entries, Customers, Products, and Plants.\n\n"
        "Try asking:\n"
        "- *Which products have the highest billing volume?*\n"
        "- *Show deliveries with no billing (broken flows)*\n"
        "- *Top 5 customers by total revenue*\n"
        "- *Trace billing document 90504248*"
    ),
    "too_short": (
        "Please provide a more specific question about the ERP dataset. "
        "For example: *Which customer has the highest total billed amount?*"
    ),
    "injection": (
        "⚠️ That input appears to contain instructions unrelated to ERP data analysis. "
        "Please ask a data question about the dataset."
    ),
}

# ── ABSOLUTE BLOCK SIGNALS (block even if domain words present) ─────────────
# These indicate clearly non-ERP intent regardless of incidental domain words
ABSOLUTE_BLOCK_SIGNALS = [
    r"\b(poem|poetry|haiku|sonnet|limerick|lyrics|riddle|fiction)\b",
    r"\bwrite\b.{0,40}\b(story|essay|script|code|novel|blog)\b",
    r"\b(story|essay)\b.{0,20}\b(about|on|for)\b",
    r"\b(machine learning|deep learning|neural network|large language model|chatgpt)\b",
    r"\bgenerate\b.{0,20}\b(image|picture|video|audio|photo)\b",
    r"\btranslate\b.{0,20}\b(text|sentence|word|phrase|this)\b",
    r"\b(capital of|population of|president of|prime minister of)\b",
    r"\bwho is\b.{0,30}\b(musk|bezos|gates|zuckerberg|obama|trump|modi|biden)\b",
]

PROMPT_INJECTION_PATTERNS = [
    r"ignore (previous|above|prior|all) instructions",
    r"\byou are now\b",
    r"\bpretend (you are|to be)\b",
    r"\bact as\b(?!.{0,10}(analyst|expert|assistant))",
    r"\bjailbreak\b",
    r"\bsystem prompt\b",
    r"\bforget (your|all) (instructions|rules|guidelines)\b",
    r"\bdisregard (your|all|the)\b",
    r"\bdo anything now\b",
    r"\bdan mode\b",
    r"\boverride (your|all)\b",
]


def is_allowed_query(query: str) -> Tuple[bool, str]:
    """
    Returns (allowed: bool, rejection_message: str)
    rejection_message is empty string when allowed=True.
    """
    q = query.lower().strip()
    raw = query.strip()

    # 1. Too short / trivial
    words = q.split()
    if len(words) < 2:
        return False, REJECTION_MESSAGES["too_short"]

    # 2a. Absolute block signals — regardless of domain keyword overlap
    for pattern in ABSOLUTE_BLOCK_SIGNALS:
        if re.search(pattern, q, re.IGNORECASE):
            return False, REJECTION_MESSAGES["off_topic"]

    # 2b. Prompt injection — hard block
    for pattern in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            return False, REJECTION_MESSAGES["injection"]

    # 3. Domain keyword scan
    domain_hit_count = sum(1 for kw in DOMAIN_KEYWORDS if kw in q)

    # 4. Off-topic signal scan
    off_topic_hits = []
    for pattern in OFF_TOPIC_SIGNALS:
        if re.search(pattern, q, re.IGNORECASE):
            off_topic_hits.append(pattern)

    # Decision logic:
    # - Any off-topic signal AND zero domain keywords → block
    # - Zero domain keywords AND query is long (>4 words) AND no document IDs → block
    # - Otherwise → allow (LLM will further validate intent)

    has_doc_id = bool(re.search(r'\b[89]\d{7,10}\b', raw))  # SAP-style document IDs

    if off_topic_hits and domain_hit_count == 0:
        return False, REJECTION_MESSAGES["off_topic"]

    if domain_hit_count == 0 and len(words) > 4 and not has_doc_id:
        return False, REJECTION_MESSAGES["off_topic"]

    # Edge: pure greeting with no data intent
    if re.search(r'^\s*(hi|hello|hey|howdy|greetings|sup|yo)\s*[\.,!]?\s*$', q):
        return False, REJECTION_MESSAGES["too_short"]

    return True, ""

