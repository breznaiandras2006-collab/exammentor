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
    Parses 1-based inclusive page ranges.

    Examples:
      "1-3, 5, 7-10" -> [(1,3),(5,5),(7,10)]
      " 2 ; 4-6 "    -> [(2,2),(4,6)]
    """
    s = (ranges_text or "").strip()
    if not s:
        return []

    # allow ";" as separator too
    s = s.replace(";", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]

    out: List[Tuple[int, int]] = []
    for p in parts:
        if "-" in p:
            x, y = p.split("-", 1)
            x = x.strip()
            y = y.strip()
            if not x or not y:
                raise ValueError(f"Invalid range token: {p!r}")
            a = int(x)
            b = int(y)
            if a <= 0 or b <= 0:
                raise ValueError("Page numbers must be >= 1")
            if a > b:
                a, b = b, a
            out.append((a, b))
        else:
            n = int(p)
            if n <= 0:
                raise ValueError("Page numbers must be >= 1")
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


def parse_page_sequence(sequence_text: str, total_pages: int) -> List[int]:
    """
    Parses a page sequence in order (1-based), allowing ranges.

    Examples (total_pages=10):
      "3,1,2"       -> [3,1,2]
      "1-3, 7, 9-10"-> [1,2,3,7,9,10]
      "6-4"         -> [4,5,6] (range is normalized)

    Raises ValueError on invalid tokens or out-of-range pages.
    """
    s = (sequence_text or "").strip()
    if not s:
        return []

    s = s.replace(";", ",")
    parts = [p.strip() for p in s.split(",") if p.strip()]

    seq: List[int] = []
    for p in parts:
        if "-" in p:
            x, y = p.split("-", 1)
            x = x.strip()
            y = y.strip()
            if not x or not y:
                raise ValueError(f"Invalid range token: {p!r}")
            a = int(x)
            b = int(y)
            if a <= 0 or b <= 0:
                raise ValueError("Page numbers must be >= 1")
            if a > b:
                a, b = b, a
            for n in range(a, b + 1):
                if n < 1 or n > total_pages:
                    raise ValueError(f"Page {n} out of range (1..{total_pages})")
                seq.append(n)
        else:
            n = int(p)
            if n < 1 or n > total_pages:
                raise ValueError(f"Page {n} out of range (1..{total_pages})")
            seq.append(n)

    return seq


def extract_pages_pdf_bytes(pdf_bytes: bytes, ranges: List[Tuple[int, int]]) -> bytes:
    """
    Extract pages given by inclusive ranges, keeping natural order.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)
    seq: List[int] = []
    for a, b in ranges:
        a = int(a)
        b = int(b)
        if a <= 0 or b <= 0:
            raise ValueError("Page numbers must be >= 1")
        if a > b:
            a, b = b, a
        if a > total:
            continue
        b = min(b, total)
        for n in range(a, b + 1):
            seq.append(n)

    if not seq:
        raise ValueError("No pages selected")

    writer = PdfWriter()
    for n in seq:
        writer.add_page(reader.pages[n - 1])

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def reorder_pages_pdf_bytes(pdf_bytes: bytes, sequence: List[int]) -> bytes:
    """
    Reorder / duplicate pages based on sequence (1-based).
    Example: [3,1,1,2] duplicates page 1.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)
    if not sequence:
        raise ValueError("No page sequence provided")

    writer = PdfWriter()
    for n in sequence:
        if n < 1 or n > total:
            raise ValueError(f"Page {n} out of range (1..{total})")
        writer.add_page(reader.pages[n - 1])

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
