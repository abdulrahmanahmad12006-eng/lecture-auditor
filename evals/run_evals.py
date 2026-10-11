import json
import time
import sqlite3
import os
import sys
from typing import List, Dict, Any, Set

# Add lecture_auditor to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lecture_auditor'))

from lecture_auditor.retriever import HybridRetriever
from lecture_auditor.config import config
import requests

# Configuration from config module
DB_PATH = config.DB_PATH
ENDPOINT_URL = config.LLM_BASE_URL
MODEL_NAME = config.LLM_MODEL
TOP_K = config.TOP_K

def get_relevant_chunk_ids(keywords: List[str]) -> Set[int]:
    """
    Return a set of chunk IDs that contain all the given keywords (case-insensitive).
    If no keywords, return all chunk IDs.
    """
    if not keywords:
        # Return all chunk IDs
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM chunks")
        all_ids = {row[0] for row in cursor.fetchall()}
        conn.close()
        return all_ids

    # Build a query that checks for each keyword (case-insensitive)
    # We'll use lower(text) LIKE '%keyword%' for each keyword
    conditions = []
    params = []
    for kw in keywords:
        conditions.append("lower(text) LIKE ?")
        params.append(f"%{kw.lower()}%")

    where_clause = " AND ".join(conditions)
    query = f"SELECT id FROM chunks WHERE {where_clause}"

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        ids = {row[0] for row in cursor.fetchall()}
    except sqlite3.Error as e:
        print(f"Database error while fetching relevant chunks: {e}")
        ids = set()
    finally:
        conn.close()
    return ids

def compute_faithfulness(context_chunks: List[Dict[str, Any]], answer: str) -> float:
    """
    Use the LLM to judge the faithfulness of the answer given the context.
    Returns a score between 0.0 and 1.0.
    """
    # Format the context for the prompt
    context_lines = []
    for i, chunk in enumerate(context_chunks, start=1):
        # Include some metadata to help the model identify the source
        meta = []
        if chunk.get('filename'):
            meta.append(f"filename={chunk['filename']}")
        if chunk.get('page_number') is not None:
            meta.append(f"page={chunk['page_number']}")
        if chunk.get('section_title'):
            meta.append(f"section={chunk['section_title']}")
        meta_str = ", ".join(meta)
        context_lines.append(f"[Source {i}] ({meta_str}): {chunk['text']}")
    context_text = "\n\n".join(context_lines)

    prompt = f"""You are a faithfulness evaluator. Determine to what extent the answer is supported by the provided context.
Answer with a single number between 0 and 100, where:
- 100 means the answer is entirely supported by the context (every statement can be backed by the context)
- 0 means the answer is not supported by the context at all (contains information not in the context or contradicts it)
Consider only factual consistency; ignore minor paraphrasing.

Context:
{context_text}

Answer:
{answer}

Faithfulness score (0-100):"""

    url = f"{ENDPOINT_URL}/chat/completions"
    payload = {
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,  # We want deterministic scoring
        "max_tokens": 10
    }

    try:
        response = requests.post(url, json=payload, timeout=config.LLM_TIMEOUT)
        response.raise_for_status()
        result = response.json()
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0].get("message", {}).get("content", "").strip()
            # Extract the first number from the content
            import re
            match = re.search(r'\d+(\.\d+)?', content)
            if match:
                score = float(match.group())
                # Clamp to 0-100
                score = max(0.0, min(100.0, score))
                return score / 100.0  # Convert to 0-1 range
            else:
                print(f"Could not extract score from LLM output: '{content}'")
                return 0.0
        else:
            print("Unexpected response format from LLM endpoint")
            return 0.0
    except requests.exceptions.RequestException as e:
        print(f"Error calling LLM for faithfulness: {e}")
        return 0.0

