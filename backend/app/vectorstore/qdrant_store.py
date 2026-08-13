from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.vectorstore.base import SearchResult, VectorPoint, VectorStore
from app.vectorstore.payload_schema import ChunkPayload


def build_permission_filter(workspace_id: str, allowed_roles: list[str]) -> qmodels.Filter:
    """The permission filter baked into every retrieval query itself -- not a
    post-hoc application-layer filter. A pure function so it's testable
    without a live Qdrant instance."""
    return qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="workspace_id", match=qmodels.MatchValue(value=workspace_id)
            ),
            qmodels.FieldCondition(
                key="allowed_roles", match=qmodels.MatchAny(any=allowed_roles)
            ),
        ]
    )


class QdrantVectorStore(VectorStore):
    def __init__(self, url: str, collection_name: str) -> None:
        self._client = QdrantClient(url=url)
        self._collection_name = collection_name

    def ensure_collection(self, dimension: int) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection_name in existing:
            return
        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=qmodels.VectorParams(size=dimension, distance=qmodels.Distance.COSINE),
        )
        for field_name in ("workspace_id", "document_id", "allowed_roles"):
            self._client.create_payload_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=qmodels.PayloadSchemaType.KEYWORD,
            )

    def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        self._client.upsert(
            collection_name=self._collection_name,
            points=[
                qmodels.PointStruct(id=p.id, vector=p.vector, payload=p.payload.to_dict())
                for p in points
            ],
        )

    def search(
        self,
        vector: list[float],
        *,
        workspace_id: str,
        allowed_roles: list[str],
        limit: int = 6,
    ) -> list[SearchResult]:
        query_filter = build_permission_filter(workspace_id, allowed_roles)
        results = self._client.search(
            collection_name=self._collection_name,
            query_vector=vector,
            query_filter=query_filter,
            limit=limit,
        )
        return [
            SearchResult(id=str(r.id), score=r.score, payload=ChunkPayload.from_dict(r.payload))
            for r in results
        ]

    def delete_by_document(self, document_id: str, exclude_version_id: str | None = None) -> None:
        must = [
            qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=document_id))
        ]
        must_not = []
        if exclude_version_id:
            must_not.append(
                qmodels.FieldCondition(
                    key="document_version_id", match=qmodels.MatchValue(value=exclude_version_id)
                )
            )
        self._client.delete(
            collection_name=self._collection_name,
            points_selector=qmodels.FilterSelector(
                filter=qmodels.Filter(must=must, must_not=must_not)
            ),
        )
