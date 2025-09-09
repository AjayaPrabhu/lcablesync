#from predict_image import predict_circuit_domain
#from circuit_classifier.predict_image import predict_circuit_domain

from flask import Flask, render_template, request, jsonify, send_from_directory, send_file
import os
import re
import io

import pandas as pd
from PIL import Image
import pytesseract

import numpy as np
import cv2  # (kept if you use it elsewhere)

from ocr_utils import extract_text_from_pdf, extract_lib_paths_from_text

app = Flask(__name__)

# ---------- Paths ----------
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
PDF_ROOT = r"C:\LCableserver"
EXCEL_PATH = r"C:\lcablesync\sfa_dp.xlsx"

# ---------- Load Excel ----------
try:
    df = pd.read_excel(EXCEL_PATH)
    df.columns = df.columns.str.strip()
    df['Code Fonction'] = df['Code Fonction'].astype(str).str.lower().str.strip()
    print("Excel loaded successfully.")
except Exception as e:
    df = pd.DataFrame()
    print(f"Failed to load Excel: {e}")

# ---------- Display name mapping ----------
display_names = {
    'Code Fonction': 'sfa code',
    'wording System in ENG': 'system'
}

# ---------- Helpers ----------
def is_allowed_doc(filename: str) -> bool:
    return filename.lower().endswith(('.pdf', '.txt'))

def is_bl_file(fname: str) -> bool:
    return fname.lower().startswith('bl_')

def strict_platform_sfa_regex(platform: str, sfa: str) -> re.Pattern:
    """
    Return a compiled regex that matches: _{platform}_{sfa}_ (case-insensitive)
    If platform is empty, allow any [a-z0-9_]+ as platform.
    """
    if platform:
        pat = rf"_{re.escape(platform)}_{re.escape(sfa)}_"
    else:
        pat = rf"_[a-z0-9_]+_{re.escape(sfa)}_"
    return re.compile(pat, re.IGNORECASE)

def filter_pdfs(sfa_input: str = "", platform_input: str = "", filename_input: str = ""):
    """
    Return list of tuples (file, rel_path, fname_lower) for files that pass filters:
    - optional filename substring
    - optional platform substring (in name)
    - SFA must appear immediately after platform token (strict)
    - skip BL_ files for dashboard-like uses (caller can decide to skip or not)
    """
    matched = []
    sfa_input = (sfa_input or "").strip().lower()
    platform_input = (platform_input or "").strip().lower()
    filename_input = (filename_input or "").strip().lower()

    sfa_pattern = strict_platform_sfa_regex(platform_input, sfa_input) if sfa_input else None

    for root, _, files in os.walk(PDF_ROOT):
        for file in files:
            if not is_allowed_doc(file):
                continue

            fname = file.lower()
            if filename_input and filename_input not in fname:
                continue
            if platform_input and platform_input not in fname:
                continue
            if sfa_pattern and not sfa_pattern.search(fname):
                continue

            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, PDF_ROOT).replace("\\", "/")
            matched.append((file, rel_path, fname))
    return matched

# ---------- Routes ----------
def perform_search(sfa_input: str = "", platform_input: str = "", filename_input: str = ""):
    """
    Unified search function used by both dashboard and PDF search.
    Enforces strict rule: SFA must appear immediately after platform.
    Returns a list of dicts with {name, path}.
    """
    results = []
    sfa_input = (sfa_input or "").strip().lower()
    platform_input = (platform_input or "").strip().lower()
    filename_input = (filename_input or "").strip().lower()

    for root, _, files in os.walk(PDF_ROOT):
        for file in files:
            if not is_allowed_doc(file):
                continue

            fname = file.lower()
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, PDF_ROOT).replace("\\", "/")

            # ✅ filename filter
            if filename_input and filename_input not in fname:
                continue

            # ✅ platform filter
            if platform_input and platform_input not in fname:
                continue

            # ✅ strict SFA filter
            if sfa_input:
                if platform_input:
                    # must be like "...platform_sfa_"
                    pattern = rf"{re.escape(platform_input)}_{re.escape(sfa_input)}_"
                else:
                    # allow any platform: "...<platform>_sfa_"
                    pattern = rf"_[a-z0-9_]+_{re.escape(sfa_input)}_"

                if not re.search(pattern, fname):
                    continue

            results.append({
                "name": file,
                "path": rel_path
            })

    return results

