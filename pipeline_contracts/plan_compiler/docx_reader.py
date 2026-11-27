"""Deterministic DOCX block extraction with source-location provenance.

Uses only the Python standard library. It preserves body order, paragraph styles,
numbering metadata, table coordinates and the original text of every extracted block.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_NS = {"w": _W[1:-1]}


@dataclass(frozen=True)
class ExtractedBlock:
    kind: str
    text: str
    location: dict
    style: str | None = None
    list_info: dict | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "text": self.text, "location": dict(self.location),
            "style": self.style, "list_info": self.list_info,
        }


def _text(node: ET.Element) -> str:
    parts = []
    for child in node.iter():
        if child.tag == _W + "t" and child.text:
            parts.append(child.text)
        elif child.tag == _W + "tab":
            parts.append("\t")
        elif child.tag in {_W + "br", _W + "cr"}:
            parts.append("\n")
    return "".join(parts)


def _paragraph_info(p: ET.Element) -> tuple[str | None, dict | None]:
    ppr = p.find(_W + "pPr")
    if ppr is None:
        return None, None
    style_el = ppr.find(_W + "pStyle")
    style = style_el.get(_W + "val") if style_el is not None else None
    num_pr = ppr.find(_W + "numPr")
    list_info = None
    if num_pr is not None:
        num_id = num_pr.find(_W + "numId")
        ilvl = num_pr.find(_W + "ilvl")
        list_info = {
            "num_id": num_id.get(_W + "val") if num_id is not None else None,
            "level": ilvl.get(_W + "val") if ilvl is not None else "0",
        }
    return style, list_info


def read_frozen_docx(path: str | Path) -> list[ExtractedBlock]:
    """Read paragraphs and tables in document order; fail on malformed DOCX."""
    source = Path(path)
    if source.suffix.lower() != ".docx" or not source.is_file():
        raise FileNotFoundError(f"Frozen DOCX does not exist or is not .docx: {source}")
    try:
        with ZipFile(source) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
    except (KeyError, ET.ParseError, OSError) as exc:
        raise ValueError(f"Invalid or unsupported DOCX package: {exc}") from exc

    body = root.find(".//" + _W + "body")
    if body is None:
        raise ValueError("DOCX has no w:body")
    blocks: list[ExtractedBlock] = []
    p_index = 0
    table_index = 0
    for child in list(body):
        if child.tag == _W + "p":
            p_index += 1
            style, list_info = _paragraph_info(child)
            blocks.append(ExtractedBlock(
                "paragraph", _text(child),
                {"part": "word/document.xml", "paragraph": p_index},
                style, list_info,
            ))
        elif child.tag == _W + "tbl":
            table_index += 1
            for row_index, row in enumerate(child.findall(_W + "tr"), start=1):
                cells = row.findall(_W + "tc")
                for col_index, cell in enumerate(cells, start=1):
                    paras = cell.findall(".//" + _W + "p")
                    cell_text = "\n".join(_text(p) for p in paras)
                    blocks.append(ExtractedBlock(
                        "table_cell", cell_text,
                        {"part": "word/document.xml", "table": table_index,
                         "row": row_index, "column": col_index},
                    ))
    return blocks
