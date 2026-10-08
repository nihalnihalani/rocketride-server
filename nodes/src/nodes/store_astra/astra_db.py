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

import os
from depends import depends

requirements = os.path.dirname(os.path.realpath(__file__)) + '/requirements.txt'
depends(requirements)

from typing import List, Callable, Dict, Any, Optional, Sequence, Tuple
from uuid import uuid4
import re
import json
import base64

from astrapy import DataAPIClient, Database
from astrapy.data_types import DataAPIVector
from astrapy.info import CollectionDefinition, CollectionVectorOptions, CollectionLexicalOptions

try:
    from astrapy.exceptions import TooManyDocumentsToCountException
except ImportError:  # older astrapy: count_documents has no upper bound to exceed

    class TooManyDocumentsToCountException(Exception):  # type: ignore[no-redef]
        """Placeholder that is never raised."""


from ai.common.schema import Doc, DocFilter, DocMetadata, QuestionText
from ai.common.store import DocumentStoreBase
from ai.common.store.errors import StoreUnsupported, ToolRefusal
from ai.common.store.vx_types import ChunkPage, DocPage, DocumentRow, StoreInfo
from ai.common.config import Config

from rocketlib import warning

# objectId of the collection's control record
CONTROL_OBJECT_ID = 'schema'

# count_documents needs a ceiling; above it the count is unknown (the Data API caps counts near 1000)
COUNT_UPPER_BOUND = 1000

# Metadata keys stored with every chunk: the declared DocMetadata fields plus the control record's extras.
# Other extras (file size, ingest time, ...) are not stored on Astra.
STORED_META_KEYS = frozenset(DocMetadata.model_fields) | {'vectorSize', 'modelName'}

# Astra metric -> the explorer's metric vocabulary
METRICS = {'cosine': 'cosine', 'euclidean': 'l2', 'dot_product': 'ip'}


def _meta_dump(metadata: DocMetadata) -> Dict[str, Any]:
    """The metadata stored with a chunk: declared fields and the control-record extras, never null."""
    return {k: v for k, v in metadata.model_dump(exclude_none=True).items() if k in STORED_META_KEYS}


