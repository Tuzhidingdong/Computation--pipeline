"""Frozen scientific plan compilation."""
from .compiler import CompilationResult, compile_confirmed_manifest, compile_docx, write_manifest
from .docx_reader import ExtractedBlock, read_frozen_docx
from .manifest import MANIFEST_SCHEMA_VERSION, build_project_manifest, detect_conflicts, extract_claims

__all__ = [
    "CompilationResult", "compile_confirmed_manifest", "compile_docx", "write_manifest",
    "ExtractedBlock", "read_frozen_docx", "MANIFEST_SCHEMA_VERSION",
    "build_project_manifest", "detect_conflicts", "extract_claims",
]
