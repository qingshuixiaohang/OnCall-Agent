"""轻量级关键词索引。

Milvus 负责语义召回，本模块使用 SQLite FTS5 保留一份可持久化的关键词索引，
用于补足服务名、错误码、命令和配置项等精确匹配场景。两路结果由上层使用
Reciprocal Rank Fusion (RRF) 合并，不改动现有 Milvus collection schema。
"""

import json
import re
import sqlite3
from pathlib import Path

from langchain_core.documents import Document
from loguru import logger

from app.config import config, resolve_project_path

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:/-]*|[\u4e00-\u9fff]+")
_CJK_PATTERN = re.compile(r"^[\u4e00-\u9fff]+$")
_FILTER_FIELDS = {"service_name", "environment", "document_type"}


class KeywordIndexService:
    """基于 SQLite FTS5 的持久化关键词索引。"""

    def __init__(self, database_path: str) -> None:
        self.database_path = resolve_project_path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database_path), timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS keyword_chunks USING fts5(
                    chunk_id UNINDEXED,
                    token_text,
                    content UNINDEXED,
                    metadata UNINDEXED
                )
                """
            )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """将英文标识符保留为完整 token，中文按二元词切分。"""
        tokens: list[str] = []
        for match in _TOKEN_PATTERN.finditer(text):
            value = match.group(0).lower()
            if _CJK_PATTERN.fullmatch(value):
                if len(value) == 1:
                    tokens.append(value)
                else:
                    tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
            else:
                tokens.append(value)
        return list(dict.fromkeys(tokens))

    def upsert_documents(self, ids: list[str], documents: list[Document]) -> None:
        if len(ids) != len(documents):
            raise ValueError("关键词索引的 ids 数量必须和 documents 数量一致")

        rows = []
        for chunk_id, document in zip(ids, documents, strict=True):
            metadata = dict(document.metadata)
            metadata["_chunk_id"] = chunk_id
            rows.append(
                (
                    chunk_id,
                    " ".join(self._tokenize(document.page_content)),
                    document.page_content,
                    json.dumps(metadata, ensure_ascii=False),
                )
            )

        with self._connect() as connection:
            connection.executemany(
                "DELETE FROM keyword_chunks WHERE chunk_id = ?",
                [(row[0],) for row in rows],
            )
            connection.executemany(
                """
                INSERT INTO keyword_chunks (chunk_id, token_text, content, metadata)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )

        logger.info(f"关键词索引写入完成: {len(rows)} 个分片")

    def delete_by_source(self, source: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM keyword_chunks
                WHERE json_extract(metadata, '$."_source"') = ?
                """,
                (source,),
            )
            deleted_count = cursor.rowcount

        if deleted_count:
            logger.info(f"关键词索引删除旧数据: {source}, 数量={deleted_count}")
        return deleted_count

    def search(
        self,
        query: str,
        k: int,
        filters: dict[str, str] | None = None,
    ) -> list[Document]:
        tokens = self._tokenize(query)
        if not tokens:
            return []

        match_query = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
        conditions = ["keyword_chunks MATCH ?"]
        parameters: list[object] = [match_query]

        for key, value in (filters or {}).items():
            if key not in _FILTER_FIELDS:
                continue
            conditions.append(f"json_extract(metadata, '$.{key}') = ?")
            parameters.append(value)

        parameters.append(max(k, 1))
        sql = f"""
            SELECT content, metadata
            FROM keyword_chunks
            WHERE {' AND '.join(conditions)}
            ORDER BY bm25(keyword_chunks)
            LIMIT ?
        """

        try:
            with self._connect() as connection:
                rows = connection.execute(sql, parameters).fetchall()
        except sqlite3.OperationalError as error:
            logger.warning(f"关键词检索不可用，将只使用向量检索: {error}")
            return []

        documents = []
        for row in rows:
            metadata = json.loads(row["metadata"])
            metadata["keyword_match"] = True
            documents.append(Document(page_content=row["content"], metadata=metadata))

        logger.info(f"关键词检索完成: query='{query[:80]}', 结果数={len(documents)}")
        return documents


keyword_index_service = KeywordIndexService(config.rag_keyword_index_path)