def main():
    # Load dataset
    dataset_path = os.path.join(os.path.dirname(__file__), "dataset.json")
    if not os.path.exists(dataset_path):
        print(f"Dataset file not found: {dataset_path}")
        sys.exit(1)

    with open(dataset_path, 'r', encoding='utf-8') as f:
        dataset = json.load(f)

    if not isinstance(dataset, list):
        print("Dataset must be a list of question objects")
        sys.exit(1)

    # Initialize retriever once
    print("Initializing retriever...")
    retriever = HybridRetriever(DB_PATH)

    # Lists to store per-question metrics
    recalls = []
    faithfulness_scores = []
    latencies_search = []
    latencies_gen = []
    latencies_total = []

    print(f"Running evaluation on {len(dataset)} questions...")
    for i, item in enumerate(dataset):
        question = item.get("question", "").strip()
        expected_keywords = item.get("expected_keywords", [])
        if not question:
            print(f"Skipping item {i}: empty question")
            continue

        print(f"\nQuestion {i+1}/{len(dataset)}: {question}")
        print(f"Expected keywords: {expected_keywords}")

        # --- Hybrid Search ---
        start_search = time.time()
        try:
            # We'll use the retriever's hybrid_search method directly
            search_results = retriever.hybrid_search(question, limit=TOP_K)
        except Exception as e:
            print(f"Error during hybrid search: {e}")
            search_results = []
        end_search = time.time()
        latency_search = (end_search - start_search) * 1000  # ms
        latencies_search.append(latency_search)

        # Extract retrieved chunk IDs
        retrieved_ids = set()
        for result in search_results:
            # The search result should have an 'id' field (the database row id)
            if 'id' in result:
                retrieved_ids.add(result['id'])

        # --- Compute Relevant Chunks ---
        relevant_ids = get_relevant_chunk_ids(expected_keywords)

        # --- Context Recall ---
        if relevant_ids:
            intersection = retrieved_ids & relevant_ids
            recall = len(intersection) / len(relevant_ids) if len(relevant_ids) > 0 else 0.0
        else:
            # If no relevant chunks in the database, recall is 0 (cannot retrieve what's not there)
            recall = 0.0
        recalls.append(recall)

        print(f"  Retrieved {len(search_results)} chunks, {len(relevant_ids)} relevant chunks in DB")
        print(f"  Context Recall: {recall:.2%}")

        # --- Generate Answer ---
        start_gen = time.time()
        try:
            # We'll use the generator's convenience function, but we need to import it.
            # To avoid re-initializing the retriever inside the generator, we can use our own retriever instance?
            # The generator's generate_answer function creates its own HybridRetriever instance.
            # For simplicity, we'll call the generator's function (it will create a new retriever each time).
            # This is okay for evaluation but not optimal.
            from lecture_auditor.generator import generate_answer
            answer_obj = generate_answer(question, endpoint_url=ENDPOINT_URL, model_name=MODEL_NAME)
            answer = answer_obj.answer
        except Exception as e:
            print(f"Error generating answer: {e}")
            answer = ""
        end_gen = time.time()
        latency_gen = (end_gen - start_gen) * 1000  # ms
        latencies_gen.append(latency_gen)

        # --- Faithfulness ---
        faithfulness = 0.0
        if answer and search_results:
            faithfulness = compute_faithfulness(search_results, answer)
        faithfulness_scores.append(faithfulness)

        print(f"  Answer length: {len(answer)}")
        print(f"  Faithfulness: {faithfulness:.2%}")
        print(f"  Search latency: {latency_search:.2f} ms")
        print(f"  Generation latency: {latency_gen:.2f} ms")

        # Total latency for this question (search + generation)
        latency_total = latency_search + latency_gen
        latencies_total.append(latency_total)

    # Close the retriever
    retriever.close()

    # Compute averages
    avg_recall = sum(recalls) / len(recalls) if recalls else 0.0
    avg_faithfulness = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 0.0
    avg_latency_search = sum(latencies_search) / len(latencies_search) if latencies_search else 0.0
    avg_latency_gen = sum(latencies_gen) / len(latencies_gen) if latencies_gen else 0.0
    avg_latency_total = sum(latencies_total) / len(latencies_total) if latencies_total else 0.0

    # Prepare results dictionary
    results = {
        "dataset_size": len(dataset),
        "top_k": TOP_K,
        "average_context_recall": avg_recall,
        "average_faithfulness": avg_faithfulness,
        "average_latency_search_ms": avg_latency_search,
        "average_latency_generation_ms": avg_latency_gen,
        "average_latency_total_ms": avg_latency_total,
        "per_question": [
            {
                "question": item.get("question", ""),
                "expected_keywords": item.get("expected_keywords", []),
                "context_recall": recalls[i] if i < len(recalls) else 0.0,
                "faithfulness": faithfulness_scores[i] if i < len(faithfulness_scores) else 0.0,
                "latency_search_ms": latencies_search[i] if i < len(latencies_search) else 0.0,
                "latency_generation_ms": latencies_gen[i] if i < len(latencies_gen) else 0.0,
                "latency_total_ms": latencies_total[i] if i < len(latencies_total) else 0.0
            }
            for i, item in enumerate(dataset)
        ]
    }

    # Save results
    output_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    print("\n=== Evaluation Summary ===")
    print(f"Dataset size: {len(dataset)}")
    print(f"Average Context Recall: {avg_recall:.2%}")
    print(f"Average Faithfulness: {avg_faithfulness:.2%}")
    print(f"Average Search Latency: {avg_latency_search:.2f} ms")
    print(f"Average Generation Latency: {avg_latency_gen:.2f} ms")
    print(f"Average Total Latency: {avg_latency_total:.2f} ms")
    print(f"Results saved to: {output_path}")

if __name__ == "__main__":
    main()