@app.route('/analyze-pdf', methods=['POST'])
def analyze_pdf():
    pdf_file = request.files.get('file')
    if not pdf_file:
        return jsonify({'error': 'No PDF uploaded'}), 400

    try:
        os.makedirs("temp", exist_ok=True)
        temp_path = os.path.join("temp", pdf_file.filename)
        pdf_file.save(temp_path)

        text = extract_text_from_pdf(temp_path)

        # ✅ Print everything after the SOMMAIRE marker
        marker = "SOMMAIRE DE LA SCHEMATHEQUE PDF:"
        idx = text.find(marker)
        if idx != -1:
            text_after_marker = text[idx + len(marker):].strip()
            print("📄 Everything after SOMMAIRE marker:\n", text_after_marker)
        else:
            print("⚠️ Marker not found in PDF text.")

        os.remove(temp_path)

        paths = extract_lib_paths_from_text(text)
        if paths:
            return jsonify({'result': "\n".join(paths)})
        else:
            return jsonify({'result': '❌ No matching $LIB_FONCTIONS_SITE/05_RNTBCI/ paths found.'})

    except Exception as e:
        return jsonify({'error': f"PDF processing failed: {e}"}), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.get_json().get('message', '').strip().lower()
    matched_rows = df[df['Code Fonction'] == user_input]
    if not matched_rows.empty:
        row = matched_rows.iloc[0]
        result = {display_names.get(col, col): str(row[col]) for col in df.columns}
        return jsonify(response="\n".join([f"{k}: {v}" for k, v in result.items()]))
    else:
        return jsonify(response="No match found in Code Fonction.")

@app.route('/search-pdf')
def search_pdf():
    sfa_input = request.args.get("sfa", "").strip().lower()
    platform_input = request.args.get("platform", "").strip().lower()
    filename_input = request.args.get("filename", "").strip().lower()

    # If user accidentally provides "c1ahsevo_cmfb" → normalize to just "cmfb"
    if platform_input and "_" in platform_input:
        platform_input = platform_input.split("_")[-1]

    results = []
    for root, _, files in os.walk(PDF_ROOT):
        for file in files:
            if not file.lower().endswith(('.pdf', '.txt')):
                continue

            fname = file.lower()
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, PDF_ROOT).replace("\\", "/")

            # ✅ filename filter
            if filename_input and filename_input not in fname:
                continue

            # ✅ platform filter
            if platform_input and platform_input not in fname:
                continue

            # ✅ strict SFA filter (only immediate after platform)
            if sfa_input:
                if platform_input:
                    # allow any prefix, must be like "...platform_sfa_"
                    pattern = rf"{re.escape(platform_input)}_{re.escape(sfa_input)}_"
                else:
                    pattern = rf"_[a-z0-9]+_{re.escape(sfa_input)}_"

                if not re.search(pattern, fname):
                    continue

            results.append({
                "name": file,
                "path": rel_path
            })

    return jsonify(results)


@app.route('/preview/<path:rel_path>')
def preview_file(rel_path):
    try:
        # Build safe absolute path
        abs_root = os.path.abspath(PDF_ROOT)
        safe_path = os.path.abspath(os.path.normpath(os.path.join(PDF_ROOT, rel_path)))

        # Security: ensure inside PDF_ROOT
        if os.path.commonpath([abs_root, safe_path]) != abs_root:
            return {"error": "Access denied"}, 403

        if not os.path.isfile(safe_path):
            return {"error": f"File not found: {safe_path}"}, 404

        # Return file for in-browser preview
        return send_file(safe_path, as_attachment=False)

    except Exception as e:
        return {"error": str(e)}, 500
@app.route('/search-summary')
def search_summary():
    sfa_input = request.args.get("sfa", "").strip()
    platform_input = request.args.get("platform", "").strip()
    filename_input = request.args.get("filename", "").strip()

    results = perform_search(sfa_input, platform_input, filename_input)

    summary = {}

    for r in results:
        path = r["path"]
        fname = r["name"]

        # Extract project
        project_match = re.search(r"/(X[0-9A-Za-z]+)[/_]", path)
        project = project_match.group(1) if project_match else "UNKNOWN"

        # Extract version
        version_match = re.search(r"_(V[0-9]+)", fname, re.IGNORECASE)
        version = version_match.group(1).upper() if version_match else "V?"

        # Extract milestone
        milestone_match = re.search(
            r"\b(VPC|VC|PIED|PIEC|PIEB|PT1?|PT2?|RFQ|QCDP)\b",
            path + " " + fname,
            re.IGNORECASE
        )
        milestone = milestone_match.group(1).upper() if milestone_match else "UNK"

        key = (project, milestone)
        if key not in summary:
            summary[key] = set()
        summary[key].add(version)

    details = []
    locators = []
    for (project, milestone), versions in summary.items():
        versions_sorted = sorted(versions, key=lambda v: int(v[1:]) if v[1:].isdigit() else 0)
        locator = f"{project}-{milestone}-" + ",".join(versions_sorted)
        locators.append(locator)
        details.append({
            "project": project,
            "marker": milestone,
            "versions": versions_sorted
        })

    return jsonify({
        "locators": locators,
        "details": details,
        "total_groups": len(summary)
    })

