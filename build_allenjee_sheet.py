#!/usr/bin/env python3
"""
build_allenjee_sheet.py - Uniform Single-Column Compact Test Sheet Generator for Allen JEE Chemistry (O-1 & O-2).

Matches the authentic, clean, uniform single-column layout of the reference student test:
1. Pure Single-Column Layout: Questions span the full readable width (~507 pt) at 1:1 natural vector scale.
2. 100% Uniform Font Size: Every question is rendered without scaling distortion, ensuring small,
   aligned, and uniform text and formulas across all pages.
3. Tight Content Trimming: Eliminates wasteful trailing space by computing the exact lowest text/draw coordinate
   and clamping to any subsequent question/paragraph boundary.
4. Clean Vector Redactions: Completely redacts original question numbers and Allen codes (e.g. CK0105, CBO0018, TE0058, CC0020).
5. Sequential Renumbering: (1., 2., 3... N) dynamically inserted at the left margin (x = 26.0 pt).
6. Header Box on Page 1: Space for Title, Candidate Name, Roll No, Question Count, Marks.
7. Subsequent Pages: Questions start right away at the top inside the outer border for maximum compactness.
8. Structured 5-Block Table for Answer Key on final page.
9. Pure Vector Output: Zero rasterization, preserving crisp vector quality.
"""

import argparse
import copy
import json
import math
import os
import random
import re
import sys
import pymupdf as fitz

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(ROOT_DIR)

BASE_DIR = os.path.join(ROOT_DIR, "allen jee", "Chemistry[Separate]")
if not os.path.exists(BASE_DIR):
    alt_base = os.path.join(PARENT_DIR, "allen jee", "Chemistry[Separate]")
    if os.path.exists(alt_base):
        BASE_DIR = alt_base

DB_PATH = os.path.join(ROOT_DIR, "allenjee_database.json")
if not os.path.exists(DB_PATH):
    alt_db = os.path.join(ROOT_DIR, "aitsver2-main", "allenjee_database.json")
    if os.path.exists(alt_db):
        DB_PATH = alt_db

# Single-Column Page Layout Geometry (Identical to student test reference)
PW, PH = 595.0, 842.0
MX = 36.0               # Outer margin
COL_X0 = 45.0
COL_X1 = 552.0
COL_W = COL_X1 - COL_X0 # 507.0 pt

P1_HEADER_TOP = 22.0
P1_HEADER_BOT = 74.0
P1_Y_START = 82.0
SUB_Y_START = 28.0
COL_Y_END = 804.0
FOOTER_Y = 814.0
GAP_Q = 8.0

# Legacy constants for compatibility
HEADER_Y_CUT = 50.0
FOOTER_Y_CUT = 790.0

SECTION_ORDER = {'single': 0, 'numerical': 1, 'multi': 2, 'paragraph': 3, 'matrix': 4}
SECTION_TITLES = {
    'single': 'SECTION 1: SINGLE CHOICE QUESTIONS',
    'numerical': 'SECTION 2: NUMERICAL VALUE TYPE',
    'multi': 'SECTION 3: ONE OR MORE THAN ONE CHOICE',
    'paragraph': 'SECTION 4: PARAGRAPH BASED QUESTIONS',
    'matrix': 'SECTION 5: MATRIX MATCH QUESTIONS'
}

CODE_RE = re.compile(r'^[A-Z]{2,4}[0-9O]{3,5}$')

def clean_watermarks(doc):
    """Blanks Form XObject watermarks once per document, strictly targeting small XObjects (<500 bytes)."""
    for xref in range(1, doc.xref_length()):
        try:
            s = doc.xref_stream(xref).decode("latin1", errors="ignore")
            if len(s) < 500 and (("<0024002F002F00280031>" in s or "130.08 Tf" in s or "$//(1" in s or "Session :" in s) and "0.707" in s):
                doc.update_stream(xref, b"")
        except Exception:
            pass

