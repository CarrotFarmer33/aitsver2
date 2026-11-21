#!/usr/bin/env python3
"""
build_unified_sheet.py - Multi-Source Vector Test Sheet Generator.
Supports seamless compilation of practice test sheets from:
1. M.S. Chouhan Organic Chemistry (Level 1 & Selected Questions)
2. Allen JEE Chemistry (O-1 & O-2)
3. Allen NEET Chemistry
4. FIITJEE AITS Question Banks
5. Any hybrid combination of 2 or more question banks!

Features:
- Dynamic crop calibration across all sources (eliminates stray codes, watermarks, banner descenders, and gaps).
- Strict answer key validation: questions without answer keys are excluded.
- Native vector PDF rendering with zero quality loss.
"""

import os
import sys
import json
import re
import random
import pymupdf as fitz

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(ROOT_DIR) == "scratch":
    ROOT_DIR = os.path.dirname(ROOT_DIR)
PARENT_DIR = os.path.dirname(ROOT_DIR)
sys.path.insert(0, ROOT_DIR)

import build_allenjee_sheet as baj
from build_vector_test import QuestionManager, find_question_parts
from build_sheets import CROP_X0, CROP_X1, remove_watermarks, open_pdf
import cloud_resolver

PW, PH = 595.0, 842.0
MX = 36.0
COL_W = 507.0
COL_X0 = 45.0
COL_X1 = 552.0
# 2-column layout geometry (Neeraj Kumar & NEET)
COL_W_HALF = 235.0
COL0_X0 = 45.0
COL1_X0 = 325.0
CENTER_X = 295.0


P1_HEADER_TOP = 22.0
P1_HEADER_BOT = 74.0
P1_Y_START = 82.0
SUB_Y_START = 28.0
COL_Y_END = 804.0
GAP_Q = 9.0

def apply_svg_crop_text(svg_text, crop):
    if not crop:
        return svg_text
    top_p = max(0.0, min(50.0, float(crop.get("top", 0) or 0))) / 100.0
    bot_p = max(0.0, min(50.0, float(crop.get("bottom", 0) or 0))) / 100.0
    left_p = max(0.0, min(40.0, float(crop.get("left", 0) or 0))) / 100.0
    right_p = max(0.0, min(40.0, float(crop.get("right", 0) or 0))) / 100.0
    if top_p == 0 and bot_p == 0 and left_p == 0 and right_p == 0:
        return svg_text

    m = re.search(r'viewBox="([^"]+)"', svg_text, re.IGNORECASE)
    if not m:
        return svg_text
    parts = [float(p) for p in re.split(r'[\s,]+', m.group(1).strip()) if p]
    if len(parts) != 4:
        return svg_text

    x, y, w, h = parts
    new_x = x + (w * left_p)
    new_y = y + (h * top_p)
    new_w = max(1.0, w * (1.0 - left_p - right_p))
    new_h = max(1.0, h * (1.0 - top_p - bot_p))

    svg_text = svg_text[:m.start(1)] + f"{new_x:.2f} {new_y:.2f} {new_w:.2f} {new_h:.2f}" + svg_text[m.end(1):]
    svg_text = re.sub(r'(<svg\b[^>]*\bwidth=")[0-9.]+(?:pt|px)?', rf'\g<1>{new_w:.2f}pt', svg_text, count=1, flags=re.I)
    svg_text = re.sub(r'(<svg\b[^>]*\bheight=")[0-9.]+(?:pt|px)?', rf'\g<1>{new_h:.2f}pt', svg_text, count=1, flags=re.I)
    return svg_text

def apply_rect_crop(rect, crop):
    if not crop:
        return rect
    top_p = max(0.0, min(50.0, float(crop.get("top", 0) or 0))) / 100.0
    bot_p = max(0.0, min(50.0, float(crop.get("bottom", 0) or 0))) / 100.0
    left_p = max(0.0, min(40.0, float(crop.get("left", 0) or 0))) / 100.0
    right_p = max(0.0, min(40.0, float(crop.get("right", 0) or 0))) / 100.0
    if top_p == 0 and bot_p == 0 and left_p == 0 and right_p == 0:
        return rect
    h = rect.height
    w = rect.width
    return fitz.Rect(
        rect.x0 + (w * left_p),
        rect.y0 + (h * top_p),
        rect.x1 - (w * right_p),
        rect.y1 - (h * bot_p)
    )

def has_answer_key(q):
    """Returns True if the question has a valid, non-blank answer key."""
    if not q:
        return False
    ans = q.get("answer") or q.get("ans") or q.get("correct_option")
    if ans is None:
        return False
    s = str(ans).strip()
    return s != "" and s != "-" and s != "?" and s.lower() not in ("none", "null", "[blank]")

