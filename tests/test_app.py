"""Integration tests for FastAPI /health and /chat endpoints.
"""

import os
import pytest
from fastapi.testclient import TestClient
from app import app


client = TestClient(app)


def test_health_endpoint():
    """Tests GET /health endpoint returns 200 OK and expected structure."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "active_llm_provider" in data
    assert "vector_store_documents" in data
    assert data["database_status"] == "healthy"


def test_chat_endpoint_grounded_response():
    """Tests POST /chat endpoint with a sample inquiry."""
    payload = {
        "message": "What are your business hours?",
        "session_id": "test_session_123",
        "channel": "api"
    }
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert data["session_id"] == "test_session_123"
    assert data["channel"] == "api"
    assert isinstance(data["sources"], list)


def test_chat_endpoint_lead_capture():
    """Tests POST /chat endpoint detects contact lead details."""
    payload = {
        "message": "Can I book an appointment? My email is testuser@example.com",
        "session_id": "test_session_lead",
        "channel": "api"
    }
    response = client.post("/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["lead_captured"] is True
