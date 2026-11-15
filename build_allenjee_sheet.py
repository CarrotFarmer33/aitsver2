#!/usr/bin/env python3
"""
build_allenjee_sheet.py - Uniform 2-Column Compact Test Sheet Generator for Allen JEE Chemistry (O-1 & O-2).

Matches the authentic, compact, uniform 2-column layout of the NEET sheets:
1. Uniform 2-Column Layout: Questions scale uniformly to fit 258 pt columns with a vertical dividing line.
2. Tight Content Trimming: Eliminates wasteful trailing space by computing the exact lowest text/draw coordinate
   and clamping to any subsequent question/paragraph boundary.
3. Clean Vector Redactions: Completely redacts original question numbers and Allen codes (e.g. CK0105, IG0065, AE0048, CBO0027).
4. Sequential Renumbering: (1., 2., 3... N) dynamically inserted at the top-left of each question.
5. Header Box on Page 1: Chapter Name, Candidate Name, Roll No, Question Count, Marks.
6. Structured 5-Block Table for Answer Key on final page.
7. Pure Vector Output: Zero rasterization, preserving crisp vector quality.
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

# 2-Column Page Layout Geometry (Identical to NEET sheets)
PW, PH = 595.0, 842.0
MX = 24.0               # Compact 24 pt outer margin
COL_W = 258.0           # Width of each column (258 * 2 + 31 = 547; 595 - 48 = 547)
COL1_X0 = MX            # Left column: 24.0 -> 282.0
CENTER_X = 297.5        # Center dividing line
COL2_X0 = 313.0         # Right column: 313.0 -> 571.0

# Legacy exports for backwards compatibility
COL_X0 = 45.0
COL_X1 = 552.0
HEADER_Y_CUT = 50.0
FOOTER_Y_CUT = 790.0
P1_Y_START = 76.0
SUB_Y_START = 26.0

P1_HEADER_TOP = 18.0
P1_HEADER_BOT = 68.0
P1_COL_Y_START = 76.0   # Questions start below header on Page 1
SUB_COL_Y_START = 26.0  # Questions start at top on Page 2+
COL_Y_END = 804.0
FOOTER_Y = 814.0
GAP_Q = 6.0

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
        # Allen question code (e.g. CK0105, IG0065, AE0048, CBO0027, QN0001)
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

    # Running headers & margin node markers
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

def add_sheet_page(doc, title="CHEMISTRY PRACTICE TEST", is_first_page=False, total_questions=20, cand_name=None, time_limit=90, subtitle=""):
    page = doc.new_page(width=PW, height=PH)

    if is_first_page:
        # Header Box matching NEET aesthetic
        page.draw_rect(fitz.Rect(MX, P1_HEADER_TOP, PW - MX, P1_HEADER_BOT), color=(0.12, 0.22, 0.45), fill=(0.96, 0.98, 1.0), width=0.8)
        page.insert_text(fitz.Point(MX + 10, P1_HEADER_TOP + 13), "PRACTICE TEST", fontsize=8.5, fontname="hebo", color=(0.12, 0.22, 0.45))

        title_disp = title.upper() if title else "ALLEN JEE PRACTICE TEST"
        max_marks = total_questions * 4
        tag_text = f"Questions: {total_questions}  |  Max Marks: {max_marks}"
        tag_w = fitz.get_text_length(tag_text, fontname="hebo", fontsize=8.5)
        avail_title_w = (PW - MX - 15 - tag_w) - (MX + 10)

        font_sz = 10.0
        while font_sz > 7.5 and fitz.get_text_length(f"TEST: {title_disp}", fontname="hebo", fontsize=font_sz) > avail_title_w:
            font_sz -= 0.5

        if fitz.get_text_length(f"TEST: {title_disp}", fontname="hebo", fontsize=font_sz) > avail_title_w:
            while len(title_disp) > 10 and fitz.get_text_length(f"TEST: {title_disp}...", fontname="hebo", fontsize=font_sz) > avail_title_w:
                title_disp = title_disp[:-1]
            title_disp = title_disp.rstrip() + "..."

        page.insert_text(fitz.Point(MX + 10, P1_HEADER_TOP + 28), f"TEST: {title_disp}", fontsize=font_sz, fontname="hebo", color=(0.0, 0.0, 0.0))
        page.insert_text(fitz.Point(PW - MX - 10 - tag_w, P1_HEADER_TOP + 28), tag_text, fontsize=8.5, fontname="hebo", color=(0.25, 0.25, 0.25))

        c_str = f"Candidate Name: {cand_name}   " if cand_name else "Candidate Name: _____________________________________   "
        page.insert_text(fitz.Point(MX + 10, P1_HEADER_TOP + 43), c_str + "Roll No.: _________________   Score: _____ / " + str(max_marks), fontsize=8.0, fontname="helv", color=(0.3, 0.3, 0.3))

        # Vertical dividing center line
        page.draw_line(fitz.Point(CENTER_X, P1_COL_Y_START - 4), fitz.Point(CENTER_X, COL_Y_END), color=(0.7, 0.7, 0.7), width=0.5)
    else:
        # Vertical dividing center line on subsequent pages
        page.draw_line(fitz.Point(CENTER_X, SUB_COL_Y_START - 4), fitz.Point(CENTER_X, COL_Y_END), color=(0.7, 0.7, 0.7), width=0.5)

    # Footer line and title
    page.draw_line(fitz.Point(MX, FOOTER_Y), fitz.Point(PW - MX, FOOTER_Y), color=(0.8, 0.8, 0.8), width=0.5)
    page.insert_text(fitz.Point(MX, FOOTER_Y + 11), f"Allen JEE Chemistry  •  {title}", fontsize=7.5, fontname="helv", color=(0.45, 0.45, 0.45))
    return page

def draw_answer_key_grid(page, y_start, key_data):
    """5-Block NEET-style structured table for the answer key."""
    title_rect = fitz.Rect(MX, y_start, PW - MX, y_start + 18)
    page.draw_rect(title_rect, color=(0.12, 0.22, 0.45), fill=(0.12, 0.22, 0.45))
    page.insert_text(fitz.Point(MX + 8, y_start + 13), "ANSWER KEY", fontsize=9.5, fontname="hebo", color=(1, 1, 1))

    table_top_y = y_start + 24.0
    num_blocks = 5
    total_table_w = PW - 2 * MX
    block_w = total_table_w / num_blocks
    q_col_w = 42.0
    ans_col_w = block_w - q_col_w
    header_h = 22.0
    row_h = 20.0

    for b_idx in range(num_blocks):
        bx = MX + b_idx * block_w
        q_hdr_rect = fitz.Rect(bx, table_top_y, bx + q_col_w, table_top_y + header_h)
        page.draw_rect(q_hdr_rect, color=(0.12, 0.22, 0.45), fill=(0.12, 0.22, 0.45), width=0.5)
        q_tw = fitz.get_text_length("Q.No.", fontname="hebo", fontsize=8.5)
        page.insert_text(fitz.Point(bx + (q_col_w - q_tw) / 2, table_top_y + 15), "Q.No.", fontsize=8.5, fontname="hebo", color=(1.0, 1.0, 1.0))

        ans_hdr_rect = fitz.Rect(bx + q_col_w, table_top_y, bx + block_w, table_top_y + header_h)
        page.draw_rect(ans_hdr_rect, color=(0.12, 0.22, 0.45), fill=(0.12, 0.22, 0.45), width=0.5)
        ans_tw = fitz.get_text_length("Ans", fontname="hebo", fontsize=8.5)
        page.insert_text(fitz.Point(bx + q_col_w + (ans_col_w - ans_tw) / 2, table_top_y + 15), "Ans", fontsize=8.5, fontname="hebo", color=(1.0, 1.0, 1.0))

    rows_per_block = math.ceil(len(key_data) / num_blocks)
    for b_idx in range(num_blocks):
        bx = MX + b_idx * block_w
        for r_idx in range(rows_per_block):
            item_idx = b_idx * rows_per_block + r_idx
            ry = table_top_y + header_h + r_idx * row_h
            row_fill = (0.97, 0.98, 1.0) if (r_idx % 2 == 1) else (1.0, 1.0, 1.0)
            q_cell = fitz.Rect(bx, ry, bx + q_col_w, ry + row_h)
            ans_cell = fitz.Rect(bx + q_col_w, ry, bx + block_w, ry + row_h)
            page.draw_rect(q_cell, color=(0.75, 0.8, 0.9), fill=row_fill, width=0.4)
            page.draw_rect(ans_cell, color=(0.75, 0.8, 0.9), fill=row_fill, width=0.4)

            if item_idx < len(key_data):
                item = key_data[item_idx]
                q_num = item.get("num", item_idx + 1)
                ans_val = item.get("ans", "-")
                ans_text = f"({ans_val})" if str(ans_val).isdigit() else str(ans_val)
                q_str = str(q_num)
                q_w = fitz.get_text_length(q_str, fontname="helv", fontsize=8.5)
                page.insert_text(fitz.Point(bx + (q_col_w - q_w) / 2, ry + 13.5), q_str, fontsize=8.5, fontname="helv", color=(0.0, 0.0, 0.0))
                ans_w = fitz.get_text_length(ans_text, fontname="hebo", fontsize=8.5)
                page.insert_text(fitz.Point(bx + q_col_w + (ans_col_w - ans_w) / 2, ry + 13.5), ans_text, fontsize=8.5, fontname="hebo", color=(0.08, 0.28, 0.65))

    table_total_h = header_h + rows_per_block * row_h
    page.draw_rect(fitz.Rect(MX, table_top_y, PW - MX, table_top_y + table_total_h), color=(0.12, 0.22, 0.45), width=0.8)
    return table_top_y + table_total_h + 10

def sort_questions_by_pattern(questions):
    def q_key(q):
        is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
        raw_type = "paragraph" if is_para else q.get("type", "single")
        sec_idx = SECTION_ORDER.get(raw_type, 0)
        p_id = q.get("paragraphId", "") if is_para else ""
        q_num = q.get("questionNumber", 0)
        return (sec_idx, p_id, q_num)
    return sorted(questions, key=q_key)

def calculate_tight_y1(page, y0, y1):
    """
    Finds the exact bottom-most coordinate of real question content,
    clamping to the start of any subsequent question or paragraph header.
    """
    # 1. Clamp y1 if a subsequent question or paragraph starts inside [y0+20, y1]
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

def generate_custom_test(
    chapter_name=None,
    question_count=25,
    out_pdf_path="allen_test.pdf",
    bank="both",
    selected_qids=None,
    title="Practice Sheet",
    subtitle="",
    cand_name=None,
    time_limit=90,
    crops=None,
    chapters=None,
    seed=42
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

    # PASS 2: Layout in uniform 2-column format
    doc = fitz.open()
    curr_page = add_sheet_page(doc, title=title, is_first_page=True, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
    curr_col = 1
    curr_y = P1_COL_Y_START

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

        # 1. Section Banner if section changed
        if q_sec != current_sec and len(set(q.get("type", "single") for q in chosen)) > 1:
            current_sec = q_sec
            sec_title = SECTION_TITLES.get(current_sec, f"SECTION: {current_sec.upper()}")
            col_start_y = P1_COL_Y_START if len(doc) == 1 else SUB_COL_Y_START
            if curr_y + 24.0 > COL_Y_END:
                if curr_col == 1:
                    curr_col = 2
                    curr_y = col_start_y
                else:
                    curr_page = add_sheet_page(doc, title=title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                    curr_col = 1
                    curr_y = SUB_COL_Y_START

            col_x = COL1_X0 if curr_col == 1 else COL2_X0
            sec_rect = fitz.Rect(col_x, curr_y, col_x + COL_W, curr_y + 16.0)
            curr_page.draw_rect(sec_rect, color=(0.12, 0.22, 0.45), fill=(0.12, 0.22, 0.45))
            curr_page.insert_text(fitz.Point(col_x + 6.0, curr_y + 11.5), sec_title, fontsize=8.0, fontname="hebo", color=(1.0, 1.0, 1.0))
            curr_y += 20.0

        # 2. Passage Card if new paragraph group
        pid = q.get("paragraphId")
        if is_para and pid and (pid not in drawn_paras):
            drawn_paras.add(pid)
            p_crop = q.get("passageCrop")
            if p_crop:
                p_pno, px0, py0, px1, py1 = p_crop
                pass_page = src_doc[p_pno - 1]
                tight_py1 = calculate_tight_y1(pass_page, py0, py1)
                pass_clip = fitz.Rect(45.0, max(py0, 72.0), 552.0, tight_py1)
                p_scale = COL_W / pass_clip.width
                pass_h = max(pass_clip.height * p_scale, 20.0)

                col_start_y = P1_COL_Y_START if len(doc) == 1 else SUB_COL_Y_START
                if curr_y + pass_h + 20.0 > COL_Y_END:
                    if curr_col == 1:
                        curr_col = 2
                        curr_y = col_start_y
                    else:
                        curr_page = add_sheet_page(doc, title=title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                        curr_col = 1
                        curr_y = SUB_COL_Y_START

                col_x = COL1_X0 if curr_col == 1 else COL2_X0
                q_start, q_end = para_ranges.get(pid, (test_idx, test_idx))
                pass_txt = f"PARAGRAPH FOR QUESTIONS {q_start} TO {q_end}" if q_start != q_end else f"PARAGRAPH FOR QUESTION {q_start}"

                hdr_rect = fitz.Rect(col_x, curr_y, col_x + COL_W, curr_y + 14.0)
                curr_page.draw_rect(hdr_rect, color=(0.7, 0.75, 0.8), fill=(0.94, 0.96, 0.98), width=0.5)
                curr_page.insert_text(fitz.Point(col_x + 5.0, curr_y + 10.0), pass_txt, fontsize=7.5, fontname="hebo", color=(0.08, 0.18, 0.38))
                curr_y += 16.0

                dest_pass = fitz.Rect(col_x, curr_y, col_x + COL_W, curr_y + pass_h)
                curr_page.show_pdf_page(dest_pass, src_doc, p_pno - 1, clip=pass_clip)
                curr_y += pass_h + GAP_Q

        # 3. Question Rendering with Tight Trimming
        seg = q["segments"][0]
        pno, x0, y0, x1, y1 = seg
        page = src_doc[pno - 1]

        tight_y1 = calculate_tight_y1(page, y0, y1)
        clip_rect = fitz.Rect(45.0, max(y0, 72.0), 552.0, tight_y1)
        src_w = clip_rect.width
        src_h = max(clip_rect.height, 15.0)

        scale = COL_W / src_w
        target_h = src_h * scale

        col_start_y = P1_COL_Y_START if len(doc) == 1 else SUB_COL_Y_START
        if curr_y + target_h > COL_Y_END:
            if curr_col == 1:
                curr_col = 2
                curr_y = col_start_y
            else:
                curr_page = add_sheet_page(doc, title=title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                curr_col = 1
                curr_y = SUB_COL_Y_START

        col_x = COL1_X0 if curr_col == 1 else COL2_X0
        dest_rect = fitz.Rect(col_x, curr_y, col_x + COL_W, curr_y + target_h)
        curr_page.show_pdf_page(dest_rect, src_doc, pno - 1, clip=clip_rect)

        # Dynamic Sequential Question Number
        curr_page.insert_text(fitz.Point(col_x + 1.5, curr_y + 11.0), f"{test_idx}.", fontsize=9.5, fontname="hebo", color=(0, 0, 0))

        curr_y += target_h + GAP_Q

    # 4. Final Answer Key Page (5-Block NEET Table)
    ak_page = doc.new_page(width=PW, height=PH)
    ak_title_rect = fitz.Rect(MX, P1_HEADER_TOP, PW - MX, P1_HEADER_TOP + 32)
    ak_page.draw_rect(ak_title_rect, color=(0.12, 0.22, 0.45), fill=(0.96, 0.98, 1.0), width=0.8)
    ak_page.insert_text(fitz.Point(MX + 10, P1_HEADER_TOP + 13), "ANSWER KEY", fontsize=8.5, fontname="hebo", color=(0.12, 0.22, 0.45))
    ak_page.insert_text(fitz.Point(MX + 10, P1_HEADER_TOP + 27), f"{title.upper()}", fontsize=10.5, fontname="hebo", color=(0.0, 0.0, 0.0))
    ak_page.draw_line(fitz.Point(MX, FOOTER_Y), fitz.Point(PW - MX, FOOTER_Y), color=(0.8, 0.8, 0.8), width=0.5)
    ak_page.insert_text(fitz.Point(MX, FOOTER_Y + 11), f"Allen JEE Chemistry  •  {title}", fontsize=7.5, fontname="helv", color=(0.45, 0.45, 0.45))

    draw_answer_key_grid(ak_page, P1_HEADER_TOP + 40.0, key_data)

    # 5. Page Numbering ("Page X of Y")
    total_pages = len(doc)
    for p_no in range(total_pages):
        page_obj = doc[p_no]
        pg_str = f"Page {p_no + 1} of {total_pages}"
        pg_w = fitz.get_text_length(pg_str, fontname="helv", fontsize=7.5)
        page_obj.insert_text(fitz.Point(PW - MX - pg_w, FOOTER_Y + 11), pg_str, fontsize=7.5, fontname="helv", color=(0.45, 0.45, 0.45))

    os.makedirs(os.path.dirname(os.path.abspath(out_pdf_path)), exist_ok=True)
    doc.save(out_pdf_path)
    doc.close()
    for d in open_docs.values():
        d.close()

    print(f"✓ Saved 2-Column Allen JEE Test Sheet: {os.path.abspath(out_pdf_path)} ({total_pages} pages)")
    return {
        "ok": True,
        "success": True,
        "total_questions": len(chosen),
        "total_pages": total_pages,
        "out_pdf": out_pdf_path,
        "filename": os.path.basename(out_pdf_path)
    }

def main():
    parser = argparse.ArgumentParser(description="Generate 2-Column Uniform Allen JEE Test Sheet.")
    parser.add_argument("--chapter", "-c", default=None, help="Chapter name")
    parser.add_argument("--chapters", nargs="+", default=None, help="List of chapters")
    parser.add_argument("--count", "-n", type=int, default=25, help="Number of questions (default: 25)")
    parser.add_argument("--bank", "-b", default="both", choices=["O-1", "O-2", "both"])
    parser.add_argument("--out", "-o", default="allen_test.pdf", help="Output PDF file path")
    parser.add_argument("--seed", "-s", type=int, default=42, help="Random seed")
    parser.add_argument("--title", "-t", default="Practice Sheet", help="Title")
    parser.add_argument("--cand-name", default=None, help="Candidate name")
    args = parser.parse_args()

    generate_custom_test(
        chapter_name=args.chapter,
        chapters=args.chapters,
        question_count=args.count,
        bank=args.bank,
        out_pdf_path=args.out,
        seed=args.seed,
        title=args.title,
        cand_name=args.cand_name
    )

if __name__ == "__main__":
    main()