def calibrate_allenjee_bounds(page, y0, y1):
    """
    Calibrate crop bounds for an Allen JEE question.
    Eliminates stray header lines, preceding section banners (and their descenders),
    trailing question codes (e.g. CBO0001, AS0076), and unindents the question.
    """
    words = page.get_text("words")
    band_words = [w for w in words if y0 - 1.0 <= w[1] <= y1 and 42.0 <= w[0] <= 552.0]
    content_words = [
        w for w in band_words
        if w[1] >= max(y0, 70.0)
        and not (w[1] < y0 + 12.0 and any(h in w[4].lower() for h in ["exercise", "session", "only", "option", "allen", "$//(1", "(only"]))
    ]
    if not content_words:
        return fitz.Rect(74.0, max(y0, 70.0), 552.0, min(y1, 770.0))

    top_w = min(content_words, key=lambda w: w[1])
    cal_y0 = max(y0, top_w[1] - 1.5)

    real_words = [
        w for w in content_words
        if not re.fullmatch(r"^[A-Z]{2,4}\d{4,5}$", w[4].strip())
        and not any(k in w[4].lower() for k in ["session", "allen", "$//(1"])
    ]
    if real_words:
        max_w = max(real_words, key=lambda w: w[3])
        drawings = [d for d in page.get_drawings() if 42.0 <= d['rect'].x0 and d['rect'].x1 <= 552.0 and cal_y0 <= d['rect'].y0 <= y1]
        drawings = [d for d in drawings if d['rect'].height < (y1 - cal_y0)]
        max_d_y = max((d['rect'].y1 for d in drawings), default=cal_y0)
        cal_y1 = min(max(max_w[3], max_d_y) + 3.0, y1)
    else:
        cal_y1 = y1

    # Stem text starts around 70..115 after question number
    stem_words = [w for w in real_words if 68.0 <= w[0] <= 115.0 and w[1] <= cal_y0 + 15.0]
    cal_x0 = (min(w[0] for w in stem_words) - 3.0) if stem_words else 74.0
    cal_x0 = max(68.0, min(80.0, cal_x0))

    return fitz.Rect(cal_x0, max(cal_y0, 70.0), 552.0, min(cal_y1, 770.0))

def calibrate_allenchem_bounds(page, x0, y0, x1, y1):
    """Calibrate bounds for 2-column Allen NEET questions."""
    clip_x0 = 48.5 if x0 < 200 else 301.5
    clip_x1 = 295.0 if x0 < 200 else 548.0
    words = page.get_text("words")
    band_words = [w for w in words if clip_x0 <= w[0] <= clip_x1 and y0 - 1.0 <= w[1] <= y1]
    content_words = [
        w for w in band_words
        if w[1] >= max(y0, 70.0)
        and not (w[1] < y0 + 10.0 and any(h in w[4].lower() for h in ["pre-medical", "chemistry", "allen", "$//(1", "session", "exercise"]))
    ]
    if not content_words:
        return fitz.Rect(clip_x0 + 24.0, max(y0, 70.0), clip_x1, min(y1, 770.0))

    top_w = min(content_words, key=lambda w: w[1])
    cal_y0 = max(y0, top_w[1] - 1.5)
    max_w = max(content_words, key=lambda w: w[3])
    drawings = [d for d in page.get_drawings() if clip_x0 <= d['rect'].x0 and d['rect'].x1 <= clip_x1 and cal_y0 <= d['rect'].y0 <= y1]
    drawings = [d for d in drawings if d['rect'].height < (y1 - cal_y0)]
    max_d_y = max((d['rect'].y1 for d in drawings), default=cal_y0)
    cal_y1 = min(max(max_w[3], max_d_y) + 3.0, y1)

    stem_words = [w for w in content_words if clip_x0 + 15.0 <= w[0] <= clip_x0 + 70.0 and w[1] <= cal_y0 + 15.0]
    cal_x0 = (min(w[0] for w in stem_words) - 3.0) if stem_words else (clip_x0 + 24.0)

    return fitz.Rect(cal_x0, max(cal_y0, 70.0), clip_x1, min(cal_y1, 770.0))

def calibrate_fiitjee_bounds(page, a, b):
    """Calibrate bounds for FIITJEE AITS questions."""
    words = page.get_text("words")
    band_words = [w for w in words if 70.0 <= w[0] <= 550.0 and a - 1.0 <= w[1] <= b]
    content_words = [
        w for w in band_words
        if w[1] >= max(a, 56.0)
        and not (w[1] < a + 8.0 and any(h in w[4].lower() for h in ["fiitjee", "section", "part", "paper", "aits"]))
    ]
    if not content_words:
        return fitz.Rect(98.0, a, 545.0, b)

    top_w = min(content_words, key=lambda w: w[1])
    cal_y0 = max(a, top_w[1] - 1.5)
    max_w = max(content_words, key=lambda w: w[3])
    drawings = [d for d in page.get_drawings() if 70.0 <= d['rect'].x0 and d['rect'].x1 <= 550.0 and cal_y0 <= d['rect'].y0 <= b]
    drawings = [d for d in drawings if d['rect'].height < (b - cal_y0)]
    max_d_y = max((d['rect'].y1 for d in drawings), default=cal_y0)
    cal_y1 = min(max(max_w[3], max_d_y) + 3.0, b)

    stem_words = [w for w in content_words if 75.0 <= w[0] <= 125.0 and w[1] <= cal_y0 + 15.0]
    cal_x0 = (min(w[0] for w in stem_words) - 3.0) if stem_words else 98.0
    cal_x0 = max(78.0, min(104.0, cal_x0))

    return fitz.Rect(cal_x0, cal_y0, 545.0, cal_y1)

