#!/usr/bin/env python3
"""
build_unified_sheet.py - Multi-Source Vector Test Sheet Generator.
Supports seamless compilation of practice test sheets from:
1. M.S. Chouhan Organic Chemistry (Level 1 & Selected Questions)
2. Allen JEE Chemistry (O-1 & O-2)
3. Allen NEET Chemistry
4. FIITJEE AITS Question Banks
5. Any hybrid combination of 2 or more question banks!
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

PW, PH = 595.0, 842.0
MX = 36.0
COL_W = 516.0
COL_X0 = 45.0
COL_X1 = 552.0

P1_HEADER_TOP = 22.0
P1_HEADER_BOT = 74.0
P1_Y_START = 82.0
SUB_Y_START = 28.0
COL_Y_END = 804.0
GAP_Q = 9.0

def load_all_question_maps():
    q_map = {}

    # 1. MS Chouhan
    ms_db_path = os.path.join(ROOT_DIR, "mschouhan_database.json")
    if os.path.exists(ms_db_path):
        try:
            with open(ms_db_path, "r", encoding="utf-8") as f:
                ms_db = json.load(f)
            for q in ms_db.get("questions", []):
                q_map[q["id"]] = q
        except Exception as e:
            print("Error loading MS Chouhan database:", e)

    # 2. Allen JEE
    allenjee_db_path = os.path.join(ROOT_DIR, "allenjee_database.json")
    if os.path.exists(allenjee_db_path):
        try:
            with open(allenjee_db_path, "r", encoding="utf-8") as f:
                allen_db = json.load(f)
            for q in allen_db.get("questions", []):
                q_map[q["id"]] = q
        except Exception as e:
            print("Error loading Allen JEE database:", e)

    # 3. Allen Chem (NEET)
    allenchem_db_path = os.path.join(ROOT_DIR, "allenchem_database.json")
    if os.path.exists(allenchem_db_path):
        try:
            with open(allenchem_db_path, "r", encoding="utf-8") as f:
                chem_db = json.load(f)
            for q in chem_db.get("questions", []):
                q_map[q["id"]] = q
        except Exception as e:
            print("Error loading Allen Chem database:", e)

    # 4. FIITJEE
    try:
        qm = QuestionManager.get_instance()
        for q in qm.questions:
            if "id" in q:
                q_map[q["id"]] = q
    except Exception as e:
        print("Error loading FIITJEE QuestionManager:", e)

    return q_map

def clean_mschouhan_doc(doc):
    for pi in range(len(doc) - 1):
        p = doc[pi]
        for w in p.get_text("words"):
            m = re.fullmatch(r"(\d{1,3})\.", w[4])
            if m and w[0] < 35 and w[1] > 40:
                p.add_redact_annot(fitz.Rect(w[0] - 2, w[1] - 1, w[2] + 2, w[3] + 1))
        p.apply_redactions()

def generate_multi_source_test(selected_qids, out_pdf_path="custom_test.pdf", title="Practice Sheet", subtitle="", cand_name=None, time_limit=90):
    q_map = load_all_question_maps()
    chosen = []
    seen_ids = set()

    for qid in selected_qids:
        if qid in q_map and qid not in seen_ids:
            seen_ids.add(qid)
            chosen.append(q_map[qid])

    if not chosen:
        raise ValueError("None of the requested questions could be found in the databases.")

    doc = fitz.open()
    cur_page = baj.add_sheet_page(doc, title, is_first_page=True, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
    cur_y = P1_Y_START
    page_num = 1

    open_docs = {}
    key_data = []

    qm = QuestionManager.get_instance()

    for idx, q in enumerate(chosen):
        q_label_num = idx + 1
        ans = q.get("answer") or "-"
        key_data.append({"num": q_label_num, "ans": ans})

        qid = str(q.get("id", ""))

        # Check source type
        if qid.startswith("mschouhan_"):
            pdf_rel = q.get("pdfName") or "mschouhan/Chapter_Wise_Level_1/07_Aldehydes_and_Ketones_Level_1.pdf"
            norm_rel = pdf_rel.replace("/", os.sep)
            cand_paths = [
                os.path.join(ROOT_DIR, norm_rel),
                os.path.join(PARENT_DIR, norm_rel),
                os.path.join(PARENT_DIR, "mschouhan", os.path.basename(norm_rel)),
            ]
            full_pdf_path = next((p for p in cand_paths if os.path.exists(p)), cand_paths[1])
            if full_pdf_path not in open_docs:
                src_doc = fitz.open(full_pdf_path)
                clean_mschouhan_doc(src_doc)
                open_docs[full_pdf_path] = src_doc
            else:
                src_doc = open_docs[full_pdf_path]

            parts = q.get("segments", [])
            # parts is list of [pno, x0, y0, x1, y1] (1-based pno)
            tot_h = sum(p[4] - p[2] for p in parts)
            # Check page overflow
            if cur_y + tot_h + GAP_Q > COL_Y_END:
                page_num += 1
                cur_page = baj.add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                cur_y = SUB_Y_START

            # Draw question number
            cur_page.insert_text(fitz.Point(COL_X0 - 18, cur_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="helv", color=(0, 0, 0))

            # Draw question segments
            for pno, x0, y0, x1, y1 in parts:
                h = y1 - y0
                clip_r = fitz.Rect(15.0, y0, 445.0, y1)
                target_r = fitz.Rect(COL_X0, cur_y, COL_X0 + 430.0, cur_y + h)
                cur_page.show_pdf_page(target_r, src_doc, pno - 1, clip=clip_r)
                cur_y += h
            cur_y += GAP_Q

        elif qid.startswith("allenjee_"):
            pdf_rel = q.get("pdfName") or ""
            norm_rel = pdf_rel.replace("/", os.sep)
            cand_paths = [
                os.path.join(ROOT_DIR, norm_rel),
                os.path.join(PARENT_DIR, norm_rel),
                os.path.join(PARENT_DIR, "allen jee", "Chemistry[Separate]", norm_rel),
                os.path.join(PARENT_DIR, "allen jee", "Chemistry[Separate]", os.path.basename(norm_rel)),
            ]
            full_pdf_path = next((p for p in cand_paths if os.path.exists(p)), cand_paths[1])

            if full_pdf_path not in open_docs:
                src_doc = fitz.open(full_pdf_path)
                baj.clean_source_doc(src_doc)
                open_docs[full_pdf_path] = src_doc
            else:
                src_doc = open_docs[full_pdf_path]

            # Render passage if paragraph
            is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
            p_crop = q.get("passageCrop")
            if is_para and p_crop:
                p_pno, px0, py0, px1, py1 = p_crop
                pass_h = py1 - py0
                if cur_y + pass_h + 20 > COL_Y_END:
                    page_num += 1
                    cur_page = baj.add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                    cur_y = SUB_Y_START
                clip_r = fitz.Rect(COL_X0, py0, COL_X1, py1)
                target_r = fitz.Rect(COL_X0, cur_y, COL_X1, cur_y + pass_h)
                cur_page.show_pdf_page(target_r, src_doc, p_pno - 1, clip=clip_r)
                cur_y += pass_h + 4.0

            seg = q["segments"][0]
            pno, x0, y0, x1, y1 = seg
            seg_h = y1 - y0

            if cur_y + seg_h + GAP_Q > COL_Y_END:
                page_num += 1
                cur_page = baj.add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                cur_y = SUB_Y_START

            cur_page.insert_text(fitz.Point(COL_X0 - 18, cur_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="helv", color=(0, 0, 0))
            clip_r = fitz.Rect(COL_X0, max(y0, baj.HEADER_Y_CUT), COL_X1, min(y1, baj.FOOTER_Y_CUT))
            target_r = fitz.Rect(COL_X0, cur_y, COL_X1, cur_y + seg_h)
            cur_page.show_pdf_page(target_r, src_doc, pno - 1, clip=clip_r)
            cur_y += seg_h + GAP_Q

        elif qid.startswith("allenchem_"):
            import build_allenchem_sheet as bas
            pdf_rel = q.get("pdfName")
            full_pdf_path = os.path.join(bas.CHAPTER_DIR, pdf_rel)
            if full_pdf_path not in open_docs:
                src_doc = fitz.open(full_pdf_path)
                bas.clean_source_document(src_doc)
                open_docs[full_pdf_path] = src_doc
            else:
                src_doc = open_docs[full_pdf_path]

            seg = q["segments"][0]
            pno, x0, y0, x1, y1 = seg
            clip_x0 = 48.5 if x0 < 150 else 301.5
            clip_x1 = 295.0 if x0 < 150 else 548.0
            clip_r = fitz.Rect(clip_x0, max(y0, 70.0), clip_x1, min(y1, 770.0))
            seg_h = clip_r.height

            if cur_y + seg_h + GAP_Q > COL_Y_END:
                page_num += 1
                cur_page = baj.add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                cur_y = SUB_Y_START

            cur_page.insert_text(fitz.Point(COL_X0 - 18, cur_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="helv", color=(0, 0, 0))
            target_r = fitz.Rect(COL_X0, cur_y, COL_X0 + clip_r.width, cur_y + seg_h)
            cur_page.show_pdf_page(target_r, src_doc, pno - 1, clip=clip_r)
            cur_y += seg_h + GAP_Q

        else:
            # FIITJEE AITS Question
            key = qm.find_pdf_key(q)
            if key and key in qm.pdfs:
                pdf_path = qm.pdfs[key]
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
                    tot_h = sum(b - a for _, a, b in parts)
                    if cur_y + tot_h + GAP_Q > COL_Y_END:
                        page_num += 1
                        cur_page = baj.add_sheet_page(doc, title, is_first_page=False, total_questions=len(chosen), cand_name=cand_name, time_limit=time_limit, subtitle=subtitle)
                        cur_y = SUB_Y_START

                    cur_page.insert_text(fitz.Point(COL_X0 - 18, cur_y + 11), f"{q_label_num}.", fontsize=9.5, fontname="helv", color=(0, 0, 0))
                    w = COL_X1 - COL_X0
                    for pno, a, b in parts:
                        h = b - a
                        clip_r = fitz.Rect(CROP_X0, a, CROP_X1, b)
                        target_r = fitz.Rect(COL_X0, cur_y, COL_X1, cur_y + h)
                        cur_page.show_pdf_page(target_r, src_doc, pno, clip=clip_r)
                        cur_y += h
                    cur_y += GAP_Q

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

    return {
        "ok": True,
        "total_questions": len(chosen),
        "total_pages": len(fitz.open(out_pdf_path))
    }

if __name__ == "__main__":
    from scratch.test_mixed_sheet import test_mixed
    # Test generation
    q_map = load_all_question_maps()
    fiitjee_ids = [q["id"] for q in QuestionManager.get_instance().questions if q.get("paper") == "adv"][:2]
    allen_ids = [q["id"] for q in json.load(open("allenjee_database.json", encoding="utf-8"))["questions"][:2]]
    ms_ids = [q["id"] for q in json.load(open("mschouhan_database.json", encoding="utf-8"))["questions"] if q.get("star") == "two_star"][:2]

    test_qids = fiitjee_ids + allen_ids + ms_ids
    print(f"Generating test with {len(test_qids)} questions from 3 different sources...")
    out_p = "scratch/test_multi_source.pdf"
    res = generate_multi_source_test(test_qids, out_p, title="JEE Hybrid Practice Sheet", subtitle="FIITJEE + Allen + M.S. Chouhan Combined")
    print("Result:", res)
    print("Generated PDF at:", os.path.abspath(out_p))
