import os
import sys
import tempfile
import sqlite3
from unittest.mock import Mock, patch, MagicMock

# Add lecture_auditor to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lecture_auditor'))

import lecture_auditor.retriever as retriever

def test_init_creates_connection_and_fts_table(tmp_path):
    """Test that HybridRetriever initializes DB connection and ensures FTS table."""
    db_path = tmp_path / "test.db"
    # Create a minimal database with chunks table
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            page_number INTEGER,
            section_title TEXT,
            chunk_id TEXT,
            text TEXT
        )
    """)
    conn.commit()
    conn.close()

    # Initialize retriever
    ret = retriever.HybridRetriever(db_path=str(db_path))
    assert ret.conn is not None
    # Check that FTS table exists
    cursor = ret.conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='chunks_fts'
    """)
    table = cursor.fetchone()
    cursor.close()
    assert table is not None, "FTS table should be created"
    ret.close()

def test_add_chunk_to_indexes(tmp_path):
    """Test adding a chunk to both FTS and FAISS indexes."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            page_number INTEGER,
            section_title TEXT,
            chunk_id TEXT,
            text TEXT
        )
    """)
    # Insert a chunk to get an ID
    conn.execute("""
        INSERT INTO chunks (filename, page_number, section_title, chunk_id, text)
        VALUES (?, ?, ?, ?, ?)
    """, ("test.pdf", 1, "INTRO", "1_0", "This is test text."))
    conn.commit()
    conn.close()

    # Initialize retriever
    ret = retriever.HybridRetriever(db_path=str(db_path))

    # Add the chunk to indexes (we know the row id is 1)
    ret.add_chunk_to_indexes(1, "This is test text.")

    # Check FTS table has entry
    cursor = ret.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM chunks_fts WHERE rowid=1")
    count = cursor.fetchone()[0]
    cursor.close()
    assert count == 1, "FTS table should have one entry for the chunk"

    # If dependencies are available, check FAISS
    if retriever.DEPS_AVAILABLE:
        assert ret.faiss_index is not None
        assert ret.faiss_index.ntotal == 1
        assert ret.id_map == [1]
    else:
        # If deps not available, FAISS should be None
        assert ret.faiss_index is None
        assert ret.id_map == []

    ret.close()

def test_build_indexes_from_db(tmp_path):
    """Test building indexes from existing database."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            page_number INTEGER,
            section_title TEXT,
            chunk_id TEXT,
            text TEXT
        )
    """)
    # Insert two chunks
    conn.executemany("""
        INSERT INTO chunks (filename, page_number, section_title, chunk_id, text)
        VALUES (?, ?, ?, ?, ?)
    """, [
        ("test1.pdf", 1, "INTRO", "1_0", "First chunk text."),
        ("test2.pdf", 2, "METHODS", "2_0", "Second chunk text.")
    ])
    conn.commit()
    conn.close()

    ret = retriever.HybridRetriever(db_path=str(db_path))
    ret.build_indexes_from_db()

    # Check FTS table has both entries
    cursor = ret.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM chunks_fts")
    count = cursor.fetchone()[0]
    cursor.close()
    assert count == 2, "FTS table should have two entries"

    # Check FAISS if deps available
    if retriever.DEPS_AVAILABLE:
        assert ret.faiss_index is not None
        assert ret.faiss_index.ntotal == 2
        assert set(ret.id_map) == {1, 2}
    else:
        assert ret.faiss_index is None

    ret.close()

def test_lexical_search(tmp_path):
    """Test lexical search using FTS5."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            page_number INTEGER,
            section_title TEXT,
            chunk_id TEXT,
            text TEXT
        )
    """)
    conn.executemany("""
        INSERT INTO chunks (filename, page_number, section_title, chunk_id, text)
        VALUES (?, ?, ?, ?, ?)
    """, [
        ("test.pdf", 1, "INTRO", "1_0", "The quick brown fox"),
        ("test.pdf", 1, "INTRO", "1_1", "Jumps over the lazy dog")
    ])
    conn.commit()
    conn.close()

    # Import inside to ensure patches apply
    import lecture_auditor.retriever as retriever_local
    ret = retriever_local.HybridRetriever(db_path=str(db_path))
    # Build FTS table (already done in init, but we ensure)
    # Actually, the FTS table is created in _init_database, but we need to populate it.
    # The _init_database creates the FTS table and inserts existing chunks.
    # So we can search directly.

    results = ret.lexical_search("quick brown", limit=5)
    assert len(results) == 1
    assert results[0]['filename'] == "test.pdf"
    assert results[0]['text'] == "The quick brown fox"
    assert 'lexical_score' in results[0]

    ret.close()

def test_dense_search(tmp_path):
    """Test dense search with mocked dependencies."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            page_number INTEGER,
            section_title TEXT,
            chunk_id TEXT,
            text TEXT
        )
    """)
    conn.executemany("""
        INSERT INTO chunks (filename, page_number, section_title, chunk_id, text)
        VALUES (?, ?, ?, ?, ?)
    """, [
        ("test.pdf", 1, "INTRO", "1_0", "First chunk"),
        ("test.pdf", 1, "INTRO", "1_1", "Second chunk")
    ])
    conn.commit()
    conn.close()

    # Import inside to ensure patches apply
    import lecture_auditor.retriever as retriever_local
    from unittest.mock import Mock

    # Create retriever instance
    ret = retriever_local.HybridRetriever(db_path=str(db_path))

    # Override DEPS_AVAILABLE to True to ensure we use the FAISS path
    retriever_local.DEPS_AVAILABLE = True
    # Provide a mock model that returns a fixed embedding
    mock_model = Mock()
    mock_model.encode.return_value = Mock()
    mock_model.encode.return_value.astype.return_value = Mock()
    ret.model = mock_model
    # Provide a mock faiss index that returns predefined search results
    mock_index = Mock()
    mock_index.search.return_value = (
        [[0.9, 0.8]],  # distances
        [[0, 1]]       # indices
    )
    ret.faiss_index = mock_index
    # Set up id_map to map index positions to chunk IDs
    ret.id_map = [1, 2]  # assuming two chunks in the database

    # Now perform the search
    results = ret.dense_search("test query", limit=2)

    # We expect two results
    assert len(results) == 2
    # Check that the results have dense_score
    for res in results:
        assert 'dense_score' in res
        assert res['search_type'] == 'dense'

    # Clean up is not necessary as the instance is local