def clean_source_page(page):
    """Permanently redacts question codes, original numbers, headers and margin nodes from a single page."""
    words = page.get_text("words")
    for w in words:
        text = w[4].strip()
        # Allen question code (e.g. CK0105, IG0065, AE0048, CBO0027, QN0001, CBO0018, TE0058, CC0020)
        if CODE_RE.fullmatch(text):
            page.add_redact_annot(fitz.Rect(w[0] - 1.5, w[1] - 1.5, w[2] + 2.0, w[3] + 1.5), fill=False)
        # Original question number at left margin
        elif 42.0 <= w[0] <= 65.0:
            m_q = re.match(r'^(?:Q\.?|Q)?(\d+)(?:\.([A-Za-z].*)|\.?)$', text)
            if m_q:
                rest = m_q.group(2)
                if not rest:
                    page.add_redact_annot(fitz.Rect(w[0] - 2.0, w[1] - 1.5, w[2] + 2.0, w[3] + 1.5), fill=False)
                else:
                    ratio = (len(text) - len(rest)) / len(text)
                    end_x = w[0] + (w[2] - w[0]) * ratio
                    page.add_redact_annot(fitz.Rect(w[0] - 2.0, w[1] - 1.5, end_x, w[3] + 1.5), fill=False)

    # Running headers, footers & margin node markers
    for b in page.get_text("blocks"):
        r = fitz.Rect(b[:4])
        t = b[4].strip()
        if b[3] < 72.0 or b[1] > 770.0:
            page.add_redact_annot(r, fill=False)
        elif (b[0] < 45.0 or b[2] > 550.0) and ("node" in t.lower() or t == "E"):
            page.add_redact_annot(r, fill=False)

    page.apply_redactions(graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)

def clean_source_doc(doc):
    """Full-document clean for external callers like build_unified_sheet.py."""
    clean_watermarks(doc)
    for p in doc:
        clean_source_page(p)

def add_sheet_page(doc, title="PRACTICE SHEET", is_first_page=False, total_questions=20, cand_name=None, time_limit=90, subtitle=""):
    page = doc.new_page(width=PW, height=PH)

    # Outer page border (exact match to student test reference)
    page.draw_rect(fitz.Rect(18, 18, PW - 18, PH - 18), color=(0.2, 0.2, 0.2), width=0.75)

    if is_first_page:
        # Header Box matching student test reference
        hb = fitz.Rect(24, P1_HEADER_TOP, PW - 24, P1_HEADER_BOT)
        page.draw_rect(hb, color=(0.1, 0.2, 0.4), fill=(0.96, 0.97, 0.99), width=1.0)
        disp_title = (title if title else "PRACTICE SHEET").upper()
        page.insert_text(fitz.Point(32, P1_HEADER_TOP + 15), disp_title, fontsize=11, fontname="hebo", color=(0.08, 0.18, 0.38))
        if subtitle:
            sub = subtitle
        else:
            sub = f"{total_questions} Questions | Max Marks: {total_questions * 4} | Time: {time_limit} Mins"
        page.insert_text(fitz.Point(32, P1_HEADER_TOP + 28), sub, fontsize=8, fontname="helv", color=(0.3, 0.3, 0.3))

        c_name = f"Candidate Name: {cand_name if cand_name else '____________________'}"
        page.insert_text(fitz.Point(32, P1_HEADER_TOP + 42), c_name, fontsize=8, fontname="helv", color=(0.1, 0.1, 0.1))
        page.insert_text(fitz.Point(320, P1_HEADER_TOP + 42), "Roll No: ________________", fontsize=8, fontname="helv", color=(0.1, 0.1, 0.1))

    return page

