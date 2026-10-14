"""OCR engine wrapper, image/PDF loading, orientation. Everything runs locally (RapidOCR on ONNX Runtime)."""
import io, os, re
import numpy as np, cv2
from PIL import Image, ImageOps

_eng = None
def engine():
    global _eng
    if _eng is None:
        from rapidocr_onnxruntime import RapidOCR
        _eng = RapidOCR()
    return _eng

_CACHE = os.environ.get("CHECKFLOW_OCR_CACHE")   # dev only: memoize OCR results on disk while tuning parsers

def ocr(img):
    """-> list of {t, s, x0, y0, x1, y1} in image pixel coordinates."""
    if _CACHE:
        import hashlib, pickle
        os.makedirs(_CACHE, exist_ok=True)
        f = os.path.join(_CACHE, hashlib.md5(img.tobytes() + str(img.shape).encode()).hexdigest() + ".pkl")
        if os.path.exists(f): return pickle.load(open(f, "rb"))
        out = _ocr(img); pickle.dump(out, open(f, "wb")); return out
    return _ocr(img)

def _ocr(img):
    r, _ = engine()(img)
    import math
    out = []
    for b, t, s in (r or []):
        if not t.strip(): continue
        ang = math.atan2(b[1][1] - b[0][1], (b[1][0] - b[0][0]) or 1e-6)
        out.append(dict(t=t.strip(), s=float(s), x0=min(p[0] for p in b), y0=min(p[1] for p in b),
                        x1=max(p[0] for p in b), y1=max(p[1] for p in b), a=ang))
    return out

def skew(items):
    """Median text-line angle (radians) of the page, from the longer OCR boxes."""
    angs = sorted(i.get("a", 0) for i in items if len(i["t"]) >= 6)
    return angs[len(angs) // 2] if angs else 0.0

def w_(i): return i["x1"] - i["x0"]
def h_(i): return i["y1"] - i["y0"]
def cy_(i): return (i["y0"] + i["y1"]) / 2
def norm(s): return re.sub(r"[^A-Z0-9]", "", (s or "").upper())
def text_of(items): return " ".join(i["t"] for i in items)

def _resize_max(a, max_side):
    s = max_side / max(a.shape[:2])
    return cv2.resize(a, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else a

PDF_DPI = 150

def load_pages(data, filename=""):
    """Bytes of an image or a (multi-page) PDF -> list of BGR numpy images."""
    if data[:5] == b"%PDF-" or filename.lower().endswith(".pdf"):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        out = []
        for page in pdf:
            pil = page.render(scale=PDF_DPI / 72).to_pil().convert("RGB")
            out.append(_resize_max(np.array(pil)[:, :, ::-1].copy(), 2200))
        pdf.close()
        return out
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    return [_resize_max(np.array(im)[:, :, ::-1].copy(), 2000)]

ROT = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
def rotate(img, deg): return img if not deg else cv2.rotate(img, ROT[deg])

def _quality(items):
    """How much readable text an OCR pass produced (upright text scores high, rotated text low)."""
    good = [i for i in items if len(i["t"]) >= 3 and sum(c.isalnum() for c in i["t"]) / len(i["t"]) > 0.6]
    return sum(i["s"] * min(len(i["t"]), 30) for i in good)

def orient(img):
    """Pick the rotation (0/90/180/270) that yields the most readable text. Cheap: works on a small copy.
    RapidOCR reads upside-down words too, so 180 must win clearly (layout positions matter to the parsers)."""
    small = _resize_max(img, 900)
    base = ocr(small)
    if not base: return 0
    long_ = [i for i in base if len(i["t"]) >= 4]
    vert = sum(1 for i in long_ if h_(i) > 1.3 * w_(i))
    if long_ and vert / len(long_) >= 0.35:
        q90, q270 = _quality(ocr(rotate(small, 90))), _quality(ocr(rotate(small, 270)))
        return 90 if q90 >= q270 else 270
    q0 = _quality(base)
    if q0 > 400: return 0
    q180 = _quality(ocr(rotate(small, 180)))
    return 180 if q180 > 1.4 * q0 + 20 else 0

def jpeg(img, q=80, max_side=1800):
    ok, buf = cv2.imencode(".jpg", _resize_max(img, max_side), [cv2.IMWRITE_JPEG_QUALITY, q])
    return buf.tobytes()
