"""视频创作咨询模块的数据访问层。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db.base import session_scope
from app.db.models import ConsultRecord, ConsultSession


def create_session(db_url: str, title: str, category: str = "general") -> int:
    with session_scope(db_url) as s:
        row = ConsultSession(title=title[:120] or "新咨询", category=category)
        s.add(row)
        s.flush()
        return row.id


def add_record(
    db_url: str,
    session_id: int,
    question: str,
    answer: str,
    highlights: list[str] | None = None,
    provider: str = "local",
    model: str = "rule-engine",
    is_fallback: bool = True,
) -> int:
    with session_scope(db_url) as s:
        row = ConsultRecord(
            session_id=session_id,
            question=question,
            answer=answer,
            highlights=list(highlights or []),
            provider=provider,
            model=model,
            is_fallback=is_fallback,
        )
        s.add(row)
        s.flush()
        return row.id


def list_sessions(db_url: str, limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(db_url) as s:
        rows = s.scalars(
            select(ConsultSession).order_by(ConsultSession.created_at.desc()).limit(limit)
        ).all()
        return [
            {"id": r.id, "title": r.title, "category": r.category, "created_at": r.created_at}
            for r in rows
        ]


def list_records(db_url: str, session_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with session_scope(db_url) as s:
        stmt = select(ConsultRecord).order_by(ConsultRecord.created_at.desc()).limit(limit)
        if session_id:
            stmt = stmt.where(ConsultRecord.session_id == session_id)
        return [
            {
                "id": r.id,
                "session_id": r.session_id,
                "question": r.question,
                "answer": r.answer,
                "highlights": list(r.highlights or []),
                "provider": r.provider,
                "model": r.model,
                "is_fallback": r.is_fallback,
                "created_at": r.created_at,
            }
            for r in s.scalars(stmt)
        ]


def delete_session(db_url: str, session_id: int) -> None:
    with session_scope(db_url) as s:
        row = s.get(ConsultSession, session_id)
        if row is not None:
            s.delete(row)
