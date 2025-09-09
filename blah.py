import fitz  # PyMuPDF
import re
from pdf2image import convert_from_bytes
import easyocr
import numpy as np
import cv2
import sys
import pandas as pd
from thefuzz import process
import os

# === CONFIG ===
POPPLER_PATH = r"C:\tes\poppler-24.07.0\Library\bin"  # Update this to your Poppler bin path
OCR_SCALE = 2
SIMILARITY_THRESHOLD = 80  # Threshold for fuzzy matching (0-100)

# Initialize OCR (English + French)
reader = easyocr.Reader(['en', 'fr'], gpu=False)


def normalize_string(s):
    s = s.upper().strip()
    replacements = {
        '0': 'O',
        '1': 'I',
        '5': 'S',
        '8': 'B',
        '$': 'S',
        'L': 'I',
        '¡': 'I',  # If needed
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    return s


def similarity_score(s1, s2):
    """Returns similarity ratio (0-1) after normalization."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, normalize_string(s1), normalize_string(s2)).ratio()


def preprocess_pil_image(pil_img, scale=OCR_SCALE):
    img = pil_img.convert("L")
    arr = np.array(img)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    arr = clahe.apply(arr)
    arr = cv2.medianBlur(arr, 3)
    _, arr = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    h, w = arr.shape
    return cv2.resize(arr, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)


def ocr_image(pil_img):
    preprocessed = preprocess_pil_image(pil_img)
    results = reader.readtext(preprocessed)
    lines = [res[1].strip() for res in results if len(res) >= 2 and res[1].strip()]
    print(f"🔍 OCR detected {len(lines)} lines:")
    for l in lines:
        print("  →", l)
    return lines


def extract_fields_from_lines(lines):
    fields = {
        "Project": "Not found",
        "Milestone": "Not found",
        "Maturity": "Not found",
        "Version": "Not found",
        "SFA CODE": "Not found",
        "Serial Definition": "Not found",
        "SFA Name": "Not found",
        "Applicability": "Not found",
        "SFA Type": "Not found",
    }

    def extract_by_key(key):
        key_lc = key.lower()
        for line in lines:
            l = line.lower()
            if key_lc in l:
                pattern = re.compile(rf"{re.escape(key_lc)}\s*[:=]\s*(.+)", re.IGNORECASE)
                m = pattern.search(line)
                if m:
                    return m.group(1).strip()
                parts = line.split(key, 1)[-1].split(":", 1)
                if len(parts) > 1:
                    return parts[1].strip()
                parts = line.split(key, 1)[-1].split("=", 1)
                if len(parts) > 1:
                    return parts[1].strip()
        return None

    for k in fields.keys():
        val = extract_by_key(k)
        if val:
            if k == "SFA CODE":
                fields["SFA CODE"] = val
                fields["Serial Definition"] = val
            else:
                fields[k] = val

    # Version fallback when maturity contains version info
    if fields["Version"] == "Not found" and fields["Maturity"].startswith(('V', 'v')):
        fields["Version"] = fields["Maturity"]

    # Heuristic fallback for Project as alphanumeric like 'X1310'
    if fields["Project"] == "Not found":
        for ln in lines:
            if re.match(r"^[A-Za-z]+\d+$", ln):
                fields["Project"] = ln
                break

    # Numeric fallback for Project (2-4 digit number < 2030)
    if fields["Project"] == "Not found":
        for ln in lines:
            m = re.search(r"\b(\d{2,4})\b", ln)
            if m and int(m.group(1)) < 2030:
                fields["Project"] = m.group(1)
                break

    return fields


def contains_valid_metadata(lines):
    for ln in lines:
        if re.search(r"[A-Za-z]+\d+", ln):
            return True
    return False



def fuzzy_match_value(value, reference_list, threshold=SIMILARITY_THRESHOLD):
    """
    Match value to reference list using fuzzy matching.
    Returns (best_match, score) or (None, 0) if no match or empty reference list.
    """
    if not value or value == "Not found":
        return None, 0
    if not reference_list:
        # avoid calling extractOne on empty list
        return None, 0
    
    value_norm = normalize_string(value)
    result = process.extractOne(value_norm, reference_list)
    if result is None:
        return None, 0
    match, score = result
    if score >= threshold:
        return match, score
    return None, score



def match_extracted_fields(extracted_fields, pdf_recog_df):
    matched = {}

    # Normalize reference lists (drop NaNs and strip)
    def get_norm_ref_list(col):
        if col in pdf_recog_df.columns:
            return pdf_recog_df[col].dropna().astype(str).str.strip().map(normalize_string).unique().tolist()
        else:
            return []

    project_refs = get_norm_ref_list("Project")
    milestone_refs = get_norm_ref_list("Milestone")
    maturity_refs = get_norm_ref_list("Maturity")
    sfa_code_refs = get_norm_ref_list("SFA CODE")
    sfa_name_refs = get_norm_ref_list("SFA Name")
    applicability_refs = get_norm_ref_list("Applicability")
    sfa_type_refs = get_norm_ref_list("SFA Type")

    # Match fields
    def do_match(field_name, ref_list):
        val = extracted_fields.get(field_name, None)
        match, score = fuzzy_match_value(val, ref_list)
        matched[field_name] = {
            "extracted_value": val,
            "matched_value": match if match else val,
            "similarity": score,
        }

    do_match("Project", project_refs)
    do_match("Milestone", milestone_refs)
    do_match("Maturity", maturity_refs)
    do_match("SFA CODE", sfa_code_refs)
    do_match("SFA Name", sfa_name_refs)
    do_match("Applicability", applicability_refs)
    do_match("SFA Type", sfa_type_refs)

    # For Version and Serial Definition just keep as-is (or extend similarly)
    matched["Version"] = {
        "extracted_value": extracted_fields.get("Version", "Not found"),
        "matched_value": extracted_fields.get("Version", "Not found"),
        "similarity": 100,
    }
    matched["Serial Definition"] = {
        "extracted_value": extracted_fields.get("Serial Definition", "Not found"),
        "matched_value": extracted_fields.get("Serial Definition", "Not found"),
        "similarity": 100,
    }

    return matched


def extract_title_block(pdf_path):
    print(f"Opening PDF: {pdf_path}")
    doc = fitz.open(pdf_path)
    page = doc[0]

    text = page.get_text().strip()
    print("=== Extracted text from first page ===")
    print(text)

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if not contains_valid_metadata(lines):
        print("Text extraction insufficient/invalid, running OCR fallback...")
        try:
            images = convert_from_bytes(
                open(pdf_path, "rb").read(),
                first_page=1,
                last_page=1,
                poppler_path=POPPLER_PATH,
                dpi=300,
            )
            if not images:
                print("❌ PDF to image conversion failed.")
                return {}

            pil_img = images[0]
            ocr_lines = ocr_image(pil_img)
            fields = extract_fields_from_lines(ocr_lines)

            if fields["Project"] == "Not found":
                for ln in ocr_lines:
                    if re.match(r"^[A-Za-z]+\d+$", ln):
                        fields["Project"] = ln
                        break

            return fields
        except Exception as e:
            print(f"❌ OCR fallback failed: {e}")
            return {}
    else:
        fields = extract_fields_from_lines(lines)
        if fields["Project"] == "Not found":
            for ln in lines:
                if re.match(r"^[A-Za-z]+\d+$", ln):
                    fields["Project"] = ln
                    break
        return fields


def main(pdf_path, excel_path):
    # Check files exist
    if not os.path.isfile(pdf_path):
        print(f"PDF file not found: {pdf_path}")
        return
    if not os.path.isfile(excel_path):
        print(f"Excel file not found: {excel_path}")
        return

    print("\n=== Loading reference Excel data ===")
    pdf_recog = pd.read_excel(excel_path, dtype=str)
    pdf_recog.columns = pdf_recog.columns.str.strip()
    # Lowercase and strip for 'Code Fonction' or others if used further
    # pdf_recog['Code Fonction'] = pdf_recog['Code Fonction'].astype(str).str.lower().str.strip()

    print("\n=== Starting PDF metadata extraction ===")
    extracted_fields = extract_title_block(pdf_path)

    print("\n=== Matching extracted fields against reference Excel data ===")
    matched = match_extracted_fields(extracted_fields, pdf_recog)

    print("\n=== Final Results ===")
    for field, info in matched.items():
        print(f"{field}: Extracted='{info['extracted_value']}', Matched='{info['matched_value']}', Similarity={info['similarity']:.1f}")

    print("\n--- Extraction & matching completed ---")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <pdf_file_path> <reference_excel_path>")
        sys.exit(1)

    pdf_file = sys.argv[1]
    excel_file = sys.argv[2]

    main(pdf_file, excel_file)
