import json
import requests
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ValidationError

# Import the hybrid search function from retriever
try:
    from lecture_auditor.retriever import hybrid_search
except ImportError:
    # Fallback if running from within the lecture_auditor directory
    from lecture_auditor.retriever import hybrid_search

# Import configuration
from lecture_auditor.config import config

# Pydantic model for validating the LLM output
class GeneratedAnswer(BaseModel):
    answer: str = Field(..., description="The generated answer string with inline citations")
    citations: List[int] = Field(..., description="List of unique source numbers cited in the answer")

    @classmethod
    def validate_json(cls, json_str: str) -> "GeneratedAnswer":
        """Parse and validate a JSON string from the LLM."""
        try:
            data = json.loads(json_str)
            return cls(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"Invalid LLM output: {e}")

class AnswerGenerator:
    def __init__(self,
                 endpoint_url: Optional[str] = None,
                 model_name: Optional[str] = None,
                 temperature: float = 0.0,
                 max_tokens: int = 500,
                 top_k: int = 5):
        """
        Initialize the answer generator.

        Args:
            endpoint_url: Base URL of the OpenAI-compatible API (defaults to config)
            model_name: Model name to use for generation (defaults to config)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            top_k: Number of retrieval results to use as context
        """
        self.endpoint_url = (endpoint_url or config.LLM_BASE_URL).rstrip('/')
        self.model_name = (model_name or config.LLM_MODEL)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_k = top_k
        self.session = requests.Session()

    def _format_context(self, search_results: List[Dict[str, Any]]) -> str:
        """Format search results into a context string with source numbers."""
        context_lines = []
        for i, result in enumerate(search_results, start=1):
            # Create a source identifier
            source_info = f"[Source {i}]"
            metadata = []
            if result.get('filename'):
                metadata.append(f"filename={result['filename']}")
            if result.get('page_number') is not None:
                metadata.append(f"page={result['page_number']}")
            if result.get('section_title'):
                metadata.append(f"section={result['section_title']}")
            metadata_str = ", ".join(metadata)
            text = result.get('text', '').strip()
            context_lines.append(f"{source_info} ({metadata_str}): {text}")
        return "\n\n".join(context_lines)

    def _build_prompt(self, question: str, context: str) -> str:
        """Build the prompt for the LLM with strict grounding instructions."""
        prompt = f"""Answer the question based ONLY on the following sources. Do not use any external knowledge.
For each sentence in your answer, cite the source(s) used by mentioning the source number in square brackets.
If you cannot answer the question based on the sources, say "I cannot answer based on the provided sources."

Sources:
{context}

Question: {question}

Provide your answer as a JSON object with two fields:
- "answer": a string containing your answer with inline citations like [1] or [1,2]
- "citations": a list of unique source numbers that were cited in the answer

Example:
{{
  "answer": "The mitochondria is the powerhouse of the cell [1].",
  "citations": [1]
}}
"""
        return prompt

    def _call_llm(self, prompt: str) -> str:
        """Call the local OpenAI-compatible endpoint."""
        url = f"{self.endpoint_url}/chat/completions"
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        try:
            response = self.session.post(url, json=payload, timeout=config.LLM_TIMEOUT)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Failed to connect to LLM endpoint at {self.endpoint_url}: {e}")
        result = response.json()
        # Extract the generated text
        if "choices" in result and len(result["choices"]) > 0:
            message = result["choices"][0].get("message", {})
            return message.get("content", "").strip()
        else:
            raise ValueError("Unexpected response format from LLM endpoint")

    def generate_answer(self, question: str) -> GeneratedAnswer:
        """
        Generate a grounded answer to the question.

        Returns:
            GeneratedAnswer: Pydantic validated answer with citations
        """
        # Step 1: Retrieve relevant context using hybrid search
        search_results = hybrid_search(question, limit=self.top_k)
        if not search_results:
            # If no results, return a default answer indicating lack of context
            return GeneratedAnswer(
                answer="I cannot answer based on the provided sources.",
                citations=[]
            )

        # Step 2: Format context
        context = self._format_context(search_results)

        # Step 3: Build prompt
        prompt = self._build_prompt(question, context)

        # Step 4: Call LLM
        llm_output = self._call_llm(prompt)

        # Step 5: Parse and validate with Pydantic
        try:
            answer = GeneratedAnswer.validate_json(llm_output)
            return answer
        except ValueError as e:
            # If validation fails, we can try to extract answer and citations naively?
            # For simplicity, we'll raise an error; in production we might retry or fallback.
            raise ValueError(f"Failed to validate LLM output: {e}. Output was: {llm_output}")

    def close(self):
        """Close the requests session."""
        self.session.close()

# Convenience function for quick generation
def generate_answer(question: str,
                   endpoint_url: Optional[str] = None,
                   model_name: Optional[str] = None) -> GeneratedAnswer:
    """
    Generate a grounded answer to a question using default settings.

    Args:
        question: The question to answer
        endpoint_url: Base URL of the OpenAI-compatible API (defaults to config)
        model_name: Model name to use (defaults to config)

    Returns:
        GeneratedAnswer: Pydantic validated answer
    """
    generator = AnswerGenerator(endpoint_url=endpoint_url, model_name=model_name)
    try:
        return generator.generate_answer(question)
    finally:
        generator.close()