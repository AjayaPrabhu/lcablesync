# ocr_utils.py
from pdf2image import convert_from_bytes
from PIL import Image
import easyocr
import fitz
import re
import numpy as np
import cv2
import pandas as pd
import difflib
import unicodedata
import os

# ------------- CONFIG -------------
POPPLER_PATH = r"C:\tes\poppler-24.07.0\Library\bin"
PDF_RECOG_PATH = r"C:\lcablesync\pdf_recog.xlsx"
OCR_SCALE = 3            # upscaling factor for OCR
HEADER_CROP_RATIO = 0.20 # top 20% default header
# ----------------------------------

# initialize OCR reader (add 'fr' if documents are French-heavy)
reader = easyocr.Reader(['en', 'fr'], gpu=False)

# load recognition Excel safely
if os.path.exists(PDF_RECOG_PATH):
    df_recog = pd.read_excel(PDF_RECOG_PATH)
    df_recog.columns = df_recog.columns.str.strip()
else:
    df_recog = pd.DataFrame(columns=['Project', 'Milestone', 'Maturity'])

# ensure expected cols exist (may be empty)
EXPECTED_COLS = ['Project', 'Milestone', 'Maturity']
for c in EXPECTED_COLS:
    if c not in df_recog.columns:
        df_recog[c] = ""

# keep original strings but normalized for matching
for c in EXPECTED_COLS:
    df_recog[c] = df_recog[c].astype(str).str.strip()

# ---------- helpers ----------
def _strip_accents(s: str) -> str:
    if not s:
        return s
    return ''.join(ch for ch in unicodedata.normalize('NFD', s) if unicodedata.category(ch) != 'Mn')

def _normalize_for_match(s: str) -> str:
    s = (s or "").strip()
    s = _strip_accents(s)
    s = re.sub(r'[\u2018\u2019\u201c\u201d`]', "'", s)  # fancy quotes
    s = re.sub(r'[\s\-_]+', ' ', s)
    return s.lower()

