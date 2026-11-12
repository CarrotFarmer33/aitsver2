#!/usr/bin/env python3
"""
build_allenchem_sheet.py - Fully Customized 2-Column Compact Test Sheet Generator for Allen Chemistry.

User Requirements Implemented:
1. Re-numbers questions sequentially (1., 2., 3...) and completely redacts original question numbers.
2. Header box ONLY on Page 1 (with space for Chapter Name, Candidate Name, Roll No., Marks).
   Subsequent pages have NO header box, starting questions directly at the top for maximum compactness.
3. Completely cuts/redacts Allen question codes (e.g. CK0105, MC0001, TH0001) from both questions and answer key.
4. Clean, structured TABLE format for the Answer Key (bordered NEET grid with Q.No. & Ans).
5. 100% Watermark Removal (blanks the diagonal ALLEN logo and session text without rasterization).
6. 2-Column authentic compact layout with center dividing line and minimal margins (24 pt).
"""

import argparse
import json
import math
import os
import random
import re
import sys
import fitz

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CHAPTER_DIR = os.path.join(ROOT_DIR, "neet module", "allenchem_chapters")
if not os.path.exists(CHAPTER_DIR):
    alt_dir = os.path.join(os.path.dirname(ROOT_DIR), "neet module", "allenchem_chapters")
    if os.path.exists(alt_dir):
        CHAPTER_DIR = alt_dir

DB_PATH = os.path.join(ROOT_DIR, "allenchem_database.json")
if not os.path.exists(DB_PATH):
    alt_db = os.path.join(os.path.dirname(ROOT_DIR), "allenchem_database.json")
    if os.path.exists(alt_db):
        DB_PATH = alt_db

PW, PH = 595.0, 842.0
MX = 24.0              # Compact 24 pt margin
COL_W = 258.0          # Width of each column (258 * 2 + 31 = 547; 595 - 48 = 547)
COL1_X0 = MX           # 24.0 -> 282.0
CENTER_X = 297.5       # Center dividing line
COL2_X0 = 313.0        # 313.0 -> 571.0

P1_HEADER_TOP = 18.0
P1_HEADER_BOT = 68.0
P1_COL_Y_START = 76.0  # Questions start after header on Page 1
SUB_COL_Y_START = 26.0 # Questions start at top on Page 2+
COL_Y_END = 804.0
FOOTER_Y = 814.0
GAP_Q = 6.0

def clean_source_document(doc):
    """
    1. Blanks diagonal Form XObject watermarks ($//(1 ALLEN logo & Session : 2020-21).
    2. Completely redacts all original question numbers, question codes, top running headers,
       topic banners, decorative rules, and side margin paths upfront.
    Returns a dictionary of (page_num, orig_q_num) -> y0_coord for question alignment.
    """
    for xref in range(1, doc.xref_length()):
        try:
            s = doc.xref_stream(xref).decode('latin1', errors='ignore')
            if 'Session :' in s and ('<0024002F' in s or 'Blondie' in s or '/C2_0' in s):
                doc.update_stream(xref, b'')
        except Exception:
            pass

    q_positions = {}

    for page_idx, page in enumerate(doc):
        for w in page.get_text("words"):
            text = w[4]
            if (45.0 <= w[0] <= 70.0 or 300.0 <= w[0] <= 325.0) and text.endswith('.') and text[:-1].isdigit():
                q_num = int(text[:-1])
                q_positions[(page_idx + 1, q_num)] = w[1]
                page.add_redact_annot(fitz.Rect(w[0] - 1, w[1] - 1, w[2] + 2, w[3] + 1), fill=False)
            elif re.fullmatch(r'[A-Z]{2}\d{4}', text):
                page.add_redact_annot(fitz.Rect(w[0] - 1, w[1] - 1, w[2] + 1, w[3] + 1), fill=False)

        for b in page.get_text("blocks"):
            r = fitz.Rect(b[:4])
            text = b[4].strip()
            if b[3] < 68.0 and any(w in text.lower() for w in ["allen", "pre-medical"]):
                page.add_redact_annot(r, fill=False)
            elif (b[0] < 45.0 or b[2] > 550.0) and ("node" in text.lower() or "module" in text.lower() or text == "E"):
                page.add_redact_annot(r, fill=False)

        for d in page.get_drawings():
            dr = d["rect"]
            if dr.y1 <= 68.0 or dr.y0 >= 772.0:
                page.add_redact_annot(dr, fill=False)
            elif 14.0 <= dr.height <= 50.0 and dr.width > 180.0:
                page.add_redact_annot(dr, fill=False)

        page.apply_redactions(graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)

    return q_positions

