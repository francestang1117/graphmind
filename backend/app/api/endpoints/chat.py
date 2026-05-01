from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import json
from pydantic import BaseModel, Field
from typing import Optional
import uuid

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.services.qa_engine import qa_engine

router = APIRouter()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None
    stream: bool = False


@router.post("/")
async def chat(
    request: ChatRequest,
    user: UserRecord = Depends(current_user_or_dev),
):
    """Answer a question using retrieved document and graph context."""
    conv_id = request.conversation_id or str(uuid.uuid4())

    if request.stream:
        return StreamingResponse(
            stream_response(request.message, conv_id, user.id),
            media_type="text/event-stream",
        )

    result = qa_engine.answer(
        question=request.message,
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
