#!/usr/bin/env python3
"""
build_allenjee_sheet.py - Single-Column Compact Test Sheet Generator for Allen JEE Chemistry (O-1 & O-2).

Key Features:
1. Pure Single-Column Layout: Questions span the full readable width (~510 pt) with minimal margins.
2. Strict Pattern Grouping & Section Headers:
   - Section 1: Single Correct (SCQ)
   - Section 2: Numerical Value Type
   - Section 3: One or More Than One Correct (MSQ)
   - Section 4: Comprehension / Paragraph Based (ALWAYS grouped with passage rendered first)
   - Section 5: Match the Following / Matrix Match
3. Dynamic Sequential Renumbering: (1., 2., 3... N) across all sections.
4. Passage Cards: Dynamic header `(Paragraph for Question Nos. X to Y)` with vector passage graphic.
5. Watermarks and Question Codes (CK0214, AS0076, etc.) 100% removed.
6. Structured Table Format for the Answer Key (bordered grid with Q.No. & Ans).
7. Pure Vector PDF with zero rasterization.
"""

import argparse
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

PW, PH = 595.0, 842.0
MX = 36.0               # Clean 36 pt margin
COL_W = 516.0           # 552 - 36 = 516
COL_X0 = 45.0
COL_X1 = 552.0

P1_HEADER_TOP = 22.0
P1_HEADER_BOT = 74.0
P1_Y_START = 82.0
SUB_Y_START = 28.0
COL_Y_END = 804.0
GAP_Q = 8.0
HEADER_Y_CUT = 50.0
FOOTER_Y_CUT = 790.0

SECTION_ORDER = {'single': 0, 'numerical': 1, 'multi': 2, 'paragraph': 3, 'matrix': 4}
SECTION_TITLES = {
    'single': 'SECTION 1: SINGLE CHOICE QUESTIONS',
    'numerical': 'SECTION 2: NUMERICAL VALUE TYPE',
    'multi': 'SECTION 3: ONE OR MORE THAN ONE CHOICE QUESTIONS',
    'paragraph': 'SECTION 4: COMPREHENSION / PARAGRAPH BASED QUESTIONS',
    'matrix': 'SECTION 5: MATCH THE FOLLOWING / MATRIX MATCH'
}

PARA_HEADER_RE = re.compile(
    r'(?:PARAGRAPH|COMPREHENSION|PASSAGE)\s*(?:#\s*\d+)?\s*(?:FOR)?\s*\(?\s*(?:QUESTION|QUE\.?|Q\.?)?\s*(?:NOS?\.?)?\s*\(?\s*(?:Q\.?)?\s*(\d+)\s*(?:TO|&|-|AND)\s*(?:Q\.?)?\s*(\d+)\s*\)?',
    re.IGNORECASE
)

def clean_source_doc(doc):
    for xref in range(1, doc.xref_length()):
        try:
            s = doc.xref_stream(xref).decode("latin1", errors="ignore")
            if (("<0024002F002F00280031>" in s or "130.08 Tf" in s or "$//(1" in s or "Session :" in s) and "0.707" in s) or ("[(n)-27(o)47(de" in s):
                doc.update_stream(xref, b"")
        except Exception:
            pass

    for page in doc:
        words = page.get_text("words")
        for w in words:
            # Question code (e.g. CK0214, AS0076, AE0048)
            if len(w[4]) == 6 and w[4][:2].isupper() and w[4][2:].isdigit():
                page.draw_rect(fitz.Rect(w[0] - 1.5, w[1] - 1.5, w[2] + 1.5, w[3] + 1.5), color=None, fill=(1, 1, 1))
            # Question number at left margin (matches 1., Q.1, Q.12., Q.12.Which)
            elif 42.0 <= w[0] <= 60.0:
                m_q = re.match(r'^(?:Q\.?|Q)?(\d+)(?:\.([A-Za-z].*)|\.?)$', w[4])
                if m_q:
                    rest = m_q.group(2)
                    if not rest:
                        page.draw_rect(fitz.Rect(w[0] - 2.0, w[1] - 1.5, w[2] + 2.0, w[3] + 1.5), color=None, fill=(1, 1, 1))
                    else:
                        ratio = (len(w[4]) - len(rest)) / len(w[4])
                        end_x = w[0] + (w[2] - w[0]) * ratio
                        page.draw_rect(fitz.Rect(w[0] - 2.0, w[1] - 1.5, end_x, w[3] + 1.5), color=None, fill=(1, 1, 1))

        # Redact original Paragraph header line so we can replace it with dynamic question range
        p_txt = page.get_text("text")
        for line in p_txt.split("\n"):
            if PARA_HEADER_RE.search(line.strip()):
                # Locate header words on page
                h_words = [w for w in words if any(k in w[4].upper() for k in ["PARAGRAPH", "COMPREHENSION", "PASSAGE"])]
                if h_words:
                    h_y0 = min(w[1] for w in h_words)
                    h_y1 = max(w[3] for w in h_words)
                    page.draw_rect(fitz.Rect(COL_X0 - 4.0, h_y0 - 2.0, COL_X1, h_y1 + 4.0), color=None, fill=(1, 1, 1))

