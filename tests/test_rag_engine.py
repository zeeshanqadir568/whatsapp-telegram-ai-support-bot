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


@pytest.mark.parametrize(
    "text, expected",
    [
        ("call me at +1 555-123-4567 please", "+1 555-123-4567"),
        ("mera number 0300 1234567 hai", "0300 1234567"),
        ("WhatsApp: +92 321 7654321", "+92 321 7654321"),
        ("order 12345 arrived", None),  # too short to be a phone number
    ],
)
def test_lead_heuristics_extract_full_phone_number(text, expected):
    engine = RAGEngine.__new__(RAGEngine)  # heuristics need no vector store or LLM
    lead = engine._extract_lead_heuristics(text)
    assert lead["phone"] == expected
    assert lead["has_lead"] is (expected is not None)


class _ScriptedLLM:
    """Returns canned replies in order and records the prompts it was given."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def generate_response(self, system_prompt, user_prompt):
        self.prompts.append(system_prompt)
        return self.replies.pop(0)


class _NoDocs:
    def similarity_search(self, query, top_k=3):
        return []


def _engine_with(llm):
    engine = RAGEngine.__new__(RAGEngine)
    engine.vector_manager = _NoDocs()
    engine.llm_provider = llm
    return engine


def test_devanagari_reply_is_retried_in_latin_script():
    llm = _ScriptedLLM("हम रविवार को बंद हैं।", "Hum Itwaar ko band hote hain.")
    reply, _, _ = _engine_with(llm).answer_query("Aap Sunday ko khulay hain?")
    assert reply == "Hum Itwaar ko band hote hain."
    assert "English letters only" in llm.prompts[1]


def test_devanagari_twice_falls_back_to_safe_reply():
    llm = _ScriptedLLM("हम बंद हैं।", "फिर से हिंदी।")
    reply, _, _ = _engine_with(llm).answer_query("Aap Sunday ko khulay hain?")
    assert "our team will help you" in reply


def test_latin_reply_is_not_retried():
    llm = _ScriptedLLM("We are closed on Sundays.")
    reply, _, _ = _engine_with(llm).answer_query("Are you open on Sunday?")
    assert reply == "We are closed on Sundays." and len(llm.prompts) == 1
