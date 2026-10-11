import os
import shutil
from typing import Any, List

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Import our modules
from lecture_auditor.ingestion import ingest_pdf, init_db as init_ingestion_db
from lecture_auditor.retriever import HybridRetriever
from lecture_auditor.generator import generate_answer
from lecture_auditor.config import config

app = FastAPI(title="Lecture Auditor API")

# Allow CORS for the frontend (if served from a different port)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Global retriever instance (initialized on startup)
retriever_instance: HybridRetriever = None

# Ensure data directory exists
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

@app.on_event("startup")
async def startup_event():
    global retriever_instance
    # Initialize the ingestion database (ensure tables exist)
    init_ingestion_db()
    # Initialize the retriever (this will ensure FTS table exists and load model)
    retriever_instance = HybridRetriever()
    # Build indexes from existing data (if any)
    try:
        retriever_instance.build_indexes_from_db()
    except Exception as e:
        # If there's an error (e.g., no data), we can still proceed
        print(f"Warning: Could not build indexes on startup: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    global retriever_instance
    if retriever_instance:
        retriever_instance.close()

@app.get("/")
async def read_root():
    """Serve the main HTML page."""
    from fastapi.responses import FileResponse
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/api/health")
async def health_check():
    """Return system health status."""
    # Check database reachable
    db_ok = False
    chunk_count = 0
    document_count = 0
    try:
        conn = retriever_instance.conn
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM chunks")
        chunk_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT filename) FROM chunks")
        document_count = cursor.fetchone()[0]
        db_ok = True
    except Exception:
        db_ok = False

    # Check LLM endpoint reachable
    llm_ok = False
    try:
        # We'll do a simple request to the LLM endpoint with a minimal payload
        import requests
        resp = requests.post(
            f"{config.LLM_BASE_URL}/chat/completions",
            json={
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": "test"}],
                "max_tokens": 1
            },
            timeout=5.0
        )
        if resp.status_code < 500:
            llm_ok = True
    except Exception:
        llm_ok = False

    return JSONResponse(content={
        "database": {
            "reachable": db_ok,
            "chunk_count": chunk_count,
            "document_count": document_count
        },
        "llm_endpoint": {
            "reachable": llm_ok,
            "url": config.LLM_BASE_URL
        }
    })

# Helper function to sanitize filename
def _sanitize_filename(filename: str) -> str:
    """Remove path components and keep only safe characters."""
    # Remove any path components
    filename = os.path.basename(filename)
    # Keep only alphanumeric, dot, hyphen, underscore
    safe_chars = []
    for c in filename:
        if c.isalnum() or c in '.-_':
            safe_chars.append(c)
    filename = ''.join(safe_chars)
    # Ensure it ends with .pdf
    if not filename.lower().endswith('.pdf'):
        filename = filename + '.pdf'
    # Avoid empty filename
    if not filename or filename == '.pdf':
        filename = 'uploaded.pdf'
    return filename

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Upload PDF files, save them to data/, run ingestion, and update indexes incrementally.
    Returns per-file success/error and overall statistics.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    results = []
    total_chunks_before = _get_total_chunks()
    total_chunks_added = 0

    for file in files:
        file_result = {
            "filename": file.filename,
            "success": False,
            "error": None,
            "chunks_added": 0
        }
        try:
            # Validate file type
            if not file.filename.lower().endswith('.pdf'):
                raise ValueError("File is not a PDF")

            # Sanitize filename
            safe_filename = _sanitize_filename(file.filename)

            # Save the file
            file_path = os.path.join(DATA_DIR, safe_filename)
            # Avoid overwriting by adding a timestamp if needed? We'll replace existing file.
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            # Delete existing chunks for this filename to avoid duplicates
            deleted_count = retriever_instance.delete_chunks_by_filename(safe_filename)
            if deleted_count > 0:
                # Rebuild indexes after deletion to keep FAISS index consistent
                # We'll rebuild after ingestion as well, but we can do it now to keep index clean.
                pass  # We'll rebuild after ingestion

            # Ingest the file (this inserts chunks into the database)
            ingest_pdf(file_path)

            # Get the newly added chunks for this filename to add to indexes incrementally
            new_chunks = retriever_instance.get_chunks_by_filename(safe_filename)
            if new_chunks:
                # Convert to the format expected by add_chunks: (filename, page_number, section_title, chunk_id, text)
                chunks_to_add = [
                    (
                        chunk['filename'],
                        chunk['page_number'],
                        chunk['section_title'],
                        chunk['chunk_id'],
                        chunk['text']
                    )
                    for chunk in new_chunks
                ]
                retriever_instance.add_chunks(chunks_to_add)
                file_result["chunks_added"] = len(chunks_to_add)
                total_chunks_added += len(chunks_to_add)
            else:
                # No chunks were extracted
                pass

            file_result["success"] = True
        except Exception as e:
            file_result["error"] = str(e)
        finally:
            # Close the file handle
            file.file.close()
        results.append(file_result)

    total_chunks_after = _get_total_chunks()

    return JSONResponse(content={
        "message": f"Processed {len(files)} file(s)",
        "files": results,
        "total_chunks_before": total_chunks_before,
        "total_chunks_added": total_chunks_added,
        "total_chunks_after": total_chunks_after
    })