def add_sheet_page(doc, title="Practice Sheet", is_first_page=False, total_questions=20, cand_name=None, time_limit=60, subtitle=""):
    page = doc.new_page(width=PW, height=PH)
    # Outer page border
    page.draw_rect(fitz.Rect(18, 18, PW - 18, PH - 18), color=(0.2, 0.2, 0.2), width=0.75)

    if is_first_page:
        # Header Box
        hb = fitz.Rect(24, P1_HEADER_TOP, PW - 24, P1_HEADER_BOT)
        page.draw_rect(hb, color=(0.1, 0.2, 0.4), fill=(0.96, 0.97, 0.99), width=1.0)
        disp_title = (title if title else "Practice Sheet").upper()
        page.insert_text(fitz.Point(32, P1_HEADER_TOP + 15), disp_title, fontsize=11, fontname="helv", fontfile=None, color=(0.08, 0.18, 0.38))
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
    title_rect = fitz.Rect(MX, y_start, PW - MX, y_start + 18)
    page.draw_rect(title_rect, color=(0.1, 0.2, 0.4), fill=(0.1, 0.2, 0.4))
    page.insert_text(fitz.Point(MX + 8, y_start + 13), "ANSWER KEY", fontsize=9.5, fontname="helv", color=(1, 1, 1))

    cur_y = y_start + 22
    row_h = 16.0
    cols = 10
    col_w = (PW - 2 * MX) / cols

    # Header Row
    page.draw_rect(fitz.Rect(MX, cur_y, PW - MX, cur_y + row_h), color=(0.6, 0.6, 0.6), fill=(0.92, 0.94, 0.96), width=0.5)
    for c in range(cols):
        cx = MX + c * col_w
        page.insert_text(fitz.Point(cx + 4, cur_y + 11), f"Q.{c+1}...", fontsize=7.5, fontname="helv", color=(0.2, 0.2, 0.2))
        page.draw_line(fitz.Point(cx + col_w, cur_y), fitz.Point(cx + col_w, cur_y + row_h), color=(0.7, 0.7, 0.7), width=0.5)
    cur_y += row_h

    # Answer Grid
    for chunk_start in range(0, len(key_data), cols):
        chunk = key_data[chunk_start:chunk_start + cols]
        page.draw_rect(fitz.Rect(MX, cur_y, PW - MX, cur_y + row_h), color=(0.6, 0.6, 0.6), width=0.5)
        for c, item in enumerate(chunk):
            cx = MX + c * col_w
            q_txt = f"{item['num']}: {item['ans']}"
            page.insert_text(fitz.Point(cx + 3, cur_y + 11), q_txt, fontsize=7.5, fontname="helv", color=(0.0, 0.0, 0.0))
            page.draw_line(fitz.Point(cx + col_w, cur_y), fitz.Point(cx + col_w, cur_y + row_h), color=(0.7, 0.7, 0.7), width=0.5)
        cur_y += row_h

    return cur_y