def draw_answer_key_grid(page, y_start, key_data):
    """5-Block structured table for the answer key."""
    title_rect = fitz.Rect(24, y_start, PW - 24, y_start + 18)
    page.draw_rect(title_rect, color=(0.1, 0.2, 0.4), fill=(0.1, 0.2, 0.4))
    page.insert_text(fitz.Point(32, y_start + 13), "ANSWER KEY", fontsize=9.5, fontname="hebo", color=(1, 1, 1))

    table_top_y = y_start + 24.0
    num_blocks = 5
    total_table_w = PW - 48.0
    block_w = total_table_w / num_blocks
    q_col_w = 42.0
    ans_col_w = block_w - q_col_w
    header_h = 22.0
    row_h = 20.0

    for b_idx in range(num_blocks):
        bx = 24.0 + b_idx * block_w
        q_hdr_rect = fitz.Rect(bx, table_top_y, bx + q_col_w, table_top_y + header_h)
        page.draw_rect(q_hdr_rect, color=(0.1, 0.2, 0.4), fill=(0.1, 0.2, 0.4), width=0.5)
        q_tw = fitz.get_text_length("Q.No.", fontname="hebo", fontsize=8.5)
        page.insert_text(fitz.Point(bx + (q_col_w - q_tw) / 2.0, table_top_y + 14.0), "Q.No.", fontsize=8.5, fontname="hebo", color=(1, 1, 1))

        a_hdr_rect = fitz.Rect(bx + q_col_w, table_top_y, bx + block_w, table_top_y + header_h)
        page.draw_rect(a_hdr_rect, color=(0.1, 0.2, 0.4), fill=(0.1, 0.2, 0.4), width=0.5)
        a_tw = fitz.get_text_length("Ans", fontname="hebo", fontsize=8.5)
        page.insert_text(fitz.Point(bx + q_col_w + (ans_col_w - a_tw) / 2.0, table_top_y + 14.0), "Ans", fontsize=8.5, fontname="hebo", color=(1, 1, 1))

    num_rows = math.ceil(len(key_data) / num_blocks)
    for r_idx in range(num_rows):
        ry = table_top_y + header_h + r_idx * row_h
        bg_color = (0.96, 0.97, 0.99) if (r_idx % 2 == 1) else (1.0, 1.0, 1.0)

        for b_idx in range(num_blocks):
            item_idx = r_idx + b_idx * num_rows
            bx = 24.0 + b_idx * block_w

            q_cell = fitz.Rect(bx, ry, bx + q_col_w, ry + row_h)
            page.draw_rect(q_cell, color=(0.75, 0.8, 0.85), fill=bg_color, width=0.5)

            a_cell = fitz.Rect(bx + q_col_w, ry, bx + block_w, ry + row_h)
            page.draw_rect(a_cell, color=(0.75, 0.8, 0.85), fill=bg_color, width=0.5)

            if item_idx < len(key_data):
                item = key_data[item_idx]
                q_str = str(item["num"])
                q_tw = fitz.get_text_length(q_str, fontname="hebo", fontsize=8.5)
                page.insert_text(fitz.Point(bx + (q_col_w - q_tw) / 2.0, ry + 13.5), q_str, fontsize=8.5, fontname="hebo", color=(0.1, 0.2, 0.4))

                ans_str = str(item["ans"]).strip()
                ans_tw = fitz.get_text_length(ans_str, fontname="hebo", fontsize=8.5)
                page.insert_text(fitz.Point(bx + q_col_w + (ans_col_w - ans_tw) / 2.0, ry + 13.5), ans_str, fontsize=8.5, fontname="hebo", color=(0.1, 0.1, 0.1))

    return table_top_y + header_h + num_rows * row_h

def get_tight_y0(page, y0, y1):
    """
    Ensures y0 begins cleanly at the question stem or question number,
    avoiding slicing through preceding topic banners (e.g. BENT'S RULE AND DRAGO'S RULE).
    """
    words = page.get_text("words")
    q_words = [
        w for w in words
        if 42.0 <= w[0] <= 65.0
        and (y0 - 10.0 <= w[1] <= y0 + 35.0)
        and re.match(r'^(?:Q\.?\s*)?\d+\.?', w[4].strip())
    ]
    if q_words:
        first_q = min(q_words, key=lambda w: w[1])
        return max(y0, first_q[1] - 2.5)
    return y0

def calculate_tight_y1(page, y0, y1):
    """
    Finds the exact bottom-most coordinate of real question content,
    clamping to the start of any subsequent question or paragraph header.
    """
    # 1. Clamp y1 if a subsequent question or paragraph starts inside [y0+18, y1]
    blocks = page.get_text("blocks")
    for b in blocks:
        if y0 + 18.0 < b[1] < y1:
            txt = b[4].strip()
            if re.search(r'(?:Paragraph|Passage|Comprehension)\s+for', txt, re.I) or re.match(r'^(?:Q\.?\s*)?\d+\.?', txt):
                y1 = min(y1, b[1] - 2.0)

    # 2. Find lowest content text & drawing
    words = [w for w in page.get_text("words") if 42.0 <= w[0] <= 555.0 and y0 - 1.0 <= w[1] <= y1]
    content_words = [
        w for w in words
        if not CODE_RE.fullmatch(w[4].strip())
        and '$//(1' not in w[4]
        and 'session' not in w[4].lower()
        and 'allen' not in w[4].lower()
        and not (w[1] > y1 - 12 and re.match(r'^\d+\.?$', w[4]))
    ]
    max_text_y = max((w[3] for w in content_words), default=y1)

    drawings = [d for d in page.get_drawings() if 42.0 <= d['rect'].x0 and d['rect'].x1 <= 555.0 and y0 - 1.0 <= d['rect'].y0 <= y1]
    drawings = [d for d in drawings if d['rect'].height < (y1 - y0)]
    max_draw_y = max((d['rect'].y1 for d in drawings), default=y0)

    # Clean 4.5 pt padding for subscripts/descenders, bounded by original y1
    return min(max(max_text_y, max_draw_y) + 4.5, y1)