@app.post("/api/query")
async def query_question(payload: dict[str, Any]):
    """
    Accept a question and return a grounded answer with citations and source metadata.
    Expected payload: {"question": "string"}
    """
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    # Check if there are any chunks in the database
    total_chunks = _get_total_chunks()
    if total_chunks == 0:
        return JSONResponse(content={
            "answer": "No documents have been indexed yet. Please upload some PDF documents first.",
            "citations": [],
            "sources": [],
            "error": "No documents indexed"
        })

    try:
        # Get search results
        search_results = hybrid_search(question, limit=5)
        if not search_results:
            return JSONResponse(content={
                "answer": "I cannot answer based on the provided sources.",
                "citations": [],
                "sources": [],
                "info": "No relevant content found for the question."
            })

        # Build context and call generator
        # We'll reuse the generator's internal steps to avoid duplication, but we can also call generate_answer.
        # However, we need the search results to build the sources list.
        # We'll call the generator's internal methods to get the answer and also keep the search results.
        from lecture_auditor.generator import AnswerGenerator
        generator = AnswerGenerator()
        context = generator._format_context(search_results)
        prompt = generator._build_prompt(question, context)
        llm_output = generator._call_llm(prompt)
        answer_obj = generator.GeneratedAnswer.validate_json(llm_output)
        generator.close()

        # Build sources list from search results and answer_obj.citations
        # answer_obj.citations is a list of source numbers (1-based) indicating which search results were cited.
        sources = []
        for idx in answer_obj.citations:
            # idx is 1-based
            if 1 <= idx <= len(search_results):
                result = search_results[idx-1]
                sources.append({
                    "filename": result.get('filename'),
                    "page_number": result.get('page_number'),
                    "section_title": result.get('section_title'),
                    "text_snippet": result.get('text', '')[:200]  # snippet of first 200 chars
                })

        return JSONResponse(content={
            "answer": answer_obj.answer,
            "citations": answer_obj.citations,
            "sources": sources
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating answer: {str(e)}")

@app.delete("/api/documents/{filename}")
async def delete_document(filename: str):
    """
    Delete a document and its chunks from the system.
    """
    # Sanitize the filename for safety
    safe_filename = _sanitize_filename(filename)
    # Delete chunks from database and indexes
    deleted_count = retriever_instance.delete_chunks_by_filename(safe_filename)
    if deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"No document found with filename '{safe_filename}'")

    # Optionally, delete the actual file from the data directory
    file_path = os.path.join(DATA_DIR, safe_filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            # Ignore errors in file deletion
            pass

    return JSONResponse(content={
        "message": f"Document '{safe_filename}' deleted successfully.",
        "deleted_chunks": deleted_count
    })

@app.get("/api/documents")
async def get_documents():
    """
    Return a list of processed files and chunk counts.
    """
    try:
        conn = retriever_instance.conn
        cursor = conn.cursor()
        # Get distinct filenames and count of chunks per file
        cursor.execute("""
            SELECT filename, COUNT(*) as chunk_count
            FROM chunks
            GROUP BY filename
            ORDER BY filename
        """)
        rows = cursor.fetchall()
        files_info = [
            {"filename": row["filename"], "chunk_count": row["chunk_count"]}
            for row in rows
        ]
        # Get total chunks
        total_chunks = _get_total_chunks()
        return JSONResponse(content={
            "files": files_info,
            "total_chunks": total_chunks
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving documents: {str(e)}")

@app.get("/api/evals")
async def get_evals():
    """
    Return evaluation results if available, otherwise provide guidance.
    """
    evals_dir = os.path.join(os.path.dirname(__file__), "..", "evals")
    results_file = os.path.join(evals_dir, "results.json")
    if os.path.exists(results_file):
        try:
            with open(results_file, 'r') as f:
                data = json.load(f)
            return JSONResponse(content=data)
        except Exception as e:
            return JSONResponse(content={
                "error": f"Failed to read evaluation results: {str(e)}"
            }, status_code=500)
    else:
        # No results yet
        return JSONResponse(content={
            "message": "No evaluation results available. Run the evaluation script first:",
            "instructions": "python evals/run_evals.py [--mode lexical|dense|hybrid] [--all]",
            "example": "python evals/run_evals.py --all"
        })

def _get_total_chunks():
    """Helper to get total number of chunks in the database."""
    try:
        conn = retriever_instance.conn
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM chunks")
        count = cursor.fetchone()[0]
        return count
    except Exception:
        return 0

if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading
    import time
    # Open browser after a short delay, unless NO_BROWSER is set
    if os.environ.get("NO_BROWSER") != "1":
        def open_browser():
            time.sleep(1.5)  # Wait for server to start
            webbrowser.open("http://127.0.0.1:8000")
        threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("lecture_auditor.app:app", host=config.HOST, port=config.PORT, reload=True)