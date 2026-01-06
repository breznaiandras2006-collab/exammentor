# tools.py
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import List, Tuple, Optional

from pypdf import PdfReader, PdfWriter

# Optional extras (installed via requirements.txt)
try:  # watermark / page numbers
    from reportlab.pdfgen import canvas as _rl_canvas
    from reportlab.lib.colors import Color as _rl_Color
except Exception:  # pragma: no cover
    _rl_canvas = None
    _rl_Color = None

try:  # images -> PDF
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:  # PDF -> images
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

import difflib


# ---------------- Study helpers ----------------
_SEP_PATTERNS = [
    r"\s*:\s*",
    r"\s+-\s+",
    r"\s+–\s+",
    r"\s+—\s+",
    r"\s*=\s*",
    r"\s*->\s*",
    r"\s*=>\s*",
]


def extract_qa_pairs(note_body: str) -> List[Tuple[str, str]]:
    """Heuristic Q/A extractor from a note body.

    Supports common patterns:
    - Term: definition
    - Term - definition (also en-dash/em-dash)
    - Q: ... / A: ... pairs
    """
    text = (note_body or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln]

    out: List[Tuple[str, str]] = []

    # Q:/A: mode
    pending_q: Optional[str] = None
    for ln in lines:
        l = re.sub(r"^[\-*•\u2022\u25CF]+\s+", "", ln).strip()
        if not l:
            continue
        if l.lower().startswith("q:"):
            pending_q = l[2:].strip()
            continue
        if l.lower().startswith("a:") and pending_q:
            a = l[2:].strip()
            if pending_q and a:
                out.append((pending_q, a))
            pending_q = None
            continue

    # separator mode (line-by-line)
    for ln in lines:
        l = re.sub(r"^[\-*•\u2022\u25CF]+\s+", "", ln).strip()
        if not l:
            continue

        # skip Q:/A: tokens handled already
        if l.lower().startswith("q:") or l.lower().startswith("a:"):
            continue

        # try split on first matching separator
        for pat in _SEP_PATTERNS:
            m = re.search(pat, l)
            if not m:
                continue
            left = l[: m.start()].strip()
            right = l[m.end() :].strip()
            if left and right:
                # prevent obviously bad splits (super long "question")
                if len(left) <= 180 and len(right) <= 4000:
                    out.append((left, right))
            break

    # de-dup (keep order)
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for q, a in out:
        key = (q.strip(), a.strip())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(key)
    return uniq


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


# ---------------- PDF Extras (Watermark, Page Numbers, Images, Compare) ----------------
def add_text_watermark_pdf_bytes(
    pdf_bytes: bytes,
    watermark_text: str,
    *,
    font_size: int = 46,
    rotation: int = 45,
    opacity: float = 0.12,
) -> bytes:
    """Add a diagonal text watermark to every page.

    Uses reportlab to generate a per-page overlay PDF and merges it with pypdf.
    """
    if _rl_canvas is None or _rl_Color is None:
        raise RuntimeError("reportlab nincs telepítve (watermark funkcióhoz kell)")

    text = (watermark_text or "").strip()
    if not text:
        raise ValueError("Watermark szöveg üres")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()

    for page in reader.pages:
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)

        # create overlay
        buf = io.BytesIO()
        c = _rl_canvas.Canvas(buf, pagesize=(w, h))
        alpha = max(0.02, min(float(opacity), 0.6))
        c.setFillColor(_rl_Color(0, 0, 0, alpha=alpha))
        c.setFont("Helvetica", int(font_size))
        c.saveState()
        c.translate(w / 2.0, h / 2.0)
        c.rotate(int(rotation))
        c.drawCentredString(0, 0, text)
        c.restoreState()
        c.showPage()
        c.save()
        buf.seek(0)

        overlay = PdfReader(buf).pages[0]
        try:
            page.merge_page(overlay)
        except Exception:
            # older pypdf name
            page.mergePage(overlay)
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def add_page_numbers_pdf_bytes(
    pdf_bytes: bytes,
    *,
    start_at: int = 1,
    font_size: int = 10,
    y: int = 18,
    template: str = "{n}/{total}",
    opacity: float = 0.85,
) -> bytes:
    """Add page numbers to every page (bottom-center)."""
    if _rl_canvas is None or _rl_Color is None:
        raise RuntimeError("reportlab nincs telepítve (oldalszám funkcióhoz kell)")

    reader = PdfReader(io.BytesIO(pdf_bytes))
    total = len(reader.pages)
    writer = PdfWriter()

    for idx, page in enumerate(reader.pages, start=0):
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)

        n = int(start_at) + idx
        label = template.format(n=n, total=total)

        buf = io.BytesIO()
        c = _rl_canvas.Canvas(buf, pagesize=(w, h))
        alpha = max(0.2, min(float(opacity), 1.0))
        c.setFillColor(_rl_Color(0, 0, 0, alpha=alpha))
        c.setFont("Helvetica", int(font_size))
        c.drawCentredString(w / 2.0, int(y), label)
        c.showPage()
        c.save()
        buf.seek(0)

        overlay = PdfReader(buf).pages[0]
        try:
            page.merge_page(overlay)
        except Exception:
            page.mergePage(overlay)
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def images_to_pdf_bytes(images: List[Tuple[str, bytes]]) -> bytes:
    """Convert multiple images to a single PDF.

    images: list of (filename, bytes) in desired order.
    """
    if Image is None:
        raise RuntimeError("Pillow nincs telepítve (képek→PDF funkcióhoz kell)")
    if not images:
        raise ValueError("Nincs feltöltött kép")

    pil_images = []
    for name, bts in images:
        try:
            im = Image.open(io.BytesIO(bts))
            if im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            elif im.mode != "RGB":
                im = im.convert("RGB")
            pil_images.append(im)
        except Exception as e:
            raise ValueError(f"Nem tudom megnyitni a képet: {name} ({e})")

    first, rest = pil_images[0], pil_images[1:]
    out = io.BytesIO()
    first.save(out, format="PDF", save_all=True, append_images=rest)
    return out.getvalue()


