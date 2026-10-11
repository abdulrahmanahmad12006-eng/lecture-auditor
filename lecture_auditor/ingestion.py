import sqlite3
import os
from typing import List, Tuple
from pypdf import PdfReader

def init_db(db_path: str = "data/app.db") -> None:
    """Initialize the SQLite database and create the chunks table if it doesn't exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            section_title TEXT,
            chunk_id TEXT NOT NULL,
            text TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def is_heading(line: str) -> bool:
    """Simple heuristic to detect headings."""
    line = line.strip()
    if not line:
        return False
    # All caps and relatively short
    if line.isupper() and len(line) < 50:
        return True
    # Ends with colon and short
    if line.endswith(':') and len(line) < 60:
        return True
    return False

def extract_chunks_from_pdf(pdf_path: str) -> List[Tuple[str, int, str, str, str]]:
    """
    Extract text chunks from a PDF with header-based semantic chunking.
    Returns a list of tuples: (filename, page_number, section_title, chunk_id, text)
    """
    filename = os.path.basename(pdf_path)
    reader = PdfReader(pdf_path)
    chunks = []

    for page_num, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        if not text:
            continue

        lines = text.split('\n')
        current_section = ""
        current_chunk_lines = []
        chunk_index = 0

        for line in lines:
            stripped = line.strip()
            if is_heading(stripped):
                # If we have accumulated lines, save as a chunk
                if current_chunk_lines:
                    chunk_text = '\n'.join(current_chunk_lines).strip()
                    if chunk_text:
                        chunk_id = f"{page_num}_{chunk_index}"
                        chunks.append((filename, page_num, current_section, chunk_id, chunk_text))
                        chunk_index += 1
                        current_chunk_lines = []
                # Update current section
                current_section = stripped
            else:
                # Accumulate line into current chunk
                if stripped:  # ignore empty lines
                    current_chunk_lines.append(stripped)

        # Save any remaining lines as a chunk
        if current_chunk_lines:
            chunk_text = '\n'.join(current_chunk_lines).strip()
            if chunk_text:
                chunk_id = f"{page_num}_{chunk_index}"
                chunks.append((filename, page_num, current_section, chunk_id, chunk_text))

    return chunks

def ingest_pdf(pdf_path: str, db_path: str = "data/app.db") -> None:
    """Ingest a single PDF file into the SQLite database."""
    init_db(db_path)
    chunks = extract_chunks_from_pdf(pdf_path)

    if not chunks:
        print(f"No chunks extracted from {pdf_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT INTO chunks (filename, page_number, section_title, chunk_id, text)
        VALUES (?, ?, ?, ?, ?)
    """, chunks)
    conn.commit()
    conn.close()
    print(f"Ingested {len(chunks)} chunks from {pdf_path} into {db_path}")

if __name__ == "__main__":
    # Example usage: ingest all PDFs in data directory
    data_dir = "data"
    if os.path.exists(data_dir):
        for filename in os.listdir(data_dir):
            if filename.lower().endswith('.pdf'):
                pdf_path = os.path.join(data_dir, filename)
                ingest_pdf(pdf_path)
    else:
        print("Data directory not found. Place PDF files in the 'data' directory.")