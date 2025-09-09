import fitz  # PyMuPDF
import re
import numpy as np
import easyocr
from PIL import Image

# Initialize EasyOCR once
reader = easyocr.Reader(['en'], gpu=False)

def extract_text_from_pdf(pdf_stream, force_ocr=False):
    """
    Extracts text from PDF (PyMuPDF) and falls back to OCR if needed.
    """
    text = ""
    try:
        with fitz.open(stream=pdf_stream.read(), filetype="pdf") as doc:
            for page in doc:
                page_text = page.get_text()

                if force_ocr or not page_text.strip():
                    pix = page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    img_np = np.array(img)
                    ocr_results = reader.readtext(img_np)
                    page_text = "\n".join([line[1] for line in ocr_results])

                text += page_text + "\n"
    except Exception as e:
        print(f"❌ PDF text extraction failed: {e}")

    return text

def extract_lib_paths(text):
    """
    Finds $LIB_FONCTIONS_SITE/05_RNTBCI/... style paths.
    """
    pattern = r"\$LIB_FONCTIONS_SITE/05_RNTBCI/[^\s,;]+"
    matches = re.findall(pattern, text)
    return sorted(set(matches))

def extract_pdf_metadata_and_paths(pdf_stream, force_ocr=False):
    """
    Reads a PDF, extracts metadata, LIB paths, and returns
    segment until 'sheet1'.
    """
    text = extract_text_from_pdf(pdf_stream, force_ocr=force_ocr)
    paths = extract_lib_paths(text)

    metadata = {
        "Project": re.search(r"Project[:\s]+(.+)", text, re.IGNORECASE).group(1).strip() if re.search(r"Project[:\s]+(.+)", text, re.IGNORECASE) else "Not found",
        "Milestone": re.search(r"Milestone[:\s]+(.+)", text, re.IGNORECASE).group(1).strip() if re.search(r"Milestone[:\s]+(.+)", text, re.IGNORECASE) else "Not found",
        "Maturity": re.search(r"Maturity[:\s]+(.+)", text, re.IGNORECASE).group(1).strip() if re.search(r"Maturity[:\s]+(.+)", text, re.IGNORECASE) else "Not found",
    }

    # Extract text up to "sheet1" (case-insensitive)
    sheet_match = re.search(r"(.+?sheet\s*1)", text, re.IGNORECASE | re.DOTALL)
    segment = sheet_match.group(1).strip() if sheet_match else ""

    return metadata, paths, segment
