"""llm-json-extractor: turn messy prose into clean, schema-validated JSONL.

Copyright (c) 2026 Asdale Dynamics, LLC. MIT licensed.
"""

from .extractor import ExtractResult, extract_document
from .parse import JsonParseError, extract_json_object

__all__ = [
    "ExtractResult",
    "JsonParseError",
    "extract_document",
    "extract_json_object",
]

__version__ = "0.1.0"
