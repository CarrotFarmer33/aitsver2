#!/usr/bin/env python3
"""build_vector_test.py - Generates 100% native vector test sheets (exact build_sheets format).

Zero raster images. Text is 100% selectable and copyable. Math, equations, diagrams,
and tables maintain infinite vector sharpness on zoom. All FIITJEE watermarks and
margin/header banners are automatically removed.

For JEE Main pattern:
Strictly generates 25 Single Choice Questions (SCQ / Section A) and 5 Numerical Type (NAT / Section B) per subject.

Optimized with O(1) pre-computed segments cache for sub-second test generation.
"""

import argparse
import collections
import glob
import json
import os
import random
import re
import sys
import time
import pymupdf as fitz

from build_sheets import (
    CROP_X0, CROP_X1, GAP, GREY, LABEL_W, MX, NAVY, PH, PW, RULE, SOL_RE,
    SRC_BOT, SRC_TOP, TINT, TOP, BOT, Sheet, open_pdf, slug, tight, walk_pdfs,
    remove_watermarks
)
from build_chem_sheets import chem_segments

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(ROOT_DIR, "source")
DB_PATHS = [
    os.path.join(ROOT_DIR, "database.json"),
    os.path.join(ROOT_DIR, "chemistry_database.json"),
    os.path.join(ROOT_DIR, "maths_advanced_database.json"),
    os.path.join(ROOT_DIR, "maths_main_database.json"),
]

TYPE_ORDER = [
    ("single", "Single Correct (MCQ)"),
    ("multi", "One or More Correct (MSQ)"),
    ("numerical", "Numerical / Integer Answer (NAT)"),
    ("paragraph", "Comprehension / Paragraph"),
]
TYPE_NAME = dict(TYPE_ORDER)
TYPE_NAME.update({
    "mcq": "Single Correct (MCQ)",
    "msq": "One or More Correct (MSQ)",
    "nat": "Numerical / Integer Answer (NAT)",
})

def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

def has_valid_answer(q):
    """Check if question has a confirmed, non-empty answer in the database."""
    a = q.get("answer") or q.get("ans") or q.get("correct_answer") or q.get("correct") or q.get("key")
    if a is None:
        return False
    if isinstance(a, list):
        return len(a) > 0 and any(str(x).strip() not in ("", "-", "None", "null", "?") for x in a)
    s = str(a).strip()
    return s not in ("", "-", "None", "null", "?", "NA", "N/A", "none")

def get_paper(q, db_path=""):
    exam = q.get("exam")
    if exam:
        e = str(exam).lower()
        if "adv" in e: return "adv"
        if "main" in e: return "main"
        return exam
    src = str(q.get("source") or q.get("source_paper") or q.get("paper") or "") + " " + str(q.get("paperTitle") or q.get("paper_title") or "")
    m = bool(re.search(r'(\bJM\b|JEE[\s_-]?M\b|JEEM|\bMains?\b|_Mains?\b)', src, re.I))
    a = bool(re.search(r'(\bJA\b|JEE[\s_-]?A\b|JEEA|\bAdv)', src, re.I))
    if m and not a: return "main"
    if a and not m: return "adv"
    if m and a: return "main" if re.search(r'\bMain\b', src, re.I) else "adv"
    if re.search(r'Paper[- _]?(1|2|I{1,2})\b|\bP[- ]?[12]\b', src, re.I): return "adv"
    if "advanced" in db_path: return "adv"
    if "main" in db_path: return "main"
    return "other"

