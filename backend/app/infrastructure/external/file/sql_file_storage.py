"""Postgres-backed file storage.

Stores binary content inline in `files.content` (BYTEA). Adequate for
chat-attachment scale (KB to a few MB). For large blobs swap to disk-volume
or S3 later via the same FileStorage protocol.
"""

import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, BinaryIO, Dict, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import undefer

from app.application.errors.exceptions import NotFoundError
from app.domain.external.file import FileStorage
from app.domain.models.file import FileInfo
from app.infrastructure.models.sql import FileRow

logger = logging.getLogger(__name__)


def _row_to_info(row: FileRow) -> FileInfo:
    return FileInfo(
        file_id=row.file_id,
        filename=row.filename,
        content_type=row.content_type,
        size=row.size,
        upload_date=row.upload_date,
        metadata=row.file_metadata,
        user_id=row.user_id,
    )


class SqlFileStorage(FileStorage):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upload_file(
        self,
        file_data: BinaryIO,
        filename: str,
        user_id: str,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> FileInfo:
        # Accept either a BinaryIO stream or raw bytes. The agent's screenshot
        # path handed us `bytes` directly and the strict .read() blew up.
        if isinstance(file_data, (bytes, bytearray)):
            content = bytes(file_data)
        else:
            content = file_data.read()
        size = len(content)
        file_id = uuid.uuid4().hex
        meta = {
            "filename": filename,
            "user_id": user_id,
            **(metadata or {}),
        }
        if content_type:
            meta["contentType"] = content_type

        async with self._session_factory() as db:
            row = FileRow(
                file_id=file_id,
                filename=filename,
                content_type=content_type,
                size=size,
                user_id=user_id,
                file_metadata=meta,
                content=content,
                upload_date=datetime.now(timezone.utc),
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return _row_to_info(row)

    async def download_file(
        self, file_id: str, user_id: Optional[str] = None
    ) -> Tuple[BinaryIO, FileInfo]:
        async with self._session_factory() as db:
            # `content` is `deferred()` on FileRow — must be `undefer`'d up
            # front, otherwise touching `row.content` after the session closes
            # triggers a sync lazy-load and SQLAlchemy raises MissingGreenlet.
            row = await db.scalar(
                select(FileRow)
                .options(undefer(FileRow.content))
                .where(FileRow.file_id == file_id)
            )
            # Treat "wrong user" as not-found to avoid leaking existence.
            if not row or (user_id is not None and row.user_id != user_id):
                if row and user_id is not None:
                    logger.warning(
                        "Access denied: file %s does not belong to user %s",
                        file_id, user_id,
                    )
                raise NotFoundError(f"File not found: {file_id}")
            # Snapshot fields into the FileInfo + bytes BEFORE the with block
            # exits so nothing is lazy-loaded post-session.
            content_bytes = bytes(row.content)
            info = _row_to_info(row)
            return io.BytesIO(content_bytes), info

    async def delete_file(self, file_id: str, user_id: str) -> bool:
        async with self._session_factory() as db:
            row = await db.get(FileRow, file_id)
            if not row or row.user_id != user_id:
                if row and row.user_id != user_id:
                    logger.warning(
                        "Delete access denied: file %s does not belong to user %s",
                        file_id, user_id,
                    )
                return False
            await db.delete(row)
            await db.commit()
            return True

    async def get_file_info(
        self, file_id: str, user_id: Optional[str] = None
    ) -> Optional[FileInfo]:
        async with self._session_factory() as db:
            row = await db.get(FileRow, file_id)
            if not row or (user_id is not None and row.user_id != user_id):
                if row and user_id is not None:
                    logger.warning(
                        "Access denied: file %s does not belong to user %s",
                        file_id, user_id,
                    )
                return None
            return _row_to_info(row)
