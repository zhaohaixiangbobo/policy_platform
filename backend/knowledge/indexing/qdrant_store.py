"""Qdrant 存储适配层。

适配层封装版本化 collection、payload index、幂等 upsert、point 核验、Dense 查询
和 alias 原子切换，使上层索引流程不依赖 qdrant-client 的响应对象细节。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time
from typing import Any, Callable, Sequence, TypeVar

from qdrant_client import QdrantClient, models


LOGGER = logging.getLogger("policy_platform.worker.dependencies.qdrant")
ResultT = TypeVar("ResultT")


@dataclass(frozen=True)
class VectorPoint:
    point_id: str
    vector: list[float]
    payload: dict[str, Any]


@dataclass(frozen=True)
class StoredPoint:
    point_id: str
    vector: list[float] | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class SearchHit:
    point_id: str
    score: float
    payload: dict[str, Any]


class QdrantVectorStore:
    """面向制度索引的 Qdrant 操作集合。"""

    def __init__(
        self,
        url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.client = QdrantClient(url=url, api_key=api_key, timeout=timeout_seconds)

    @staticmethod
    def _call(
        operation: str,
        callback: Callable[[], ResultT],
        *,
        collection_name: str | None = None,
        item_count: int | None = None,
    ) -> ResultT:
        """记录Qdrant调用耗时和失败类型，不记录向量、payload或认证信息。"""

        started = time.perf_counter()
        LOGGER.info(
            "event=dependency_call_started dependency=qdrant operation=%s collection=%s item_count=%s",
            operation, collection_name or "-", item_count if item_count is not None else "-",
        )
        try:
            result = callback()
        except Exception as exc:
            LOGGER.error(
                "event=dependency_call_failed dependency=qdrant operation=%s collection=%s item_count=%s elapsed_ms=%d error_type=%s",
                operation, collection_name or "-", item_count if item_count is not None else "-",
                int((time.perf_counter() - started) * 1000), type(exc).__name__,
            )
            raise
        LOGGER.info(
            "event=dependency_call_completed dependency=qdrant operation=%s collection=%s item_count=%s elapsed_ms=%d",
            operation, collection_name or "-", item_count if item_count is not None else "-",
            int((time.perf_counter() - started) * 1000),
        )
        return result

    def collection_exists(self, collection_name: str) -> bool:
        """只检查物理存储，复用历史运行时绝不隐式创建空 collection。"""
        return self._call("collection_exists", lambda: self.client.collection_exists(collection_name),
                          collection_name=collection_name)

    def alias_targets(self) -> set[str]:
        """清理时保护全部 Alias，不只保护平台默认 Alias。"""
        return {str(item.collection_name) for item in self._call("get_aliases", self.client.get_aliases).aliases}

    def delete_collection(self, collection_name: str) -> None:
        """由经过清单和引用校验的维护入口调用。"""
        if collection_name in self.alias_targets():
            raise ValueError("Alias 正在引用该 collection，禁止清理")
        self._call("delete_collection", lambda: self.client.delete_collection(collection_name),
                   collection_name=collection_name)

    def ensure_collection(
        self,
        collection_name: str,
        *,
        vector_name: str,
        dimension: int,
        distance_metric: str,
    ) -> None:
        exists = self._call(
            "collection_exists",
            lambda: self.client.collection_exists(collection_name),
            collection_name=collection_name,
        )
        if not exists:
            distance = self._distance(distance_metric)
            self._call(
                "create_collection",
                lambda: self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config={
                        vector_name: models.VectorParams(size=dimension, distance=distance)
                    },
                ),
                collection_name=collection_name,
            )
            return

        info = self._call(
            "get_collection", lambda: self.client.get_collection(collection_name),
            collection_name=collection_name,
        )
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict) or vector_name not in vectors:
            raise ValueError(f"Collection {collection_name} 缺少命名向量 {vector_name}")
        params = vectors[vector_name]
        if int(params.size) != dimension or params.distance != self._distance(distance_metric):
            raise ValueError(f"Collection {collection_name} 的向量契约与 IndexRun 不一致")

    def ensure_payload_indexes(self, collection_name: str) -> None:
        info = self._call(
            "get_collection", lambda: self.client.get_collection(collection_name),
            collection_name=collection_name,
        )
        existing = set((info.payload_schema or {}).keys())
        fields = {
            "document_id": models.PayloadSchemaType.INTEGER,
            "document_status": models.PayloadSchemaType.KEYWORD,
            "confidentiality_level": models.PayloadSchemaType.KEYWORD,
            "authority_level": models.PayloadSchemaType.KEYWORD,
            "document_code": models.PayloadSchemaType.KEYWORD,
            "chunk_type": models.PayloadSchemaType.KEYWORD,
        }
        for field_name, field_schema in fields.items():
            if field_name not in existing:
                self._call(
                    "create_payload_index",
                    lambda field_name=field_name, field_schema=field_schema: self.client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field_name,
                        field_schema=field_schema,
                        wait=True,
                    ),
                    collection_name=collection_name,
                )

    def upsert(
        self, collection_name: str, vector_name: str, points: Sequence[VectorPoint]
    ) -> None:
        structs = [
            models.PointStruct(
                id=point.point_id,
                vector={vector_name: point.vector},
                payload=point.payload,
            )
            for point in points
        ]
        self._call(
            "upsert",
            lambda: self.client.upsert(
                collection_name=collection_name, points=structs, wait=True,
            ),
            collection_name=collection_name,
            item_count=len(structs),
        )

    def exact_count(self, collection_name: str) -> int:
        response = self._call(
            "count",
            lambda: self.client.count(collection_name=collection_name, exact=True),
            collection_name=collection_name,
        )
        return int(response.count)

    def retrieve(
        self,
        collection_name: str,
        point_ids: Sequence[str],
        *,
        vector_name: str,
        with_vectors: bool,
    ) -> dict[str, StoredPoint]:
        ids = list(point_ids)
        records = self._call(
            "retrieve",
            lambda: self.client.retrieve(
                collection_name=collection_name,
                ids=ids,
                with_payload=True,
                with_vectors=[vector_name] if with_vectors else False,
            ),
            collection_name=collection_name,
            item_count=len(ids),
        )
        result: dict[str, StoredPoint] = {}
        for record in records:
            vector: list[float] | None = None
            if with_vectors and isinstance(record.vector, dict):
                raw_vector = record.vector.get(vector_name)
                if isinstance(raw_vector, list):
                    vector = [float(value) for value in raw_vector]
            result[str(record.id)] = StoredPoint(
                point_id=str(record.id),
                vector=vector,
                payload=dict(record.payload or {}),
            )
        return result

    def alias_target(self, alias_name: str) -> str | None:
        response = self._call("get_aliases", self.client.get_aliases)
        for alias in response.aliases:
            if alias.alias_name == alias_name:
                return str(alias.collection_name)
        return None

    def switch_alias(self, alias_name: str, collection_name: str) -> None:
        current = self.alias_target(alias_name)
        if current == collection_name:
            return
        operations: list[models.CreateAliasOperation | models.DeleteAliasOperation] = []
        if current is not None:
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=alias_name)
                )
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=collection_name, alias_name=alias_name
                )
            )
        )
        self._call(
            "switch_alias",
            lambda: self.client.update_collection_aliases(change_aliases_operations=operations),
            collection_name=collection_name,
        )

    def search(
        self,
        alias_name: str,
        *,
        vector_name: str,
        query_vector: list[float],
        limit: int,
        query_filter: models.Filter | None = None,
    ) -> list[SearchHit]:
        response = self._call(
            "query_points",
            lambda: self.client.query_points(
                collection_name=alias_name,
                query=query_vector,
                using=vector_name,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            ),
            collection_name=alias_name,
        )
        return [
            SearchHit(
                point_id=str(point.id),
                score=float(point.score),
                payload=dict(point.payload or {}),
            )
            for point in response.points
        ]

    @staticmethod
    def build_filter(
        *,
        document_ids: Sequence[int] | None = None,
        document_statuses: Sequence[str] | None = None,
        confidentiality_levels: Sequence[str] | None = None,
        authority_levels: Sequence[str] | None = None,
    ) -> models.Filter | None:
        conditions: list[models.FieldCondition] = []
        values = {
            "document_id": list(document_ids or []),
            "document_status": list(document_statuses or []),
            "confidentiality_level": list(confidentiality_levels or []),
            "authority_level": list(authority_levels or []),
        }
        for key, selected in values.items():
            if not selected:
                continue
            if len(selected) == 1:
                match: models.MatchValue | models.MatchAny = models.MatchValue(
                    value=selected[0]
                )
            else:
                match = models.MatchAny(any=selected)
            conditions.append(models.FieldCondition(key=key, match=match))
        return models.Filter(must=conditions) if conditions else None

    @staticmethod
    def _distance(value: str) -> models.Distance:
        if value == "cosine":
            return models.Distance.COSINE
        raise ValueError(f"不支持的 Qdrant distance_metric：{value}")