class QuestionManager:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.questions = []
        self.q_by_id = {}
        self.pdfs = {}       # stem -> path
        self.sol_files = {}  # stem -> path
        self.sol_paths = {}  # q_pdf_key -> sol_pdf_path
        self.nkeys = {}      # stem -> normalized stem
        self.doc_cache = {}  # stem -> (doc, by_sub, by_no)
        self.sol_cache = {}  # stem -> (doc, s_sub, s_no)
        self.segments_cache = {}
        self._load_databases()
        self._index_pdfs()
        self._load_segments_cache()

    def _load_databases(self):
        t0 = time.time()
        for p in DB_PATHS:
            if not os.path.exists(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                qs = data.get("questions", data if isinstance(data, list) else [])
                for q in qs:
                    if not has_valid_answer(q):
                        continue
                    qid = q.get("id")
                    if qid and qid not in self.q_by_id:
                        q["paper"] = get_paper(q, p)
                        is_para = bool(q.get("paragraph") or q.get("type") == "paragraph" or q.get("paragraphId") or q.get("passageText") or q.get("passageImages"))
                        if is_para:
                            q["paragraph"] = True
                            if not q.get("rawType"):
                                q["rawType"] = q.get("type") or "single"
                            q["type"] = "paragraph"
                        self.q_by_id[qid] = q
                        self.questions.append(q)
            except Exception as e:
                print(f"Warning: could not load {p}: {e}")
        print(f"Indexed {len(self.questions)} questions across all databases in {time.time()-t0:.2f}s")

    def _index_pdfs(self):
        if not os.path.isdir(SOURCE_DIR):
            print(f"Warning: source dir '{SOURCE_DIR}' not found")
            return
        t0 = time.time()
        for p in walk_pdfs(SOURCE_DIR):
            stem = os.path.splitext(os.path.basename(p))[0]
            if SOL_RE.search(stem):
                self.sol_files[stem] = p
            else:
                self.pdfs[stem] = p

        self.nkeys = {k: norm(k) for k in self.pdfs}

        # Match solutions to question PDFs
        for p, path in self.sol_files.items():
            stem = norm(SOL_RE.sub("", p))
            c = [k for k, nk in self.nkeys.items() if nk == stem or nk in stem or stem in nk]
            if c:
                best_k = min(c, key=lambda k: abs(len(self.nkeys[k]) - len(stem)))
                self.sol_paths[best_k] = path

        print(f"Indexed {len(self.pdfs)} question PDFs, {len(self.sol_files)} solution PDFs in {time.time()-t0:.2f}s")

    def _load_segments_cache(self):
        cache_path = os.path.join(ROOT_DIR, "segments_cache.json")
        if os.path.exists(cache_path):
            try:
                t0 = time.time()
                with open(cache_path, "r", encoding="utf-8") as f:
                    self.segments_cache = json.load(f)
                q_count = len(self.segments_cache.get("questions", {}))
                s_count = len(self.segments_cache.get("solutions", {}))
                print(f"Loaded instant segments cache ({q_count} questions, {s_count} solutions) in {time.time()-t0:.2f}s")
            except Exception as e:
                print(f"Warning: could not load segments_cache.json: {e}")

    def find_pdf_key(self, q):
        hay = (
            norm(q.get("zipName")),
            norm(q.get("paperTitle")),
            norm(q.get("source")),
        )
        c = [k for k, nk in self.nkeys.items() if nk and (nk in hay[0] or nk in hay[1] or nk in hay[2])]
        return max(c, key=lambda k: len(self.nkeys[k])) if c else None

def fmt_answer(x):
    a = x.get("answer") or x.get("ans") or x.get("correct_answer") or x.get("correct") or x.get("key")
    if a is None or a == "":
        return "-"
    if isinstance(a, list):
        return ",".join(str(v).strip().upper() for v in a)
    s = str(a).strip().upper()
    return s if s else "-"

def find_question_parts(by_sub, by_no, sub_name, qno):
    """Subject-aware segment lookup avoiding cross-subject bleed in sequential papers."""
    try:
        qno_int = int(qno)
    except (ValueError, TypeError):
        qno_int = 1

    sub_key = str(sub_name or "").strip().lower()
    if sub_key in ("math", "maths", "mathematics"):
        sub_norm = "mathematics"
        offsets = [0, 60, 50] if qno_int <= 30 else [0, -60, -50]
    elif sub_key in ("chem", "chemistry"):
        sub_norm = "chemistry"
        offsets = [0, 30, 25] if qno_int <= 30 else [0, -30, -25]
    else:
        sub_norm = "physics"
        offsets = [0]

    def get_sub_seg(s, num):
        if (s, num) in by_sub and by_sub[(s, num)]:
            return by_sub[(s, num)]
        if (s, str(num)) in by_sub and by_sub[(s, str(num))]:
            return by_sub[(s, str(num))]
        str_key = f"{s}||{num}"
        if str_key in by_sub and by_sub[str_key]:
            return by_sub[str_key]
        return None

    # 1. Exact subject match in by_sub (checks both int and string keys)
    for off in offsets:
        cand_no = qno_int + off
        if cand_no > 0:
            seg = get_sub_seg(sub_norm, cand_no)
            if seg:
                return seg

    # 2. Check untagged or any-subject (None, cand_no) in by_sub
    for off in offsets:
        cand_no = qno_int + off
        if cand_no > 0:
            seg = get_sub_seg(None, cand_no)
            if seg:
                other_claim = any(
                    get_sub_seg(other_s, cand_no)
                    for other_s in ("physics", "chemistry", "mathematics")
                    if other_s != sub_norm
                )
                if not other_claim:
                    return seg

    # 3. Fallback to by_no: prevent cross-subject bleeding
    int_keys = [int(k) for k in by_no.keys() if str(k).isdigit()]
    max_no = max(int_keys) if int_keys else 0
    for off in offsets:
        cand_no = qno_int + off
        seg = by_no.get(cand_no) or by_no.get(str(cand_no))
        if seg:
            if any(get_sub_seg(other_s, cand_no) for other_s in ("physics", "chemistry", "mathematics") if other_s != sub_norm):
                continue
            if sub_norm == "physics":
                if cand_no <= 30:
                    return seg
            elif sub_norm == "chemistry":
                if max_no > 30 and (26 <= cand_no <= 60):
                    return seg
                elif max_no <= 30 and off != 0:
                    return seg
            elif sub_norm == "mathematics":
                if max_no > 30 and cand_no >= 51:
                    return seg
                elif max_no <= 30 and off != 0:
                    return seg

    return None

def build_test_pdf(
    chapters=None,
    count=None,
    pattern="adv",
    subjects=None,
    paper="all",
    title="JEE ADVANCED PRACTICE TEST",
    subtitle="Chapter-wise Practice Sheet | Questions cropped from source papers",
    include_solutions=True,
    remove_watermark=True,
    selected_qids=None,
    out_pdf=None,
    shuffle=True
):
    """Builds a vector test PDF with sub-second generation using pre-computed segments cache."""
    qm = QuestionManager.get_instance()

    # 1. Filter candidates
    matched = []
    target_count = len(selected_qids) if selected_qids else count

    if selected_qids:
        # Build subject set early so we can filter even when qids are pre-selected
        subj_set = [s.strip().lower() for s in (subjects or []) if s.strip()]
        for qid in selected_qids:
            if qid in qm.q_by_id:
                q = qm.q_by_id[qid]
                # Apply subject filter: drop questions whose subject doesn't match
                # the requested subjects (catches DB mis-tags like a Physics question
                # sneaking into a Chemistry-only custom test).
                if subj_set:
                    q_sub = str(q.get("subject", "")).strip().lower()
                    if q_sub not in subj_set:
                        continue
                if pattern == "main":
                    is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
                    t_str = str(q.get("rawType") or q.get("type", "")).lower()
                    if is_para or "para" in t_str or "comp" in t_str or "multi" in t_str or "msq" in t_str:
                        continue
                matched.append(q)
    else:
        chap_set = [c.strip().lower() for c in (chapters or []) if c.strip()]
        subj_set = [s.strip().lower() for s in (subjects or []) if s.strip()]

        if pattern == "main":
            # STRICTLY 25 SCQ and 5 Numerical per subject
            all_known_subjs = ["physics", "chemistry", "mathematics"]
            target_subjs = [s for s in all_known_subjs if s in subj_set] if subj_set else all_known_subjs
            if not target_subjs:
                target_subjs = ["physics"]

            per_sub_scq = 20
            per_sub_nat = 5
            if count is not None and count != 25 * len(target_subjs):
                per_sub_total = max(1, count // len(target_subjs))
                per_sub_scq = round(per_sub_total * 20 / 25)
                per_sub_nat = max(1, per_sub_total - per_sub_scq)

            for s_name in target_subjs:
                sub_pool = []
                for q in qm.questions:
                    if str(q.get("subject", "")).strip().lower() != s_name:
                        continue
                    if paper != "all" and q.get("paper") != paper:
                        continue
                    if chap_set:
                        q_ch = str(q.get("chapter", "")).strip().lower()
                        if not any(c in q_ch or q_ch in c for c in chap_set):
                            continue
                    sub_pool.append(q)

                scq_cands = []
                nat_cands = []
                for q in sub_pool:
                    is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
                    if is_para:
                        continue
                    t_str = str(q.get("rawType") or q.get("type", "")).lower()
                    if "para" in t_str or "comp" in t_str or "multi" in t_str or "msq" in t_str:
                        continue
                    k = qm.find_pdf_key(q)
                    if not k:
                        continue
                    if t_str in ("single", "mcq"):
                        scq_cands.append(q)
                    elif t_str in ("numerical", "nat"):
                        nat_cands.append(q)

                if shuffle:
                    random.shuffle(scq_cands)
                    random.shuffle(nat_cands)

                def cluster_by_paper(cands, needed):
                    by_paper = collections.defaultdict(list)
                    for q in cands:
                        by_paper[qm.find_pdf_key(q)].append(q)
                    clustered = []
                    papers = list(by_paper.keys())
                    if shuffle:
                        random.shuffle(papers)
                    for _ in range(4):
                        for p in papers:
                            if by_paper[p]:
                                clustered.append(by_paper[p].pop(0))
                                if len(clustered) >= needed + 12:
                                    break
                        if len(clustered) >= needed + 12:
                            break
                    if len(clustered) < needed:
                        for rem_list in by_paper.values():
                            clustered.extend(rem_list)
                    return clustered

                picked_scq = cluster_by_paper(scq_cands, per_sub_scq)
                picked_nat = cluster_by_paper(nat_cands, per_sub_nat)

                matched.extend(picked_scq[:per_sub_scq + 15])
                matched.extend(picked_nat[:per_sub_nat + 10])

            target_count = len(target_subjs) * (per_sub_scq + per_sub_nat)
        else:
            for q in qm.questions:
                if subj_set:
                    q_sub = str(q.get("subject", "")).strip().lower()
                    if q_sub not in subj_set:
                        continue
                if paper != "all" and q.get("paper") != paper:
                    continue
                if chap_set:
                    q_ch = str(q.get("chapter", "")).strip().lower()
                    if not any(c in q_ch or q_ch in c for c in chap_set):
                        continue
                matched.append(q)

            if shuffle:
                random.seed(int(time.time() * 1000) % 100000)
                random.shuffle(matched)

            # Paper clustering for variety and speed
            by_paper = collections.defaultdict(list)
            for q in matched:
                k = qm.find_pdf_key(q)
                if k:
                    by_paper[k].append(q)
            clustered = []
            papers = list(by_paper.keys())
            if shuffle:
                random.shuffle(papers)
            for _ in range(5):
                for p in papers:
                    if by_paper[p]:
                        clustered.append(by_paper[p].pop(0))
                        if len(clustered) >= (target_count or 30) + 15:
                            break
                if len(clustered) >= (target_count or 30) + 15:
                    break
            if len(clustered) < (target_count or 30):
                for rem in by_paper.values():
                    clustered.extend(rem)
            matched = clustered if clustered else matched

    if not matched:
        raise ValueError("No questions found matching your selection criteria.")

    # Filter to questions that actually have matching PDFs
    valid_candidates = []
    pool_limit = max((target_count or 30) * 2, 20)
    for q in matched:
        key = qm.find_pdf_key(q)
        if key:
            valid_candidates.append((q, key))
            if len(valid_candidates) >= pool_limit:
                break

    if not valid_candidates:
        raise ValueError("Could not find source papers for the selected questions.")

    # 2. Document & Segment cache helpers
    doc_cache = {}
    seg_cache = {}
    sol_cache = {}

    def get_segments_for_question(key):
        if key in seg_cache:
            return seg_cache[key]
        
        # 1. Check pre-computed segments cache (instant O(1))
        q_cache = qm.segments_cache.get("questions", {})
        if key in q_cache:
            sub_d = {}
            for item_k, parts in q_cache[key]["by_sub"].items():
                if "||" in item_k:
                    s_name, s_num = item_k.split("||", 1)
                    try:
                        sub_d[(s_name.lower(), int(s_num))] = parts
                    except ValueError:
                        pass
                    sub_d[(s_name.lower(), s_num)] = parts
                else:
                    sub_d[(item_k.lower(), None)] = parts
            no_d = {int(item_k): parts for item_k, parts in q_cache[key]["by_no"].items() if str(item_k).isdigit()}
            seg_cache[key] = (sub_d, no_d)
            return seg_cache[key]

        # 2. Fallback: on-the-fly scan
        if key not in doc_cache:
            doc_cache[key] = open_pdf(qm.pdfs[key])
        doc = doc_cache[key]
        if doc:
            try:
                sub_d, no_d = chem_segments(doc)
            except Exception:
                sub_d, no_d = {}, {}
            seg_cache[key] = (sub_d, no_d)
        else:
            seg_cache[key] = ({}, {})
        return seg_cache[key]

    def get_sol(k):
        if k not in qm.sol_paths:
            return None
        if k in sol_cache:
            return sol_cache[k]
        
        sol_stem = os.path.splitext(os.path.basename(qm.sol_paths[k]))[0]
        s_cache = qm.segments_cache.get("solutions", {})
        
        # 1. Check pre-computed segments cache (instant O(1))
        if sol_stem in s_cache:
            s_sub = {}
            for item_s, parts in s_cache[sol_stem]["by_sub"].items():
                if "||" in item_s:
                    sub_name, sub_num = item_s.split("||", 1)
                    try:
                        s_sub[(sub_name.lower(), int(sub_num))] = parts
                    except ValueError:
                        pass
                    s_sub[(sub_name.lower(), sub_num)] = parts
                else:
                    s_sub[(item_s.lower(), None)] = parts
            s_no = {int(item_s): parts for item_s, parts in s_cache[sol_stem]["by_no"].items() if str(item_s).isdigit()}
            sol_doc = open_pdf(qm.sol_paths[k])
            if sol_doc and remove_watermark:
                remove_watermarks(sol_doc)
            sol_cache[k] = (sol_doc, s_sub, s_no)
            return sol_cache[k]

        # 2. Fallback: on-the-fly scan
        sol_doc = open_pdf(qm.sol_paths[k])
        if sol_doc:
            if remove_watermark:
                remove_watermarks(sol_doc)
            try:
                s_sub, s_no = chem_segments(sol_doc)
                sol_cache[k] = (sol_doc, s_sub, s_no)
            except Exception:
                sol_cache[k] = None
        else:
            sol_cache[k] = None
        return sol_cache[k]

    placed_questions = []  # (q, key, doc, parts, qno)
    placed_counts = collections.defaultdict(lambda: {"scq": 0, "nat": 0})

    for q, key in valid_candidates:
        sub_key = str(q.get("subject", "")).strip().lower()
        t_key = str(q.get("rawType") or q.get("type", "")).lower()
        is_nat = ("numerical" in t_key or "nat" in t_key)

        if pattern == "main" and not selected_qids:
            if is_nat and placed_counts[sub_key]["nat"] >= per_sub_nat:
                continue
            if not is_nat and placed_counts[sub_key]["scq"] >= per_sub_scq:
                continue
        elif target_count and len(placed_questions) >= target_count:
            break

        by_sub, by_no = get_segments_for_question(key)
        qno = q.get("questionNumber") or q.get("number") or 1
        sub_name = str(q.get("subject", "")).strip().lower()

        parts = find_question_parts(by_sub, by_no, sub_name, qno)
        if not parts:
            continue

        if key not in doc_cache:
            d = open_pdf(qm.pdfs[key])
            if d and remove_watermark:
                remove_watermarks(d)
            doc_cache[key] = d
        doc = doc_cache[key]
        if not doc:
            continue

        placed_questions.append((q, key, doc, parts, qno))
        if is_nat:
            placed_counts[sub_key]["nat"] += 1
        else:
            placed_counts[sub_key]["scq"] += 1

    if not placed_questions:
        raise ValueError("Failed to crop questions from source papers.")

    # 3. Sort placed questions by subject, then by section/type
    def sort_key(item):
        q, key, doc, parts, qno = item
        subj_order = {"physics": 0, "chemistry": 1, "mathematics": 2, "maths": 2}
        s_rank = subj_order.get(str(q.get("subject", "")).lower(), 9)
        is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
        t_str = "paragraph" if is_para else str(q.get("rawType") or q.get("type", "")).lower()
        if pattern == "main":
            t_rank = 0 if ("single" in t_str or "mcq" in t_str) else 1
        else:
            t_rank = 0 if "single" in t_str or "mcq" in t_str else (1 if "multi" in t_str or "msq" in t_str else (2 if "num" in t_str or "nat" in t_str else 3))
        return (s_rank, t_rank, q.get("year", 0), qno)

    placed_questions.sort(key=sort_key)

    # 4. Generate Sheet
    if not out_pdf:
        os.makedirs(os.path.join(ROOT_DIR, "generated_tests"), exist_ok=True)
        ts = int(time.time() * 1000)
        out_pdf = os.path.join(ROOT_DIR, "generated_tests", f"test_{ts}.pdf")

    sh = Sheet(title, subtitle)
    sh.cover(len(placed_questions), 1)

    has_multiple_subjects = len(set(q.get("subject", "") for q, *_ in placed_questions)) > 1
    current_sec = None
    placed = []
    rows = []

    for idx, (q, key, doc, parts, qno) in enumerate(placed_questions, 1):
        q_sub = q.get("subject", "")
        is_para = bool(q.get("paragraph") or q.get("type") == "paragraph")
        q_type = "paragraph" if is_para else str(q.get("rawType") or q.get("type", "")).lower()
        if pattern == "main":
            type_lbl = "Section B (Numerical)" if ("num" in q_type or "nat" in q_type) else "Section A (MCQ)"
        else:
            type_lbl = "Comprehension / Paragraph" if is_para else TYPE_NAME.get(q_type, "Questions")

        sec_heading = f"{q_sub} &ndash; {type_lbl}" if has_multiple_subjects else type_lbl
        if sec_heading != current_sec:
            current_sec = sec_heading
            sh.begin_section(current_sec.replace("&ndash;", "-"))

        label = f"Q{idx}"
        yr = str(q.get("year", ""))
        tag = f"{yr} | Q{qno}"
        ans = fmt_answer(q)

        e = sh.add_question(label, tag, doc, parts, meta={
            "pid": q.get("paperTitle", key),
            "q": qno,
            "ans": ans,
            "sec": current_sec,
            "subject": q_sub,
            "chapter": q.get("chapter", "")
        })

        placed.append((e, label, key, qno, q))
        rows.append((label, ans))

    # 5. Answer Key Grid
    if rows:
        sh.answer_key(rows)

    # 6. Solutions Section
    if include_solutions:
        sol_rows = []
        for e, label, key, qno, q in placed:
            so = get_sol(key)
            if so:
                sol_doc, s_sub, s_no = so
                sub_name = str(q.get("subject", "")).strip().lower()
                s_parts = find_question_parts(s_sub, s_no, sub_name, qno)
                if s_parts:
                    sol_rows.append((e, label, sol_doc, s_parts, CROP_X0, CROP_X1))

        if sol_rows:
            sh.add_solutions(sol_rows)

    # Save PDF
    os.makedirs(os.path.dirname(os.path.abspath(out_pdf)), exist_ok=True)
    sh.save(out_pdf)

    # Also keep a copy at latest_test.pdf for easy access
    latest_path = os.path.join(os.path.dirname(os.path.abspath(out_pdf)), "latest_test.pdf")
    try:
        import shutil
        shutil.copyfile(out_pdf, latest_path)
    except Exception:
        pass

    return {
        "success": True,
        "out_pdf": out_pdf,
        "filename": os.path.basename(out_pdf),
        "total_questions": len(placed),
        "total_pages": len(sh.doc),
        "answer_count": len(rows),
    }

def main():
    parser = argparse.ArgumentParser(description="Build custom vector test sheets.")
    parser.add_argument("--chapters", nargs="*", default=[], help="Chapters to include")
    parser.add_argument("--subjects", nargs="*", default=[], help="Subjects to include")
    parser.add_argument("--count", type=int, default=30, help="Number of questions")
    parser.add_argument("--pattern", choices=["adv", "main", "custom"], default="adv", help="Exam pattern")
    parser.add_argument("--paper", choices=["all", "main", "adv"], default="all", help="Paper source")
    parser.add_argument("--title", default="JEE ADVANCED PRACTICE TEST", help="Test title")
    parser.add_argument("--subtitle", default="Chapter-wise Practice Sheet | Questions cropped from source papers", help="Test subtitle")
    parser.add_argument("--no-solutions", action="store_true", help="Omit worked solutions")
    parser.add_argument("--out", default=None, help="Output PDF path")
    args = parser.parse_args()

    res = build_test_pdf(
        chapters=args.chapters,
        subjects=args.subjects,
        count=args.count,
        pattern=args.pattern,
        paper=args.paper,
        title=args.title,
        subtitle=args.subtitle,
        include_solutions=not args.no_solutions,
        out_pdf=args.out
    )
    print(f"Generated: {res['out_pdf']} ({res['total_questions']} Qs, {res['total_pages']} pages)")

if __name__ == "__main__":
    main()
