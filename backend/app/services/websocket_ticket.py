"""Short-lived tickets for browser WebSocket handshakes."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import settings

log = logging.getLogger(__name__)

JOB_WS_TICKET_TTL_SECONDS = 60


@dataclass
class _MemoryTicket:
    user_id: str
    expires_at: datetime


_memory_tickets: dict[tuple[str, str], _MemoryTicket] = {}


async def _redis_client():
    """Return a Redis client when the local setup has redis-py available."""
    try:
        import redis.asyncio as aioredis

        return aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        return None


def _redis_key(ticket: str, job_id: str) -> str:
    job_digest = hashlib.sha256(job_id.encode("utf-8")).hexdigest()
    return f"ws-ticket:{ticket}:{job_digest}"


def _payload(user_id: str, job_id: str) -> str:
    return json.dumps({"user_id": user_id, "job_id": job_id}, separators=(",", ":"))


async def issue_job_ws_ticket(job_id: str, user_id: str) -> str:
    """Issue a one-use ticket for one user's one background job."""
    ticket = secrets.token_urlsafe(32)
    client = await _redis_client()

    if client:
        try:
            await client.setex(
                _redis_key(ticket, job_id),
                JOB_WS_TICKET_TTL_SECONDS,
                _payload(user_id, job_id),
            )
            return ticket
        except Exception as exc:
            log.warning("Redis WebSocket ticket storage failed; using local fallback: %s", exc)
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    now = datetime.now(timezone.utc)
    _memory_tickets.update(
        {
            key: record
            for key, record in _memory_tickets.items()
            if record.expires_at > now
        }
    )
    _memory_tickets[(ticket, job_id)] = _MemoryTicket(
        user_id=user_id,
        expires_at=now + timedelta(seconds=JOB_WS_TICKET_TTL_SECONDS),
    )
    return ticket


async def consume_job_ws_ticket(ticket: str, job_id: str) -> str | None:
    """Consume a ticket once and return its user id when it matches the job."""
    if not ticket or len(ticket) > 256 or not job_id:
        return None

    client = await _redis_client()
    if client:
        try:
            # GETDEL makes two tabs race safely: only one receives the value.
            raw = await client.getdel(_redis_key(ticket, job_id))
            if not raw:
                return None
            data = json.loads(raw)
            if data.get("job_id") != job_id:
                return None
            return data.get("user_id")
        except Exception as exc:
            log.warning("Redis WebSocket ticket lookup failed; using local fallback: %s", exc)
        finally:
            try:
                await client.aclose()
            except Exception:
                pass

    key = (ticket, job_id)
    record = _memory_tickets.pop(key, None)
    if not record or record.expires_at <= datetime.now(timezone.utc):
        return None
    return record.user_id
