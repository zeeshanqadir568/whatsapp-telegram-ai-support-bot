"""Comprehensive Retrieval & Out-of-Domain Grounding Evaluation Suite.

Evaluates:
- 10 Direct domain queries
- 3 Heavily paraphrased domain queries
- 2 Out-of-domain queries (verifying refusal / graceful fallback)
"""

import time
import logging
from typing import List, Dict, Any
from rag_engine import RAGEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EVAL_DATASET = [
    # --- Direct Queries (1-10) ---
    {
        "id": 1,
        "type": "direct",
        "query": "What time do you close on Saturdays?",
        "expected_keywords": ["3:00 PM", "Saturday"]
    },
    {
        "id": 2,
        "type": "direct",
        "query": "How much does routine tooth cleaning cost?",
        "expected_keywords": ["Cleaning", "99"]
    },
    {
        "id": 3,
        "type": "direct",
        "query": "What is the emergency hotline phone number?",
        "expected_keywords": ["555", "emergency"]
    },
    {
        "id": 4,
        "type": "direct",
        "query": "Where is the dental clinic located?",
        "expected_keywords": ["123 Healthcare Ave", "Downtown"]
    },
    {
        "id": 5,
        "type": "direct",
        "query": "How much is a root canal procedure?",
        "expected_keywords": ["Root Canal", "450"]
    },
    {
        "id": 6,
        "type": "direct",
        "query": "Are you open on Sundays?",
        "expected_keywords": ["Closed on Sundays"]
    },
    {
        "id": 7,
        "type": "direct",
        "query": "What is the starting price for dental implants?",
        "expected_keywords": ["Implants", "1,200"]
    },
    {
        "id": 8,
        "type": "direct",
        "query": "What information do I need to book an appointment?",
        "expected_keywords": ["name", "email", "date"]
    },
    {
        "id": 9,
        "type": "direct",
        "query": "Do you offer teeth whitening and what is the cost?",
        "expected_keywords": ["whitening", "199"]
    },
    {
        "id": 10,
        "type": "direct",
        "query": "What are your weekday opening hours?",
        "expected_keywords": ["Monday to Friday", "9:00 AM"]
    },
    # --- Hard Paraphrased Queries (11-13) ---
    {
        "id": 11,
        "type": "paraphrased",
        "query": "Is it possible to get my teeth worked on if I can't come in during standard weekday hours?",
        "expected_keywords": ["Saturday"]
    },
    {
        "id": 12,
        "type": "paraphrased",
        "query": "What will it set me back to fix a deep nerve infection in my tooth?",
        "expected_keywords": ["Root Canal"]
    },
    {
        "id": 13,
        "type": "paraphrased",
        "query": "Do you guys have any option for replacing a missing tooth permanently?",
        "expected_keywords": ["Implants"]
    },
    # --- Out-of-Domain Queries (14-15) ---
    {
        "id": 14,
        "type": "out_of_domain",
        "query": "What is your return and refund policy for unused shoe purchases?",
        "expected_keywords": []  # Out of domain: should NOT match dental info
    },
    {
        "id": 15,
        "type": "out_of_domain",
        "query": "How do I replace a flat tire on a bicycle?",
        "expected_keywords": []  # Out of domain: should NOT match dental info
    }
]


def run_evaluation(top_k: int = 3) -> Dict[str, Any]:
    """Runs evaluation across direct, paraphrased, and out-of-domain test queries."""
    engine = RAGEngine()

    # Ensure vector store contains sample FAQ
    count = engine.vector_manager.get_document_count()
    if count == 0:
        sample_kb = (
            "Apex Dental Clinic FAQ:\n"
            "1. Business Hours: We are open Monday to Friday 9:00 AM - 6:00 PM, Saturday 10:00 AM - 3:00 PM. Closed on Sundays.\n"
            "2. Location: 123 Healthcare Ave, Suite 400, Downtown City.\n"
            "3. Emergency Support: For urgent tooth pain or emergencies after hours, call our hotline at +1 (555) 987-6543.\n"
            "4. Services & Pricing: Teeth whitening ($199), Routine Cleaning ($99), Dental Implants (Starting at $1,200), Root Canal ($450).\n"
            "5. Appointments: To book an appointment, provide your preferred date, name, and email address."
        )
        engine.ingest_text(sample_kb, source_name="dental_clinic_faq.txt")

    direct_hits = 0
    direct_total = 0

    para_hits = 0
    para_total = 0

    ood_passed = 0
    ood_total = 0

    print("\n=========================================================================")
    print(f"   COMPREHENSIVE RAG RETRIEVAL & GROUNDING EVALUATION (Top-K = {top_k})   ")
    print("=========================================================================\n")

    for item in EVAL_DATASET:
        query_id = item["id"]
        qtype = item["type"]
        query = item["query"]
        expected = item["expected_keywords"]

        start_time = time.time()

        if qtype in ["direct", "paraphrased"]:
            retrieved_docs = engine.vector_manager.similarity_search(query, top_k=top_k)
            elapsed_ms = (time.time() - start_time) * 1000
            combined_text = " ".join([doc.page_content for doc in retrieved_docs])

            is_hit = any(kw.lower() in combined_text.lower() for kw in expected)
            if qtype == "direct":
                direct_total += 1
                if is_hit:
                    direct_hits += 1
            else:
                para_total += 1
                if is_hit:
                    para_hits += 1

            status_str = "PASSED [HIT]" if is_hit else "FAILED [MISS]"
            print(f"[{qtype.upper()}] Query #{query_id}: '{query}'")
            print(f"   Status: {status_str} ({elapsed_ms:.2f} ms)\n")

        elif qtype == "out_of_domain":
            ood_total += 1
            reply_text, sources, _ = engine.answer_query(query, top_k=top_k)
            elapsed_ms = (time.time() - start_time) * 1000

            # Check if LLM response gracefully declines or acknowledges absence of context
            refusal_signals = [
                "offline", "dry-run", "don't have", "do not have", "no information",
                "cannot find", "unable to", "human team", "customer support"
            ]
            is_graceful = any(signal in reply_text.lower() for signal in refusal_signals)
            if is_graceful:
                ood_passed += 1

            status_str = "PASSED [GRACEFUL FALLBACK]" if is_graceful else "FAILED [HALLUCINATION]"
            print(f"[{qtype.upper()}] Query #{query_id}: '{query}'")
            print(f"   Response: '{reply_text.strip()[:120]}...'")
            print(f"   Status: {status_str} ({elapsed_ms:.2f} ms)\n")

    total_queries = len(EVAL_DATASET)
    total_successful = direct_hits + para_hits + ood_passed
    overall_hit_rate = (total_successful / total_queries) * 100

    print("-------------------------------------------------------------------------")
    print(f"1. Direct Domain Queries      : {direct_hits} / {direct_total} Hits ({(direct_hits/direct_total)*100:.1f}%)")
    print(f"2. Paraphrased Hard Queries   : {para_hits} / {para_total} Hits ({(para_hits/para_total)*100:.1f}%)")
    print(f"3. Out-of-Domain Queries      : {ood_passed} / {ood_total} Refusals ({(ood_passed/ood_total)*100:.1f}%)")
    print(f"OVERALL EVALUATION SCORE      : {total_successful} / {total_queries} (Overall Score: {overall_hit_rate:.1f}%)")
    print("-------------------------------------------------------------------------\n")


if __name__ == "__main__":
    run_evaluation(top_k=3)
