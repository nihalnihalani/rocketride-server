# =============================================================================
# RocketRide Engine
# =============================================================================
# MIT License
# Copyright (c) 2026 Aparavi Software AG
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# =============================================================================

"""Value types of the vector store explorer hooks (frozen interface).

These are what the optional ``DocumentStoreBase`` hooks return (``describe``,
``listDocuments``, ``scrollChunks``, ``knnGraph``) and the string vocabularies the
tools answer with (codes, capabilities, caveats). The tools turn them into JSON;
nothing here is sent over the wire as-is.

This module imports nothing at run time beyond the standard library, so drivers
and tests can import it cheaply. ``Doc`` and ``numpy`` appear in annotations only.

See ``docs/development/nodes/vector-tool-contract.md`` sections 2 and 4.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple

if TYPE_CHECKING:  # annotations only; no run-time dependency on numpy or the schema package
    import numpy as np

    from ..schema import Doc

# -----------------------------------------------------------------------------
# Keys and filters
# -----------------------------------------------------------------------------

#: Which rows a listing or read covers. ``'active'`` excludes soft-deleted rows.
Deleted = Literal['active', 'deleted', 'all']

#: The values of :data:`Deleted`, in documentation order.
DELETED_VALUES: Tuple[str, ...] = ('active', 'deleted', 'all')

#: The logical key of a chunk: ``(objectId, chunkId)``.
Key = Tuple[str, int]

#: objectId of the collection's control record. Never listed; refused on every external write path.
CONTROL_OBJECT_ID = 'schema'

# -----------------------------------------------------------------------------
# Hook return types
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class StoreInfo:
    """What ``DocumentStoreBase.describe()`` reports about the store.

    Never carries a host, port, DSN, credential or database name.
    """

    #: 'pgvector' | 'qdrant' | 'chroma' | 'milvus' | 'weaviate' | 'pinecone' | 'astra' | 'atlas'
    backend: str
    backend_version: Optional[str]
    #: Collection or table name, never the database name; None when absent.
    collection: Optional[str]
    collection_exists: bool
    #: Whether the control record is present; None when the collection does not exist.
    control_record: Optional[bool]
    #: pgvector only: False while the ``meta`` column could not be added yet; None on other backends.
    meta_column: Optional[bool]
    #: 'cosine' | 'l2' | 'ip' | None
    metric: Optional[str]
    dimension: Optional[int]
    model: Optional[str]
    index: Optional[Dict[str, Any]]
    size_bytes: Optional[int]
    #: Entries from :data:`CAVEATS`.
    caveats: List[str]


@dataclass(frozen=True)
class DocumentRow:
    """One document (one objectId) in a ``listDocuments`` page."""

    objectId: str
    path: str
    #: Chunks stored for the document; None when the backend cannot count them cheaply.
    chunks: Optional[int]
    has_first_chunk: bool
    deleted: bool
    tables: Optional[int]
    nodeId: Optional[str]
    size: Optional[int]
    modifyTime: Optional[int]
    #: UTC ISO-8601 when stored.
    ingestedAt: Optional[str]
    #: Backend id of the display row (chunk 0 when present).
    pointId: Optional[str]


@dataclass(frozen=True)
class DocPage:
    """One page of ``listDocuments``."""

    items: List[DocumentRow]
    #: Opaque cursor for the next page; None when the listing ended.
    next_cursor: Optional[str]
    #: Total documents, when known.
    total: Optional[int]
    counts_exact: bool
    #: True when every objectId appears at most once across the whole listing.
    distinct: bool
    #: True when rows arrive ordered by (path, objectId); otherwise the client sorts what it loaded.
    sorted: bool
    #: Entries from :data:`CAVEATS`.
    caveats: List[str]


@dataclass(frozen=True)
class ChunkPage:
    """One page of ``scrollChunks``, in chunk order. The docs never carry embeddings."""

    docs: List['Doc']
    has_more: bool
    #: The chunkId to pass as ``after_chunk`` for the next page.
    next_after: int


@dataclass(frozen=True)
class KnnGraph:
    """A k-nearest-neighbour graph over sampled keys, in Qdrant's offsets layout.

    Row ``i``'s neighbours are ``cols[offsets_row[i]:offsets_row[i + 1]]`` with
    similarities ``sims[...]`` (higher is closer).
    """

    k: int
    offsets_row: 'np.ndarray'
    cols: 'np.ndarray'
    sims: 'np.ndarray'
    #: 'native' (computed by the backend) | 'node' (computed by vx_math on the node)
    source: str


# -----------------------------------------------------------------------------
# Vocabularies (contract section 4.1)
# -----------------------------------------------------------------------------

#: Every ``code`` a failure envelope may carry.
TOOL_CODES: Tuple[str, ...] = (
    'INVALID_INPUT',
    'UNSUPPORTED',
    'NOT_FOUND',
    'RESERVED_ID',
    'COLLECTION_MISSING',
    'STORE_ERROR',
    'DIMENSION_MISMATCH',
    'MODEL_MISMATCH',
    'NO_EMBEDDER',
    'LIMIT_EXCEEDED',
    'SAMPLE_EXPIRED',
    'BUSY',
    'TIMEOUT',
    'RATE_LIMITED',
    'WRITES_DISABLED',
    'WRITES_SOURCE',
    'WRITES_PUBLIC',
    'WRITES_BROADCAST',
    'WRITES_AGENT',
    'WRITES_UNKNOWN_CALLER',
)

#: Boolean keys of ``dialect.capabilities`` (``projection`` is a list, reported beside them).
CAPABILITY_KEYS: Tuple[str, ...] = (
    'describe',
    'count',
    'count_documents',
    'documents',
    'documents_distinct',
    'documents_sorted',
    'chunks',
    'vectors',
    'sample',
    'sample_light',
    'sample_stratified_native',
    'knn_native',
    'project',
    'neighbors',
    'search_vector',
    'search_keyword',
    'remove',
    'remove_count',
    'soft_delete',
    'embed_node',
)

#: Projections the ``sample`` tool can compute on the node.
PROJECTIONS: Tuple[str, ...] = ('pca',)

#: Every caveat string a tool answer may carry.
CAVEATS: Tuple[str, ...] = (
    'brute_force_search',
    'no_filtered_count',
    'biased_sample',
    'score_scale_raw',
    'score_scale_inverted_fixed',
    'shared_org_table',
    'experimental',
    'cloud_only_unverified',
    'extras_not_stored',
    'documents_by_first_chunk',
    'document_count_capped',
    'documents_unsorted',
    'documents_paging_unsupported',
    'model_mismatch',
    'meta_column_pending',
)

#: ``sampleChunks`` strategies and the ``strategy_used`` values of a ``sample`` answer.
SAMPLE_STRATEGIES: Tuple[str, ...] = ('random', 'stratified', 'first')

#: ``KnnGraph.source`` / ``sample.knn_source`` values.
KNN_SOURCES: Tuple[str, ...] = ('native', 'node')

#: ``dialect.support`` values.
SUPPORT_LEVELS: Tuple[str, ...] = ('supported', 'experimental')

__all__ = [
    'CAPABILITY_KEYS',
    'CAVEATS',
    'CONTROL_OBJECT_ID',
    'ChunkPage',
    'DELETED_VALUES',
    'Deleted',
    'DocPage',
    'DocumentRow',
    'KNN_SOURCES',
    'Key',
    'KnnGraph',
    'PROJECTIONS',
    'SAMPLE_STRATEGIES',
    'SUPPORT_LEVELS',
    'StoreInfo',
    'TOOL_CODES',
]
