# Lecture Auditor

A web-based system for ingesting lecture PDFs, enabling semantic search and grounded question answering with citations.

## Features

- PDF ingestion with header-based semantic chunking
- Hybrid search combining lexical (FTS5) and dense vector (FAISS + sentence-transformers) search using Reciprocal Rank Fusion (RRF)
- Grounded answer generation using a local LLM (OpenAI-compatible) with citations
- Modern dark-mode web interface with file upload, chat, and evaluation dashboard
- RESTful API for programmatic access
- Evaluation suite to measure context recall, faithfulness, and latency

## Tech Stack

- **Language**: Python 3.9+
- **Backend**: FastAPI (ASGI server via Uvicorn)
- **Frontend**: HTML5, CSS3, vanilla JavaScript
- **Core Libraries**:
  - `pypdf`: PDF text extraction
  - `sentence-transformers`: Dense vector embeddings (all-MiniLM-L6-v2 model)
  - `faiss-cpu`: Efficient similarity search for embeddings
  - `sqlite3`: Built-in SQLite database driver
  - `requests`: HTTP communication with local LLM endpoint
  - `pydantic`: Data validation and settings management
  - `python-dotenv`: Environment variable loading
  - `pytest`: Unit testing framework
  - `ruff`: Linting (dev dependency)
- **Database**: SQLite file at `data/app.db`
- **AI Models/Services**:
  - Local OpenAI-compatible LLM endpoint (expected at `http://127.0.0.1:8082/v1`) for answer generation
  - Sentence-transformers model (`all-MiniLM-L6-v2`) for embeddings

## Project Structure

```
lecture-auditor/
├─ app.py                     # Main FastAPI app: serves static files, defines API endpoints
├─ pyproject.toml             # Project metadata and dependencies
├─ lecture_auditor/
│  ├─ __init__.py             # Package initializer
│  ├─ ingestion.py            # PDF ingestion with semantic chunking
│  ├─ retriever.py            # Hybrid search (FTS5 + FAISS + RRF)
│  ├─ generator.py            # Grounded answer generation with LLM
│  └─ config.py               # Configuration from environment variables
├─ static/                    # Frontend assets served by the server
│  ├─ index.html              # Main UI: header with status, sidebar (upload/indexing), main panel (chat/tabs)
│  ├─ styles.css              # Dark-mode styling, layout, responsive tweaks
│  └─ app.js                  # Frontend logic: status polling, file upload, chat, docs list, evals tab
├─ evals/                     # Evaluation suite
│  ├─ dataset.json            # 10 synthetic technical exam questions with expected keywords
│  ├─ run_evals.py            # Script to compute context recall, faithfulness, and latency; saves results.json
│  └─ results.json            # Evaluation results (generated after running evals/run_evals.py)
├─ tests/                     # Unit tests
│  ├─ test_ingestion.py       # Tests for PDF ingestion and chunking
│  ├─ test_retriever.py       # Tests for hybrid retriever components
│  ├─ test_generator.py       # Tests for answer generation and validation
│  └─ test_api.py             # Tests for API endpoints
├─ data/                      # Stores uploaded PDFs and SQLite database (app.db)
├─ config/                    # Configuration files
│  └─ taxonomy.yaml           # Placeholder for lecture taxonomy configuration (unused)
├─ .env.example               # Example environment variables (copy to .env and customize)
├─ start.bat                  # Windows startup script
├─ start.sh                   # Mac/Linux startup script
├─ .vscode/
│  ├─ tasks.json              # VS Code tasks
│  └─ launch.json             # VS Code launch configuration
└─ index.html                 # Root landing page (redirects to app if server is running)
```

## Setup

1. **Prerequisites**:
   - Python 3.9+ installed
   - A local OpenAI-compatible LLM endpoint running at `http://127.0.0.1:8082/v1` (this URL is configurable via environment variables)
     Examples: `text-generation-webui` with `--api`, `llama.cpp` server with `-c`, or similar.
     The endpoint must support `/v1/chat/completions` with JSON payload matching OpenAI's chat format.

2. **Installation**:
   ```bash
   # Clone or copy the project
   cd lecture-auditor
   # Install dependencies
   pip install -e .
   ```

3. **Environment Variables** (optional):
   Copy `.env.example` to `.env` and adjust as needed:
   ```bash
   cp .env.example .env
   # Edit .env to change defaults
   ```
   Available variables:
   - `LLM_BASE_URL`: Base URL of the LLM API (default: `http://127.0.0.1:8082/v1`)
   - `LLM_MODEL`: Model name to use (default: `local-model`)
   - `TOP_K`: Number of retrieval results to use as context (default: `5`)
   - `DB_PATH`: Path to SQLite database (default: `data/app.db`)
   - `DATA_DIR`: Directory for storing uploaded PDFs (default: `data`)
   - `HOST`: Server host (default: `0.0.0.0`)
   - `PORT`: Server port (default: `8000`)
   - `LLM_TIMEOUT`: Request timeout for LLM API in seconds (default: `30.0`)

