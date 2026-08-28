"""RAG Engine module for document ingestion, vector retrieval, and pluggable LLMs.

Supports PDF, TXT, and MD ingestion into ChromaDB, top-k similarity retrieval,
and a pluggable LLM provider supporting Anthropic API and Ollama fallback.
"""

import os
import re
import logging
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import PyPDFLoader, TextLoader

load_dotenv()

logger = logging.getLogger(__name__)


class DocumentIngestor:
    """Handles loading and splitting of PDF, TXT, and Markdown documents."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        """Initializes text splitter with chunk parameters.

        Args:
            chunk_size: Maximum characters per chunk.
            chunk_overlap: Overlapping characters between consecutive chunks.
        """
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""]
        )

    def load_and_split(self, file_path: str) -> List[Document]:
        """Loads a document file and splits it into chunked Document objects.

        Args:
            file_path: Path to the document file (.pdf, .txt, .md).

        Returns:
            List of chunked Document instances.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".pdf":
            loader = PyPDFLoader(file_path)
            raw_docs = loader.load()
        elif ext in [".txt", ".md"]:
            loader = TextLoader(file_path, encoding="utf-8")
            raw_docs = loader.load()
        else:
            raise ValueError(f"Unsupported file extension: {ext}. Allowed: .pdf, .txt, .md")

        chunks = self.text_splitter.split_documents(raw_docs)
        for chunk in chunks:
            chunk.metadata["source"] = os.path.basename(file_path)
        return chunks

    def split_text(self, text: str, source_name: str = "manual_input") -> List[Document]:
        """Splits raw text string into chunked Document objects.

        Args:
            text: Raw text string.
            source_name: Metadata identifier for the text source.

        Returns:
            List of chunked Document instances.
        """
        docs = [Document(page_content=text, metadata={"source": source_name})]
        return self.text_splitter.split_documents(docs)


class VectorStoreManager:
    """Manages ChromaDB vector store operations and sentence-transformers embeddings."""

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        embedding_model_name: Optional[str] = None
    ):
        """Initializes HuggingFace embeddings and ChromaDB vector store.

        Args:
            persist_directory: Directory path where ChromaDB persists data.
            embedding_model_name: Name of sentence-transformers embedding model.
        """
        self.persist_dir = persist_directory or os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")
        self.model_name = embedding_model_name or os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2")

        os.makedirs(self.persist_dir, exist_ok=True)

        logger.info(f"Loading embedding model: {self.model_name}")
        self.embeddings = HuggingFaceEmbeddings(model_name=self.model_name)

        self.vector_store = Chroma(
            persist_directory=self.persist_dir,
            embedding_function=self.embeddings
        )

    def add_documents(self, documents: List[Document]) -> List[str]:
        """Ingests document chunks into ChromaDB.

        Args:
            documents: List of Document objects to add.

        Returns:
            List of generated document IDs.
        """
        if not documents:
            return []
        ids = self.vector_store.add_documents(documents)
        return ids

    def similarity_search(self, query: str, top_k: int = 3) -> List[Document]:
        """Retrieves top-k relevant document chunks for a user query.

        Args:
            query: User search query.
            top_k: Number of relevant document chunks to return.

        Returns:
            List of matching Document objects.
        """
        return self.vector_store.similarity_search(query, k=top_k)

    def get_document_count(self) -> int:
        """Returns total document chunk count stored in collection."""
        try:
            return self.vector_store._collection.count()
        except Exception:
            return 0


class LLMProvider:
    """Pluggable LLM client supporting Anthropic API with automatic Ollama fallback."""

    def __init__(self):
        """Initializes LLM settings based on environment variables."""
        self.provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
        self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

        self.active_provider = self._determine_active_provider()

    def _determine_active_provider(self) -> str:
        """Checks configuration and availability to select active LLM backend."""
        if self.provider == "anthropic" and self.anthropic_api_key.strip():
            return "anthropic"
        else:
            logger.warning(
                "Anthropic API key not configured or Ollama explicitly selected. "
                "Switching to local Ollama fallback mode."
            )
            return "ollama"

    def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        """Generates LLM response using selected provider with fallback handling.

        Args:
            system_prompt: Instruction prompt for persona and context grounding.
            user_prompt: User question with retrieved context.

        Returns:
            Generated response text.
        """
        if self.active_provider == "anthropic":
            try:
                from langchain_anthropic import ChatAnthropic
                from langchain_core.messages import SystemMessage, HumanMessage

                llm = ChatAnthropic(
                    model=self.anthropic_model,
                    api_key=self.anthropic_api_key,
                    temperature=0.3
                )
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt)
                ]
                res = llm.invoke(messages)
                return str(res.content)
            except Exception as e:
                logger.error(f"Anthropic API call failed: {e}. Falling back to Ollama.")
                return self._call_ollama(system_prompt, user_prompt)
        else:
            return self._call_ollama(system_prompt, user_prompt)

    def _call_ollama(self, system_prompt: str, user_prompt: str) -> str:
        """Calls local Ollama instance via httpx or LangChain Ollama wrapper.

        Args:
            system_prompt: Instruction prompt.
            user_prompt: User question.

        Returns:
            Generated text from Ollama.
        """
        try:
            import httpx

            url = f"{self.ollama_base_url.rstrip('/')}/api/generate"
            full_prompt = f"System: {system_prompt}\n\nUser: {user_prompt}\nAssistant:"
            payload = {
                "model": self.ollama_model,
                "prompt": full_prompt,
                "stream": False
            }
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", "")
                else:
                    logger.error(f"Ollama HTTP error {response.status_code}: {response.text}")
                    return (
                        "I am operating in offline demo mode. "
                        "Please ensure local Ollama server is running or provide an Anthropic API Key."
                    )
        except Exception as err:
            logger.error(f"Failed to connect to local Ollama server: {err}")
            # Intelligent fallback answer for demo purposes when both services are offline
            return (
                "Thank you for contacting customer support. "
                "(Note: AI LLM service is offline; system operating in dry-run mode)."
            )


