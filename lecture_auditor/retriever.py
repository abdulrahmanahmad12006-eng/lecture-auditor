import sqlite3
import os
from typing import List, Tuple, Dict, Any
import numpy as np

# Try to import optional dependencies, but allow missing for testing
try:
    from sentence_transformers import SentenceTransformer
    import faiss
    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False

class HybridRetriever:
    def __init__(self, db_path: str = "data/app.db", model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize the hybrid retriever.

        Args:
            db_path: Path to SQLite database containing chunks table
            model_name: Sentence transformer model name for embeddings
        """
        self.db_path = db_path
        self.model_name = model_name
        self.conn = None
        self.fts_table = "chunks_fts"
        self.model = None
        self.faiss_index = None
        self.id_map = []  # Maps FAISS index position to database row id
        self.k_rrf = 60  # RRF parameter

        if DEPS_AVAILABLE:
            self.model = SentenceTransformer(model_name)
        else:
            self.model = None
            self.faiss_index = None

        self._init_database()

    def _init_database(self):
        """Initialize database connection and ensure FTS5 table exists."""
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database not found at {self.db_path}")

        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row

        # Check if FTS5 table exists, create if not
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name=?
        """, (self.fts_table,))
        if not cursor.fetchone():
            self._create_fts_table()
        cursor.close()

    def _create_fts_table(self):
        """Create FTS5 virtual table for full-text search."""
        cursor = self.conn.cursor()
        # Create FTS5 table on the text content
        cursor.execute(f"""
            CREATE VIRTUAL TABLE {self.fts_table} USING fts5(
                text,
                content='chunks',
                content_rowid='id'
            )
        """)
        # Populate the FTS table with existing data
        cursor.execute(f"""
            INSERT INTO {self.fts_table}(rowid, text)
            SELECT id, text FROM chunks
        """)
        self.conn.commit()
        cursor.close()

    def _ensure_faiss_index(self, dimension: int):
        """Ensure FAISS index is initialized with given dimension."""
        if not DEPS_AVAILABLE:
            return
        if self.faiss_index is None:
            # Using Inner Product (IP) for cosine similarity with normalized vectors
            self.faiss_index = faiss.IndexFlatIP(dimension)
            self.id_map = []

    def add_chunk_to_indexes(self, row_id: int, text: str):
        """Add a single chunk to both FTS and FAISS indexes."""
        # FTS is already populated via triggers or we can insert directly
        # We'll use the FTS table's ability to sync with content table via triggers?
        # For simplicity, we'll rebuild FTS when needed or use incremental insert.
        # Since we are adding after ingestion, we can insert into FTS.
        cursor = self.conn.cursor()
        cursor.execute(f"""
            INSERT INTO {self.fts_table}(rowid, text)
            VALUES (?, ?)
        """, (row_id, text))
        self.conn.commit()
        cursor.close()

        # FAISS indexing
        if DEPS_AVAILABLE and self.model is not None:
            embedding = self.model.encode([text], normalize_embeddings=True)
            if self.faiss_index is None:
                self._ensure_faiss_index(embedding.shape[1])
            self.faiss_index.add(embedding.astype('float32'))
            self.id_map.append(row_id)

    def add_chunks(self, chunks: List[Tuple[str, int, str, str, str]]) -> None:
        """
        Add multiple chunks to the database and update indexes incrementally.
        chunks: list of tuples (filename, page_number, section_title, chunk_id, text)
        """
        if not chunks:
            return
        cursor = self.conn.cursor()
        # Insert all chunks into the database
        cursor.executemany("""
            INSERT INTO chunks (filename, page_number, section_title, chunk_id, text)
            VALUES (?, ?, ?, ?, ?)
        """, chunks)
        self.conn.commit()
        # Get the inserted row ids (assuming they are inserted in the same order as chunks)
        # We need to retrieve the ids for the inserted rows. Since we don't have a way to get them directly,
        # we can query for the rows we just inserted by matching the chunk_id values we know.
        # However, chunk_id may not be unique if we don't enforce uniqueness. We'll assume chunk_id is unique.
        # We'll fetch the ids for the given chunk_ids.
        chunk_ids = [c[3] for c in chunks]  # chunk_id is the 4th element (0-indexed)
        # Build a query to get ids for these chunk_ids
        if chunk_ids:
            placeholders = ','.join(['?'] * len(chunk_ids))
            cursor.execute(f"""
                SELECT id, chunk_id FROM chunks WHERE chunk_id IN ({placeholders})
            """, chunk_ids)
            rows = cursor.fetchall()
            # Map chunk_id to id
            id_map = {row['chunk_id']: row['id'] for row in rows}
            # Now add each chunk to indexes
            for filename, page_num, section_title, chunk_id, text in chunks:
                row_id = id_map.get(chunk_id)
                if row_id is not None:
                    self.add_chunk_to_indexes(row_id, text)
                else:
                    # This should not happen if chunk_id is unique and we just inserted them
                    pass
        cursor.close()

    def delete_chunks_by_filename(self, filename: str) -> int:
        """
        Delete all chunks with the given filename from the database and indexes.
        Returns the number of chunks deleted.
        """
        cursor = self.conn.cursor()
        # First, get the ids of chunks to delete
        cursor.execute("SELECT id FROM chunks WHERE filename = ?", (filename,))
        ids_to_delete = [row[0] for row in cursor.fetchall()]
        if not ids_to_delete:
            cursor.close()
            return 0
        # Delete from chunks table
        cursor.execute("DELETE FROM chunks WHERE filename = ?", (filename,))
        # Delete from FTS table
        cursor.execute(f"DELETE FROM {self.fts_table} WHERE rowid IN ({','.join(['?']*len(ids_to_delete))})", ids_to_delete)
        # For FAISS, we cannot easily delete specific vectors; we will rebuild the index from remaining chunks
        # However, if DEPS_AVAILABLE is False, we skip FAISS handling.
        if DEPS_AVAILABLE:
            # We'll rebuild the FAISS index from the remaining chunks
            # First, get all remaining chunks
            cursor.execute("SELECT id, text FROM chunks ORDER BY id")
            remaining_rows = cursor.fetchall()
            if remaining_rows:
                # Rebuild FAISS index
                texts = [row['text'] for row in remaining_rows]
                row_ids = [row['id'] for row in remaining_rows]
                embeddings = self.model.encode(texts, normalize_embeddings=True) if self.model is not None else None
                if embeddings is not None:
                    dimension = embeddings.shape[1]
                    self._ensure_faiss_index(dimension)
                    # Reset index and id_map
                    self.faiss_index.reset()
                    self.id_map = []
                    self.faiss_index.add(embeddings.astype('float32'))
                    self.id_map = row_ids
            else:
                # No remaining chunks: reset index
                self.faiss_index = None
                self.id_map = []
        self.conn.commit()
        cursor.close()
        return len(ids_to_delete)

    def get_chunks_by_filename(self, filename: str) -> List[Dict[str, Any]]:
        """Get all chunks for a given filename."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, filename, page_number, section_title, chunk_id, text
            FROM chunks
            WHERE filename = ?
        """, (filename,))
        rows = cursor.fetchall()
        cursor.close()
        return [
            {
                'id': row['id'],
                'filename': row['filename'],
                'page_number': row['page_number'],
                'section_title': row['section_title'],
                'chunk_id': row['chunk_id'],
                'text': row['text']
            }
            for row in rows
        ]

    def build_indexes_from_db(self):
        """Build or rebuild both indexes from the chunks table."""
        cursor = self.conn.cursor()
        # Clear existing FTS table and repopulate
        cursor.execute(f"DELETE FROM {self.fts_table}")
        cursor.execute(f"""
            INSERT INTO {self.fts_table}(rowid, text)
            SELECT id, text FROM chunks
        """)
        self.conn.commit()

        # Build FAISS index
        if DEPS_AVAILABLE and self.model is not None:
            # Get all chunks
            cursor.execute("SELECT id, text FROM chunks ORDER BY id")
            rows = cursor.fetchall()
            if rows:
                texts = [row['text'] for row in rows]
                row_ids = [row['id'] for row in rows]
                embeddings = self.model.encode(texts, normalize_embeddings=True)
                dimension = embeddings.shape[1]
                self._ensure_faiss_index(dimension)
                # Reset index and id_map
                self.faiss_index.reset()
                self.id_map = []
                self.faiss_index.add(embeddings.astype('float32'))
                self.id_map = row_ids
            else:
                # No chunks, create empty index with default dimension? We'll use 384 for MiniLM
                self._ensure_faiss_index(384)
        cursor.close()

    def lexical_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Perform lexical search using FTS5."""
        cursor = self.conn.cursor()
        # Use FTS5 to search and join with chunks table to get metadata
        cursor.execute(f"""
            SELECT chunks.id, chunks.filename, chunks.page_number,
                   chunks.section_title, chunks.chunk_id, chunks.text,
                   bm25({self.fts_table}) as score
            FROM {self.fts_table}
            JOIN chunks ON chunks.id = {self.fts_table}.rowid
            WHERE {self.fts_table} MATCH ?
            ORDER BY score
            LIMIT ?
        """, (query, limit))
        results = []
        for row in cursor.fetchall():
            results.append({
                'id': row['id'],
                'filename': row['filename'],
                'page_number': row['page_number'],
                'section_title': row['section_title'],
                'chunk_id': row['chunk_id'],
                'text': row['text'],
                'lexical_score': float(row['score']) if row['score'] is not None else 0.0,
                'search_type': 'lexical'
            })
        cursor.close()
        return results

    def dense_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Perform dense vector search using FAISS."""
        if not DEPS_AVAILABLE or self.model is None or self.faiss_index is None:
            return []

        query_embedding = self.model.encode([query], normalize_embeddings=True)
        distances, indices = self.faiss_index.search(
            query_embedding.astype('float32'), limit
        )

        results = []
        for i, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            if idx < 0 or idx >= len(self.id_map):
                continue
            row_id = self.id_map[idx]
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT id, filename, page_number, section_title, chunk_id, text
                FROM chunks WHERE id = ?
            """, (row_id,))
            row = cursor.fetchone()
            cursor.close()
            if row:
                results.append({
                    'id': row['id'],
                    'filename': row['filename'],
                    'page_number': row['page_number'],
                    'section_title': row['section_title'],
                    'chunk_id': row['chunk_id'],
                    'text': row['text'],
                    'dense_score': float(dist),  # Inner product, higher is better
                    'search_type': 'dense',
                    'rank': i
                })
        return results

    def hybrid_search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Perform hybrid search using Reciprocal Rank Fusion (RRF)."""
        # Get results from both searchers
        lexical_results = self.lexical_search(query, limit=limit*2)  # Get more for fusion
        dense_results = self.dense_search(query, limit=limit*2)

        # Create maps for scoring
        scores = {}
        # Process lexical results
        for rank, result in enumerate(lexical_results, start=1):
            doc_id = result['id']
            rrf_score = 1.0 / (self.k_rrf + rank)
            if doc_id not in scores:
                scores[doc_id] = {'score': 0.0, 'doc': result}
            scores[doc_id]['score'] += rrf_score

        # Process dense results
        for rank, result in enumerate(dense_results, start=1):
            doc_id = result['id']
            rrf_score = 1.0 / (self.k_rrf + rank)
            if doc_id not in scores:
                scores[doc_id] = {'score': 0.0, 'doc': result}
            scores[doc_id]['score'] += rrf_score

        # Sort by combined RRF score descending
        sorted_docs = sorted(scores.values(), key=lambda x: x['score'], reverse=True)

        # Format final results
        final_results = []
        for item in sorted_docs[:limit]:
            doc = item['doc']
            doc['hybrid_score'] = item['score']
            doc['search_type'] = 'hybrid'
            # Remove internal scores if desired, but we keep them for debugging
            final_results.append(doc)

        return final_results

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

# Convenience function for quick search
def search(query: str, db_path: str = "data/app.db", limit: int = 10) -> List[Dict[str, Any]]:
    """Perform a hybrid search on the given query."""
    retriever = HybridRetriever(db_path)
    try:
        return retriever.hybrid_search(query, limit)
    finally:
        retriever.close()

# Alias for compatibility with generator
def hybrid_search(query: str, db_path: str = "data/app.db", limit: int = 10) -> List[Dict[str, Any]]:
    """Alias for search function."""
    return search(query, db_path, limit)