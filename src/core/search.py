import re
import math
from typing import List, Dict, Tuple, Optional
import numpy as np
from src.core.chunker import CodeChunk

def tokenize(text: str) -> List[str]:
    """Tokenizes code and natural language into lowercase word and symbol tokens."""
    # Split camelCase, snake_case, and non-alphanumeric chars
    s1 = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    tokens = re.findall(r'[a-zA-Z0-9_\u3131-\uD79D]+', s1.lower())
    return [t for t in tokens if len(t) > 1]

class BM25Engine:
    """Fast, pure-Python BM25 implementation optimized for code and documentation."""
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_len: List[int] = []
        self.avg_doc_len: float = 0.0
        self.doc_count: int = 0
        self.idf: Dict[str, float] = {}
        self.doc_freqs: List[Dict[str, int]] = []
        self.chunk_ids: List[str] = []

    def index(self, chunks: List[CodeChunk]):
        self.doc_count = len(chunks)
        self.doc_len = []
        self.doc_freqs = []
        self.chunk_ids = [c.id for c in chunks]
        df: Dict[str, int] = {}

        for chunk in chunks:
            # Code search: boost symbol name and file path heavily
            enriched_text = f"{chunk.file_path} {chunk.file_path} {chunk.symbol_name or ''} {chunk.symbol_name or ''} {chunk.content}"
            tokens = tokenize(enriched_text)
            self.doc_len.append(len(tokens))
            tf: Dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            self.doc_freqs.append(tf)

            for t in set(tokens):
                df[t] = df.get(t, 0) + 1

        self.avg_doc_len = sum(self.doc_len) / max(1, self.doc_count)

        # Compute IDF
        self.idf = {}
        for term, freq in df.items():
            # BM25 IDF formulation with smoothing
            self.idf[term] = math.log(1.0 + (self.doc_count - freq + 0.5) / (freq + 0.5))

    def query(self, query_text: str, top_k: int = 20) -> List[Tuple[int, float]]:
        """Returns list of (doc_index, score) sorted by relevance."""
        if not self.doc_count:
            return []

        query_tokens = tokenize(query_text)
        if not query_tokens:
            return []

        scores = [0.0] * self.doc_count

        for q_token in query_tokens:
            idf_val = self.idf.get(q_token, 0.0)
            if idf_val <= 0.0:
                continue

            for idx in range(self.doc_count):
                tf = self.doc_freqs[idx].get(q_token, 0)
                if tf == 0:
                    continue
                d_len = self.doc_len[idx]
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (d_len / self.avg_doc_len))
                scores[idx] += idf_val * (numerator / denominator)

        ranked = [(i, scores[i]) for i in range(self.doc_count) if scores[i] > 0.0]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_k]

class FastFeatureVectorizer:
    """
    Subword and keyword hashing vectorizer for zero-dependency semantic cosine similarity.
    Generates dense embeddings using character n-grams and term hashes.
    """
    def __init__(self, dim: int = 256):
        self.dim = dim

    def encode(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        tokens = tokenize(text)
        if not tokens:
            return vec

        for t in tokens:
            # Word hash
            h1 = hash(t) % self.dim
            vec[h1] += 1.0
            # 3-gram character hashes
            if len(t) >= 3:
                for i in range(len(t) - 2):
                    sub = t[i:i+3]
                    h2 = hash(sub) % self.dim
                    vec[h2] += 0.5

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

class HybridSearchEngine:
    """
    Combines BM25 Lexical search + Semantic Vector similarity + Reciprocal Rank Fusion (RRF).
    """
    def __init__(self):
        self.bm25 = BM25Engine()
        self.vectorizer = FastFeatureVectorizer(dim=256)
        self.chunks: List[CodeChunk] = []
        self.vectors: Optional[np.ndarray] = None

    def build_index(self, chunks: List[CodeChunk]):
        self.chunks = chunks
        if not chunks:
            self.vectors = None
            return

        self.bm25.index(chunks)
        # Precompute vectors
        vec_list = []
        for c in chunks:
            text = f"{c.file_path} {c.symbol_name or ''} {c.content}"
            vec_list.append(self.vectorizer.encode(text))
        self.vectors = np.array(vec_list, dtype=np.float32)

    def search(self, query: str, top_k: int = 8) -> List[Tuple[CodeChunk, float, str]]:
        """
        Searches the chunks using hybrid BM25 + Vector scoring + filename boosting.
        Returns list of (CodeChunk, final_score, match_reason).
        """
        if not self.chunks or not query.strip():
            return []

        # 1. BM25 Search
        bm25_results = self.bm25.query(query, top_k=top_k * 3)
        bm25_ranks: Dict[int, int] = {idx: rank + 1 for rank, (idx, _) in enumerate(bm25_results)}

        # 2. Vector Cosine Similarity Search
        vector_ranks: Dict[int, int] = {}
        if self.vectors is not None:
            q_vec = self.vectorizer.encode(query)
            q_norm = np.linalg.norm(q_vec)
            if q_norm > 0:
                sims = np.dot(self.vectors, q_vec)
                # Sort indices by cosine similarity descending
                top_vec_indices = np.argsort(-sims)[:top_k * 3]
                for rank, idx in enumerate(top_vec_indices):
                    if sims[idx] > 0.05:
                        vector_ranks[int(idx)] = rank + 1

        # 3. Path boosting
        # If query contains mentions of file names (e.g. "auth.ts", "config.py")
        query_lower = query.lower()
        path_boosted: Dict[int, float] = {}
        for idx, chunk in enumerate(self.chunks):
            fname = chunk.file_path.lower().split('/')[-1]
            if fname in query_lower or chunk.file_path.lower() in query_lower:
                path_boosted[idx] = 1.5

        # 4. Reciprocal Rank Fusion (RRF)
        # RRF Score = 1 / (60 + bm25_rank) + 1 / (60 + vec_rank) + path_boost
        all_candidates = set(bm25_ranks.keys()) | set(vector_ranks.keys()) | set(path_boosted.keys())
        scored_candidates: List[Tuple[int, float, str]] = []

        for idx in all_candidates:
            b_rank = bm25_ranks.get(idx, 999)
            v_rank = vector_ranks.get(idx, 999)
            
            rrf_score = 0.0
            reasons = []

            if idx in bm25_ranks:
                rrf_score += 1.0 / (50.0 + b_rank)
                reasons.append(f"Keyword/Symbol match (rank #{b_rank})")

            if idx in vector_ranks:
                rrf_score += 1.0 / (50.0 + v_rank)
                reasons.append(f"Semantic match (rank #{v_rank})")

            if idx in path_boosted:
                rrf_score += 0.03
                reasons.append(f"Direct file reference: {self.chunks[idx].file_path}")

            scored_candidates.append((idx, rrf_score, ", ".join(reasons)))

        scored_candidates.sort(key=lambda x: x[1], reverse=True)

        final_results = []
        for idx, score, reason in scored_candidates[:top_k]:
            final_results.append((self.chunks[idx], score, reason))

        return final_results