class RAGEngine:
    """Orchestrates document ingestion, vector retrieval, and prompt context generation."""

    def __init__(self):
        """Initializes document ingestor, vector manager, and LLM provider."""
        self.ingestor = DocumentIngestor()
        self.vector_manager = VectorStoreManager()
        self.llm_provider = LLMProvider()

    def ingest_file(self, file_path: str) -> int:
        """Ingests a file into vector store.

        Args:
            file_path: Path to .pdf, .txt, or .md file.

        Returns:
            Number of chunked documents added.
        """
        chunks = self.ingestor.load_and_split(file_path)
        ids = self.vector_manager.add_documents(chunks)
        return len(ids)

    def ingest_text(self, text: str, source_name: str = "manual_doc") -> int:
        """Ingests raw text into vector store.

        Args:
            text: Content string.
            source_name: Label for source reference.

        Returns:
            Number of chunked documents added.
        """
        chunks = self.ingestor.split_text(text, source_name=source_name)
        ids = self.vector_manager.add_documents(chunks)
        return len(ids)

    def answer_query(
        self,
        query: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
        top_k: int = 3
    ) -> Tuple[str, List[str], Dict[str, Any]]:
        """Executes RAG flow to generate grounded response and detect lead details.

        Args:
            query: User input query string.
            chat_history: Optional list of past messages [{'role': 'user'|'assistant', 'content': '...'}]
            top_k: Number of reference context chunks to retrieve.

        Returns:
            Tuple of (response_text, list_of_source_names, extracted_lead_dict)
        """
        # 1. Retrieve relevant contexts
        docs = self.vector_manager.similarity_search(query, top_k=top_k)
        sources = list(set([doc.metadata.get("source", "Knowledge Base") for doc in docs]))

        context_str = "\n---\n".join([doc.page_content for doc in docs]) if docs else "No relevant context found."

        # 2. Format history string
        history_str = ""
        if chat_history:
            for msg in chat_history[-6:]:
                role = "User" if msg["role"] == "user" else "Assistant"
                history_str += f"{role}: {msg['content']}\n"

        # 3. System Prompt construction
        system_prompt = (
            "You are a helpful, professional AI Customer Support Assistant for a business. "
            "Use the provided Knowledge Base Context below to accurately answer the user's inquiry. "
            "If the context does not contain enough information to answer, politely state what you know "
            "and offer to connect them with a human team member. Be concise, friendly, and helpful.\n\n"
            f"KNOWLEDGE BASE CONTEXT:\n{context_str}\n"
        )

        user_prompt = f"Recent Chat History:\n{history_str}\nUser Question: {query}"

        # 4. Generate LLM reply
        response_text = self.llm_provider.generate_response(system_prompt, user_prompt)

        # 5. Extract potential lead details (regex heuristics)
        extracted_lead = self._extract_lead_heuristics(query)

        return response_text, sources, extracted_lead

    def _extract_lead_heuristics(self, text: str) -> Dict[str, Any]:
        """Simple pattern extraction for phone, email, and name intent."""
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        phone_pattern = r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'

        emails = re.findall(email_pattern, text)
        phones = re.findall(phone_pattern, text)

        phone_val = None
        if phones:
            p = phones[0]
            phone_val = p if isinstance(p, str) else "".join(p)

        lead_data = {
            "has_lead": False,
            "email": emails[0] if emails else None,
            "phone": phone_val,
            "name": None,
            "intent": "support_inquiry"
        }

        if lead_data["email"] or lead_data["phone"]:
            lead_data["has_lead"] = True

        return lead_data