def sort_questions_by_pattern(questions):
    """
    Sort questions strictly in the specified order:
    1. Single Correct
    2. Numerical
    3. Multi Correct
    4. Paragraph (grouped by paragraphId)
    5. Matrix Match
    """
    def q_key(q):
        is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
        raw_type = "paragraph" if is_para else q.get("type", "single")
        sec_idx = SECTION_ORDER.get(raw_type, 0)
        p_id = q.get("paragraphId", "") if is_para else ""
        q_num = q.get("questionNumber", 0)
        return (sec_idx, p_id, q_num)

    return sorted(questions, key=q_key)

def generate_custom_test(chapter_name=None, question_count=30, out_pdf_path="allen_test.pdf", bank="both", selected_qids=None, title="Practice Sheet", subtitle="", cand_name=None, time_limit=90):
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    all_qs = db.get("questions", [])
    qid_map = {q["id"]: q for q in all_qs}

    if selected_qids:
        chosen = []
        seen_pids = set()
        for qid in selected_qids:
            if qid in qid_map:
                q = qid_map[qid]
                if q.get("paragraph"):
                    pid = q.get("paragraphId")
                    if pid and pid not in seen_pids:
                        seen_pids.add(pid)
                        group_ids = q.get("paragraphGroup", [qid])
                        for gid in group_ids:
                            if gid in qid_map and qid_map[gid] not in chosen:
                                chosen.append(qid_map[gid])
                else:
                    if q not in chosen:
                        chosen.append(q)
    else:
        pool = all_qs
        if chapter_name and chapter_name != "All":
            pool = [q for q in pool if str(q.get("chapter", "")).strip().lower() == chapter_name.strip().lower()]
        if bank == "O-1":
            pool = [q for q in pool if q.get("bank") == "O-1"]
        elif bank == "O-2":
            pool = [q for q in pool if q.get("bank") == "O-2"]

        # Separate pool into non-para and para groups
        non_para = [q for q in pool if not q.get("paragraph") and q.get("type") != "paragraph"]
        para_groups = {}
        for q in pool:
            if q.get("paragraph") or q.get("type") == "paragraph":
                pid = q.get("paragraphId") or q.get("id")
                para_groups.setdefault(pid, []).append(q)

        chosen = []
        # If count requested is small or large, pick a balanced sample
        # Include a paragraph group if O-2 or both and paragraphs exist
        if (bank in ["O-2", "both"]) and para_groups and question_count >= 10:
            pid = random.choice(list(para_groups.keys()))
            chosen.extend(para_groups[pid])

        rem_count = question_count - len(chosen)
        if rem_count > 0:
            if len(non_para) <= rem_count:
                chosen.extend(non_para)
            else:
                chosen.extend(random.sample(non_para, rem_count))

    if not chosen:
        raise ValueError("No questions selected matching the criteria")

    # Sort strictly into the 5 pattern sections with paragraphs grouped together
    chosen = sort_questions_by_pattern(chosen)

    # Compute dynamic question ranges for each paragraph group in the test
    para_ranges = {}
    for idx, q in enumerate(chosen):
        if q.get("paragraph") or q.get("type") == "paragraph":
            pid = q.get("paragraphId")
            if pid:
                if pid not in para_ranges:
                    para_ranges[pid] = [idx + 1, idx + 1]
                else:
                    para_ranges[pid][1] = idx + 1

    doc = fitz.open()
    cur_page = add_sheet_page(doc, title, is_first_page=True, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit)
    cur_y = P1_Y_START
    page_num = 1

    open_docs = {}
    key_data = []
    current_sec = None
    drawn_paras = set()

    for idx, q in enumerate(chosen):
        q_label_num = idx + 1
        key_data.append({"num": q_label_num, "ans": q.get("answer") or "-"})

        is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
        q_sec = "paragraph" if is_para else q.get("type", "single")

        # Source PDF preparation
        pdf_name = q.get("pdfName") or ""
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
        full_pdf_path = next((p for p in cand_paths if os.path.exists(p)), cand_paths[1])

        if full_pdf_path not in open_docs:
            src_doc = fitz.open(full_pdf_path)
            clean_source_doc(src_doc)
            open_docs[full_pdf_path] = src_doc
        else:
            src_doc = open_docs[full_pdf_path]

        # 1. Render Section Header if pattern section changes
        if q_sec != current_sec:
            current_sec = q_sec
            sec_title = SECTION_TITLES.get(current_sec, f"SECTION: {current_sec.upper()}")
            # Check if section header fits
            if cur_y + 36 > COL_Y_END:
                page_num += 1
                cur_page = add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit)
                cur_y = SUB_Y_START

            # Section Banner
            sec_rect = fitz.Rect(COL_X0 - 16, cur_y, COL_X1, cur_y + 18)
            cur_page.draw_rect(sec_rect, color=(0.1, 0.2, 0.4), fill=(0.1, 0.2, 0.4))
            cur_page.insert_text(fitz.Point(COL_X0 - 8, cur_y + 13), sec_title, fontsize=9.5, fontname="helv", color=(1, 1, 1))
            cur_y += 24

        # 2. Render Passage Card if entering a new paragraph group
        pid = q.get("paragraphId")
        if is_para and pid and (pid not in drawn_paras):
            drawn_paras.add(pid)
            p_crop = q.get("passageCrop")
            if p_crop:
                p_pno, px0, py0, px1, py1 = p_crop
                pass_h = py1 - py0
                # Check if passage card fits
                if cur_y + pass_h + 30 > COL_Y_END:
                    page_num += 1
                    cur_page = add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit)
                    cur_y = SUB_Y_START

                # Passage Header Bar
                q_start, q_end = para_ranges.get(pid, (q_label_num, q_label_num))
                pass_header_text = f"Paragraph for Questions {q_start} to {q_end}" if q_start != q_end else f"Paragraph for Question {q_start}"
                header_rect = fitz.Rect(COL_X0 - 16, cur_y, COL_X1, cur_y + 15)
                cur_page.draw_rect(header_rect, color=(0.7, 0.75, 0.8), fill=(0.94, 0.96, 0.98), width=0.5)
                cur_page.insert_text(fitz.Point(COL_X0 - 8, cur_y + 11), pass_header_text.upper(), fontsize=8.5, fontname="helv", color=(0.08, 0.18, 0.38))
                cur_y += 18

                # Passage Vector Content
                clip_r = fitz.Rect(COL_X0, py0, COL_X1, py1)
                target_r = fitz.Rect(COL_X0, cur_y, COL_X1, cur_y + pass_h)
                cur_page.show_pdf_page(target_r, src_doc, p_pno - 1, clip=clip_r)
                cur_y += pass_h + GAP_Q

        # 3. Render Question Content
        seg = q["segments"][0]
        pno, x0, y0, x1, y1 = seg
        seg_h = y1 - y0

        # Check if question fits on current page
        if cur_y + seg_h + GAP_Q > COL_Y_END:
            page_num += 1
            cur_page = add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit)
            cur_y = SUB_Y_START

        # Draw sequential question number at left margin
        cur_page.insert_text(fitz.Point(COL_X0 - 16, cur_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="helv", color=(0, 0, 0))

        # Show native vector question
        clip_r = fitz.Rect(COL_X0, y0, COL_X1, y1)
        target_r = fitz.Rect(COL_X0, cur_y, COL_X1, cur_y + seg_h)
        cur_page.show_pdf_page(target_r, src_doc, pno - 1, clip=clip_r)

        cur_y += seg_h + GAP_Q

    # ALWAYS add the Answer Key on the next page so the student copy does not contain the answer key
    page_num += 1
    cur_page = add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
    cur_y = SUB_Y_START
    draw_answer_key_grid(cur_page, cur_y + 10, key_data)

    doc.save(out_pdf_path)
    doc.close()
    for d in open_docs.values():
        d.close()

    return {
        "ok": True,
        "total_questions": len(chosen),
        "total_pages": page_num,
        "out_pdf": out_pdf_path
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chapter", default=None)
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--bank", default="both", choices=["O-1", "O-2", "both"])
    parser.add_argument("--out", default="test_allenjee.pdf")
    args = parser.parse_args()

    res = generate_custom_test(
        chapter_name=args.chapter,
        question_count=args.count,
        bank=args.bank,
        out_pdf_path=args.out
    )
    print("Generated:", res)