def add_test_page(doc, chapter_title, is_first_page=False, total_questions=20, cand_name=None):
    page = doc.new_page(width=PW, height=PH)
    
    if is_first_page:
        page.draw_rect(fitz.Rect(MX, P1_HEADER_TOP, PW - MX, P1_HEADER_BOT), color=(0.12, 0.22, 0.45), fill=(0.96, 0.98, 1.0), width=0.8)
        
        page.insert_text(
            fitz.Point(MX + 10, P1_HEADER_TOP + 13),
            "ALLEN CAREER INSTITUTE  •  TARGET: NEET (UG) PRACTICE TEST",
            fontsize=8.5, fontname="hebo", color=(0.12, 0.22, 0.45)
        )
        title_disp = chapter_title.upper() if chapter_title else "CHEMISTRY PRACTICE TEST"
        if len(title_disp) > 42:
            title_disp = title_disp[:39] + "..."
        page.insert_text(
            fitz.Point(MX + 10, P1_HEADER_TOP + 28),
            f"TEST: {title_disp}",
            fontsize=10.0, fontname="hebo", color=(0.0, 0.0, 0.0)
        )
        max_marks = total_questions * 4
        tag_text = f"Questions: {total_questions}  |  Max Marks: {max_marks}"
        tag_w = fitz.get_text_length(tag_text, fontname="hebo", fontsize=8.5)
        page.insert_text(
            fitz.Point(PW - MX - 10 - tag_w, P1_HEADER_TOP + 28),
            tag_text, fontsize=8.5, fontname="hebo", color=(0.25, 0.25, 0.25)
        )
        c_str = f"Candidate Name: {cand_name}   " if cand_name else "Candidate Name: _____________________________________   "
        page.insert_text(
            fitz.Point(MX + 10, P1_HEADER_TOP + 43),
            c_str + "Roll No.: _________________   Score: _____ / " + str(max_marks),
            fontsize=8.0, fontname="helv", color=(0.3, 0.3, 0.3)
        )
        page.draw_line(fitz.Point(CENTER_X, P1_COL_Y_START - 4), fitz.Point(CENTER_X, COL_Y_END), color=(0.7, 0.7, 0.7), width=0.5)
    else:
        page.draw_line(fitz.Point(CENTER_X, SUB_COL_Y_START - 4), fitz.Point(CENTER_X, COL_Y_END), color=(0.7, 0.7, 0.7), width=0.5)

    page.draw_line(fitz.Point(MX, FOOTER_Y), fitz.Point(PW - MX, FOOTER_Y), color=(0.8, 0.8, 0.8), width=0.5)
    page.insert_text(
        fitz.Point(MX, FOOTER_Y + 11),
        f"NEET Chemistry  •  {chapter_title}",
        fontsize=7.5, fontname="helv", color=(0.45, 0.45, 0.45)
    )

    return page

