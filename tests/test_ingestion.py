import os
import sys
import sqlite3
import tempfile
from unittest.mock import Mock, patch

# Add the lecture_auditor directory to the path so we can import ingestion
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lecture_auditor'))

import lecture_auditor.ingestion as ingestion

def test_init_db_creates_table(tmp_path):
    """Test that init_db creates the chunks table."""
    db_path = tmp_path / "test.db"
    ingestion.init_db(str(db_path))

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'")
    table_exists = cursor.fetchone()
    conn.close()

    assert table_exists is not None, "Chunks table should be created"

def test_is_heading():
    """Test the heading detection heuristic."""
    assert ingestion.is_heading("INTRODUCTION") == True
    assert ingestion.is_heading("CONCLUSION:") == True
    assert ingestion.is_heading("This is a normal sentence.") == False
    assert ingestion.is_heading("") == False
    assert ingestion.is_heading("   ") == False
    # Long all caps line should not be heading (too long)
    long_line = "A" * 60
    assert ingestion.is_heading(long_line) == False

@patch('lecture_auditor.ingestion.PdfReader')
def test_extract_chunks_from_pdf(mock_pdf_reader, tmp_path):
    """Test chunk extraction from a mocked PDF."""
    # Setup mock PDF with two pages
    mock_page1 = Mock()
    mock_page1.extract_text.return_value = (
        "INTRODUCTION\n"
        "This is the first chunk.\n"
        "It spans two lines.\n"
        "\n"
        "METHODS:\n"
        "This is the second chunk.\n"
    )
    mock_page2 = Mock()
    mock_page2.extract_text.return_value = (
        "RESULTS:\n"
        "Found something interesting.\n"
        "\n"
        "CONCLUSION:\n"
        "We finished.\n"
    )

    mock_reader_instance = Mock()
    mock_reader_instance.pages = [mock_page1, mock_page2]
    mock_pdf_reader.return_value = mock_reader_instance

    # Create a dummy PDF file path (won't be actually read due to mock)
    pdf_path = str(tmp_path / "dummy.pdf")

    chunks = ingestion.extract_chunks_from_pdf(pdf_path)

    # We expect chunks:
    # Page 1:
    #   Heading: INTRODUCTION -> section becomes INTRODUCTION
    #   Lines: "This is the first chunk.", "It spans two lines." -> chunk1
    #   Empty line -> not accumulated
    #   Heading: METHODS: -> section becomes METHODS:
    #   Lines: "This is the second chunk." -> chunk2
    # Page 2:
    #   Heading: RESULTS: -> section becomes RESULTS:
    #   Lines: "Found something interesting." -> chunk3
    #   Heading: CONCLUSION: -> section becomes CONCLUSION:
    #   Lines: "We finished." -> chunk4
    expected_chunks = [
        ("dummy.pdf", 1, "INTRODUCTION", "1_0", "This is the first chunk.\nIt spans two lines."),
        ("dummy.pdf", 1, "METHODS:", "1_1", "This is the second chunk."),
        ("dummy.pdf", 2, "RESULTS:", "2_0", "Found something interesting."),
        ("dummy.pdf", 2, "CONCLUSION:", "2_1", "We finished."),
    ]

    assert len(chunks) == len(expected_chunks)
    for i, (filename, page_num, section, chunk_id, text) in enumerate(chunks):
        exp_filename, exp_page, exp_section, exp_chunk_id, exp_text = expected_chunks[i]
        assert filename == exp_filename
        assert page_num == exp_page
        assert section == exp_section
        assert chunk_id == exp_chunk_id
        assert text == exp_text

def test_ingest_pdf_inserts_into_db(tmp_path):
    """Test that ingest_pdf inserts data into the database."""
    db_path = tmp_path / "test.db"
    # Create a dummy PDF file (we'll mock PdfReader)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 dummy")  # just to have a file

    # Mock PdfReader to return known text
    mock_page = Mock()
    mock_page.extract_text.return_value = (
        "HEADER:\n"
        "Chunk text here.\n"
    )

    with patch('lecture_auditor.ingestion.PdfReader') as mock_pdf_reader:
        mock_reader_instance = Mock()
        mock_reader_instance.pages = [mock_page]
        mock_pdf_reader.return_value = mock_reader_instance

        # Call ingest_pdf with our temporary paths
        ingestion.ingest_pdf(str(pdf_path), str(db_path))

    # Check the database
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT filename, page_number, section_title, chunk_id, text FROM chunks")
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 1
    filename, page_num, section, chunk_id, text = rows[0]
    assert os.path.basename(str(pdf_path)) == filename
    assert page_num == 1
    assert section == "HEADER:"
    assert chunk_id == "1_0"
    assert text == "Chunk text here."