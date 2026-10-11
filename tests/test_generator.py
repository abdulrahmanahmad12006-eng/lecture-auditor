import os
import sys
import json
from unittest.mock import Mock, patch

# Add lecture_auditor to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lecture_auditor'))

import lecture_auditor.generator as generator

def test_format_context():
    """Test formatting of search results into context string."""
    gen = generator.AnswerGenerator()
    search_results = [
        {
            'filename': 'test.pdf',
            'page_number': 1,
            'section_title': 'Introduction',
            'text': 'This is the first chunk.'
        },
        {
            'filename': 'test.pdf',
            'page_number': 2,
            'section_title': 'Methods',
            'text': 'This is the second chunk.'
        }
    ]
    context = gen._format_context(search_results)
    assert '[Source 1]' in context
    assert 'filename=test.pdf' in context
    assert 'page=1' in context
    assert 'section=Introduction' in context
    assert 'This is the first chunk.' in context
    assert '[Source 2]' in context
    assert 'page=2' in context
    assert 'section=Methods' in context
    assert 'This is the second chunk.' in context
    gen.close()

def test_build_prompt():
    """Test prompt building."""
    gen = generator.AnswerGenerator()
    context = "[Source 1] (filename=test.pdf): Hello world"
    question = "What is the greeting?"
    prompt = gen._build_prompt(question, context)
    assert question in prompt
    assert context in prompt
    assert "Answer the question based ONLY on the following sources" in prompt
    assert 'JSON object with two fields' in prompt
    # Check that the example JSON is present (with single braces)
    assert '{' in prompt and '}' in prompt
    assert '"answer": "The mitochondria is the powerhouse of the cell [1]."' in prompt
    assert '"citations": [1]' in prompt
    gen.close()

@patch('lecture_auditor.generator.requests.Session.post')
@patch('lecture_auditor.generator.hybrid_search')
def test_generate_answer_success(mock_hybrid_search, mock_post):
    """Test successful answer generation and validation."""
    # Mock hybrid_search to return two results
    mock_hybrid_search.return_value = [
        {
            'id': 1,
            'filename': 'lecture1.pdf',
            'page_number': 5,
            'section_title': 'Overview',
            'text': 'Photosynthesis is the process by which plants convert light energy into chemical energy.',
            'lexical_score': 0.8,
            'dense_score': 0.75
        },
        {
            'id': 2,
            'filename': 'lecture2.pdf',
            'page_number': 3,
            'section_title': 'Details',
            'text': 'Chlorophyll is the green pigment involved in photosynthesis.',
            'lexical_score': 0.6,
            'dense_score': 0.65
        }
    ]

    # Mock the LLM response to return a valid JSON
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "answer": "Photosynthesis converts light energy into chemical energy [1]. Chlorophyll is the green pigment involved [2].",
                    "citations": [1, 2]
                })
            }
        }]
    }
    mock_post.return_value = mock_response

    gen = generator.AnswerGenerator()
    answer = gen.generate_answer("What is photosynthesis?")
    gen.close()

    # Validate the returned object
    assert isinstance(answer, generator.GeneratedAnswer)
    assert "Photosynthesis converts light energy" in answer.answer
    assert answer.citations == [1, 2]
    # Ensure the hybrid_search was called
    mock_hybrid_search.assert_called_once_with("What is photosynthesis?", limit=5)
    # Ensure the LLM was called
    mock_post.assert_called_once()

@patch('lecture_auditor.generator.requests.Session.post')
@patch('lecture_auditor.generator.hybrid_search')
def test_generate_answer_no_context(mock_hybrid_search, mock_post):
    """Test generation when no search results are found."""
    mock_hybrid_search.return_value = []

    gen = generator.AnswerGenerator()
    answer = gen.generate_answer("Obscure question")
    gen.close()

    assert isinstance(answer, generator.GeneratedAnswer)
    assert answer.answer == "I cannot answer based on the provided sources."
    assert answer.citations == []
    mock_hybrid_search.assert_called_once_with("Obscure question", limit=5)
    # LLM should not be called
    mock_post.assert_not_called()

@patch('lecture_auditor.generator.requests.Session.post')
@patch('lecture_auditor.generator.hybrid_search')
def test_generate_answer_invalid_json(mock_hybrid_search, mock_post):
    """Test handling of invalid JSON from LLM."""
    mock_hybrid_search.return_value = [{
        'filename': 'test.pdf',
        'page_number': 1,
        'section_title': 'Intro',
        'text': 'Sample text.'
    }]

    # Mock LLM to return invalid JSON
    mock_response = Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "content": "Not a JSON"
            }
        }]
    }
    mock_post.return_value = mock_response

    gen = generator.AnswerGenerator()
    try:
        gen.generate_answer("Test question")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "Invalid LLM output" in str(e)
    finally:
        gen.close()

def test_convenience_function():
    """Test the convenience generate_answer function."""
    # We'll mock the AnswerGenerator class
    with patch('lecture_auditor.generator.AnswerGenerator') as mock_gen_class:
        mock_instance = Mock()
        mock_instance.generate_answer.return_value = generator.GeneratedAnswer(
            answer="Test answer",
            citations=[1]
        )
        mock_gen_class.return_value = mock_instance

        result = generator.generate_answer("Test question")
        assert isinstance(result, generator.GeneratedAnswer)
        assert result.answer == "Test answer"
        assert result.citations == [1]
        mock_gen_class.assert_called_once()
        mock_instance.generate_answer.assert_called_once_with("Test question")
        mock_instance.close.assert_called_once()

if __name__ == "__main__":
    # Simple test runner
    import pytest
    pytest.main([__file__, "-v"])