def generate_custom_test(chapter_name=None, question_count=20, out_pdf_path=None, seed=42, selected_qids=None, title=None, subtitle=None, cand_name=None, time_limit=None):
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database {DB_PATH} not found.")

    with open(DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)

    q_by_id = {q["id"]: q for q in db["questions"]}

    if selected_qids:
        selected_qs = [q_by_id[qid] for qid in selected_qids if qid in q_by_id and q_by_id[qid].get("answer")]
    elif chapter_name and chapter_name.lower() != "all":
        qs = [q for q in db["questions"] if chapter_name.lower() in q["chapter"].lower() and q.get("answer")]
        if not qs:
            qs = [q for q in db["questions"] if q.get("answer")]
        random.seed(seed)
        selected_qs = random.sample(qs, min(question_count, len(qs)))
    else:
        qs = [q for q in db["questions"] if q.get("answer")]
        random.seed(seed)
        selected_qs = random.sample(qs, min(question_count, len(qs)))

    if not selected_qs:
        raise ValueError("No matching Allen Chemistry questions found.")

    # Sort systematically (Exercise-I first, Exercise-III second, then by questionNumber)
    if not selected_qids:
        selected_qs.sort(key=lambda x: (0 if ("Exercise-I" in x.get("exercise", "") and "III" not in x.get("exercise", "")) else 1, x["questionNumber"]))

    actual_chap_title = title or (selected_qs[0]["chapter"] if len(set(q["chapter"] for q in selected_qs)) == 1 else "Chemistry Practice Test")
    if not out_pdf_path:
        safe_name = actual_chap_title.replace(" ", "_").replace("&", "and").replace("/", "_")
        out_pdf_path = f"Allen_Test_{safe_name}.pdf"

    print(f"Generating 2-Column Customized Test for '{actual_chap_title}' ({len(selected_qs)} questions)...")

    opened_src_docs = {}
    doc_q_coords = {}
    for q in selected_qs:
        pdf_name = q["pdfName"]
        if pdf_name not in opened_src_docs:
            src_file_path = os.path.join(CHAPTER_DIR, pdf_name)
            src_doc = fitz.open(src_file_path)
            q_coords = clean_source_document(src_doc)
            opened_src_docs[pdf_name] = src_doc
            doc_q_coords[pdf_name] = q_coords

    out_doc = fitz.open()
    
    curr_page = add_test_page(out_doc, actual_chap_title, is_first_page=True, total_questions=len(selected_qs), cand_name=cand_name)
    curr_col = 1
    curr_y = P1_COL_Y_START

    q_answers = []

    for test_idx, q in enumerate(selected_qs, 1):
        pdf_name = q["pdfName"]
        src_doc = opened_src_docs[pdf_name]
        q_coords = doc_q_coords[pdf_name]
        seg = q["segments"][0]
        p_num, x0, y0, x1, y1 = seg
        orig_q = q["questionNumber"]

        q_num_y = q_coords.get((p_num, orig_q))
        if q_num_y is not None:
            clip_y0 = max(q_num_y - 2.0, 70.0)
        else:
            clip_y0 = max(y0, 70.0)

        clip_y1 = min(y1, 770.0)

        if x0 < 150:
            clip_x0 = 48.5
            clip_x1 = 295.0
        else:
            clip_x0 = 301.5
            clip_x1 = 548.0

        if clip_y1 <= clip_y0:
            clip_y1 = clip_y0 + 50.0

        clip_rect = fitz.Rect(clip_x0, clip_y0, clip_x1, clip_y1)
        src_w = clip_rect.width
        src_h = clip_rect.height
        
        scale = COL_W / src_w
        target_h = src_h * scale

        is_p1 = (len(out_doc) == 1)
        col_start_y = P1_COL_Y_START if is_p1 else SUB_COL_Y_START

        if curr_y + target_h > COL_Y_END:
            if curr_col == 1:
                curr_col = 2
                curr_y = col_start_y
            else:
                curr_page = add_test_page(out_doc, actual_chap_title, is_first_page=False, cand_name=cand_name)
                curr_col = 1
                curr_y = SUB_COL_Y_START

        col_x = COL1_X0 if curr_col == 1 else COL2_X0
        dest_rect = fitz.Rect(col_x, curr_y, col_x + COL_W, curr_y + target_h)

        curr_page.show_pdf_page(dest_rect, src_doc, p_num - 1, clip=clip_rect)

        curr_page.insert_text(
            fitz.Point(col_x + 2.0, curr_y + 12.5),
            f"{test_idx}.",
            fontsize=10.0, fontname="hebo", color=(0.0, 0.0, 0.0)
        )

        curr_y += target_h + GAP_Q
        q_answers.append((test_idx, q["answer"]))

    # Answer Key Table
    ak_page = out_doc.new_page(width=PW, height=PH)
    
    ak_title_rect = fitz.Rect(MX, P1_HEADER_TOP, PW - MX, P1_HEADER_TOP + 32)
    ak_page.draw_rect(ak_title_rect, color=(0.12, 0.22, 0.45), fill=(0.96, 0.98, 1.0), width=0.8)
    ak_page.insert_text(
        fitz.Point(MX + 10, P1_HEADER_TOP + 13),
        "ALLEN CAREER INSTITUTE  •  TARGET: NEET (UG)",
        fontsize=8.5, fontname="hebo", color=(0.12, 0.22, 0.45)
    )
    ak_page.insert_text(
        fitz.Point(MX + 10, P1_HEADER_TOP + 27),
        f"ANSWER KEY : {actual_chap_title.upper()}",
        fontsize=10.5, fontname="hebo", color=(0.0, 0.0, 0.0)
    )
    ak_page.draw_line(fitz.Point(MX, FOOTER_Y), fitz.Point(PW - MX, FOOTER_Y), color=(0.8, 0.8, 0.8), width=0.5)

    table_top_y = P1_HEADER_TOP + 42.0
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
        ak_page.draw_rect(q_hdr_rect, color=(0.12, 0.22, 0.45), fill=(0.12, 0.22, 0.45), width=0.5)
        q_tw = fitz.get_text_length("Q.No.", fontname="hebo", fontsize=8.5)
        ak_page.insert_text(fitz.Point(bx + (q_col_w - q_tw) / 2, table_top_y + 15), "Q.No.", fontsize=8.5, fontname="hebo", color=(1.0, 1.0, 1.0))
        
        ans_hdr_rect = fitz.Rect(bx + q_col_w, table_top_y, bx + block_w, table_top_y + header_h)
        ak_page.draw_rect(ans_hdr_rect, color=(0.12, 0.22, 0.45), fill=(0.12, 0.22, 0.45), width=0.5)
        ans_tw = fitz.get_text_length("Ans", fontname="hebo", fontsize=8.5)
        ak_page.insert_text(fitz.Point(bx + q_col_w + (ans_col_w - ans_tw) / 2, table_top_y + 15), "Ans", fontsize=8.5, fontname="hebo", color=(1.0, 1.0, 1.0))

    rows_per_block = math.ceil(len(q_answers) / num_blocks)
    
    for b_idx in range(num_blocks):
        bx = MX + b_idx * block_w
        for r_idx in range(rows_per_block):
            item_idx = b_idx * rows_per_block + r_idx
            ry = table_top_y + header_h + r_idx * row_h
            
            row_fill = (0.97, 0.98, 1.0) if (r_idx % 2 == 1) else (1.0, 1.0, 1.0)
            
            q_cell = fitz.Rect(bx, ry, bx + q_col_w, ry + row_h)
            ans_cell = fitz.Rect(bx + q_col_w, ry, bx + block_w, ry + row_h)
            
            ak_page.draw_rect(q_cell, color=(0.75, 0.8, 0.9), fill=row_fill, width=0.4)
            ak_page.draw_rect(ans_cell, color=(0.75, 0.8, 0.9), fill=row_fill, width=0.4)

            if item_idx < len(q_answers):
                q_num, ans_val = q_answers[item_idx]
                ans_text = f"({ans_val})" if ans_val.isdigit() else str(ans_val)
                
                q_str = str(q_num)
                q_w = fitz.get_text_length(q_str, fontname="helv", fontsize=8.5)
                ak_page.insert_text(fitz.Point(bx + (q_col_w - q_w) / 2, ry + 13.5), q_str, fontsize=8.5, fontname="helv", color=(0.0, 0.0, 0.0))

                ans_w = fitz.get_text_length(ans_text, fontname="hebo", fontsize=8.5)
                ak_page.insert_text(fitz.Point(bx + q_col_w + (ans_col_w - ans_w) / 2, ry + 13.5), ans_text, fontsize=8.5, fontname="hebo", color=(0.08, 0.28, 0.65))

    table_total_h = header_h + rows_per_block * row_h
    ak_page.draw_rect(fitz.Rect(MX, table_top_y, PW - MX, table_top_y + table_total_h), color=(0.12, 0.22, 0.45), width=0.8)

    total_pages = len(out_doc)
    for p_no in range(total_pages):
        page_obj = out_doc[p_no]
        pg_str = f"Page {p_no + 1} of {total_pages}"
        pg_w = fitz.get_text_length(pg_str, fontname="helv", fontsize=7.5)
        page_obj.insert_text(fitz.Point(PW - MX - pg_w, FOOTER_Y + 11), pg_str, fontsize=7.5, fontname="helv", color=(0.45, 0.45, 0.45))

    os.makedirs(os.path.dirname(os.path.abspath(out_pdf_path)), exist_ok=True)
    out_doc.save(out_pdf_path)
    print(f"✓ Saved 2-Column Customized Test Sheet: {os.path.abspath(out_pdf_path)} ({total_pages} pages)")
    return {
        "success": True,
        "out_pdf": out_pdf_path,
        "filename": os.path.basename(out_pdf_path),
        "total_questions": len(selected_qs),
        "total_pages": total_pages
    }

def main():
    parser = argparse.ArgumentParser(description="Generate 2-Column Customized NEET Test Sheet from Allen Chemistry Module.")
    parser.add_argument("--chapter", "-c", default=None, help="Chapter name (e.g. 'Chemical Kinetics')")
    parser.add_argument("--count", "-n", type=int, default=25, help="Number of questions (default: 25)")
    parser.add_argument("--out", "-o", default=None, help="Output PDF file path")
    parser.add_argument("--seed", "-s", type=int, default=42, help="Random seed for selection")
    args = parser.parse_args()

    generate_custom_test(chapter_name=args.chapter, question_count=args.count, out_pdf_path=args.out, seed=args.seed)

if __name__ == "__main__":
    main()