def load_all_question_maps():
    q_map = {}

    def get_valid_db_path(name):
        p1 = baj.find_existing_path(name)
        if os.path.exists(p1): return p1
        p2 = baj.find_existing_path(os.path.join("aitsver2-main", name))
        if os.path.exists(p2): return p2
        return cloud_resolver.get_db_path(name)

    # 1. MS Chouhan
    ms_db_path = get_valid_db_path("mschouhan_database.json")
    if ms_db_path and os.path.exists(ms_db_path):
        try:
            with open(ms_db_path, "r", encoding="utf-8") as f:
                ms_db = json.load(f)
            for q in ms_db.get("questions", []):
                q_map[q["id"]] = q
        except Exception as e:
            print("Error loading MS Chouhan database:", e)

    # 2. Allen JEE
    allenjee_db_path = get_valid_db_path("allenjee_database.json")
    if allenjee_db_path and os.path.exists(allenjee_db_path):
        try:
            with open(allenjee_db_path, "r", encoding="utf-8") as f:
                allen_db = json.load(f)
            for q in allen_db.get("questions", []):
                q_map[q["id"]] = q
        except Exception as e:
            print("Error loading Allen JEE database:", e)

    # 3. Allen Chem (NEET)
    allenchem_db_path = get_valid_db_path("allenchem_database.json")
    if allenchem_db_path and os.path.exists(allenchem_db_path):
        try:
            with open(allenchem_db_path, "r", encoding="utf-8") as f:
                chem_db = json.load(f)
            for q in chem_db.get("questions", []):
                q_map[q["id"]] = q
        except Exception as e:
            print("Error loading Allen Chem database:", e)

    # 4. Neeraj Kumar
    neeraj_db_path = get_valid_db_path("neeraj_database.json")
    if neeraj_db_path and os.path.exists(neeraj_db_path):
        try:
            with open(neeraj_db_path, "r", encoding="utf-8") as f:
                nk_db = json.load(f)
            for q in nk_db.get("questions", []):
                q_map[q["id"]] = q
        except Exception as e:
            print("Error loading Neeraj Kumar database:", e)

    # 5. FIITJEE
    try:
        qm = QuestionManager.get_instance()
        for q in qm.questions:
            if "id" in q:
                q_map[q["id"]] = q
    except Exception as e:
        print("Error loading FIITJEE QuestionManager:", e)

    # 6. Quizrr QRP
    qrp_db_path = get_valid_db_path("qrp_database.json")
    if qrp_db_path and os.path.exists(qrp_db_path):
        try:
            with open(qrp_db_path, "r", encoding="utf-8") as f:
                qrp_db = json.load(f)
            for q in qrp_db.get("questions", []):
                q_map[q["id"]] = q
        except Exception as e:
            print("Error loading QRP database:", e)

    return q_map

def clean_mschouhan_doc(doc):
    for pi in range(len(doc) - 1):
        p = doc[pi]
        for w in p.get_text("words"):
            m = re.fullmatch(r"(\d{1,3})\.", w[4])
            if m and w[0] < 35 and w[1] > 40:
                p.add_redact_annot(fitz.Rect(w[0] - 2, w[1] - 1, w[2] + 2, w[3] + 1))
        p.apply_redactions()

_MS_ZIP_HANDLE = None

def get_ms_chouhan_zip():
    global _MS_ZIP_HANDLE
    if _MS_ZIP_HANDLE is not None:
        return _MS_ZIP_HANDLE
    import zipfile
    cand_zips = [
        baj.find_existing_path("mschouhan_images.zip"),
        baj.find_existing_path(os.path.join("aitsver2-main", "mschouhan_images.zip")),
        baj.find_existing_path(os.path.join("aitsver2-main", "public", "mschouhan_images.zip")),
        os.path.join(ROOT_DIR, "mschouhan_images.zip"),
        os.path.join(PARENT_DIR, "mschouhan_images.zip"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "mschouhan_images.zip"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "aitsver2-main", "mschouhan_images.zip"),
    ]
    for cz in cand_zips:
        if cz and os.path.exists(cz):
            try:
                _MS_ZIP_HANDLE = zipfile.ZipFile(cz, 'r')
                return _MS_ZIP_HANDLE
            except Exception:
                pass
    try:
        remote_zip = cloud_resolver.ensure_file(cand_zips, remote_filename="mschouhan_images.zip")
        if remote_zip and os.path.exists(remote_zip):
            _MS_ZIP_HANDLE = zipfile.ZipFile(remote_zip, 'r')
            return _MS_ZIP_HANDLE
    except Exception:
        pass
    return None

_NEERAJ_ZIP_HANDLE = None

def get_neeraj_zip():
    global _NEERAJ_ZIP_HANDLE
    if _NEERAJ_ZIP_HANDLE is not None:
        return _NEERAJ_ZIP_HANDLE
    import zipfile
    cand_zips = [
        baj.find_existing_path("neeraj_images.zip"),
        baj.find_existing_path(os.path.join("aitsver2-main", "neeraj_images.zip")),
        baj.find_existing_path(os.path.join("aitsver2-main", "public", "neeraj_images.zip")),
        os.path.join(ROOT_DIR, "neeraj_images.zip"),
        os.path.join(PARENT_DIR, "neeraj_images.zip"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "neeraj_images.zip"),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "_internal", "neeraj_images.zip"),
    ]
    for cz in cand_zips:
        if cz and os.path.exists(cz):
            try:
                _NEERAJ_ZIP_HANDLE = zipfile.ZipFile(cz, 'r')
                return _NEERAJ_ZIP_HANDLE
            except Exception:
                pass
    return None

_ALLEN_ZIPS = {}

def get_allenjee_zip(zip_name):
    if zip_name in _ALLEN_ZIPS:
        return _ALLEN_ZIPS[zip_name]
    import zipfile
    cand_zips = [
        baj.find_existing_path(zip_name),
        baj.find_existing_path(os.path.join("aitsver2-main", zip_name)),
        baj.find_existing_path(os.path.join("aitsver2-main", "public", zip_name)),
        os.path.join(ROOT_DIR, zip_name),
        os.path.join(PARENT_DIR, zip_name),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), zip_name),
        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "_internal", zip_name),
    ]
    for cz in cand_zips:
        if cz and os.path.exists(cz):
            try:
                _ALLEN_ZIPS[zip_name] = zipfile.ZipFile(cz, 'r')
                return _ALLEN_ZIPS[zip_name]
            except Exception:
                pass
    return None