@app.route('/search-versions')
def search_versions():
    sfa_input = request.args.get("sfa", "").strip().lower()
    platform_input = request.args.get("platform", "").strip().lower()
    filename_input = request.args.get("filename", "").strip().lower()

    results = perform_search(sfa_input, platform_input, filename_input)

    versions = set()
    for r in results:
        fname = r["name"].lower()
        match = re.search(r'_v(\d+)', fname)
        if match:
            versions.add("V" + match.group(1))

    return jsonify(sorted(versions, key=lambda v: int(v[1:])))


@app.route('/analyze-image', methods=['POST'])
def analyze_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'Empty file'}), 400

    try:
        image = Image.open(file.stream).convert("RGB")
        raw_text = pytesseract.image_to_string(image, lang="eng")
        cleaned_text = raw_text.strip()
        return jsonify({'result': f"🧠 Result:\n{cleaned_text}"})
    except Exception as e:
        return jsonify({'error': f'OCR failed: {e}'}), 500

@app.route('/download/<path:path>')
def download(path):
    abs_root = os.path.abspath(PDF_ROOT)
    safe_path = os.path.abspath(os.path.normpath(os.path.join(PDF_ROOT, path)))
    if os.path.commonpath([abs_root, safe_path]) != abs_root:
        return "Access denied", 403
    return send_from_directory(os.path.dirname(safe_path), os.path.basename(safe_path), as_attachment=True)

@app.route('/extract-metadata', methods=['POST'])
def extract_metadata():
    pdf_file = request.files.get('file')
    rel_path = request.form.get("rel_path", "")  # ✅ optional relative path passed by frontend

    if not pdf_file:
        return jsonify({'error': 'No PDF uploaded'}), 400

    try:
        # Save temporary PDF
        os.makedirs("temp", exist_ok=True)
        temp_path = os.path.join("temp", pdf_file.filename)
        pdf_file.save(temp_path)

        # Extract raw text from PDF (if needed for project/milestone/maturity)
        text = extract_text_from_pdf(temp_path)

        # Cleanup temp
        os.remove(temp_path)

        # --------- Parse Metadata consistently with strict platform->SFA rule ---------
        filename_lower = pdf_file.filename.lower()

        metadata = {}
        metadata["Type_schema"] = "fonct"

        # Platform & SFA (strict: platform token immediately followed by SFA digits)
        # matches: _cmfb_1_... or _cmfa_34_...
        m = re.search(r'_(?P<platform>[a-z0-9_]+)_(?P<sfa>\d{1,4})_', filename_lower, re.IGNORECASE)
        if m:
            metadata["Platform"] = m.group("platform")
            metadata["Code_fonct"] = m.group("sfa")

        # Libellé function: grab text between the SFA and _Vn
        # e.g. ... _cmfb_1_CIRCUIT_DE_DEMARRAGE_Starter_V17.pdf
        lib = re.search(r'_[a-z0-9_]+_\d{1,4}_(?P<label>.*?)_v\d+', filename_lower, re.IGNORECASE)
        if lib:
            metadata["Libelle_fonction"] = lib.group("label").replace("_", " ").strip()

        # Project (from text content)
        proj_match = re.search(r'\b(X[0-9A-Za-z_]+)\b', text)
        if proj_match:
            metadata["Project"] = proj_match.group(1)

        # Milestone (search filename + text + folder path)
        search_space = f"{pdf_file.filename} {text} {rel_path}"
        milestone_match = re.search(
            r'\b(VPC|VC|PIED|PIEC|PT1?|PT2?|PIEB|RFQ_PIEA|RFQ|QCDP)\b',
            search_space,
            re.IGNORECASE
        )
        if milestone_match:
            metadata["Milestone"] = milestone_match.group(1).upper()

        # Maturity Schema
        lower_text = text.lower()
        if "definitif" in lower_text:
            metadata["Maturity_Schema"] = "Definitif (Serial version)"
        elif "hypothese" in lower_text:
            metadata["Maturity_Schema"] = "Hypotheses"
        elif "in work" in lower_text:
            metadata["Maturity_Schema"] = "In Work"

        return jsonify(metadata)

    except Exception as e:
        return jsonify({'error': f"Metadata extraction failed: {e}"}), 500
@app.route('/predict-image', methods=['POST'])
def predict_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'Empty file'}), 400

    try:
        os.makedirs("temp", exist_ok=True)
        filename = secure_filename(file.filename)
        img_path = os.path.join("temp", filename)
        file.save(img_path)

        result = predict_circuit_domain(img_path)
        os.remove(img_path)

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'Prediction failed: {e}'}), 500

if __name__ == '__main__':
    app.run(debug=True)
