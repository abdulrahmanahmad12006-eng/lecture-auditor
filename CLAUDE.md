# Lecture Auditor - CLAUDE.md

## Project Overview
Lecture Auditor is a web-based system for ingesting lecture PDFs, enabling semantic search and grounded question answering with citations. It targets students and educators who need to quickly retrieve and verify information from dense lecture materials. The system solves the problem of manual PDF search by providing AI-powered hybrid search and LLM-generated answers that are strictly grounded in the source text with inline citations.

## Architecture
- **Backend**: FastAPI application serving a REST API and static files
- **Core Components**:
  - `ingestion.py`: PDF text extraction (pypdf), header-based semantic chunking, SQLite storage
  - `retriever.py`: Hybrid search combining SQLite FTS5 (lexical) and FAISS with sentence-transformers (dense) using Reciprocal Rank Fusion (RRF)
  - `generator.py`: Prompt engineering, LLM API call (local OpenAI-compatible), Pydantic validation of output
  - `app.py`: API endpoints, health check, file upload/delete, query processing, static file serving
- **Frontend**: HTML/CSS/JS interface with real-time API communication
- **Database**: SQLite file (`data/app.db`) for storing chunks and metadata
- **AI Services**: Local OpenAI-compatible LLM endpoint for generation, sentence-transformers model for embeddings

## Run/Test Commands
### Setup
```bash
# Install dependencies
pip install -e .
```

### Run the Server
```bash
# Using startup scripts (recommended)
# Windows: Double-click start.bat
# Mac/Linux: ./start.sh

# Or manually:
python lecture_auditor/app.py
```
- Web UI: http://127.0.0.1:8000
- API base: http://127.0.0.1:8000/api
- The server automatically opens the browser (set NO_BROWSER=1 to disable)

### Run Tests
```bash
pytest tests/ -v
```

### Run Evaluation Suite
```bash
# Run hybrid evaluation (default)
python evals/run_evals.py

# Run all three modes (lexical, dense, hybrid) and compare
python evals/run_evals.py --all

# Run a specific mode
python evals/run_evals.py --mode lexical
python evals/run_evals.py --mode dense
python evals/run_evals.py --mode hybrid
```

## Key Decisions
- **FastAPI**: Chosen for automatic API docs, async support, and rapid development.
- **SQLite**: Selected for zero-configuration storage; adequate for prototype scale.
- **pypdf**: Pure-Python PDF text extraction; avoids external binaries or complex dependencies.
- **Header-Based Chunking**: Lightweight alternative to full layout analysis; trades robustness for simplicity and speed.
- **Sentence-Transformers + FAISS**: `all-MiniLM-L6-v2` provides good embedding quality/size balance; FAISS-CPU IndexFlatIP enables efficient inner-product (cosine similarity) search.
- **Reciprocal Rank Fusion (RRF)**: Combines lexical (FTS5/BM25) and dense (FAISS) search rankings to capture both exact term matches and semantic similarity.
- **Local LLM Endpoint**: Designed to work with any OpenAI-compatible server (e.g., `text-generation-webui`, `llama.cpp`) allowing flexible local LLM usage without code changes.
- **Pydantic Validation**: Ensures LLM output conforms to expected `{answer, citations}` schema, reducing pipeline fragility from malformed JSON.
- **Vanilla JS Frontend**: Chose no frameworks to reduce complexity and focus on backend functionality; keeps UI lightweight and easy to understand.
- **Evaluation Suite**: Built to measure core IR (context recall) and generation (faithfulness, latency) metrics, enabling data‑driven improvements.

## Rules
- **Dependencies**: Do not add new heavy dependencies without consulting the team (or noting the justification in commit messages).
- **Secrets**: Never print or commit secrets (e.g., API keys, passwords). Use environment variables for configuration.
- **Ambiguity**: If something is ambiguous, pick the simplest option and note it in the summary instead of stopping for clarification.
- **Code Quality**: Maintain clean, readable code with appropriate comments. Follow existing code style.
- **Testing**: Add tests for new functionality. Ensure existing tests pass before merging changes.

## Current Status
### Completed (as of 2026-10-11)
- ✅ PDF ingestion with header-based semantic chunking
- ✅ Hybrid search (FTS5 + FAISS + RRF)
- ✅ Grounded answer generation with LLM and Pydantic validation
- ✅ RESTful API with health, upload, query, documents, evals endpoints
- ✅ Modern dark-mode web interface with real-time API communication
- ✅ Evaluation suite with ablation modes (lexical, dense, hybrid)
- ✅ One-click launch via startup scripts and auto-browser-open
- ✅ Comprehensive unit tests for all components
- ✅ Configuration via environment variables and .env file
- ✅ CORS middleware for frontend-backend integration

### In Progress
- ❌ None - all planned phases are complete

### Future Work
- 📝 Improve chunking algorithm (layout analysis, user-defined heading patterns)
- 📝 Optimize index updates (incremental FAISS adds, avoid full rebuilds)
- 📝 Add user authentication and authorization
- 📝 Persist chat history (already implemented via localStorage)
- 📝 Enhance UI: markdown rendering for answers, better citation popups, etc.
- 📝 Expand evaluation suite with ground-truth answers for accuracy measurement
- 📝 Deployment: Docker containerization for easier sharing
- 📝 Implement taxonomy-based filtering and categorization
- 📝 Advanced UI features: drag-and-drop upload, file preview, etc.

## Acknowledgments
Built with FastAPI, sentence-transformers, FAISS, pypdf, and other open-source libraries.