_QRP_ZIP = None
def get_qrp_zip():
    global _QRP_ZIP
    if _QRP_ZIP is not None:
        return _QRP_ZIP
    for cand in [
        baj.find_existing_path("qrp_images.zip"),
        os.path.join(ROOT_DIR, "qrp_images.zip"),
        os.path.join(PARENT_DIR, "qrp_images.zip"),
        os.path.join(ROOT_DIR, "vector_zips", "qrp_images.zip"),
        os.path.join(ROOT_DIR, "aitsver2-main", "public", "qrp_images.zip"),
    ]:
        if cand and os.path.exists(cand):
            try:
                _QRP_ZIP = zipfile.ZipFile(cand, "r")
                return _QRP_ZIP
            except Exception:
                pass
    return None

def generate_multi_source_test(selected_qids, out_pdf_path="custom_test.pdf", title="Practice Sheet", subtitle="", cand_name=None, time_limit=90, crops=None, **kwargs):
    q_map = load_all_question_maps()
    chosen = []
    seen_ids = set()

    for qid in selected_qids:
        if qid in q_map and qid not in seen_ids:
            q_cand = q_map[qid]
            # STRICT REQUIREMENT: Only allow questions with valid answer keys!
            if not has_answer_key(q_cand):
                continue
            seen_ids.add(qid)
            chosen.append(q_cand)

    if not chosen:
        raise ValueError("None of the requested questions have valid answer keys or could be found in the databases.")

    SECTION_ORDER = {'single': 0, 'multi': 1, 'numerical': 2, 'paragraph': 3, 'matrix': 4}

    def get_canonical_sec(q):
        is_para = bool(q.get("paragraph") or q.get("type") in ("paragraph", "comprehension") or "comprehension" in str(q.get("rawType", "")).lower())
        if is_para:
            return "paragraph"
        t = str(q.get("type", "single")).lower()
        if "multi" in t:
            return "multi"
        if any(k in t for k in ["num", "int", "subjective"]):
            return "numerical"
        if any(k in t for k in ["matrix", "match", "column"]):
            return "matrix"
        return "single"

    # Sort chosen questions by canonical section order so questions of the same type
    # are never split into multiple duplicate sections (e.g. multiple single-correct sections)
    chosen.sort(key=lambda q: (SECTION_ORDER.get(get_canonical_sec(q), 0), q.get("questionNumber", 0)))

    doc = fitz.open()
    cur_page = baj.add_sheet_page(doc, title, is_first_page=True, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
    page_num = 1

    open_docs = {}
    key_data = []
    current_sec = None
    seen_passages = set()

    col_y = [P1_Y_START, P1_Y_START]
    two_col_top_y = P1_Y_START
    cur_col = 0
    in_two_col = False

    def prepare_one_col_space(req_h):
        nonlocal cur_page, page_num, col_y, two_col_top_y, cur_col, in_two_col
        if in_two_col:
            bot_y = max(col_y[0], col_y[1])
            if bot_y > two_col_top_y + 12.0:
                cur_page.draw_line(fitz.Point(CENTER_X, two_col_top_y), fitz.Point(CENTER_X, bot_y), color=(0.82, 0.82, 0.82), width=0.5)
            in_two_col = False

        base_y = max(col_y[0], col_y[1])
        if base_y + req_h + GAP_Q > COL_Y_END:
            page_num += 1
            cur_page = baj.add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
            base_y = SUB_Y_START

        col_y[0] = base_y
        col_y[1] = base_y
        two_col_top_y = base_y
        cur_col = 0
        return base_y

    def prepare_two_col_space(req_h):
        nonlocal cur_page, page_num, col_y, two_col_top_y, cur_col, in_two_col
        if not in_two_col:
            base_y = max(col_y[0], col_y[1])
            col_y[0] = base_y
            col_y[1] = base_y
            two_col_top_y = base_y
            cur_col = 0
            in_two_col = True

        if col_y[cur_col] + req_h + GAP_Q > COL_Y_END:
            if cur_col == 0:
                cur_col = 1
                if col_y[1] + req_h + GAP_Q > COL_Y_END:
                    bot_y = max(col_y[0], col_y[1])
                    if bot_y > two_col_top_y + 12.0:
                        cur_page.draw_line(fitz.Point(CENTER_X, two_col_top_y), fitz.Point(CENTER_X, bot_y), color=(0.82, 0.82, 0.82), width=0.5)
                    page_num += 1
                    cur_page = baj.add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                    col_y[0] = SUB_Y_START
                    col_y[1] = SUB_Y_START
                    two_col_top_y = SUB_Y_START
                    cur_col = 0
            else:
                bot_y = max(col_y[0], col_y[1])
                if bot_y > two_col_top_y + 12.0:
                    cur_page.draw_line(fitz.Point(CENTER_X, two_col_top_y), fitz.Point(CENTER_X, bot_y), color=(0.82, 0.82, 0.82), width=0.5)
                page_num += 1
                cur_page = baj.add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                col_y[0] = SUB_Y_START
                col_y[1] = SUB_Y_START
                two_col_top_y = SUB_Y_START
                cur_col = 0

        col_x = COL0_X0 if cur_col == 0 else COL1_X0
        target_y = col_y[cur_col]
        return col_x, target_y, cur_col

    qm = QuestionManager.get_instance()

    crop_map = {}
    if isinstance(crops, list):
        for item in crops:
            if isinstance(item, dict):
                cid = item.get("id")
                cdata = item.get("crop")
                if cid and cdata:
                    crop_map[str(cid)] = cdata
    elif isinstance(crops, dict):
        crop_map = {str(k): v for k, v in crops.items() if v}

    for idx, q in enumerate(chosen):
        q_label_num = idx + 1
        ans = q.get("answer") or "-"
        key_data.append({"num": q_label_num, "ans": ans})

        # Section Header Banner if pattern section changes
        q_sec = get_canonical_sec(q)
        if q_sec != current_sec:
            current_sec = q_sec
            sec_title = baj.SECTION_TITLES.get(current_sec, f"SECTION: {current_sec.upper()}")
            sec_y = prepare_one_col_space(22.0)
            sec_rect = fitz.Rect(COL_X0 - 18.0, sec_y, COL_X1, sec_y + 16.0)
            cur_page.draw_rect(sec_rect, color=(0.1, 0.2, 0.4), fill=(0.1, 0.2, 0.4))
            cur_page.insert_text(fitz.Point(COL_X0 - 10.0, sec_y + 11.5), sec_title, fontsize=8.5, fontname="hebo", color=(1.0, 1.0, 1.0))
            col_y[0] = sec_y + 22.0
            col_y[1] = col_y[0]
            two_col_top_y = col_y[0]

        qid = str(q.get("id", ""))
        q_crop = crop_map.get(qid) or crop_map.get(str(idx)) or q.get("crop")

        # -------------------------------------------------------------
        # SOURCE 1: MS Chouhan (1-column layout)
        # -------------------------------------------------------------
        if qid.startswith("mschouhan_"):
            imgs = q.get("images", [])
            svg_filename = None
            for img in imgs:
                if img.startswith("zipimg:") and img.endswith(".svg"):
                    parts = img.split("#")
                    if len(parts) == 2:
                        svg_filename = parts[1]
                        break

            rendered_svg = False
            ms_zip = get_ms_chouhan_zip()
            if ms_zip and svg_filename and svg_filename in ms_zip.namelist():
                try:
                    svg_bytes = ms_zip.read(svg_filename)
                    if q_crop:
                        svg_bytes = apply_svg_crop_text(svg_bytes.decode('utf-8', errors='ignore'), q_crop).encode('utf-8')
                    svg_doc = fitz.open("svg", svg_bytes)
                    pdf_bytes = svg_doc.convert_to_pdf()
                    pdf_src = fitz.open("pdf", pdf_bytes)

                    sw = svg_doc[0].rect.width
                    sh = svg_doc[0].rect.height
                    scale = 1.0
                    if sw > COL_W:
                        scale = COL_W / sw
                    draw_w = sw * scale
                    draw_h = sh * scale

                    target_y = prepare_one_col_space(draw_h)
                    cur_page.insert_text(fitz.Point(COL_X0 - 18, target_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))
                    target_r = fitz.Rect(COL_X0, target_y, COL_X0 + draw_w, target_y + draw_h)
                    cur_page.show_pdf_page(target_r, pdf_src, 0)
                    col_y[0] = target_y + draw_h + GAP_Q
                    col_y[1] = col_y[0]
                    two_col_top_y = col_y[0]
                    rendered_svg = True
                except Exception as e:
                    print("Error rendering MS Chouhan SVG:", e)

            if not rendered_svg:
                parts = q.get("segments", [])
                if parts:
                    pdf_rel = q.get("pdfName") or "mschouhan/Chapter_Wise_Level_1/07_Aldehydes_and_Ketones_Level_1.pdf"
                    norm_rel = pdf_rel.replace("/", os.sep)
                    cand_paths = [
                        baj.find_existing_path(norm_rel),
                        os.path.join(ROOT_DIR, norm_rel),
                        os.path.join(PARENT_DIR, norm_rel),
                        os.path.join(os.path.dirname(PARENT_DIR), norm_rel),
                        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), norm_rel),
                        os.path.join(PARENT_DIR, "mschouhan", os.path.basename(norm_rel)),
                        os.path.join(os.path.dirname(PARENT_DIR), "mschouhan", os.path.basename(norm_rel)),
                    ]
                    full_pdf_path = cloud_resolver.ensure_file(cand_paths, remote_filename=pdf_rel)
                    if full_pdf_path and os.path.exists(full_pdf_path):
                        if full_pdf_path not in open_docs:
                            src_doc = fitz.open(full_pdf_path)
                            clean_mschouhan_doc(src_doc)
                            open_docs[full_pdf_path] = src_doc
                        else:
                            src_doc = open_docs[full_pdf_path]

                        tot_h = sum(p[4] - p[2] for p in parts)
                        target_y = prepare_one_col_space(tot_h)
                        cur_page.insert_text(fitz.Point(COL_X0 - 18, target_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))
                        part_y = target_y
                        for pno, x0, y0, x1, y1 in parts:
                            h = y1 - y0
                            clip_r = fitz.Rect(15.0, y0, 445.0, y1)
                            if q_crop:
                                clip_r = apply_rect_crop(clip_r, q_crop)
                                h = clip_r.height
                            target_r = fitz.Rect(COL_X0, part_y, COL_X0 + 430.0, part_y + h)
                            cur_page.show_pdf_page(target_r, src_doc, pno - 1, clip=clip_r)
                            part_y += h
                        col_y[0] = part_y + GAP_Q
                        col_y[1] = col_y[0]
                        two_col_top_y = col_y[0]

        # -------------------------------------------------------------
        # SOURCE 2: Neeraj Kumar Physical Chemistry (2-column layout)
        # -------------------------------------------------------------
        elif qid.startswith("nk_"):
            imgs = q.get("images", [])
            svg_filename = f"{qid}.svg"
            for img in imgs:
                if img.startswith("zipimg:") and img.endswith(".svg"):
                    parts = img.split("#")
                    if len(parts) == 2:
                        svg_filename = parts[1]
                        break

            rendered_svg = False
            nk_zip = get_neeraj_zip()
            if nk_zip and svg_filename and svg_filename in nk_zip.namelist():
                try:
                    # If comprehension passage exists and hasn't been drawn yet
                    p_id = q.get("paragraphId") or (f"{qid}_para" if q.get("paragraph") else None)
                    if q.get("paragraph") and q.get("passageImages") and p_id and p_id not in seen_passages:
                        seen_passages.add(p_id)
                        pass_img = q["passageImages"][0]
                        pass_fn = pass_img.split("#")[1] if "#" in pass_img else pass_img
                        if pass_fn in nk_zip.namelist():
                            p_bytes = nk_zip.read(pass_fn)
                            p_doc = fitz.open("svg", p_bytes)
                            p_pdf = fitz.open("pdf", p_doc.convert_to_pdf())
                            pw = p_doc[0].rect.width
                            ph = p_doc[0].rect.height
                            p_scale = COL_W / pw if pw > COL_W else 1.0
                            p_dw = pw * p_scale
                            p_dh = ph * p_scale
                            pass_y = prepare_one_col_space(p_dh + 4.0)
                            p_target = fitz.Rect(COL_X0, pass_y, COL_X0 + p_dw, pass_y + p_dh)
                            cur_page.show_pdf_page(p_target, p_pdf, 0)
                            col_y[0] = pass_y + p_dh + 6.0
                            col_y[1] = col_y[0]
                            two_col_top_y = col_y[0]

                    svg_bytes = nk_zip.read(svg_filename)
                    if q_crop:
                        svg_bytes = apply_svg_crop_text(svg_bytes.decode('utf-8', errors='ignore'), q_crop).encode('utf-8')
                    svg_doc = fitz.open("svg", svg_bytes)
                    pdf_bytes = svg_doc.convert_to_pdf()
                    pdf_src = fitz.open("pdf", pdf_bytes)

                    sw = svg_doc[0].rect.width
                    sh = svg_doc[0].rect.height
                    # Scale to fit 2-column width (COL_W_HALF = 235.0)
                    scale = min(1.0, COL_W_HALF / max(sw, 1.0))
                    draw_w = sw * scale
                    draw_h = sh * scale

                    col_x, target_y, cur_c = prepare_two_col_space(draw_h)

                    # Render SVG first so white background is drawn underneath
                    target_r = fitz.Rect(col_x, target_y, col_x + draw_w, target_y + draw_h)
                    cur_page.show_pdf_page(target_r, pdf_src, 0)

                    # Draw question number AFTER SVG in left gutter so it is 100% visible on top
                    cur_page.insert_text(fitz.Point(col_x - 18.0, target_y + 11.0), f"{q_label_num}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))
                    col_y[cur_c] += draw_h + GAP_Q
                    rendered_svg = True
                except Exception as e:
                    print(f"Error rendering Neeraj SVG {svg_filename}:", e)

        # -------------------------------------------------------------
        # SOURCE 3: Allen JEE Chemistry (1-column layout)
        # -------------------------------------------------------------
        elif qid.startswith("allenjee_"):
            pdf_rel = (q.get("pdfName") or "").strip()
            full_pdf_path = None
            if pdf_rel:
                cand_path = baj.resolve_pdf_path(pdf_rel)
                if os.path.isfile(cand_path):
                    full_pdf_path = cand_path
                else:
                    norm_rel = pdf_rel.replace("/", os.sep)
                    cand_paths = [
                        baj.find_existing_path(norm_rel),
                        os.path.join(ROOT_DIR, norm_rel),
                        os.path.join(PARENT_DIR, norm_rel),
                        os.path.join(os.path.dirname(PARENT_DIR), norm_rel),
                        os.path.join(os.path.dirname(os.path.abspath(sys.executable)), norm_rel),
                    ]
                    resolved = cloud_resolver.ensure_file(cand_paths, remote_filename=pdf_rel)
                    if resolved and os.path.isfile(resolved):
                        full_pdf_path = resolved

            rendered_svg = False
            if not full_pdf_path or not os.path.isfile(full_pdf_path):
                # Fallback to pre-extracted vector SVG from image zips
                for img_ref in q.get("images", []):
                    if img_ref.startswith("zipimg:"):
                        ref_parts = img_ref[7:].split("#")
                        if len(ref_parts) == 2:
                            z_name, s_name = ref_parts
                            azip = get_allenjee_zip(z_name)
                            if azip and s_name in azip.namelist():
                                try:
                                    s_bytes = azip.read(s_name)
                                    if q_crop:
                                        s_bytes = apply_svg_crop_text(s_bytes.decode('utf-8', errors='ignore'), q_crop).encode('utf-8')
                                    svg_doc = fitz.open("svg", s_bytes)
                                    pdf_bytes = svg_doc.convert_to_pdf()
                                    pdf_src = fitz.open("pdf", pdf_bytes)

                                    sw = svg_doc[0].rect.width
                                    sh = svg_doc[0].rect.height
                                    scale = 1.0
                                    if sw > COL_W:
                                        scale = COL_W / sw
                                    draw_w = sw * scale
                                    draw_h = sh * scale

                                    target_y = prepare_one_col_space(draw_h)
                                    cur_page.insert_text(fitz.Point(COL_X0 - 18, target_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))
                                    target_r = fitz.Rect(COL_X0, target_y, COL_X0 + draw_w, target_y + draw_h)
                                    cur_page.show_pdf_page(target_r, pdf_src, 0)
                                    col_y[0] = target_y + draw_h + GAP_Q
                                    col_y[1] = col_y[0]
                                    two_col_top_y = col_y[0]
                                    rendered_svg = True
                                    break
                                except Exception as e:
                                    print(f"Error rendering Allen SVG {s_name}:", e)

            if not rendered_svg and full_pdf_path and os.path.exists(full_pdf_path):
                if full_pdf_path not in open_docs:
                    src_doc = fitz.open(full_pdf_path)
                    baj.clean_watermarks(src_doc)
                    baj.clean_source_doc(src_doc)
                    open_docs[full_pdf_path] = src_doc
                else:
                    src_doc = open_docs[full_pdf_path]

                # Render passage if paragraph and not yet rendered
                p_id = q.get("paragraphId")
                is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
                p_crop = q.get("passageCrop")
                if is_para and p_crop and p_id and p_id not in seen_passages:
                    seen_passages.add(p_id)
                    p_pno, px0, py0, px1, py1 = p_crop
                    pass_h = py1 - py0
                    pass_y = prepare_one_col_space(pass_h + 4.0)
                    clip_r = fitz.Rect(COL_X0, py0, COL_X1, py1)
                    target_r = fitz.Rect(COL_X0, pass_y, COL_X1, pass_y + pass_h)
                    cur_page.show_pdf_page(target_r, src_doc, p_pno - 1, clip=clip_r)
                    col_y[0] = pass_y + pass_h + 4.0
                    col_y[1] = col_y[0]
                    two_col_top_y = col_y[0]

                if q.get("segments"):
                    seg = q["segments"][0]
                    pno, x0, y0, x1, y1 = seg
                    page = src_doc[pno - 1]
                    
                    # Calibrate exact question boundaries dynamically
                    clip_r = calibrate_allenjee_bounds(page, y0, y1)
                    if q_crop:
                        clip_r = apply_rect_crop(clip_r, q_crop)
                    draw_w = clip_r.width
                    draw_h = clip_r.height

                    target_y = prepare_one_col_space(draw_h)
                    cur_page.insert_text(fitz.Point(COL_X0 - 18.0, target_y + 11.5), f"{q_label_num}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))
                    target_r = fitz.Rect(COL_X0, target_y, COL_X0 + draw_w, target_y + draw_h)
                    cur_page.show_pdf_page(target_r, src_doc, pno - 1, clip=clip_r)
                    col_y[0] = target_y + draw_h + GAP_Q
                    col_y[1] = col_y[0]
                    two_col_top_y = col_y[0]

        # -------------------------------------------------------------
        # SOURCE 4: Allen NEET Chemistry (2-column layout)
        # -------------------------------------------------------------
        elif qid.startswith("allenchem_"):
            import build_allenchem_sheet as bas
            pdf_rel = q.get("pdfName")
            full_pdf_path = os.path.join(bas.CHAPTER_DIR, pdf_rel)
            if not os.path.exists(full_pdf_path):
                full_pdf_path = baj.find_existing_path(os.path.join("neet module", "allenchem_chapters", pdf_rel))

            if full_pdf_path and os.path.exists(full_pdf_path):
                if full_pdf_path not in open_docs:
                    src_doc = fitz.open(full_pdf_path)
                    bas.clean_source_document(src_doc)
                    open_docs[full_pdf_path] = src_doc
                else:
                    src_doc = open_docs[full_pdf_path]

                seg = q["segments"][0]
                pno, x0, y0, x1, y1 = seg
                page = src_doc[pno - 1]

                # Calibrate NEET question bounds dynamically
                clip_r = calibrate_allenchem_bounds(page, x0, y0, x1, y1)
                if q_crop:
                    clip_r = apply_rect_crop(clip_r, q_crop)
                scale = min(1.0, COL_W_HALF / max(clip_r.width, 1.0))
                draw_w = clip_r.width * scale
                draw_h = clip_r.height * scale

                col_x, target_y, cur_c = prepare_two_col_space(draw_h)

                target_r = fitz.Rect(col_x, target_y, col_x + draw_w, target_y + draw_h)
                cur_page.show_pdf_page(target_r, src_doc, pno - 1, clip=clip_r)
                cur_page.insert_text(fitz.Point(col_x - 18.0, target_y + 11.0), f"{q_label_num}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))
                col_y[cur_c] += draw_h + GAP_Q

        # -------------------------------------------------------------
        # SOURCE 5: FIITJEE AITS Question (1-column layout)
        # -------------------------------------------------------------
        elif not qid.startswith("qrp_"):
            key = qm.find_pdf_key(q)
            pdf_path = qm.pdfs.get(key) if (key and key in qm.pdfs) else None
            if not pdf_path and key:
                pdf_path = cloud_resolver.ensure_file([os.path.join(ROOT_DIR, "source", key + ".pdf")], remote_filename=f"source/{key}.pdf")

            if pdf_path and os.path.exists(pdf_path):
                if pdf_path not in open_docs:
                    src_doc = open_pdf(pdf_path)
                    if src_doc:
                        remove_watermarks(src_doc)
                        open_docs[pdf_path] = src_doc
                else:
                    src_doc = open_docs[pdf_path]

                q_cache = qm.segments_cache.get("questions", {}).get(key, {})
                by_sub = q_cache.get("by_sub", {})
                by_no = q_cache.get("by_no", {})
                qno = q.get("questionNumber") or q.get("number") or 1
                sub_name = str(q.get("subject", "")).strip().lower()
                parts = find_question_parts(by_sub, by_no, sub_name, qno)
                if src_doc and parts:
                    calibrated_parts = []
                    tot_h = 0.0
                    for pno, a, b in parts:
                        c_rect = calibrate_fiitjee_bounds(src_doc[pno], a, b)
                        if q_crop:
                            c_rect = apply_rect_crop(c_rect, q_crop)
                        calibrated_parts.append((pno, c_rect))
                        tot_h += c_rect.height

                    target_y = prepare_one_col_space(tot_h)
                    cur_page.insert_text(fitz.Point(COL_X0 - 18, target_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))
                    part_y = target_y
                    for pno, c_rect in calibrated_parts:
                        h = c_rect.height
                        w = c_rect.width
                        scale = min(1.0, COL_W / max(w, 1.0))
                        target_r = fitz.Rect(COL_X0, part_y, COL_X0 + w * scale, part_y + h * scale)
                        cur_page.show_pdf_page(target_r, src_doc, pno, clip=c_rect)
                        part_y += h * scale
                    col_y[0] = part_y + GAP_Q
                    col_y[1] = col_y[0]
                    two_col_top_y = col_y[0]

        # -------------------------------------------------------------
        # SOURCE 6: Quizrr QRP Question (1-column layout)
        # -------------------------------------------------------------
        elif qid.startswith("qrp_"):
            imgs = q.get("images", [])
            svg_filename = None
            for img in imgs:
                if img.startswith("zipimg:") and img.endswith(".svg"):
                    parts = img.split("#")
                    if len(parts) == 2:
                        svg_filename = parts[1]
                        break

            rendered_svg = False
            qrp_zip = get_qrp_zip()
            if qrp_zip and svg_filename and svg_filename in qrp_zip.namelist():
                try:
                    svg_bytes = qrp_zip.read(svg_filename)
                    if q_crop:
                        svg_bytes = apply_svg_crop_text(svg_bytes.decode('utf-8', errors='ignore'), q_crop).encode('utf-8')
                    svg_doc = fitz.open("svg", svg_bytes)
                    pdf_bytes = svg_doc.convert_to_pdf()
                    pdf_src = fitz.open("pdf", pdf_bytes)

                    sw = svg_doc[0].rect.width
                    sh = svg_doc[0].rect.height
                    scale = 1.0
                    if sw > COL_W:
                        scale = COL_W / sw
                    draw_w = sw * scale
                    draw_h = sh * scale

                    target_y = prepare_one_col_space(draw_h)
                    cur_page.insert_text(fitz.Point(COL_X0 - 18, target_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))
                    target_r = fitz.Rect(COL_X0, target_y, COL_X0 + draw_w, target_y + draw_h)
                    cur_page.show_pdf_page(target_r, pdf_src, 0)
                    col_y[0] = target_y + draw_h + GAP_Q
                    col_y[1] = col_y[0]
                    two_col_top_y = col_y[0]
                    rendered_svg = True
                except Exception as e:
                    print("Error rendering QRP SVG:", e)

    # Finalize any open 2-column section on the last page
    if in_two_col:
        bot_y = max(col_y[0], col_y[1])
        if bot_y > two_col_top_y + 12.0:
            cur_page.draw_line(fitz.Point(CENTER_X, two_col_top_y), fitz.Point(CENTER_X, bot_y), color=(0.82, 0.82, 0.82), width=0.5)

    # Close open documents
    for odoc in open_docs.values():
        try:
            odoc.close()
        except Exception:
            pass

    # Build Structured Answer Key Table
    page_num += 1
    key_page = baj.add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
    baj.draw_answer_key_grid(key_page, SUB_Y_START + 10, key_data)

    os.makedirs(os.path.dirname(os.path.abspath(out_pdf_path)), exist_ok=True)
    doc.save(out_pdf_path, garbage=3, deflate=True)
    doc.close()

    # Split student/key copies
    base_dir = os.path.dirname(os.path.abspath(out_pdf_path))
    base_name = os.path.basename(out_pdf_path)
    if base_name.startswith("test_"):
        suffix = base_name[5:]
        student_path = os.path.join(base_dir, f"student_test_{suffix}")
        key_path = os.path.join(base_dir, f"key_test_{suffix}")
        try:
            full_doc = fitz.open(out_pdf_path)
            num_pages = len(full_doc)
            if num_pages > 1:
                s_doc = fitz.open()
                s_doc.insert_pdf(full_doc, from_page=0, to_page=num_pages - 2)
                s_doc.save(student_path, garbage=3, deflate=True)
                s_doc.close()

                k_doc = fitz.open()
                k_doc.insert_pdf(full_doc, from_page=num_pages - 1, to_page=num_pages - 1)
                k_doc.save(key_path, garbage=3, deflate=True)
                k_doc.close()
            full_doc.close()
        except Exception as e:
            print("Notice: could not split student/key copies:", e)

    return {
        "ok": True,
        "total_questions": len(chosen),
        "total_pages": len(fitz.open(out_pdf_path))
    }

if __name__ == "__main__":
    q_map = load_all_question_maps()
    # Pick sample from Ionic Equilibrium (newly added) and others
    ionic_ids = [q["id"] for q in json.load(open("allenjee_database.json", encoding="utf-8"))["questions"] if q.get("chapter") == "Ionic Equilibrium"][:2]
    ms_ids = [q["id"] for q in json.load(open("mschouhan_database.json", encoding="utf-8"))["questions"] if q.get("star") == "two_star"][:2]

    test_qids = ionic_ids + ms_ids
    print(f"Generating test with {len(test_qids)} questions...")
    out_p = "scratch/test_calibrated_multi.pdf"
    res = generate_multi_source_test(test_qids, out_p, title="Ionic Equilibrium & Organic Chemistry Test")
    print("Result:", res)
    print("Generated PDF at:", os.path.abspath(out_p))
