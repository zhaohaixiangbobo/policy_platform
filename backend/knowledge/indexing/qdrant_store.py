"""Qdrant 存储适配层。

适配层封装版本化 collection、payload index、幂等 upsert、point 核验、Dense 查询
和 alias 原子切换，使上层索引流程不依赖 qdrant-client 的响应对象细节。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from qdrant_client import QdrantClient, models


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

    def ensure_collection(
        self,
        collection_name: str,
        *,
        vector_name: str,
        dimension: int,
        distance_metric: str,
    ) -> None:
        if not self.client.collection_exists(collection_name):
            distance = self._distance(distance_metric)
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    vector_name: models.VectorParams(size=dimension, distance=distance)
                },
            )
            return

        info = self.client.get_collection(collection_name)
        vectors = info.config.params.vectors
        if not isinstance(vectors, dict) or vector_name not in vectors:
            raise ValueError(f"Collection {collection_name} 缺少命名向量 {vector_name}")
        params = vectors[vector_name]
        if int(params.size) != dimension or params.distance != self._distance(distance_metric):
            raise ValueError(f"Collection {collection_name} 的向量契约与 IndexRun 不一致")

    def ensure_payload_indexes(self, collection_name: str) -> None:
        info = self.client.get_collection(collection_name)
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
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                    wait=True,
                )

    def upsert(
        self, collection_name: str, vector_name: str, points: Sequence[VectorPoint]
    ) -> None:
        self.client.upsert(
            collection_name=collection_name,
            points=[
                models.PointStruct(
                    id=point.point_id,
                    vector={vector_name: point.vector},
                    payload=point.payload,
                )
                for point in points
            ],
            wait=True,
        )

    def exact_count(self, collection_name: str) -> int:
        return int(self.client.count(collection_name=collection_name, exact=True).count)

    def retrieve(
        self,
        collection_name: str,
        point_ids: Sequence[str],
        *,
        vector_name: str,
        with_vectors: bool,
    ) -> dict[str, StoredPoint]:
        records = self.client.retrieve(
            collection_name=collection_name,
            ids=list(point_ids),
            with_payload=True,
            with_vectors=[vector_name] if with_vectors else False,
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
        for alias in self.client.get_aliases().aliases:
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
        self.client.update_collection_aliases(change_aliases_operations=operations)

    def search(
        self,
        alias_name: str,
        *,
        vector_name: str,
        query_vector: list[float],
        limit: int,
        query_filter: models.Filter | None = None,
    ) -> list[SearchHit]:
        response = self.client.query_points(
            collection_name=alias_name,
            query=query_vector,
            using=vector_name,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
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
