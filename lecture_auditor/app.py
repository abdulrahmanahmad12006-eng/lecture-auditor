import os
import shutil
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Import our modules
from lecture_auditor.ingestion import ingest_pdf, init_db as init_ingestion_db
from lecture_auditor.retriever import HybridRetriever
from lecture_auditor.generator import generate_answer

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

# API Endpoints

@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Upload PDF files, save them to data/, run ingestion, and update indexes.
    Returns the number of files processed and total chunks added.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    saved_paths = []
    try:
        for file in files:
            # Validate file type (optional)
            if not file.filename.lower().endswith('.pdf'):
                raise HTTPException(status_code=400, detail=f"File {file.filename} is not a PDF")

            # Save the file
            file_path = os.path.join(DATA_DIR, file.filename)
            # Avoid overwriting by adding a timestamp if needed? For simplicity, we'll overwrite.
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            saved_paths.append(file_path)

        # Ingest each file
        total_chunks_before = _get_total_chunks()
        for path in saved_paths:
            ingest_pdf(path)

        # Rebuild retriever indexes to include new chunks
        retriever_instance.build_indexes_from_db()

        total_chunks_after = _get_total_chunks()
        chunks_added = total_chunks_after - total_chunks_before

        return JSONResponse(content={
            "message": f"Successfully processed {len(files)} file(s)",
            "files_processed": [os.path.join("data", f.filename) for f in files],
            "chunks_added": chunks_added,
            "total_chunks": total_chunks_after
        })
    except Exception as e:
        # Clean up saved files on error? We'll leave them for now.
        raise HTTPException(status_code=500, detail=f"Error processing files: {str(e)}")
    finally:
        # Close uploaded file handles
        for file in files:
            file.file.close()

@app.post("/api/query")
async def query_question(payload: dict):
    """
    Accept a question and return a grounded answer with citations.
    Expected payload: {"question": "string"}
    """
    question = payload.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    try:
        # Use the generator to produce an answer
        answer = generate_answer(question)
        # The generator returns a Pydantic model; convert to dict for JSON response
        return JSONResponse(content=answer.dict())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating answer: {str(e)}")

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
    Return or run benchmark results from the evals module.
    For now, we return a placeholder or run any evaluation scripts found in /evals.
    """
    evals_dir = os.path.join(os.path.dirname(__file__), "..", "evals")
    if not os.path.exists(evals_dir):
        return JSONResponse(content={
            "message": "Evals directory not found. No evaluation results available."
        })

    # Look for any Python scripts or JSON results
    results = {}
    try:
        # If there's a results.json, read it
        results_file = os.path.join(evals_dir, "results.json")
        if os.path.exists(results_file):
            import json
            with open(results_file, 'r') as f:
                results = json.load(f)
            return JSONResponse(content={"evals_results": results})

        # If there's a run_evals.py, we could run it, but for safety we'll just list what's available
        scripts = [f for f in os.listdir(evals_dir) if f.endswith('.py')]
        if scripts:
            return JSONResponse(content={
                "message": f"Evaluation scripts found: {scripts}. Please run them manually.",
                "available_scripts": scripts
            })

        # Otherwise, just list the contents
        contents = os.listdir(evals_dir)
        return JSONResponse(content={
            "message": "Evals directory contents:",
            "contents": contents
        })
    except Exception as e:
        return JSONResponse(content={
            "error": f"Error accessing evals: {str(e)}"
        }, status_code=500)

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