## How to Run

### Option 1: Using the startup scripts (recommended)
- **Windows**: Double-click `start.bat`
- **Mac/Linux**: Run `./start.sh` in a terminal

These scripts will:
1. Create/activate a virtual environment (`.venv`) if missing
2. Install dependencies if needed
3. Start the server
4. Open the browser automatically (to disable, set `NO_BROWSER=1` environment variable)

### Option 2: Manual startup
```bash
# Activate virtual environment if desired
# python -m venv .venv
# .venv/Scripts\activate  # Windows
# source .venv/bin/activate  # Mac/Linux

# Install dependencies
pip install -e .

# Start the server
python lecture_auditor/app.py
```

The server will be available at:
- **Web Interface**: http://127.0.0.1:8000
- **API Base**: http://127.0.0.1:8000/api

## Usage

1. **Upload PDF lecture files**:
   - Via the web interface: Use the upload panel in the sidebar
   - Via API: `POST /api/upload` with PDF files (multipart/form-data)
   - The system will:
     - Save PDFs to the `data/` directory
     - Extract text and perform header-based semantic chunking
     - Attach metadata (filename, page number, section title, chunk ID)
     - Store chunks in the SQLite database
     - Update search indexes (FTS5 and FAISS)

2. **Ask questions**:
   - Via the web interface: Type in the chat panel and press Enter or click Send
   - Via API: `POST /api/query` with JSON `{"question": "your question"}`
   - Returns a grounded answer with citations:
     ```json
     {
       "answer": "The mitochondria is the powerhouse of the cell [1].",
       "citations": [1],
       "sources": [
         {
           "filename": "lecture1.pdf",
           "page_number": 5,
           "section_title": "Overview",
           "text_snippet": "The mitochondria is the powerhouse of the cell..."
         }
       ]
     }
     ```
   - If no relevant information is found, the system will indicate it cannot answer based on the provided sources.

3. **Check system status**:
   - `GET /api/health`: Returns database and LLM endpoint reachability, chunk count, and document count
   - `GET /api/documents`: Returns list of processed files and chunk counts
   - `GET /api/evals`: Returns evaluation results if available, otherwise provides guidance on running the evaluation

## Evaluation Suite

The evaluation suite measures the quality of the retrieval and generation components.

### Running the Evaluation

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

The evaluation script:
- Loads `evals/dataset.json` (10 synthetic technical exam questions with expected keywords)
- For each question:
  - Measures context recall (proportion of expected relevant chunks retrieved)
  - Measures faithfulness (LLM-judged score of answer fidelity to retrieved context, 0-100%)
  - Measures latency (search and generation time in milliseconds)
- Saves detailed results to `evals/results.json`

### Viewing Evaluation Results

- After running the evaluation, visit the web interface and click the "Evals Dashboard" tab
- Or access the results directly: `GET /api/evals` returns the evaluation results JSON
- Or view the file: `evals/results.json`

## Testing

Run the test suite:
```bash
pytest tests/ -v
```

## Project Status

### Completed Features
- ✅ PDF ingestion with header-based semantic chunking (`src/ingestion.py`)
- ✅ Hybrid search (FTS5 + FAISS + RRF) (`src/retriever.py`)
- ✅ Grounded answer generation with LLM and Pydantic validation (`src/generator.py`)
- ✅ RESTful API with endpoints for upload, query, health, documents, evals (`src/app.py`)
- ✅ Modern dark-mode web interface (`static/`)
- ✅ Evaluation suite (`evals/`)
- ✅ Comprehensive unit tests (`tests/`)

### In Progress
- ❌ Frontend-backend connection: UI JavaScript now makes real API calls (Phase 4 completed)
- ❌ Evaluation suite ablation modes: Added (Phase 6 completed)
- ❌ One-click launch: Added startup scripts and auto-browser-open (Phase 5 completed)

### Future Work
- 📝 Improve chunking algorithm (e.g., using layout analysis for better section detection)
- 📝 Optimize index updates (incremental FAISS adds instead of periodic rebuilds)
- 📝 Add user authentication and authorization
- 📝 Persist chat history (already implemented via localStorage)
- 📝 Enhance UI: markdown rendering for answers, better citation popups, etc.
- 📝 Expand evaluation suite with ground-truth answers for accuracy measurement
- 📝 Deployment: Docker containerization for easier sharing
- 📝 Implement taxonomy-based filtering and categorization

## License

This project is provided as-is for educational and experimental use.

## Acknowledgements

Built with FastAPI, sentence-transformers, FAISS, pypdf, and other open-source libraries.