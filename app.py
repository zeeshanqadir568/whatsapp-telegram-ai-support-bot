"""FastAPI web application exposing /chat and /health endpoints for AI Support Bot.
"""

import os
import logging
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db, init_db
import models
from rag_engine import RAGEngine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="WhatsApp / Telegram AI Support Bot API",
    description="Production-ready starter kit for RAG-grounded customer support.",
    version="1.0.0"
)

# Enable CORS for local Streamlit admin dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global RAG Engine instance
rag_engine = RAGEngine()


# Pydantic Schemas
class ChatRequest(BaseModel):
    message: str = Field(..., description="User message content", min_length=1)
    session_id: str = Field(..., description="Unique session identifier for history tracking")
    channel: str = Field("api", description="Messaging channel: whatsapp, telegram, or api")


class ChatResponse(BaseModel):
    reply: str = Field(..., description="RAG-grounded AI assistant response")
    session_id: str = Field(..., description="Session identifier")
    channel: str = Field(..., description="Messaging channel")
    sources: List[str] = Field(default_factory=list, description="Knowledge base source documents cited")
    lead_captured: bool = Field(False, description="True if new contact lead was detected and saved")


class HealthCheckResponse(BaseModel):
    status: str
    active_llm_provider: str
    vector_store_documents: int
    database_status: str


@app.on_event("startup")
def startup_event():
    """Initializes database tables and seeds default knowledge base if empty."""
    logger.info("Initializing database tables...")
    init_db()

    # Pre-seed default business knowledge base if ChromaDB collection is currently empty
    try:
        count = rag_engine.vector_manager.get_document_count()
        if count == 0:
            logger.info("Vector store is empty. Seeding initial dental clinic FAQ knowledge base...")
            sample_kb = (
                "Apex Dental Clinic FAQ:\n"
                "1. Business Hours: We are open Monday to Friday 9:00 AM - 6:00 PM, Saturday 10:00 AM - 3:00 PM. Closed on Sundays.\n"
                "2. Location: 123 Healthcare Ave, Suite 400, Downtown City.\n"
                "3. Emergency Support: For urgent tooth pain or emergencies after hours, call our hotline at +1 (555) 987-6543.\n"
                "4. Services & Pricing: Teeth whitening ($199), Routine Cleaning ($99), Dental Implants (Starting at $1,200), Root Canal ($450).\n"
                "5. Appointments: To book an appointment, provide your preferred date, name, and email address."
            )
            rag_engine.ingest_text(sample_kb, source_name="dental_clinic_faq.txt")
            logger.info("Knowledge base seeded successfully.")
    except Exception as err:
        logger.error(f"Error during startup seeding: {err}")


@app.get("/health", response_model=HealthCheckResponse)
def health_check(db: Session = Depends(get_db)):
    """Health check endpoint exposing system status, active LLM provider, and vector stats."""
    db_status = "healthy"
    try:
        db.execute(models.Conversation.__table__.select().limit(1))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    doc_count = rag_engine.vector_manager.get_document_count()
    active_provider = rag_engine.llm_provider.active_provider

    return HealthCheckResponse(
        status="ok",
        active_llm_provider=active_provider,
        vector_store_documents=doc_count,
        database_status=db_status
    )


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest, db: Session = Depends(get_db)):
    """Core RAG-grounded support chat endpoint.

    Receives user message, fetches session history from SQLite, generates RAG reply,
    logs messages to database, and captures lead contact info if detected.
    """
    try:
        # 1. Retrieve most recent conversation history for this session
        history_records = (
            db.query(models.Conversation)
            .filter(models.Conversation.session_id == request.session_id)
            .order_by(models.Conversation.timestamp.desc())
            .limit(10)
            .all()
        )
        history_records.reverse()
        chat_history = [
            {"role": rec.role, "content": rec.content}
            for rec in history_records
            if rec.role in ["user", "assistant"]
        ]

        # 2. Save incoming user message
        user_msg = models.Conversation(
            session_id=request.session_id,
            channel=request.channel,
            role="user",
            content=request.message
        )
        db.add(user_msg)
        db.commit()

        # 3. Query RAG Engine
        reply_text, sources, lead_info = rag_engine.answer_query(
            query=request.message,
            chat_history=chat_history,
            top_k=3
        )

        # 4. Save assistant response
        assistant_msg = models.Conversation(
            session_id=request.session_id,
            channel=request.channel,
            role="assistant",
            content=reply_text
        )
        db.add(assistant_msg)

        # 5. Capture lead if contact information detected
        lead_captured = False
        if lead_info.get("has_lead"):
            lead = models.Lead(
                session_id=request.session_id,
                channel=request.channel,
                email=lead_info.get("email"),
                phone=lead_info.get("phone"),
                name=lead_info.get("name"),
                intent=lead_info.get("intent", "support_inquiry"),
                notes=f"Detected from user message: '{request.message}'"
            )
            db.add(lead)
            lead_captured = True

        db.commit()

        return ChatResponse(
            reply=reply_text,
            session_id=request.session_id,
            channel=request.channel,
            sources=sources,
            lead_captured=lead_captured
        )
    except Exception as err:
        logger.error(f"Error processing /chat request: {err}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing your message: {str(err)}"
        )


@app.get("/api/leads")
def get_leads(db: Session = Depends(get_db)):
    """API endpoint retrieving captured sales leads from SQLite database."""
    try:
        leads = db.query(models.Lead).order_by(models.Lead.created_at.desc()).all()
        return [
            {
                "id": l.id,
                "session_id": l.session_id,
                "channel": l.channel,
                "name": l.name,
                "email": l.email,
                "phone": l.phone,
                "intent": l.intent,
                "notes": l.notes,
                "created_at": l.created_at.strftime("%Y-%m-%d %H:%M:%S") if l.created_at else None
            }
            for l in leads
        ]
    except Exception as err:
        logger.error(f"Error fetching leads: {err}")
        return []


# Mount static files directory for frontend UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def read_root():
    """Serves the interactive single-page web dashboard."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "AI Support Bot API is running. Visit /docs for OpenAPI documentation."}

