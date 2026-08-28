"""Unit tests for the RAG engine module.
"""

import os
import shutil
import pytest
from rag_engine import DocumentIngestor, VectorStoreManager, RAGEngine, LLMProvider


@pytest.fixture
def temp_chroma_dir(tmp_path):
    """Fixture providing a clean temporary directory for ChromaDB."""
    dir_path = str(tmp_path / "chroma_test")
    yield dir_path
    if os.path.exists(dir_path):
        shutil.rmtree(dir_path, ignore_errors=True)


def test_document_ingestor_split_text():
    """Tests splitting raw text into document chunks."""
    ingestor = DocumentIngestor(chunk_size=100, chunk_overlap=10)
    sample_text = "This is sentence one. " * 10
    chunks = ingestor.split_text(sample_text, source_name="test_source")
    assert len(chunks) > 0
    assert chunks[0].metadata["source"] == "test_source"


def test_vector_store_manager_add_and_search(temp_chroma_dir):
    """Tests document addition and similarity search in ChromaDB."""
    vector_mgr = VectorStoreManager(persist_directory=temp_chroma_dir)
    ingestor = DocumentIngestor()
    chunks = ingestor.split_text("Apex Dental Clinic is open Monday to Friday 9am to 6pm.", source_name="hours.txt")
    
    vector_mgr.add_documents(chunks)
    assert vector_mgr.get_document_count() > 0

    results = vector_mgr.similarity_search("What are the clinic opening hours?", top_k=1)
    assert len(results) == 1
    assert "9am to 6pm" in results[0].page_content


def test_llm_provider_initialization():
    """Tests LLMProvider initialization and fallback provider detection."""
    provider = LLMProvider()
    assert provider.active_provider in ["anthropic", "ollama"]


def test_rag_engine_lead_extraction():
    """Tests lead phone and email extraction from user input."""
    engine = RAGEngine()
    lead_info = engine._extract_lead_heuristics("Hi, please call me at john@example.com or +15551234567")
    assert lead_info["has_lead"] is True
    assert lead_info["email"] == "john@example.com"
