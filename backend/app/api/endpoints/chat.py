from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
import json
from pydantic import BaseModel, Field
from typing import Optional
import uuid

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.core.rate_limit import chat_limit
from app.services.qa_engine import qa_engine

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None
    stream: bool = False


@router.post("/")
@chat_limit
async def chat(
    body: ChatRequest,
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
):
    """Answer a question using retrieved document and graph context."""
    conv_id = body.conversation_id or str(uuid.uuid4())

    if body.stream:
        return StreamingResponse(
            stream_response(body.message, conv_id, user.id),
            media_type="text/event-stream",
        )

    result = qa_engine.answer(
        question=body.message,
        conversation_id=conv_id,
        user_id=user.id,
    )

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "conversation_id": conv_id,
        "mode": result.get("mode", "local"),
    }


async def stream_response(message: str, conv_id: str, user_id: str):
    """Dependency-free SSE stream over the same QA engine result."""
    result = qa_engine.answer(question=message, conversation_id=conv_id, user_id=user_id)
    text = result["answer"]
    for start in range(0, len(text), 80):
        yield f"data: {json.dumps({'text': text[start:start + 80]})}\n\n"
    yield f"data: {json.dumps({'sources': result['sources'], 'conversation_id': conv_id, 'mode': result.get('mode', 'local')})}\n\n"
    yield "data: [DONE]\n\n"
