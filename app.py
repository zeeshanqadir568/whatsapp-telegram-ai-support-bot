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


@app.post("/api/upload")
async def upload_document(file: UploadFile = File(...)):
    """API endpoint allowing clients to upload custom PDF, TXT, or MD knowledge base files."""
    try:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in [".pdf", ".txt", ".md"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file format: {ext}. Allowed formats: .pdf, .txt, .md"
            )

        upload_dir = os.path.join(os.path.dirname(__file__), "uploads")
        os.makedirs(upload_dir, exist_ok=True)

        save_path = os.path.join(upload_dir, file.filename)
        with open(save_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        chunks_added = rag_engine.ingest_file(save_path)
        total_docs = rag_engine.vector_manager.get_document_count()

        return {
            "status": "success",
            "filename": file.filename,
            "chunks_added": chunks_added,
            "total_vector_documents": total_docs,
            "message": f"Successfully ingested '{file.filename}' into ChromaDB knowledge base."
        }
    except Exception as err:
        logger.error(f"Error uploading document: {err}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest document: {str(err)}"
        )


@app.post("/webhook/telegram")
async def telegram_webhook(update: dict, db: Session = Depends(get_db)):
    """Webhook receiver for Telegram Bot API integration."""
    try:
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")

        if not chat_id or not text:
            return {"status": "ignored"}

        # Process through RAG Engine
        reply_text, sources, lead_info = rag_engine.answer_query(
            query=text,
            chat_history=[],
            top_k=3
        )

        # Log conversation record
        user_msg = models.Conversation(session_id=chat_id, channel="telegram", role="user", content=text)
        bot_msg = models.Conversation(session_id=chat_id, channel="telegram", role="assistant", content=reply_text)
        db.add(user_msg)
        db.add(bot_msg)

        if lead_info.get("has_lead"):
            lead = models.Lead(
                session_id=chat_id,
                channel="telegram",
                email=lead_info.get("email"),
                phone=lead_info.get("phone"),
                name=lead_info.get("name"),
                intent=lead_info.get("intent", "telegram_inquiry")
            )
            db.add(lead)

        db.commit()

        # Send response via Telegram HTTP API if token present
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if tg_token:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{tg_token}/sendMessage",
                    json={"chat_id": chat_id, "text": reply_text}
                )

        return {"status": "ok", "reply": reply_text, "chat_id": chat_id}
    except Exception as err:
        logger.error(f"Telegram webhook error: {err}")
        return {"status": "error", "detail": str(err)}


@app.get("/webhook/whatsapp")
def verify_whatsapp_webhook(
    hub_mode: Optional[str] = None,
    hub_verify_token: Optional[str] = None,
    hub_challenge: Optional[str] = None
):
    """Meta WhatsApp Cloud API webhook verification handler."""
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "my_verify_token")
    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        return int(hub_challenge) if hub_challenge and hub_challenge.isdigit() else hub_challenge
    raise HTTPException(status_code=403, detail="Verification token mismatch")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(payload: dict, db: Session = Depends(get_db)):
    """Meta WhatsApp Cloud API & Twilio webhook incoming message receiver."""
    try:
        # Extract message from Meta payload structure
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return {"status": "ignored"}

        msg_obj = messages[0]
        from_number = msg_obj.get("from", "unknown_user")
        text = msg_obj.get("text", {}).get("body", "")

        if not text:
            return {"status": "ignored"}

        reply_text, sources, lead_info = rag_engine.answer_query(query=text, top_k=3)

        # Log conversation
        db.add(models.Conversation(session_id=from_number, channel="whatsapp", role="user", content=text))
        db.add(models.Conversation(session_id=from_number, channel="whatsapp", role="assistant", content=reply_text))

        if lead_info.get("has_lead"):
            db.add(models.Lead(
                session_id=from_number,
                channel="whatsapp",
                email=lead_info.get("email"),
                phone=lead_info.get("phone") or from_number,
                intent="whatsapp_inquiry"
            ))

        db.commit()
        return {"status": "ok", "reply": reply_text, "from": from_number}
    except Exception as err:
        logger.error(f"WhatsApp webhook error: {err}")
        return {"status": "error", "detail": str(err)}


# Mount static files directory for frontend UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

from fastapi import UploadFile, File
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


