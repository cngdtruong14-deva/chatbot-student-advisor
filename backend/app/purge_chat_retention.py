"""Explicit, bounded retention purge for 30-day chat and RAG feedback data.

This module is deliberately not scheduled by the application.  A production
operator may invoke it from a reviewed scheduler after a backup, first with
``--dry-run`` and then with the exact confirmation phrase.
"""
from __future__ import annotations

import argparse
import json
from uuid import uuid4

from app.store import one, run, transaction


CONFIRM = "PURGE_EXPIRED_CHAT_RETENTION"


def counts(db) -> dict[str, int]:
    return {
        "expired_feedback": one(db, """SELECT count(*) AS n FROM app.rag_feedback f
            JOIN app.chat_sessions s ON s.id=f.session_id
            WHERE f.expires_at<=now() OR s.expires_at<=now()""")["n"],
        "expired_messages": one(
            db,
            """SELECT count(*) AS n FROM app.chat_messages m
               JOIN app.chat_sessions s ON s.id=m.session_id WHERE s.expires_at<=now()""",
        )["n"],
        "expired_sessions": one(db, "SELECT count(*) AS n FROM app.chat_sessions WHERE expires_at<=now()")["n"],
    }


def purge(*, confirmed: bool) -> dict:
    with transaction() as db:
        before = counts(db)
        if not confirmed:
            return {"dry_run": True, **before}
        # Delete dependent rows first; no content is sent outside PostgreSQL.
        run(db, """DELETE FROM app.rag_feedback f USING app.chat_sessions s
            WHERE f.session_id=s.id AND (f.expires_at<=now() OR s.expires_at<=now())""")
        run(
            db,
            """DELETE FROM app.chat_messages m USING app.chat_sessions s
               WHERE m.session_id=s.id AND s.expires_at<=now()""",
        )
        run(db, "DELETE FROM app.chat_sessions WHERE expires_at<=now()")
        request_id = str(uuid4())
        entity_id = "sessions={expired_sessions},messages={expired_messages},feedback={expired_feedback}".format(**before)
        run(db, """INSERT INTO app.audit_logs(action,entity_type,entity_id,status,request_id)
            VALUES('purge_chat_retention','retention_batch',:entity,'completed',:request)""",
            entity=entity_id, request=request_id)
        return {"dry_run": False, "purged": before}


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge only expired chat/RAG feedback records")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if not args.dry_run and args.confirm != CONFIRM:
        parser.error(f"Use --dry-run or --confirm {CONFIRM}")
    print(json.dumps(purge(confirmed=not args.dry_run), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
