# tools.py
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path
from typing import List, Tuple, Optional

from pypdf import PdfReader, PdfWriter


def safe_filename(name: str, fallback: str = "file.pdf") -> str:
    """
    Makes a filename safe for saving on filesystem.
    Keeps extension if present.
    """
    name = (name or "").strip()
    if not name:
        return fallback

    # normalize
    name = unicodedata.normalize("NFKD", name)
    name = name.encode("ascii", "ignore").decode("ascii")
    name = name.lower()

    # replace spaces and invalid chars
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"[^a-z0-9._-]+", "", name)
    name = re.sub(r"_+", "_", name).strip("._-")

    if not name:
        return fallback
    return name


def make_snippet(text: str, q: str, radius: int = 80) -> str:
    """
    Returns a small snippet around the first occurrence of q in text.
    """
    t = (text or "")
    q2 = (q or "").strip()
    if not t:
        return ""
    if not q2:
        return (t[:radius * 2] + "…") if len(t) > radius * 2 else t

    low_t = t.lower()
    low_q = q2.lower()
    idx = low_t.find(low_q)
    if idx < 0:
        return (t[:radius * 2] + "…") if len(t) > radius * 2 else t

    start = max(0, idx - radius)
    end = min(len(t), idx + len(q2) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(t) else ""
    return prefix + t[start:end].replace("\n", " ").strip() + suffix


def pdf_page_count(pdf_bytes: bytes) -> int:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return len(reader.pages)


def extract_text_from_pdf(pdf_bytes: bytes, max_pages: int = 25) -> str:
    """
    Simple text extraction from PDF (pypdf).
    Good for text-based PDFs; scanned PDFs -> OCR later.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    out = []
    for i, page in enumerate(reader.pages[:max_pages]):
        try:
            out.append(page.extract_text() or "")
        except Exception:
            out.append("")
    return "\n".join(out).strip()


def compress_pdf_bytes(pdf_bytes: bytes) -> bytes:
    """
    Basic compression: re-write PDF and compress content streams.
    Not guaranteed huge savings, but usually helps a bit.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    for p in reader.pages:
        writer.add_page(p)

    # compress streams if possible
    try:
        writer.compress_content_streams()
    except Exception:
        pass

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def split_pdf_bytes(pdf_bytes: bytes,
                    ranges: List[Tuple[int, int]]) -> List[Tuple[str, bytes]]:
    """
    ranges: list of (start_page, end_page) 1-based inclusive.
    returns list of (filename, pdf_bytes)
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)

    outputs: List[Tuple[str, bytes]] = []
    for idx, (a, b) in enumerate(ranges, start=1):
        a = max(1, int(a))
        b = min(total, int(b))
        if a > b:
            continue

        writer = PdfWriter()
        for p in range(a - 1, b):
            writer.add_page(reader.pages[p])

        buf = io.BytesIO()
        writer.write(buf)
        outputs.append((f"split_{idx}_{a}-{b}.pdf", buf.getvalue()))

    return outputs


def parse_ranges(ranges_text: str) -> List[Tuple[int, int]]:
    """
    "1-3, 5-5, 7-10" -> [(1,3),(5,5),(7,10)]
    """
    s = (ranges_text or "").strip()
    if not s:
        return []

    parts = [p.strip() for p in s.split(",") if p.strip()]
    out: List[Tuple[int, int]] = []
    for p in parts:
        if "-" in p:
            x, y = p.split("-", 1)
            out.append((int(x.strip()), int(y.strip())))
        else:
            n = int(p)
            out.append((n, n))
    return out


def merge_pdf_bytes(pdf_list: List[bytes]) -> bytes:
    """Merge multiple PDFs (in order)."""
    writer = PdfWriter()
    for bts in pdf_list:
        reader = PdfReader(io.BytesIO(bts))
        for p in reader.pages:
            writer.add_page(p)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def delete_pages_pdf_bytes(pdf_bytes: bytes, ranges: List[Tuple[int, int]]) -> bytes:
    """Delete pages in 1-based inclusive ranges."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)

    to_delete = set()
    for a, b in ranges:
        a = max(1, int(a))
        b = min(total, int(b))
        for i in range(a, b + 1):
            to_delete.add(i)

    writer = PdfWriter()
    for idx, page in enumerate(reader.pages, start=1):
        if idx in to_delete:
            continue
        writer.add_page(page)

    # don't output an empty PDF
    if len(writer.pages) == 0:
        return pdf_bytes

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def rotate_pages_pdf_bytes(pdf_bytes: bytes, ranges: List[Tuple[int, int]], degrees: int) -> bytes:
    """Rotate pages in ranges by degrees (must be multiple of 90)."""
    deg = int(degrees)
    if deg % 90 != 0:
        raise ValueError("degrees must be multiple of 90")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)

    to_rotate = set()
    for a, b in ranges:
        a = max(1, int(a))
        b = min(total, int(b))
        for i in range(a, b + 1):
            to_rotate.add(i)

    writer = PdfWriter()
    for idx, page in enumerate(reader.pages, start=1):
        if idx in to_rotate:
            try:
                page.rotate(deg)
            except Exception:
                # fallback for older APIs
                try:
                    page.rotate_clockwise(deg)
                except Exception:
                    pass
        writer.add_page(page)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