def pdf_to_images_zip_bytes(
    pdf_bytes: bytes,
    *,
    fmt: str = "png",
    dpi: int = 144,
    max_pages: int = 60,
) -> bytes:
    """Render PDF pages to images and return a ZIP.

    Requires PyMuPDF (fitz). Output is a ZIP that contains page_001.png, ...
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF nincs telepítve (PDF→képek funkcióhoz kell)")

    fmt2 = (fmt or "png").strip().lower()
    if fmt2 not in ("png", "jpg", "jpeg"):
        raise ValueError("Formátum csak png vagy jpg lehet")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_count = doc.page_count
    if page_count == 0:
        raise ValueError("Üres PDF")

    limit = min(int(max_pages), page_count)
    scale = max(0.5, min(float(dpi) / 72.0, 6.0))
    mat = fitz.Matrix(scale, scale)

    out_zip = io.BytesIO()
    with zipfile.ZipFile(out_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(limit):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            ext = "png" if fmt2 == "png" else "jpg"
            img_bytes = pix.tobytes(ext)
            zf.writestr(f"page_{i+1:03d}.{ext}", img_bytes)

        # helpful info file
        zf.writestr(
            "README.txt",
            f"Exportált oldalak: {limit}/{page_count}\nDPI: {dpi}\nFormátum: {fmt2}\n",
        )

    return out_zip.getvalue()


def compare_pdfs_text_summary(
    pdf_a: bytes,
    pdf_b: bytes,
    *,
    max_pages: int = 25,
    max_diff_lines: int = 200,
) -> str:
    """Very lightweight PDF compare (text-based).

    Extracts text from first N pages, then produces a unified diff summary.
    Scanned PDFs without embedded text will produce weak results.
    """
    a = extract_text_from_pdf(pdf_a, max_pages=max_pages)
    b = extract_text_from_pdf(pdf_b, max_pages=max_pages)

    a_lines = (a or "").splitlines()
    b_lines = (b or "").splitlines()

    ratio = difflib.SequenceMatcher(None, a, b).ratio() if (a or b) else 1.0

    diff = list(
        difflib.unified_diff(
            a_lines,
            b_lines,
            fromfile="A",
            tofile="B",
            lineterm="",
            n=2,
        )
    )

    header = [
        f"Text compare (első {max_pages} oldal)",
        f"A: {len(a)} karakter | {len(a_lines)} sor",
        f"B: {len(b)} karakter | {len(b_lines)} sor",
        f"Hasonlóság (0..1): {ratio:.3f}",
        "",
    ]

    if not diff:
        return "\n".join(header + ["✅ Nincs különbség a kinyert szövegben (vagy nincs kinyerhető szöveg)."])

    # cap output
    if len(diff) > max_diff_lines:
        diff = diff[:max_diff_lines] + [f"… (diff csonkolva, összesen {len(diff)} sor)"]

    return "\n".join(header + diff)


def encrypt_pdf_bytes(pdf_bytes: bytes, password: str) -> bytes:
    """Encrypt PDF with a user password (simple)."""
    pw = (password or "").strip()
    if not pw:
        raise ValueError("Jelszó üres")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    # 128-bit is default in modern pypdf
    writer.encrypt(pw)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def strip_pdf_metadata_bytes(pdf_bytes: bytes) -> bytes:
    """Rewrite PDF without copying metadata.

    Note: this is a pragmatic approach; some PDFs may still contain embedded XMP.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
