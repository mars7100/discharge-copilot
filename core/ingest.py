"""Notes (.txt / text PDF) -> Documents + immutable SourceSpans (spec §7.1)."""
import re
from pathlib import Path

import pymupdf

from core.models import Document, SourceSpan

HEADER = re.compile(r"^(NOTE_ID|DATE|TYPE|AUTHOR ROLE):[ \t]*(.+)$", re.M)


def _pages(filename: str, data: bytes) -> list[str]:
    if filename.lower().endswith(".txt"):
        return [data.decode("utf-8")]
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        return [page.get_text() for page in pdf]


def _document(doc_id: str, filename: str, text: str) -> Document:
    h = dict(HEADER.findall(text))
    date = re.match(r"\d{4}-\d{2}-\d{2}", h.get("DATE", ""))
    day = re.search(r"Hospital Day (\d+)", h.get("DATE", ""))
    return Document(document_id=doc_id, filename=filename,
                    date=date.group() if date else None,
                    hospital_day=int(day.group(1)) if day else None,
                    type=h.get("TYPE"), author_role=h.get("AUTHOR ROLE"))


def ingest(files: list[tuple[str, bytes]]) -> tuple[list[Document], dict[str, SourceSpan], list[str]]:
    """files: (filename, raw bytes). Returns documents, spans keyed by span_id, warnings."""
    docs, spans, warnings = [], {}, []
    for raw_name, data in sorted(files):
        filename = Path(raw_name).name
        doc_id = re.sub(r"[^A-Za-z0-9_-]", "_", Path(filename).stem)
        if not filename.lower().endswith((".txt", ".pdf")):
            warnings.append(f"{filename}: unsupported type, skipped")
            continue
        if any(d.document_id == doc_id for d in docs):
            warnings.append(f"{filename}: duplicate document id '{doc_id}', skipped")
            continue
        try:
            pages = _pages(filename, data)
        except Exception as e:  # corrupt PDF / bad encoding: skip file, keep the run going
            warnings.append(f"{filename}: could not read ({e}), skipped")
            continue
        if not any(p.strip() for p in pages):
            warnings.append(f"{filename}: no extractable text (no OCR performed), skipped")
            continue
        order = 0
        for page_no, page in enumerate(pages, 1):
            for block in re.split(r"\n\s*\n", page):
                if block.strip():
                    order += 1
                    sid = f"{doc_id}_p{page_no:02d}_b{order:02d}"
                    spans[sid] = SourceSpan(span_id=sid, document_id=doc_id, filename=filename,
                                            page=page_no, order=order, text=block.strip())
        docs.append(_document(doc_id, filename, "\n".join(pages)))
    return docs, spans, warnings


def ingest_dir(path: str | Path):
    return ingest([(p.name, p.read_bytes()) for p in Path(path).iterdir() if p.is_file()])
