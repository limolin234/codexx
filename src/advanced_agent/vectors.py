from __future__ import annotations

import hashlib
import math
import secrets
from dataclasses import dataclass
from typing import Iterable

from advanced_agent.models import new_id
from advanced_agent.stores.sqlite_store import SQLiteStore
from advanced_agent.time_service import TimeService
from advanced_agent.memory_facets import facet_weights_for_profile, infer_query_profile, normalize_facets


@dataclass(slots=True)
class VectorHit:
    memory_id: str
    distance: float
    scope: str
    type: str
    summary: str
    label_kind: str
    score: float | None = None
    why_hit: dict | None = None


class HashEmbedding:
    """Deterministic lightweight embedding for local runtime tests.

    This is not a semantic model. It is a stable placeholder so the vector DB
    path is real and replaceable. A later embedding backend can implement the
    same `embed(text)` method.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        values = [0.0] * self.dim
        tokens = [tok for tok in text.lower().replace("/", " ").replace("_", " ").split() if tok]
        if not tokens:
            tokens = [text.lower() or "empty"]
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            for i in range(0, len(digest), 2):
                idx = digest[i] % self.dim
                sign = 1.0 if digest[i + 1] % 2 == 0 else -1.0
                values[idx] += sign
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]


class SQLiteVecStore:
    """sqlite-vec backed vector memory adapter.

    SQLite remains the metadata/hydration store. The vec virtual table only
    stores float vectors and returns top-k rowids.
    """

    def __init__(self, db: SQLiteStore, time: TimeService, embedding: HashEmbedding | None = None, table: str = "vec_memory") -> None:
        self.db = db
        self.time = time
        self.embedding = embedding or HashEmbedding()
        self.table = table
        self._load_extension()
        self._init_vec_table()

    def _load_extension(self) -> None:
        try:
            import sqlite_vec
        except ModuleNotFoundError as exc:  # pragma: no cover - exercised only without optional dep
            raise RuntimeError("sqlite-vec is not installed. Install with: pip install sqlite-vec") from exc
        self.sqlite_vec = sqlite_vec
        with self.db.locked():
            self.db.conn.enable_load_extension(True)
            sqlite_vec.load(self.db.conn)

    def _init_vec_table(self) -> None:
        with self.db.locked():
            self.db.conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {self.table} USING vec0(embedding float[{self.embedding.dim}])")
            self.db.conn.commit()

    def _next_rowid(self) -> int:
        # Do not derive vec rowids from SELECT MAX(...): multiple MCP server
        # processes can write the same SQLite DB concurrently. A random positive
        # 63-bit rowid avoids cross-process allocation races without introducing
        # a central allocator table.
        return secrets.randbits(63) or 1

    def add_memory(self, scope: str, type_: str, summary: str, labels: dict[str, str], content: str | None = None, importance: float = 0.5, confidence: float = 0.8, source_ref: str | None = None) -> str:
        now = self.time.wall_ms()
        memory_id = new_id("mem")
        with self.db.transaction():
            self.db.execute(
                """INSERT INTO memory_items
                (id,scope,type,title,summary,content,confidence,importance,status,created_at_ms,updated_at_ms,source_ref)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (memory_id, scope, type_, None, summary, content, confidence, importance, "active", now, now, source_ref),
            )
            for label_kind, label_text in labels.items():
                rowid = self._next_rowid()
                vector = self.embedding.embed(label_text)
                self.db.conn.execute(
                    f"INSERT INTO {self.table}(rowid, embedding) VALUES (?, ?)",
                    (rowid, self.sqlite_vec.serialize_float32(vector)),
                )
                self.db.execute(
                    """INSERT INTO memory_vectors
                    (id,memory_id,label_kind,vector_collection,vector_id,embedding_model,label_text,content_hash,created_at_ms)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (new_id("vec"), memory_id, label_kind, self.table, str(rowid), "hash-embedding-v1", label_text, hashlib.sha256(label_text.encode()).hexdigest(), now),
                )
                self.db.execute(
                    """INSERT OR REPLACE INTO memory_facets(memory_id, facet_name, facet_text, weight, created_at_ms)
                    VALUES(?,?,?,?,?)""",
                    (memory_id, label_kind, label_text, 1.0, now),
                )
            facets_text = "\n".join(f"{name}: {text}" for name, text in labels.items())
            self.db.execute(
                """INSERT INTO memory_fts(memory_id, scope, type, summary, content, facets)
                VALUES(?,?,?,?,?,?)""",
                (memory_id, scope, type_, summary, content or "", facets_text),
            )
        return memory_id


    def replace_memory_labels(self, memory_id: str, labels: dict[str, str]) -> int:
        """Replace vector/facet rows for an existing memory item.

        Used by migrations when the labeling strategy changes.  The durable
        memory item and source_ref stay intact; only retrieval labels/vectors and
        FTS text are rebuilt.
        """

        now = self.time.wall_ms()
        with self.db.transaction():
            item = self.db.query_one("SELECT id, scope, type, summary, content FROM memory_items WHERE id=?", (memory_id,))
            if item is None:
                return 0
            old_vectors = self.db.query_all("SELECT vector_collection, vector_id FROM memory_vectors WHERE memory_id=?", (memory_id,))
            for row in old_vectors:
                if row["vector_collection"] == self.table:
                    try:
                        self.db.conn.execute(f"DELETE FROM {self.table} WHERE rowid=?", (int(row["vector_id"]),))
                    except Exception:
                        pass
            self.db.execute("DELETE FROM memory_vectors WHERE memory_id=?", (memory_id,))
            self.db.execute("DELETE FROM memory_facets WHERE memory_id=?", (memory_id,))
            self.db.execute("DELETE FROM memory_fts WHERE memory_id=?", (memory_id,))
            for label_kind, label_text in labels.items():
                rowid = self._next_rowid()
                vector = self.embedding.embed(label_text)
                self.db.conn.execute(
                    f"INSERT INTO {self.table}(rowid, embedding) VALUES (?, ?)",
                    (rowid, self.sqlite_vec.serialize_float32(vector)),
                )
                self.db.execute(
                    """INSERT INTO memory_vectors
                    (id,memory_id,label_kind,vector_collection,vector_id,embedding_model,label_text,content_hash,created_at_ms)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                    (new_id("vec"), memory_id, label_kind, self.table, str(rowid), "hash-embedding-v1", label_text, hashlib.sha256(label_text.encode()).hexdigest(), now),
                )
                self.db.execute(
                    """INSERT OR REPLACE INTO memory_facets(memory_id, facet_name, facet_text, weight, created_at_ms)
                    VALUES(?,?,?,?,?)""",
                    (memory_id, label_kind, label_text, 1.0, now),
                )
            facets_text = "\n".join(f"{name}: {text}" for name, text in labels.items())
            self.db.execute(
                """INSERT INTO memory_fts(memory_id, scope, type, summary, content, facets)
                VALUES(?,?,?,?,?,?)""",
                (memory_id, item["scope"], item["type"], item["summary"], item["content"] or "", facets_text),
            )
            return len(labels)

    def search(self, query: str, scope: str | None = None, top_k: int = 5, query_profile: str = "auto", facet_weights: dict[str, float] | None = None) -> list[VectorHit]:
        top_k = max(1, min(int(top_k), 128))
        query_vec = self.sqlite_vec.serialize_float32(self.embedding.embed(query))
        profile = infer_query_profile(query, query_profile)
        weights = facet_weights_for_profile(profile, facet_weights)
        # Overfetch because scope/type/facet filtering is hydrated from metadata.
        with self.db.locked():
            rows = self.db.conn.execute(
                f"SELECT rowid, distance FROM {self.table} WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                (query_vec, min(max(top_k * 20, top_k), 4096)),
            ).fetchall()
            metas = []
            for rowid, distance in rows:
                meta = self.db.conn.execute(
                    """SELECT mv.label_kind, mi.id AS memory_id, mi.scope, mi.type, mi.summary,
                    mi.importance, mi.confidence, mi.updated_at_ms
                    FROM memory_vectors mv JOIN memory_items mi ON mi.id=mv.memory_id
                    WHERE mv.vector_collection=? AND mv.vector_id=? AND mi.status='active'""",
                    (self.table, str(rowid)),
                ).fetchone()
                metas.append((meta, distance))
        best_by_memory: dict[str, VectorHit] = {}
        for meta, distance in metas:
            if meta is None:
                continue
            if scope is not None and meta["scope"] != scope:
                continue
            label_kind = meta["label_kind"]
            weight = weights.get(label_kind, 0.15)
            if weight <= 0:
                continue
            score = weight / (1.0 + float(distance))
            hit = VectorHit(
                memory_id=meta["memory_id"],
                distance=float(distance),
                scope=meta["scope"],
                type=meta["type"],
                summary=meta["summary"],
                label_kind=label_kind,
                score=score,
            )
            current = best_by_memory.get(hit.memory_id)
            if current is None or (hit.score or 0.0) > (current.score or 0.0):
                best_by_memory[hit.memory_id] = hit
        return sorted(best_by_memory.values(), key=lambda item: item.score or 0.0, reverse=True)[:top_k]

    def hybrid_search(self, query: str, scope: str | None = None, top_k: int = 5, query_profile: str = "auto", facet_weights: dict[str, float] | None = None) -> list[VectorHit]:
        top_k = max(1, min(int(top_k), 64))
        profile = infer_query_profile(query, query_profile)
        weights = facet_weights_for_profile(profile, facet_weights)
        vector_hits = self.search(query, scope=scope, top_k=min(max(top_k * 4, top_k), 128), query_profile=profile, facet_weights=facet_weights)
        by_memory: dict[str, dict] = {}
        for rank, hit in enumerate(vector_hits):
            vector_score = hit.score if hit.score is not None else 1.0 / (1.0 + hit.distance)
            by_memory.setdefault(hit.memory_id, {
                "memory_id": hit.memory_id,
                "scope": hit.scope,
                "type": hit.type,
                "summary": hit.summary,
                "label_kind": hit.label_kind,
                "distance": hit.distance,
                "vector_score": 0.0,
                "keyword_score": 0.0,
                "rank": rank,
            })
            by_memory[hit.memory_id]["vector_score"] = max(by_memory[hit.memory_id]["vector_score"], vector_score)

        with self.db.locked():
            fts_rows = self._fts_search_locked(query, scope=scope, limit=min(max(top_k * 4, top_k), 128))
            for rank, row in enumerate(fts_rows):
                memory_id = row["memory_id"]
                item = by_memory.setdefault(memory_id, {
                    "memory_id": memory_id,
                    "scope": row["scope"],
                    "type": row["type"],
                    "summary": row["summary"],
                    "label_kind": "fts",
                    "distance": 0.0,
                    "vector_score": 0.0,
                    "keyword_score": 0.0,
                    "rank": rank,
                })
                bm25 = float(row["bm25_score"])
                item["keyword_score"] = max(item["keyword_score"], 1.0 / (1.0 + max(0.0, bm25)))

            if not by_memory:
                return []
            placeholders = ",".join("?" for _ in by_memory)
            meta_rows = self.db.conn.execute(
                f"""SELECT id, scope, type, summary, importance, confidence, updated_at_ms
                FROM memory_items WHERE id IN ({placeholders}) AND status='active'""",
                tuple(by_memory.keys()),
            ).fetchall()
            facet_rows = self.db.conn.execute(
                f"""SELECT memory_id, facet_name FROM memory_facets
                WHERE memory_id IN ({placeholders})""",
                tuple(by_memory.keys()),
            ).fetchall()

        meta_by_id = {row["id"]: row for row in meta_rows}
        facets_by_id: dict[str, set[str]] = {}
        for row in facet_rows:
            facets_by_id.setdefault(row["memory_id"], set()).add(row["facet_name"])

        now = self.time.wall_ms()
        results: list[VectorHit] = []
        for memory_id, item in by_memory.items():
            meta = meta_by_id.get(memory_id)
            if meta is None:
                continue
            matched_facets = sorted(facets_by_id.get(memory_id, set()) & set(weights.keys()))
            facet_score = sum(weights.get(name, 0.0) for name in matched_facets) / max(sum(weights.values()), 1.0)
            age_days = max(0.0, (now - int(meta["updated_at_ms"])) / 86_400_000.0)
            recency_score = 1.0 / (1.0 + age_days / 30.0)
            importance = float(meta["importance"])
            confidence = float(meta["confidence"])
            final_score = (
                item["vector_score"] * 0.48
                + item["keyword_score"] * 0.22
                + facet_score * 0.14
                + recency_score * 0.06
                + importance * 0.06
                + confidence * 0.04
            )
            results.append(VectorHit(
                memory_id=memory_id,
                distance=float(item["distance"]),
                scope=meta["scope"],
                type=meta["type"],
                summary=meta["summary"],
                label_kind=item["label_kind"],
                score=final_score,
                why_hit={
                    "vector_score": item["vector_score"],
                    "keyword_score": item["keyword_score"],
                    "facet_score": facet_score,
                    "recency_score": recency_score,
                    "importance": importance,
                    "confidence": confidence,
                    "matched_facets": matched_facets,
                    "profile": profile,
                },
            ))
        return sorted(results, key=lambda hit: hit.score or 0.0, reverse=True)[:top_k]

    def _fts_search_locked(self, query: str, scope: str | None = None, limit: int = 20):
        terms = [term.strip() for term in query.replace('"', " ").split() if term.strip()]
        if not terms:
            return []
        fts_query = " OR ".join(f'"{term}"' for term in terms[:8])
        where = "memory_fts MATCH ?"
        params: list = [fts_query]
        if scope is not None:
            where += " AND scope=?"
            params.append(scope)
        params.append(limit)
        try:
            return self.db.conn.execute(
                f"""SELECT memory_id, scope, type, summary, bm25(memory_fts) AS bm25_score
                FROM memory_fts WHERE {where}
                ORDER BY bm25(memory_fts) LIMIT ?""",
                tuple(params),
            ).fetchall()
        except Exception:
            return []


class MemoryAlignment:
    """First-pass label generator.

    Later this becomes a cheap alignment sub-agent. For now it deterministically
    creates multiple retrieval labels so sqlite-vec integration can be tested.
    """

    def labels_for(self, text: str, agent_role: str = "main") -> dict[str, str]:
        return normalize_facets({
            "semantic": text,
            "keywords": text,
        }, summary=text[:200], content=text)
