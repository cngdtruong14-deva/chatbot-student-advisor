"""Bounded user feedback for RAG evidence cards.

Feedback is never sent to an LLM and is retained for at most 30 days.  The
endpoint is intentionally idempotent for a repeated identical submission, so a
browser retry cannot create multiple labels for the same chat turn.
"""
from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from fastapi import Request
from pydantic import Field, field_validator

from app.api import APIError, Actor, DTO, envelope, page, rate_limit, require_role, router, session_owner
from app import responses as out
from app.store import one, rows, run, transaction


FeedbackLabel = Literal["helpful", "not_helpful", "incorrect_citation"]


class RAGFeedbackInput(DTO):
    label: FeedbackLabel
    rationale: str | None = Field(default=None, max_length=500)

    @field_validator("rationale")
    @classmethod
    def normalize_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


def _evidence_card(result: object) -> dict | None:
    """Return only persisted evidence-card metadata; never evaluate user text."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return None
    if not isinstance(result, dict):
        return None
    for card in result.get("cards", []):
        if isinstance(card, dict) and card.get("type") == "evidence" and isinstance(card.get("data"), dict):
            return card["data"]
    return None


def _single_release_id(evidence: dict) -> str | None:
    declared = evidence.get("release_id")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    releases = {
        citation.get("release_id")
        for citation in evidence.get("citations", [])
        if isinstance(citation, dict) and isinstance(citation.get("release_id"), str) and citation["release_id"].strip()
    }
    return next(iter(releases)) if len(releases) == 1 else None


@router.post(
    "/chat/sessions/{session_id}/messages/{client_turn_id}/feedback",
    response_model=out.Envelope[out.RAGFeedback],
)
def submit_feedback(
    session_id: UUID,
    client_turn_id: UUID,
    body: RAGFeedbackInput,
    user: Actor,
    request: Request,
):
    rate_limit(request, "rag_feedback", 30)
    with transaction() as db:
        session = session_owner(db, user, session_id)
        message = one(
            db,
            "SELECT result FROM app.chat_messages WHERE session_id=:sid AND client_turn_id=:tid FOR UPDATE",
            sid=session_id,
            tid=client_turn_id,
        )
        if not message:
            raise APIError("RESOURCE_NOT_FOUND", 404)
        evidence = _evidence_card(message["result"])
        if not evidence or not evidence.get("citations"):
            raise APIError("RAG_FEEDBACK_NOT_AVAILABLE", 422, "Lượt chat này không có bằng chứng RAG để đánh giá.")

        existing = one(
            db,
            """SELECT label,rationale,expires_at FROM app.rag_feedback
               WHERE session_id=:sid AND client_turn_id=:tid FOR UPDATE""",
            sid=session_id,
            tid=client_turn_id,
        )
        if existing:
            if existing["label"] != body.label or existing["rationale"] != body.rationale:
                raise APIError("RAG_FEEDBACK_CONFLICT", 409, "Mỗi lượt chat chỉ nhận một nhãn phản hồi không thể sửa.")
            return envelope({"saved": True, "label": existing["label"], "expires_at": existing["expires_at"], "replayed": True})

        saved = one(
            db,
            """INSERT INTO app.rag_feedback(
                 user_id,session_id,client_turn_id,label,rationale,corpus_scope,release_id,retrieval_method
               ) VALUES(:uid,:sid,:tid,:label,:rationale,:scope,:release,:method)
               RETURNING label,expires_at""",
            uid=user["id"],
            sid=session_id,
            tid=client_turn_id,
            label=body.label,
            rationale=body.rationale,
            scope=session["corpus_scope"],
            release=_single_release_id(evidence),
            method=evidence.get("retrieval_method") if isinstance(evidence.get("retrieval_method"), str) else None,
        )
        run(
            db,
            """INSERT INTO app.audit_logs(actor_id,action,entity_type,entity_id,status,request_id)
               VALUES(:uid,'rag_feedback','chat_message',:turn,:label,:turn)""",
            uid=user["id"],
            turn=str(client_turn_id),
            label=body.label,
        )
    return envelope({"saved": True, "label": saved["label"], "expires_at": saved["expires_at"], "replayed": False})


@router.get("/admin/rag-feedback")
def list_feedback(user: Actor, limit: int = 50, cursor: str | None = None):
    """Operational review surface; it excludes message content and passwords."""
    require_role(user, "admin")
    safe_limit = min(max(limit, 1), 100)
    with transaction() as db:
        items = rows(
            db,
            """SELECT id,user_id,session_id,client_turn_id,label,rationale,corpus_scope,release_id,
                      retrieval_method,created_at,expires_at
               FROM app.rag_feedback WHERE expires_at>now()
               ORDER BY created_at DESC,id DESC""",
        )
    return envelope(page(items, safe_limit, cursor))