def _meta_load(meta: Dict[str, Any]) -> DocMetadata:
    """DocMetadata from stored metadata; older rows hold explicit nulls, which are skipped."""
    return DocMetadata(**{k: v for k, v in (meta or {}).items() if v is not None})


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from a result that may be a dict or an object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _encode_cursor(offset: int, first: Optional[str]) -> str:
    """Opaque listing cursor: the next offset and the first objectId of the page just served."""
    raw = json.dumps({'o': offset, 'f': first}, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def _decode_cursor(cursor: Optional[str]) -> Tuple[int, Optional[str]]:
    """Read a cursor from :func:`_encode_cursor`; anything else is INVALID_INPUT."""
    if not cursor:
        return 0, None
    try:
        padded = cursor + '=' * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8'))
        offset = int(data['o'])
        first = data.get('f')
        if offset < 0 or (first is not None and not isinstance(first, str)):
            raise ValueError('cursor out of range')
        return offset, first
    except Exception:
        raise ToolRefusal('INVALID_INPUT', 'cursor is not one this store issued')


class Store(DocumentStoreBase):
    application_token: str | None = None
    node: str = 'astra_db'
    collection_name: str = ''
    api_endpoint: str = ''
    similarity: str = 'cosine'
    client: DataAPIClient | None = None
    database: Database | None = None

    #: Vector Explorer support level. Only an unmocked live suite can promote a driver.
    VX_SUPPORT: str = 'experimental'

    #: Capabilities beyond the hooks this driver overrides.
    VX_DRIVER_CAPABILITIES = frozenset({'search_keyword'})

    def __init__(self, provider: str, connConfig: Dict[str, Any], bag: Dict[str, Any]):
        """
        Initialize the astradb vector store.
        """
        # Init the base
        super().__init__(provider, connConfig, bag)

        # Get the nodes configuration
        config = Config.getNodeConfig(provider, connConfig)

        # Save our parameters
        self.collection_name = config.get('collection', '')

        if not re.match(r'^[A-Za-z0-9][A-Za-z0-9_]*$', self.collection_name):
            raise Exception(f'Invalid collection name: {self.collection_name}')

        # Remove leading and trailing spaces, leading http/https and :// and trailing slashes
        self.api_endpoint = config.get('api_endpoint')

        # check if the similarity matches astra configuration options
        similarity = config.get('similarity', 'cosine')
        if similarity in ['cosine', 'euclidean', 'dot_product']:
            self.similarity = similarity
        else:
            raise Exception(
                'The similarity metric you provided in the config.json does not match required astra configurations'
            )

        # Strip API key also
        self.application_token = config.get('application_token', None)
        if self.application_token is not None:
            self.application_token = self.application_token.strip()

        # Init the store
        self.client = DataAPIClient()
        self.database = self.client.get_database(self.api_endpoint, token=self.application_token)
        return

    def __del__(self):
        """
        Deinitializes the AstraDB client.
        """
        # Deinit everything we did
        self.application_token = None
        self.api_endpoint = ''
        self.client = None
        self.database = None
        return

    def _doesCollectionExist(self) -> bool:
        """
        Check if the collection exists.
        """
        if self.database is None:
            return False
        return self.collection_name in self.database.list_collection_names()

    def doesCollectionExist(self, modelName: str = None) -> bool:
        """
        Override base class to handle AstraDB-specific collection validation.

        Returns False if collection doesn't exist or doesn't have control document,
        allowing base class to create it properly.
        """
        try:
            return super().doesCollectionExist(modelName)
        except Exception:
            # If validation fails (e.g., no control document), return False
            # so base class will attempt to create/fix the collection
            return False

    def _createCollection(self, vectorSize: int) -> bool:
        """
        Create a collection with proper vector configuration.

        The base class will handle creating the control document separately.
        """
        try:
            # Define collection with custom embedding support
            collection_definition = CollectionDefinition(
                vector=CollectionVectorOptions(dimension=vectorSize, metric=self.similarity),
                lexical=CollectionLexicalOptions(enabled=True, analyzer='standard'),
            )

            # Create the collection
            self.database.create_collection(name=self.collection_name, definition=collection_definition)

            return True

        except Exception as e:
            warning(f'Collection creation failed: {e}')
            return False

    def _convertFilter(self, docFilter: DocFilter, deleted: Optional[str] = None) -> Dict:
        """
        Build the generic filter based on required permissions, node, parent, etc.

        Convert DocFilter to AstraDB query format. ``deleted`` ('active' | 'deleted' | 'all')
        overrides what the filter itself asks for (``DocFilter.deleted``, else the legacy
        ``isDeleted`` flag).
        """
        filter_dict = {}

        # If a nodeId was specified
        if docFilter.nodeId is not None:
            filter_dict['meta.nodeId'] = docFilter.nodeId

        if docFilter.isTable is not None:
            filter_dict['meta.isTable'] = docFilter.isTable

        if docFilter.tableIds is not None:
            filter_dict['meta.tableId'] = {'$in': docFilter.tableIds}

        # If a parent was specified
        if docFilter.parent is not None:
            filter_dict['meta.parent'] = {'$regex': docFilter.parent}

        # If a permissionId list was specified
        if docFilter.permissions is not None:
            filter_dict['meta.permissionId'] = {'$in': docFilter.permissions}

        # If a objectIds list was specified
        if docFilter.objectIds is not None:
            filter_dict['meta.objectId'] = {'$in': docFilter.objectIds}

        # Match other document stores (Qdrant, Postgres, Elasticsearch): default
        # queries must not return soft-deleted rows ('active'); 'deleted' returns only
        # those, and 'all' (or the legacy isDeleted=True) omits the clause.
        mode = deleted or self.resolveDeleted(docFilter)
        if mode == 'active':
            filter_dict['meta.isDeleted'] = False
        elif mode == 'deleted':
            filter_dict['meta.isDeleted'] = True

        # If we are going after specific chunks
        if docFilter.chunkIds is not None:
            filter_dict['meta.chunkId'] = {'$in': docFilter.chunkIds}

        # If we have min chunk id
        if docFilter.minChunkId is not None:
            if 'meta.chunkId' not in filter_dict:
                filter_dict['meta.chunkId'] = {}
            filter_dict['meta.chunkId']['$gte'] = docFilter.minChunkId

        # If we have max chunk id
        if docFilter.maxChunkId is not None:
            if 'meta.chunkId' not in filter_dict:
                filter_dict['meta.chunkId'] = {}
            filter_dict['meta.chunkId']['$lte'] = docFilter.maxChunkId

        return filter_dict

    def _convertToDocs(self, documents: List[Dict], floor: Optional[float] = None) -> List[Doc]:
        """
        Convert a list of AstraDB documents to Doc objects.

        Search hits (documents with ``$similarity``) below ``floor`` are dropped.
        """
        docs: List[Doc] = []

        # Now, add the documents to the results
        for document in documents:
            # Check for required fields - updated field name
            if 'content' not in document or 'meta' not in document:
                continue

            # Get the content and metadata - updated field name
            metadata = _meta_load(document['meta'])
            content = document['content']

            # Determine the score of this document
            if '$similarity' in document:
                score = document['$similarity']
                # Ignore if score is under the floor
                if floor is not None and score < floor:
                    continue
            else:
                score = 0

            # Create a new document
            doc = Doc(score=score, page_content=content, metadata=metadata)

            # Append it to this documents chunks
            docs.append(doc)

        # Return it
        return docs

    def _countWhere(self, filter_dict: Dict[str, Any]) -> Optional[int]:
        """Documents matching ``filter_dict``; None when there are more than COUNT_UPPER_BOUND."""
        collection = self.database.get_collection(self.collection_name)
        try:
            return collection.count_documents(filter_dict, upper_bound=COUNT_UPPER_BOUND)
        except TooManyDocumentsToCountException:
            return None

    def count_documents(self) -> int:
        """
        Return the number of documents in the document store.
        """
        # If the collection does not exist, by definition there are
        # no documents in the collection
        if not self._doesCollectionExist():
            return 0

        # Exact up to the count ceiling, estimated above it
        count = self._countWhere({})
        if count is None:
            count = self.database.get_collection(self.collection_name).estimated_document_count()
        return count

    def searchKeyword(self, query: QuestionText, docFilter: DocFilter) -> List[Doc]:
        """
        Keyword search using AstraDB's native lexical search.
        """
        if not self._doesCollectionExist():
            return []

        docs: List[Doc] = []

        # Convert docFilter to AstraDB filter format
        filter_dict = self._convertFilter(docFilter)

        # Pure lexical search using $lexical sort
        cursor = self.database.get_collection(self.collection_name).find(
            filter_dict,
            sort={'$lexical': query.text},  # Native BM25 lexical search
            limit=docFilter.limit,
            skip=docFilter.offset,
            projection={'$vector': 0},
        )

        # Convert results to your Doc format
        docs = self._convertToDocs(cursor)

        return docs

    def searchSemantic(self, query: QuestionText, docFilter: DocFilter) -> List[Doc]:
        """
        Semantic search.
        """
        if not self._doesCollectionExist():
            return []

        # Check embedding
        if query.embedding is None:
            raise Exception('To use semantic search, you must bind to an embedding module')

        filter_dict = self._convertFilter(docFilter)

        # Combine both lexical and vector search
        cursor = self.database.get_collection(self.collection_name).find(
            filter_dict,
            sort={'$vector': query.embedding},  # Automatic embedding generation + search
            limit=docFilter.limit,
            projection={'$lexical': 0},
            include_similarity=True,
            include_sort_vector=True,
        )

        # Convert results to your Doc format, dropping hits under the floor
        docs = self._convertToDocs(cursor, floor=self.effectiveFloor(docFilter))

        return docs

    def get(self, docFilter: DocFilter, checkCollection: bool = True) -> List[Doc]:
        """
        Retrieve documents matching the filter.

        A non-zero offset pages with ``skip``, which the Data API accepts only together
        with a sort, so those reads are ordered by (objectId, chunkId).
        """
        if checkCollection and not self._doesCollectionExist():
            return []

        collection = self.database.get_collection(self.collection_name)

        filter_dict = self._convertFilter(docFilter)

        # Execute query
        if docFilter.offset:
            cursor = collection.find(
                filter=filter_dict,
                sort={'meta.objectId': 1, 'meta.chunkId': 1},
                skip=docFilter.offset,
                limit=docFilter.limit or 100,
            )
        else:
            cursor = collection.find(filter=filter_dict, limit=docFilter.limit or 100)

        # Convert to Doc objects
        documents = list(cursor)
        return self._convertToDocs(documents)

    def getPaths(self, parent: str | None = None, offset: int = 0, limit: int = 1000) -> Dict[str, str]:
        """
        Return the parent paths of the live documents (never the control record).

        Reads chunk 0 of each document ordered by path; the Data API has no aggregation.
        """
        if not self._doesCollectionExist():
            return {}

        # Chunk 0 of the live documents
        match_filter = {'meta.chunkId': 0, 'meta.isDeleted': False, 'meta.objectId': {'$ne': CONTROL_OBJECT_ID}}

        if parent is not None:
            match_filter['meta.parent'] = parent

        collection = self.database.get_collection(self.collection_name)
        cursor = collection.find(
            filter=match_filter,
            sort={'meta.parent': 1},
            skip=offset or None,
            limit=limit,
            projection={'meta': True},
        )

        # Build paths dictionary
        paths: Dict[str, str] = {}
        for document in cursor:
            meta = document.get('meta') or {}
            parent_path = meta.get('parent')
            object_id = meta.get('objectId')
            if parent_path and object_id:
                paths[parent_path] = object_id

        return paths

    def addChunks(self, chunks: List[Doc], checkCollection: bool = True) -> None:
        """
        Add document chunks to the document store.
        """
        if not chunks:
            return

        if checkCollection and not self.createCollection(chunks):
            return

        collection = self.database.get_collection(self.collection_name)

        # Clear the documents list
        documents: List[Dict] = []

        # Clear the object id list for deletion
        objectIds: Dict = {}

        def flush():
            nonlocal documents
            nonlocal objectIds

            # First, delete existing documents if we have objectIds to delete
            if len(objectIds):
                # Delete all documents with these object IDs
                for objectId in objectIds.keys():
                    collection.delete_many({'meta.objectId': objectId})

            def is_valid_vector(vector):
                magnitude = sum(x * x for x in vector) ** 0.5
                return magnitude > 1e-6

            valid_docs = [doc for doc in documents if is_valid_vector(doc.get('$vector', [1]))]

            # Insert the new documents
            if len(valid_docs):
                collection.insert_many(valid_docs)

            # Clear them
            objectIds = {}
            documents = []

        # For each document, check if we need to delete existing chunks
        for chunk in chunks:
            # If we are writing chunk 0, then delete the object
            if not chunk.metadata.chunkId:
                # Save this object id to be deleted
                objectIds[chunk.metadata.objectId] = True

        # For each document, prepare the data for insertion
        for chunk in chunks:
            # Get the embedding
            embedding = chunk.embedding

            # If we do not have an embedding
            if embedding is None:
                raise Exception('No embedding in document')

            # The control document carries a zero vector, which the Data API rejects (and which
            # is_valid_vector below would drop): store a unit vector instead
            if chunk.metadata.objectId == CONTROL_OBJECT_ID and all(x == 0 for x in embedding):
                embedding = [0.0] * (len(embedding) - 1) + [1.0]

            # Create the document structure for AstraDB: declared metadata fields and
            # the control record's extras, without nulls (they would not read back)
            document = {
                '_id': str(uuid4()),
                '$vector': DataAPIVector(embedding),
                'content': chunk.page_content,
                'meta': _meta_dump(chunk.metadata),
            }

            documents.append(document)

            if len(documents) >= 500:
                flush()

        # Flush any remaining documents
        flush()

    def remove(self, objectIds: List[str]) -> None:
        """
        Delete all documents with a matching objectIds from the document store.
        """
        # By definition, if the collection does not exists, there
        # is nothing to delete
        if not self._doesCollectionExist():
            return

        # Build a filter for an object id
        filter_objectId = {'meta.objectId': {'$in': objectIds}}

        collection = self.database.get_collection(self.collection_name)
        collection.delete_many(filter_objectId)
        return

    def markDeleted(self, objectIds: List[str]) -> None:
        """
        Mark the set of documents with the given objectId as deleted.

        They then will not be returned from the search without specifying deleted=True
        """
        # By definition, if the collection does not exists, there
        # is nothing to mark
        if not self._doesCollectionExist():
            return

        # Build a filter for an object id
        filter_objectId = {'meta.objectId': {'$in': objectIds}}

        # Set all the objects with the given objectId to true
        collection = self.database.get_collection(self.collection_name)
        collection.update_many(filter_objectId, {'$set': {'meta.isDeleted': True}})
        return

    def markActive(self, objectIds: List[str]) -> None:
        """
        Mark the set of documents with the given objectId as active.

        This occurs if a document now 'comes back' after begin deleted
        """
        # By definition, if the collection does not exists, there
        # is nothing to mark
        if not self._doesCollectionExist():
            return

        # Build a filter for an object id
        filter_objectId = {'meta.objectId': {'$in': objectIds}}

        # Set all the objects with the given objectId to true
        collection = self.database.get_collection(self.collection_name)
        collection.update_many(filter_objectId, {'$set': {'meta.isDeleted': False}})
        return

    # Since chunks are returned in any order, and a single objectId
    # may contain tens of thousands of chunks, we grave them one
    # group at a time (renderChunkSize), put them into an array,
    # join them and call the callback
    def render(self, objectId: str, callback: Callable[[str], None]) -> None:
        """
        Given an object id, render the complete document.

        Rehydrates all the chunks into the proper order.
        """
        # By definition, if the collection does not exists, there
        # is nothing to render
        if not self._doesCollectionExist():
            return

        # Get the collection
        collection = self.database.get_collection(self.collection_name)

        # Find all chunks for the objectId
        cursor = collection.find(
            {
                'meta.objectId': objectId,
                'meta.isDeleted': False,  # Only get non-deleted chunks
            }
        )

        # Collect all chunks
        chunks = []
        for document in cursor:
            if 'content' not in document or 'meta' not in document:
                continue

            chunks.append({'chunkId': document['meta']['chunkId'], 'content': document['content']})

        # Sort by chunkId in application code (since AstraDB doesn't guarantee order)
        chunks.sort(key=lambda x: x['chunkId'])

        # Reconstruct document
        full_text = ''.join([chunk['content'] for chunk in chunks])
        callback(full_text)

    # ------------------------------------------------------------------
    # Vector Explorer hooks (docs/development/nodes/vector-tool-contract.md)
    # ------------------------------------------------------------------

    def _collection(self) -> Any:
        """The Data API collection."""
        return self.database.get_collection(self.collection_name)

    def _notControl(self, filter_dict: Dict[str, Any]) -> Dict[str, Any]:
        """``filter_dict`` with the control record excluded."""
        condition = filter_dict.get('meta.objectId')
        if isinstance(condition, dict):
            filter_dict['meta.objectId'] = {**condition, '$ne': CONTROL_OBJECT_ID}
        elif condition is None:
            filter_dict['meta.objectId'] = {'$ne': CONTROL_OBJECT_ID}
        return filter_dict

    def _toDoc(self, document: Dict[str, Any], *, with_vector: bool = False) -> Doc:
        """A Doc from a stored document; carries ``metadata.pointId`` and, on request, the embedding."""
        metadata = _meta_load(document.get('meta') or {})
        metadata.pointId = str(document.get('_id'))
        doc = Doc(score=0, page_content=document.get('content') or '', metadata=metadata)
        if with_vector:
            doc.embedding = [float(x) for x in document.get('$vector') or []]
        return doc

    def _readControl(self) -> Tuple[Optional[bool], Optional[int], Optional[str]]:
        """(control record present, vector size, model) read from the control record."""
        rows = list(self._collection().find({'meta.objectId': CONTROL_OBJECT_ID}, limit=2, projection={'meta': True}))
        if len(rows) != 1:
            return False, None, None
        meta = rows[0].get('meta') or {}
        size = meta.get('vectorSize')
        model = meta.get('modelName')
        if isinstance(size, int) and size > 0:
            self.vectorSize = size
        if isinstance(model, str) and model:
            self.modelName = model
        return True, size if isinstance(size, int) else None, model if isinstance(model, str) else None

    def describe(self) -> StoreInfo:
        """Describe the collection; never raises for a missing one and never names the endpoint."""
        caveats = ['experimental', 'cloud_only_unverified', 'extras_not_stored']
        if not self._doesCollectionExist():
            return StoreInfo(
                backend='astra',
                backend_version=None,
                collection=self.collection_name or None,
                collection_exists=False,
                control_record=None,
                meta_column=None,
                metric=METRICS.get(self.similarity),
                dimension=None,
                model=None,
                index=None,
                size_bytes=None,
                caveats=caveats,
            )

        control, dimension, model = self._readControl()
        metric = self.similarity
        try:
            vector = getattr(self._collection().options(), 'vector', None)
            if vector is not None:
                metric = getattr(vector, 'metric', None) or metric
                if dimension is None:
                    dimension = getattr(vector, 'dimension', None)
        except Exception:
            pass
        return StoreInfo(
            backend='astra',
            backend_version=None,
            collection=self.collection_name,
            collection_exists=True,
            control_record=control,
            meta_column=None,
            metric=METRICS.get(str(metric)),
            dimension=dimension,
            model=model,
            index={'type': 'vector', 'metric': str(metric), 'params': {}},
            size_bytes=None,
            caveats=caveats,
        )

    def scoreInfo(self) -> Dict[str, Any]:
        """How Doc.score is computed on Astra: the Data API's normalised $similarity."""
        if self.similarity == 'euclidean':
            formula = '1 / (1 + squared euclidean distance)'
        elif self.similarity == 'dot_product':
            formula = '(1 + dot product) / 2'
        else:
            formula = '(1 + cosine similarity) / 2'
        return {
            'formula': formula,
            'range': [0, 1],
            'higher_is_better': True,
            'floor': 0.2,
            'threshold': self.threshold_search,
        }

    def countChunks(self, docFilter: DocFilter) -> Optional[int]:
        """Chunks matching ``docFilter``, control record excluded; None above the count ceiling."""
        if not self._doesCollectionExist():
            return 0
        return self._countWhere(self._notControl(self._convertFilter(docFilter)))

    def listDocuments(
        self,
        *,
        cursor: Optional[str],
        limit: int,
        object_ids: Optional[Sequence[str]],
        deleted: str,
        sort: str,
    ) -> DocPage:
        """
        One page of documents: chunk-0 documents by offset (ordered by objectId so skip is allowed),
        with per-document chunk counts.

        A document whose chunk 0 is missing is not listed. Counts above the count ceiling are unknown.
        """
        offset, previous_first = _decode_cursor(cursor)
        limit = max(1, int(limit))
        caveats = ['documents_unsorted', 'documents_by_first_chunk', 'extras_not_stored']

        if not self._doesCollectionExist():
            return DocPage(
                items=[], next_cursor=None, total=0, counts_exact=True, distinct=False, sorted=False, caveats=caveats
            )

        first_chunks = self._notControl(
            self._convertFilter(
                DocFilter(chunkIds=[0], objectIds=list(object_ids) if object_ids else None), deleted=deleted
            )
        )
        documents = list(
            self._collection().find(
                filter=first_chunks,
                sort={'meta.objectId': 1},
                skip=offset or None,
                limit=limit + 1,
                projection={'meta': True},
            )
        )

        # The backend ignored the offset: this page repeats the previous one
        if (
            previous_first is not None
            and documents
            and (documents[0].get('meta') or {}).get('objectId') == previous_first
        ):
            return DocPage(
                items=[],
                next_cursor=None,
                total=None,
                counts_exact=True,
                distinct=False,
                sorted=False,
                caveats=caveats + ['documents_paging_unsupported'],
            )

        has_more = len(documents) > limit
        documents = documents[:limit]

        items: List[DocumentRow] = []
        exact = True
        seen = set()
        for document in documents:
            meta = document.get('meta') or {}
            object_id = meta.get('objectId')
            if not object_id or object_id in seen:
                continue
            seen.add(object_id)
            chunks = self._countWhere(self._convertFilter(DocFilter(objectIds=[object_id]), deleted=deleted))
            exact = exact and chunks is not None
            items.append(
                DocumentRow(
                    objectId=object_id,
                    path=meta.get('parent') or '',
                    chunks=chunks,
                    has_first_chunk=True,
                    deleted=bool(meta.get('isDeleted')),
                    tables=None,
                    nodeId=meta.get('nodeId'),
                    size=None,
                    modifyTime=None,
                    ingestedAt=None,
                    pointId=str(document.get('_id')),
                )
            )

        first = (documents[0].get('meta') or {}).get('objectId') if documents else None
        return DocPage(
            items=items,
            next_cursor=_encode_cursor(offset + limit, first) if has_more else None,
            total=self._countWhere(first_chunks),
            counts_exact=exact,
            distinct=False,
            sorted=False,
            caveats=caveats,
        )

    def scrollChunks(self, objectId: str, *, after_chunk: int, limit: int, deleted: str) -> ChunkPage:
        """The chunks of one document after ``after_chunk``, sorted by chunkId, without embeddings."""
        after_chunk = int(after_chunk)
        limit = max(1, int(limit))
        if objectId == CONTROL_OBJECT_ID or not self._doesCollectionExist():
            return ChunkPage(docs=[], has_more=False, next_after=after_chunk)
        filter_dict = self._convertFilter(DocFilter(objectIds=[objectId]), deleted=deleted)
        filter_dict['meta.chunkId'] = {'$gt': after_chunk}
        documents = list(
            self._collection().find(
                filter=filter_dict, sort={'meta.chunkId': 1}, limit=limit + 1, projection={'$vector': False}
            )
        )
        has_more = len(documents) > limit
        docs = [self._toDoc(document) for document in documents[:limit]]
        return ChunkPage(docs=docs, has_more=has_more, next_after=docs[-1].metadata.chunkId if docs else after_chunk)

    def sampleChunks(
        self,
        *,
        n: int,
        seed: int,
        strategy: str,
        docFilter: DocFilter,
        include_keys: Sequence[Tuple[str, int]],
    ) -> Tuple[List[Doc], str]:
        """Up to ``n`` chunks with embeddings in storage order ('first'); stratified is not native."""
        if strategy == 'stratified':
            raise StoreUnsupported('sampleChunks(strategy="stratified") is not native on Astra DB')
        if not self._doesCollectionExist():
            return [], 'first'
        pinned = {(str(o), int(c)) for o, c in include_keys or []}
        documents = self._collection().find(
            filter=self._notControl(self._convertFilter(docFilter)),
            limit=max(1, int(n)) + len(pinned),
            projection={'$vector': True, 'content': True, 'meta': True},
        )
        docs = []
        for document in documents:
            doc = self._toDoc(document, with_vector=True)
            if (doc.metadata.objectId, doc.metadata.chunkId) in pinned:
                continue
            docs.append(doc)
            if len(docs) >= n:
                break
        return docs, 'first'

    def getVectors(self, keys: Sequence[Tuple[str, int]]) -> List[Doc]:
        """Chunks with embeddings for ``keys`` (by filter: ids are random), in request order."""
        wanted = [(str(o), int(c)) for o, c in keys or [] if o != CONTROL_OBJECT_ID]
        if not wanted or not self._doesCollectionExist():
            return []
        object_ids = sorted({o for o, _ in wanted})
        chunk_ids = sorted({c for _, c in wanted})
        documents = self._collection().find(
            filter={'meta.objectId': {'$in': object_ids}, 'meta.chunkId': {'$in': chunk_ids}},
            limit=len(object_ids) * len(chunk_ids),
            projection={'$vector': True, 'content': True, 'meta': True},
        )
        found: Dict[Tuple[str, int], Doc] = {}
        for document in documents:
            doc = self._toDoc(document, with_vector=True)
            found.setdefault((doc.metadata.objectId, doc.metadata.chunkId), doc)
        return [found[key] for key in wanted if key in found]

    def removeCounted(self, objectIds: List[str]) -> Optional[int]:
        """Remove every chunk of ``objectIds``; return the rows removed."""
        ids = [o for o in objectIds or [] if o != CONTROL_OBJECT_ID]
        if not ids or not self._doesCollectionExist():
            return 0
        counted = self._countWhere({'meta.objectId': {'$in': ids}})
        result = self._collection().delete_many({'meta.objectId': {'$in': ids}})
        deleted = _field(result, 'deleted_count')
        return counted if counted is not None else deleted