# deskew image via minAreaRect of non-zero pixels
def _deskew(img):
    # img: grayscale numpy array
    coords = np.column_stack(np.where(img < 255))
    if coords.shape[0] < 10:
        return img
    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    (h, w) = img.shape[:2]
    M = cv2.getRotationMatrix2D((w//2, h//2), angle, 1.0)
    rotated = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated

def _preprocess_pil(pil_img: Image.Image, scale=OCR_SCALE):
    """Grayscale -> CLAHE -> denoise -> threshold -> deskew -> upsample"""
    img = pil_img.convert("L")
    arr = np.array(img)
    # CLAHE
    try:
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        arr = clahe.apply(arr)
    except Exception:
        pass
    arr = cv2.medianBlur(arr, 3)
    arr = _deskew(arr)
    # Otsu threshold
    try:
        _, arr_bin = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    except Exception:
        _, arr_bin = cv2.threshold(arr, 150, 255, cv2.THRESH_BINARY)
    if scale and scale != 1:
        h, w = arr_bin.shape[:2]
        arr_bin = cv2.resize(arr_bin, (w*scale, h*scale), interpolation=cv2.INTER_CUBIC)
    return arr_bin

def extract_text_from_image_pil(pil_image: Image.Image, scale=OCR_SCALE):
    """Return newline-joined OCR text for a PIL image, with debug print of lines."""
    img_np = _preprocess_pil(pil_image, scale=scale)
    results = reader.readtext(img_np)  # [bbox, text, conf]
    lines = []
    for it in results:
        if len(it) >= 2:
            t = it[1].strip()
            if t:
                lines.append(t)
    # debug print
    print("🔍 OCR detected lines (count={}):".format(len(lines)))
    for ln in lines[:200]:
        print("  →", ln)
    return "\n".join(lines)

# tolerant LIB extraction (case-insensitive, accepts OCR $->S)
def extract_lib_paths_from_text(text: str):
    if not text:
        return []

    # Match optional leading number + $LIB... and continue until "sheet1"
    pattern = re.compile(
        r'(?:\d+\s*)?[$S]\s*LIB[_\s\-]?FONCTIONS[_\s\-]?SITE.*?sheet1',
        re.IGNORECASE | re.DOTALL
    )

    matches = pattern.findall(text)
    cleaned = []
    for m in matches:
        # Collapse multiple spaces, normalize slashes
        m2 = re.sub(r'\s+', ' ', m).strip()
        m2 = m2.replace('\\', '/')
        cleaned.append(m2)

    # Unique, preserving order
    out = []
    seen = set()
    for c in cleaned:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out

# fuzzy check using difflib per-line
def _fuzzy_match_candidates_in_lines(candidates, lines, threshold=0.60):
    # returns best matching candidate (original string) or None
    best_cand = None
    best_score = 0.0
    for cand in candidates:
        cand_norm = _normalize_for_match(cand)
        for ln in lines:
            ln_norm = _normalize_for_match(ln)
            score = difflib.SequenceMatcher(None, cand_norm, ln_norm).ratio()
            if score > best_score:
                best_score = score
                best_cand = cand
    if best_score >= threshold:
        return best_cand, best_score
    return None, best_score

# extract metadata from lines + optional text_layer
def extract_metadata_from_lines(lines, text_layer=""):
    """
    lines: list of OCR lines (ordered top->bottom)
    text_layer: selectable text (if available)
    Returns dict with keys: Project, Milestone, Maturity (value or 'Not found')
    """
    combined_lines = lines[:]
    if text_layer:
        for l in text_layer.splitlines():
            if l.strip():
                combined_lines.append(l.strip())

    # quick normalization of lines
    combined_lines = [re.sub(r'\s+', ' ', l).strip() for l in combined_lines if l.strip()]
    print("ℹ️ Candidate header lines ({}):".format(len(combined_lines)))
    for ln in combined_lines[:40]:
        print("   >", ln)

    # 1) Try Maturity: pattern V\d+
    maturity = "Not found"
    for ln in combined_lines[:15]:  # search top lines first
        m = re.search(r'\bV[\s:-]*([0-9]{1,2})\b', ln, re.IGNORECASE)
        if m:
            maturity = "V" + m.group(1)
            break
    # fallback: merged text search
    if maturity == "Not found":
        merged = " ".join(combined_lines[:30])
        m = re.search(r'\bV[\s:-]*([0-9]{1,2})\b', merged, re.IGNORECASE)
        if m:
            maturity = "V" + m.group(1)

    # 2) Try Project: look for a small integer code near top (e.g. 202)
    project = "Not found"
    for ln in combined_lines[:12]:
        # common project codes are 2-4 digit numbers - adjust if your codes differ
        m = re.search(r'\b(\d{2,4})\b', ln)
        if m:
            # simple heuristic: if it's not a year > 2030 etc
            val = m.group(1)
            if not (len(val) == 4 and int(val) > 2030):
                project = val
                break
    # fallback: if df_recog contains Project candidates, fuzzy match them
    if project == "Not found" and 'Project' in df_recog.columns and df_recog['Project'].dropna().any():
        cands = [str(x).strip() for x in df_recog['Project'].dropna().unique() if str(x).strip()]
        best, score = _fuzzy_match_candidates_in_lines(cands, combined_lines, threshold=0.55)
        if best:
            project = best

    # 3) Milestone: try to match df_recog Milestone candidates by fuzzy across lines
    milestone = "Not found"
    if 'Milestone' in df_recog.columns and df_recog['Milestone'].dropna().any():
        cands = [str(x).strip() for x in df_recog['Milestone'].dropna().unique() if str(x).strip()]
        best, score = _fuzzy_match_candidates_in_lines(cands, combined_lines, threshold=0.50)
        if best:
            milestone = best

    # heuristic fallback: look for keywords like 'central' 'gateway' etc (lowercase)
    if milestone == "Not found":
        for ln in combined_lines[:12]:
            if re.search(r'central\s+gateway', ln, re.IGNORECASE) or re.search(r'gateway', ln, re.IGNORECASE):
                milestone = re.sub(r'\s+', ' ', ln).strip()
                break

    return {"Project": project, "Milestone": milestone, "Maturity": maturity}

# ---------------- main function used by Flask ----------------
def extract_pdf_metadata_and_paths(file_bytes, header_crop_ratio=HEADER_CROP_RATIO, ocr_scale=OCR_SCALE, poppler_path=POPPLER_PATH):
    """
    Returns (top_info_dict, lib_paths_list)
    top_info keys: Project, Milestone, Maturity (value or 'Not found')
    """
    # -- first page multi-crops OCR --
    first_page_img = None
    try:
        pages = convert_from_bytes(file_bytes, first_page=1, last_page=1, poppler_path=poppler_path)
        if pages:
            first_page_img = pages[0]
    except Exception as e:
        print("⚠️ convert_from_bytes first page failed:", e)
        first_page_img = None

    header_lines = []
    text_layer = ""
    if first_page_img:
        w, h = first_page_img.size
        # try several header crop heights (small->larger) to be robust
        for ratio in (header_crop_ratio * 0.6, header_crop_ratio, header_crop_ratio * 1.6):
            crop_h = max(30, int(h * ratio))
            crop = first_page_img.crop((0, 0, w, crop_h))
            txt = extract_text_from_image_pil(crop, scale=ocr_scale)
            if txt:
                header_lines.extend([l for l in txt.splitlines() if l.strip()])
        # also OCR the full first page as backup
        full_txt = extract_text_from_image_pil(first_page_img, scale=max(1, ocr_scale-1))
        if full_txt:
            header_lines.extend([l for l in full_txt.splitlines() if l.strip()])

        # try PyMuPDF text layer for first page
        try:
            doc = fitz.open("pdf", file_bytes)
            if doc.page_count >= 1:
                p0 = doc.load_page(0)
                text_layer = p0.get_text() or ""
        except Exception as e:
            print("⚠️ PyMuPDF first page text failed:", e)

    # dedupe preserve order
    seen = set()
    ordered_lines = []
    for ln in header_lines:
        ln2 = re.sub(r'\s+', ' ', ln).strip()
        if ln2 and ln2 not in seen:
            seen.add(ln2)
            ordered_lines.append(ln2)

    # extract metadata
    top_info = extract_metadata_from_lines(ordered_lines, text_layer)

    # -- last page: try text layer first, then OCR fallback --
    lib_paths = []
    try:
        doc = fitz.open("pdf", file_bytes)
        if doc.page_count >= 1:
            # text layer of last page
            try:
                last_txt = doc.load_page(doc.page_count - 1).get_text()
            except Exception as e:
                print("⚠️ fitz.get_text() last page failed:", e)
                last_txt = ""
            lib_paths = extract_lib_paths_from_text(last_txt)
            if not lib_paths:
                # OCR last page as image
                try:
                    last_img = convert_from_bytes(file_bytes, first_page=doc.page_count, last_page=doc.page_count, poppler_path=poppler_path)[0]
                    last_ocr = extract_text_from_image_pil(last_img, scale=ocr_scale)
                    lib_paths = extract_lib_paths_from_text(last_ocr)
                except Exception as e:
                    print("⚠️ OCR fallback on last page failed:", e)
    except Exception as e:
        print("⚠️ PyMuPDF open failed for last page:", e)

    # final debug print
    print("🧠 Metadata found:", top_info)
    print("🔗 LIB paths found:", lib_paths)
    return top_info, lib_paths

def extract_text_from_pdf(pdf_path):
    """Extract all text from a PDF file."""
    text = ""
    with fitz.open(pdf_path) as doc:
        for page in doc:
            text += page.get_text()
    return text
