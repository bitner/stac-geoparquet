"""Convert STAC data into Arrow tables"""

from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    Optional,
    Union,
)

import pyarrow as pa

from stac_geoparquet.arrow._schema.models import InferredSchema
from stac_geoparquet.json_reader import read_json_chunked
from stac_geoparquet.arrow._util import stac_items_to_arrow, batched_iter


def parse_stac_items_to_arrow(
    items: Iterable[Dict[str, Any]],
    *,
    chunk_size: int = 8192,
    schema: Optional[Union[pa.Schema, InferredSchema]] = None,
) -> Iterable[pa.RecordBatch]:
    """Parse a collection of STAC Items to an iterable of :class:`pyarrow.RecordBatch`.

    The objects under `properties` are moved up to the top-level of the
    Table, similar to :meth:`geopandas.GeoDataFrame.from_features`.

    Args:
        items: the STAC Items to convert
        chunk_size: The chunk size to use for Arrow record batches. This only takes
            effect if `schema` is not None. When `schema` is None, the input will be
            parsed into a single contiguous record batch. Defaults to 8192.
        schema: The schema of the input data. If provided, can improve memory use;
            otherwise all items need to be parsed into a single array for schema
            inference. Defaults to None.

    Returns:
        an iterable of pyarrow RecordBatches with the STAC-GeoParquet representation of items.
    """
    if schema is not None:
        if isinstance(schema, InferredSchema):
            schema = schema.inner

        # If schema is provided, then for better memory usage we parse input STAC items
        # to Arrow batches in chunks.
        for chunk in batched_iter(items, chunk_size):
            yield stac_items_to_arrow(chunk, schema=schema)

    else:
        # If schema is _not_ provided, then we must convert to Arrow all at once, or
        # else it would be possible for a STAC item late in the collection (after the
        # first chunk) to have a different schema and not match the schema inferred for
        # the first chunk.
        yield stac_items_to_arrow(items)


def parse_stac_ndjson_to_arrow(
    path: Union[str, Path, Iterable[Union[str, Path]]],
    *,
    chunk_size: int = 65536,
    schema: Optional[pa.Schema] = None,
) -> Iterator[pa.RecordBatch]:
    """
    Convert one or more newline-delimited JSON STAC files to a generator of Arrow
    RecordBatches.

    Each RecordBatch in the returned iterator is guaranteed to have an identical schema,
    and can be used to write to one or more Parquet files.

    Args:
        path: One or more paths to files with STAC items.
        chunk_size: The chunk size. Defaults to 65536.
        schema: The schema to represent the input STAC data. Defaults to None, in which
            case the schema will first be inferred via a full pass over the input data.
            In this case, there will be two full passes over the input data: one to
            infer a common schema across all data and another to read the data.

    Yields:
        Arrow RecordBatch with a single chunk of Item data.
    """
    # If the schema was not provided, then we need to load all data into memory at once
    # to perform schema resolution.
    if schema is None:
        inferred_schema = InferredSchema()
        inferred_schema.update_from_json(path, chunk_size=chunk_size)
        yield from parse_stac_ndjson_to_arrow(
            path, chunk_size=chunk_size, schema=inferred_schema
        )
        return

    if isinstance(schema, InferredSchema):
        schema = schema.inner

    for batch in read_json_chunked(path, chunk_size=chunk_size):
        yield stac_items_to_arrow(batch, schema=schema)
