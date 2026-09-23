"""Cross-process single-flight per session without a transaction during provider I/O."""
from contextlib import contextmanager
from hashlib import sha256
from sqlalchemy import text
from app.store import engine


@contextmanager
def session_guard(session_id):
    from app.api import APIError
    key = int.from_bytes(sha256(str(session_id).encode()).digest()[:8], 'big', signed=True)
    with engine().connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
        acquired = connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar()
        if not acquired:
            raise APIError('CHAT_BUSY', 409, 'Cuộc trò chuyện đang xử lý một lượt. Vui lòng thử lại.')
        try:
            yield
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