def test_hybrid_search_rrf(tmp_path):
    """Test hybrid search combines results using RRF."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            page_number INTEGER,
            section_title TEXT,
            chunk_id TEXT,
            text TEXT
        )
    """)
    conn.executemany("""
        INSERT INTO chunks (filename, page_number, section_title, chunk_id, text)
        VALUES (?, ?, ?, ?, ?)
    """, [
        ("test.pdf", 1, "INTRO", "1_0", "Apple banana"),
        ("test.pdf", 1, "INTRO", "1_1", "Banana cherry"),
        ("test.pdf", 1, "INTRO", "1_2", "Cherry date")
    ])
    conn.commit()
    conn.close()

    ret = retriever.HybridRetriever(db_path=str(db_path))

    # Mock the lexical and dense search methods to return controlled results
    # We'll patch the instance methods
    def mock_lexical(query, limit=10):
        # Return two results in order: id 1, then id 2
        if "apple" in query.lower():
            return [
                {'id': 1, 'filename': 'test.pdf', 'page_number': 1, 'section_title': 'INTRO', 'chunk_id': '1_0', 'text': 'Apple banana'},
                {'id': 2, 'filename': 'test.pdf', 'page_number': 1, 'section_title': 'INTRO', 'chunk_id': '1_1', 'text': 'Banana cherry'}
            ]
        return []

    def mock_dense(query, limit=10):
        # Return two results in order: id 2, then id 3
        if "cherry" in query.lower():
            return [
                {'id': 2, 'filename': 'test.pdf', 'page_number': 1, 'section_title': 'INTRO', 'chunk_id': '1_1', 'text': 'Banana cherry', 'dense_score': 0.9},
                {'id': 3, 'filename': 'test.pdf', 'page_number': 1, 'section_title': 'INTRO', 'chunk_id': '1_2', 'text': 'Cherry date', 'dense_score': 0.8}
            ]
        return []

    ret.lexical_search = mock_lexical
    ret.dense_search = mock_dense

    # Search for something that triggers both
    results = ret.hybrid_search("apple cherry", limit=3)

    # We expect three results, but let's see the ordering via RRF
    # For query "apple cherry":
    # Lexical: apple banana (rank1), banana cherry (rank2)
    # Dense: banana cherry (rank1), cherry date (rank2)
    # Compute RRF scores:
    # id1: lexical rank1 -> 1/(60+1) = 1/61 ≈ 0.0164
    # id2: lexical rank2 + dense rank1 -> 1/(60+2) + 1/(60+1) = 1/62 + 1/61 ≈ 0.0161 + 0.0164 = 0.0325
    # id3: dense rank2 -> 1/(60+2) = 1/62 ≈ 0.0161
    # So order should be id2, id1, id3
    assert len(results) == 3
    assert results[0]['id'] == 2  # banana cherry
    assert results[1]['id'] == 1  # apple banana
    assert results[2]['id'] == 3  # cherry date
    # Check that hybrid_score is present
    for res in results:
        assert 'hybrid_score' in res
        assert res['search_type'] == 'hybrid'

    ret.close()

def test_search_convenience_function(tmp_path):
    """Test the convenience search function."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE chunks (
            id INTEGER PRIMARY KEY,
            filename TEXT,
            page_number INTEGER,
            section_title TEXT,
            chunk_id TEXT,
            text TEXT
        )
    """)
    conn.execute("""
        INSERT INTO chunks (filename, page_number, section_title, chunk_id, text)
        VALUES (?, ?, ?, ?, ?)
    """, ("test.pdf", 1, "INTRO", "1_0", "Test document"))
    conn.commit()
    conn.close()

    # We'll patch the HybridRetriever class to avoid heavy dependencies
    original_init = retriever.HybridRetriever.__init__
    original_hybrid = retriever.HybridRetriever.hybrid_search

    def mock_init(self, db_path="data/app.db", model_name="all-MiniLM-L6-v2"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        # Don't initialize model or faiss to keep it light

    def mock_hybrid(self, query, limit=10):
        return [
            {'id': 1, 'filename': 'test.pdf', 'page_number': 1, 'section_title': 'INTRO', 'chunk_id': '1_0', 'text': 'Test document', 'hybrid_score': 0.5}
        ]

    retriever.HybridRetriever.__init__ = mock_init
    retriever.HybridRetriever.hybrid_search = mock_hybrid

    try:
        results = retriever.search("test", db_path=str(db_path), limit=5)
        assert len(results) == 1
        assert results[0]['text'] == "Test document"
    finally:
        retriever.HybridRetriever.__init__ = original_init
        retriever.HybridRetriever.hybrid_search = original_hybrid

if __name__ == "__main__":
    # Simple test runner for debugging
    import pytest
    pytest.main([__file__, "-v"])