def resolve_pdf_path(pdf_name):
    norm_rel = pdf_name.replace("/", os.sep)
    cand_paths = [
        os.path.join(ROOT_DIR, norm_rel),
        os.path.join(PARENT_DIR, norm_rel),
        os.path.join(BASE_DIR, norm_rel),
        os.path.join(BASE_DIR, os.path.basename(norm_rel)),
    ]
    prefix = os.path.join("allen jee", "Chemistry[Separate]")
    if norm_rel.lower().startswith(prefix.lower()):
        sub_rel = norm_rel[len(prefix):].lstrip(os.sep)
        cand_paths.append(os.path.join(BASE_DIR, sub_rel))
    return next((p for p in cand_paths if os.path.exists(p)), cand_paths[0])

def sort_questions_by_pattern(questions):
    def q_key(q):
        is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
        raw_type = "paragraph" if is_para else q.get("type", "single")
        sec_idx = SECTION_ORDER.get(raw_type, 0)
        p_id = q.get("paragraphId", "") if is_para else ""
        q_num = q.get("questionNumber", 0)
        return (sec_idx, p_id, q_num)
    return sorted(questions, key=q_key)

def generate_custom_test(
    chapter_name=None,
    question_count=25,
    out_pdf_path="allen_test.pdf",
    bank="both",
    selected_qids=None,
    title="PRACTICE SHEET",
    subtitle="",
    cand_name=None,
    time_limit=90,
    crops=None,
    seed=42,
    chapters=None
):
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    all_qs = db.get("questions", [])
    qid_map = {q["id"]: q for q in all_qs}

    chosen = []
    if selected_qids:
        seen_pids = set()
        for qid in selected_qids:
            if qid in qid_map:
                q = qid_map[qid]
                if q.get("paragraph"):
                    pid = q.get("paragraphId")
                    if pid and pid not in seen_pids:
                        seen_pids.add(pid)
                        for gid in q.get("paragraphGroup", [qid]):
                            if gid in qid_map and qid_map[gid] not in chosen:
                                chosen.append(qid_map[gid])
                else:
                    if q not in chosen:
                        chosen.append(q)
    else:
        target_chapters = chapters if chapters else ([chapter_name] if chapter_name and chapter_name != "All" else None)
        pool = all_qs
        if target_chapters:
            tc_lower = [c.strip().lower() for c in target_chapters]
            pool = [q for q in pool if any(c in q.get("chapter", "").strip().lower() or q.get("chapter", "").strip().lower() in c for c in tc_lower)]

        if bank == "O-1":
            pool = [q for q in pool if q.get("bank") == "O-1"]
        elif bank == "O-2":
            pool = [q for q in pool if q.get("bank") == "O-2"]

        non_para = [q for q in pool if not q.get("paragraph") and q.get("type") != "paragraph"]
        para_groups = {}
        for q in pool:
            if q.get("paragraph") or q.get("type") == "paragraph":
                pid = q.get("paragraphId") or q.get("id")
                para_groups.setdefault(pid, []).append(q)

        random.seed(seed)
        if (bank in ["O-2", "both"]) and para_groups and question_count >= 10:
            pid = random.choice(list(para_groups.keys()))
            chosen.extend(para_groups[pid])

        rem = question_count - len(chosen)
        if rem > 0:
            if len(non_para) <= rem:
                chosen.extend(non_para)
            else:
                chosen.extend(random.sample(non_para, rem))

    if not chosen:
        raise ValueError("No questions selected matching the criteria")

    chosen = sort_questions_by_pattern(chosen)

    # Compute paragraph question ranges
    para_ranges = {}
    for idx, q in enumerate(chosen):
        if q.get("paragraph") or q.get("type") == "paragraph":
            pid = q.get("paragraphId")
            if pid:
                if pid not in para_ranges:
                    para_ranges[pid] = [idx + 1, idx + 1]
                else:
                    para_ranges[pid][1] = idx + 1

    distinct_chaps = list(dict.fromkeys(q.get("chapter", "") for q in chosen if q.get("chapter")))
    if not title or title == "Practice Sheet":
        if len(distinct_chaps) == 1:
            title = distinct_chaps[0]
        elif len(distinct_chaps) > 1:
            title = f"{distinct_chaps[0]} & More"

    # PASS 1: Open all source documents and clean referenced pages upfront BEFORE any grafting
    open_docs = {}
    cleaned_pages = set()

    for q in chosen:
        pdf_path = resolve_pdf_path(q.get("pdfName") or "")
        if pdf_path not in open_docs:
            src_doc = fitz.open(pdf_path)
            clean_watermarks(src_doc)
            open_docs[pdf_path] = src_doc
        src_doc = open_docs[pdf_path]

        pno = q["segments"][0][0]
        page_key = (pdf_path, pno)
        if page_key not in cleaned_pages:
            clean_source_page(src_doc[pno - 1])
            cleaned_pages.add(page_key)

        # Also clean passage page if present
        if q.get("paragraph") and q.get("passageCrop"):
            pass_pno = q["passageCrop"][0]
            pass_key = (pdf_path, pass_pno)
            if pass_key not in cleaned_pages:
                clean_source_page(src_doc[pass_pno - 1])
                cleaned_pages.add(pass_key)

    # PASS 2: Layout in uniform single-column 1:1 natural scale
    doc = fitz.open()
    curr_page = add_sheet_page(doc, title=title, is_first_page=True, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
    curr_y = P1_Y_START
    page_num = 1

    key_data = []
    current_sec = None
    drawn_paras = set()

    for idx, q in enumerate(chosen):
        test_idx = idx + 1
        ans = q.get("answer") or "-"
        key_data.append({"num": test_idx, "ans": ans})

        is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
        q_sec = "paragraph" if is_para else q.get("type", "single")

        pdf_path = resolve_pdf_path(q.get("pdfName") or "")
        src_doc = open_docs[pdf_path]

        # 1. Section Header Banner if pattern section changes
        if q_sec != current_sec and len(set(q.get("type", "single") for q in chosen)) > 1:
            current_sec = q_sec
            sec_title = SECTION_TITLES.get(current_sec, f"SECTION: {current_sec.upper()}")
            if curr_y + 24.0 > COL_Y_END:
                page_num += 1
                curr_page = add_sheet_page(doc, title=title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                curr_y = SUB_Y_START

            sec_rect = fitz.Rect(COL_X0 - 18.0, curr_y, COL_X1, curr_y + 16.0)
            curr_page.draw_rect(sec_rect, color=(0.1, 0.2, 0.4), fill=(0.1, 0.2, 0.4))
            curr_page.insert_text(fitz.Point(COL_X0 - 10.0, curr_y + 11.5), sec_title, fontsize=8.5, fontname="hebo", color=(1.0, 1.0, 1.0))
            curr_y += 22.0

        # 2. Passage Card if entering a new paragraph group
        pid = q.get("paragraphId")
        if is_para and pid and (pid not in drawn_paras):
            drawn_paras.add(pid)
            p_crop = q.get("passageCrop")
            if p_crop:
                p_pno, px0, py0, px1, py1 = p_crop
                pass_page = src_doc[p_pno - 1]
                tight_py1 = calculate_tight_y1(pass_page, py0, py1)
                pass_clip = fitz.Rect(COL_X0, max(py0, 72.0), COL_X1, tight_py1)
                pass_h = pass_clip.height

                if curr_y + pass_h + 30.0 > COL_Y_END:
                    page_num += 1
                    curr_page = add_sheet_page(doc, title=title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                    curr_y = SUB_Y_START

                q_start, q_end = para_ranges.get(pid, (test_idx, test_idx))
                pass_txt = f"PARAGRAPH FOR QUESTIONS {q_start} TO {q_end}" if q_start != q_end else f"PARAGRAPH FOR QUESTION {q_start}"
                header_rect = fitz.Rect(COL_X0 - 18.0, curr_y, COL_X1, curr_y + 15.0)
                curr_page.draw_rect(header_rect, color=(0.7, 0.75, 0.8), fill=(0.94, 0.96, 0.98), width=0.5)
                curr_page.insert_text(fitz.Point(COL_X0 - 10.0, curr_y + 11.0), pass_txt, fontsize=8.0, fontname="hebo", color=(0.08, 0.18, 0.38))
                curr_y += 18.0

                dest_pass = fitz.Rect(COL_X0, curr_y, COL_X1, curr_y + pass_h)
                curr_page.show_pdf_page(dest_pass, src_doc, p_pno - 1, clip=pass_clip)
                curr_y += pass_h + GAP_Q

        # 3. Question Content Rendering
        seg = q["segments"][0]
        pno, x0, y0, x1, y1 = seg
        page = src_doc[pno - 1]

        tight_y0 = get_tight_y0(page, y0, y1)
        tight_y1 = calculate_tight_y1(page, tight_y0, y1)
        clip_rect = fitz.Rect(COL_X0, max(tight_y0, 72.0), COL_X1, min(tight_y1, 770.0))
        target_h = max(clip_rect.height, 15.0)

        # Check page overflow
        if curr_y + target_h + GAP_Q > COL_Y_END:
            page_num += 1
            curr_page = add_sheet_page(doc, title=title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
            curr_y = SUB_Y_START

        # Draw sequential question number at left margin
        curr_page.insert_text(fitz.Point(26.0, curr_y + 11.5), f"{test_idx}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))

        # Show native vector question at exact 1:1 scale (COL_X0 to COL_X1, height = target_h)
        target_rect = fitz.Rect(COL_X0, curr_y, COL_X1, curr_y + target_h)
        curr_page.show_pdf_page(target_rect, src_doc, pno - 1, clip=clip_rect)

        curr_y += target_h + GAP_Q

    # 4. Final Answer Key Page (5-Block Table)
    ak_page = doc.new_page(width=PW, height=PH)
    # Outer page border
    ak_page.draw_rect(fitz.Rect(18, 18, PW - 18, PH - 18), color=(0.2, 0.2, 0.2), width=0.75)

    ak_title_rect = fitz.Rect(24, P1_HEADER_TOP, PW - 24, P1_HEADER_TOP + 32)
    ak_page.draw_rect(ak_title_rect, color=(0.1, 0.2, 0.4), fill=(0.96, 0.98, 1.0), width=0.8)
    ak_page.insert_text(fitz.Point(32, P1_HEADER_TOP + 13), "ANSWER KEY", fontsize=8.5, fontname="hebo", color=(0.1, 0.2, 0.4))
    ak_page.insert_text(fitz.Point(32, P1_HEADER_TOP + 27), f"{title.upper()}", fontsize=10.5, fontname="hebo", color=(0.0, 0.0, 0.0))
    draw_answer_key_grid(ak_page, P1_HEADER_TOP + 40.0, key_data)

    total_pages = len(doc)

    os.makedirs(os.path.dirname(os.path.abspath(out_pdf_path)), exist_ok=True)
    doc.save(out_pdf_path, deflate=True)
    doc.close()

    for sdoc in open_docs.values():
        sdoc.close()

    return {
        "ok": True,
        "out_pdf": out_pdf_path,
        "total_questions": len(chosen),
        "total_pages": total_pages,
        "key_data": key_data
    }

def main():
    parser = argparse.ArgumentParser(description="Generate uniform single-column test sheet for Allen JEE Chemistry.")
    parser.add_argument("--chapter", help="Chapter name to filter questions")
    parser.add_argument("--count", type=int, default=25, help="Number of questions to select")
    parser.add_argument("--out", default="allen_jee_test.pdf", help="Output PDF file path")
    parser.add_argument("--bank", choices=["O-1", "O-2", "both"], default="both", help="Exercise bank")
    parser.add_argument("--title", default="PRACTICE SHEET", help="Title for the practice sheet")
    parser.add_argument("--cand", default=None, help="Candidate Name")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for selection")
    args = parser.parse_args()

    res = generate_custom_test(
        chapter_name=args.chapter,
        question_count=args.count,
        out_pdf_path=args.out,
        bank=args.bank,
        title=args.title,
        cand_name=args.cand,
        seed=args.seed
    )
    print(f"Generated test: {res['out_pdf']} ({res['total_questions']} questions, {res['total_pages']} pages)")

if __name__ == "__main__":
    main()
