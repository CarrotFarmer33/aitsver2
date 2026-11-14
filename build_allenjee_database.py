#!/usr/bin/env python3
r"""
build_allenjee_database.py - Single-Column Vector Segmenter, Watermark/Code Cleaner & Database Generator
for Allen JEE Chemistry Modules (O-1 & O-2 Question Banks).

Processes all 41 vector chapterwise Allen JEE Chemistry PDFs:
1. Automatically blanks diagonal Form XObject watermarks ($//(1® & Session: 2020-21).
2. Redacts Allen question codes (e.g., AS0076, CK0214, TH0001) with clean white vector fills.
3. Blanks original question numbers so questions can be numbered sequentially dynamically.
4. Segregates questions strictly by Exercise:
   - O-1 (Objective-1: Single Correct MCQs)
   - O-2 (Objective-2: MSQ / Matrix Match / Comprehension / Single Correct)
5. Extracts and pairs ground-truth Answer Keys for O-1 and O-2.
6. Generates pure vector SVGs (single-column format) and packages them into allenjee_images.zip.
7. Produces allenjee_database.json (compatible with AITS portal and test builder).
"""

import os
import re
import sys
import json
import zipfile
import pymupdf as fitz

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(ROOT_DIR, "allen jee", "Chemistry[Separate]")
SITE_DIR = os.path.join(ROOT_DIR, "aitsver2-main")

OUT_DB_PATH = os.path.join(ROOT_DIR, "allenjee_database.json")
OUT_SITE_DB_PATH = os.path.join(SITE_DIR, "allenjee_database.json")
OUT_ZIP_PATH = os.path.join(ROOT_DIR, "allenjee_images.zip")
OUT_SITE_ZIP_PATH = os.path.join(SITE_DIR, "allenjee_images.zip")

HEADER_Y_CUT = 70.0
FOOTER_Y_CUT = 768.0
COL_X0 = 45.0
COL_X1 = 552.0

CHAPTER_INFO = [
    # Inorganic Chemistry (Ioc)
    ("Ioc", "CB1.pdf", "Chemical Bonding-I", "Inorganic Chemistry"),
    ("Ioc", "CB2.pdf", "Chemical Bonding-II", "Inorganic Chemistry"),
    ("Ioc", "Coordination.pdf", "Coordination Compounds", "Inorganic Chemistry"),
    ("Ioc", "Environmental_.pdf", "Environmental Chemistry", "Inorganic Chemistry"),
    ("Ioc", "F block.pdf", "f-Block Elements", "Inorganic Chemistry"),
    ("Ioc", "Hydrogen.pdf", "Hydrogen & Its Compounds", "Inorganic Chemistry"),
    ("Ioc", "Metallurgy_.pdf", "Metallurgy", "Inorganic Chemistry"),
    ("Ioc", "P block_.pdf", "p-Block Elements", "Inorganic Chemistry"),
    ("Ioc", "Periodic.pdf", "Periodic Table & Periodicity", "Inorganic Chemistry"),
    ("Ioc", "Quantum no.pdf", "Quantum Numbers & Electronic Configuration", "Inorganic Chemistry"),
    # Organic Chemistry (Oc)
    ("Oc", "Acid amines.pdf", "Carboxylic Acids & Amines", "Organic Chemistry"),
    ("Oc", "Acid base_.pdf", "Acidic & Basic Strength", "Organic Chemistry"),
    ("Oc", "Alcohol ether.pdf", "Alcohols, Phenols & Ethers", "Organic Chemistry"),
    ("Oc", "Aromatic.pdf", "Aromatic Compounds", "Organic Chemistry"),
    ("Oc", "Biomolecules.pdf", "Biomolecules", "Organic Chemistry"),
    ("Oc", "Carbonyl.pdf", "Aldehydes & Ketones (Carbonyl)", "Organic Chemistry"),
    ("Oc", "Chem in everyday life.pdf", "Chemistry in Everyday Life", "Organic Chemistry"),
    ("Oc", "Electronic displacement effect.pdf", "Electronic Displacement Effects (GOC)", "Organic Chemistry"),
    ("Oc", "Halogen derivative_.pdf", "Halogen Derivatives (Alkyl & Aryl Halides)", "Organic Chemistry"),
    ("Oc", "Hydrocarbon.pdf", "Hydrocarbons (Alkanes, Alkenes, Alkynes)", "Organic Chemistry"),
    ("Oc", "Isomerism ( structural - stereo ).pdf", "Isomerism (Structural & Stereo)", "Organic Chemistry"),
    ("Oc", "Name rxn.pdf", "Named Reactions & Mechanisms", "Organic Chemistry"),
    ("Oc", "Nomenclature , common names.pdf", "IUPAC Nomenclature & Common Names", "Organic Chemistry"),
    ("Oc", "Oxidation_.pdf", "Oxidation Reactions", "Organic Chemistry"),
    ("Oc", "Polymer , POC.pdf", "Polymers & Practical Organic Chemistry", "Organic Chemistry"),
    ("Oc", "Purification_.pdf", "Purification & Characterisation", "Organic Chemistry"),
    ("Oc", "Reduction.pdf", "Reduction Reactions", "Organic Chemistry"),
    # Physical Chemistry (Pc)
    ("Pc", "Atomic.pdf", "Atomic Structure", "Physical Chemistry"),
    ("Pc", "Chem eqb.pdf", "Chemical Equilibrium", "Physical Chemistry"),
    ("Pc", "Chem kinetics.pdf", "Chemical Kinetics", "Physical Chemistry"),
    ("Pc", "Concn terms.pdf", "Concentration Terms & Stoichiometry", "Physical Chemistry"),
    ("Pc", "Ideal.pdf", "Ideal Gas State", "Physical Chemistry"),
    ("Pc", "Ionic eqb.pdf", "Ionic Equilibrium", "Physical Chemistry"),
    ("Pc", "Liq soln_.pdf", "Liquid Solutions & Colligative Properties", "Physical Chemistry"),
    ("Pc", "Mole concept_.pdf", "Mole Concept", "Physical Chemistry"),
    ("Pc", "Real.pdf", "Real Gas & van der Waals", "Physical Chemistry"),
    ("Pc", "Redox.pdf", "Redox Reactions & Equivalent Concept", "Physical Chemistry"),
    ("Pc", "Solid state.pdf", "Solid State", "Physical Chemistry"),
    ("Pc", "TD 1_.pdf", "Thermodynamics (First Law)", "Physical Chemistry"),
    ("Pc", "TD 2_.pdf", "Thermodynamics (Second & Third Law)", "Physical Chemistry"),
    ("Pc", "Thermo chem.pdf", "Thermochemistry", "Physical Chemistry")
]

def make_slug(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "_", name.lower()).strip("_")
    return s

def clean_watermarks_from_doc(doc):
    page_contents = set()
    for p in doc:
        for c in p.get_contents():
            page_contents.add(c)

    for xref in range(1, doc.xref_length()):
        if xref in page_contents:
            continue  # NEVER touch page content streams
        try:
            s = doc.xref_stream(xref).decode("latin1", errors="ignore")
            # Only blank out the diagonal watermark Form XObjects
            if ("<0024002F002F00280031>" in s or "130.08 Tf" in s or "$//(1" in s or "Session :" in s) and "0.707" in s:
                doc.update_stream(xref, b"")
        except Exception:
            pass

def parse_answer_key_tables(doc):
    ans_map = {"O-1": {}, "O-2": {}}
    cur_ex = None

    for page_idx in range(len(doc)):
        text = doc[page_idx].get_text("text")
        if not ("ANSWER" in text or "Que." in text or "Ans." in text):
            continue

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]
            m = re.search(r"EXERCISE\s*[:#]?\s*([^\n]+)", line, re.I)
            if m:
                raw = m.group(1).upper()
                if re.search(r"\bO-?(?:2|II)\b", raw):
                    cur_ex = "O-2"
                elif re.search(r"\bO-?(?:1|I)\b", raw):
                    cur_ex = "O-1"
                else:
                    cur_ex = None
                i += 1
                continue

            if cur_ex in ("O-1", "O-2") and line.startswith("Que"):
                q_nums = [int(n) for n in re.findall(r"\b\d+\b", line)]
                i += 1
                while i < len(lines) and not lines[i].startswith("Ans") and not lines[i].startswith("Que") and not re.search(r"EXERCISE", lines[i], re.I):
                    q_nums.extend([int(n) for n in re.findall(r"\b\d+\b", lines[i])])
                    i += 1
                if i < len(lines) and lines[i].startswith("Ans"):
                    ans_tokens = []
                    extra = re.sub(r"^Ans\.?\s*", "", lines[i]).strip()
                    if extra:
                        ans_tokens.append(extra)
                    i += 1
                    while i < len(lines) and not lines[i].startswith("Que") and not lines[i].startswith("Ans") and not re.search(r"EXERCISE", lines[i], re.I) and not lines[i].startswith("ANSWER"):
                        if lines[i] not in ("E", "ALLEN", "®") and not lines[i].startswith("node"):
                            ans_tokens.append(lines[i])
                        i += 1
                    for q, a in zip(q_nums, ans_tokens):
                        ans_map[cur_ex][q] = a
                continue
            i += 1

    return ans_map

def find_exercise_ranges(doc):
    ex_ranges = {}
    cur_ex = None
    start_p = None

    for p_idx, page in enumerate(doc):
        t = page.get_text("text")
        clean_lines = [l for l in t.split("\n") if not l.startswith("node") and ".p65" not in l]
        clean_text = "\n".join(clean_lines)

        if re.search(r"ANSWERS?[\s\-]KEY", clean_text, re.I) or ("Que." in clean_text and "Ans." in clean_text):
            if cur_ex and start_p is not None:
                ex_ranges[cur_ex] = (start_p, p_idx - 1)
                cur_ex = None
            break

        m = re.search(r"EXERCISE\s*[:#]\s*([^\n]+)", clean_text, re.I)
        if m:
            raw = m.group(1).upper().strip()
            if re.search(r"\bO-?(?:2|II)\b", raw):
                norm_ex = "O-2"
            elif re.search(r"\bO-?(?:1|I)\b", raw):
                norm_ex = "O-1"
            else:
                norm_ex = raw.split()[0]

            if norm_ex != cur_ex:
                if cur_ex and start_p is not None:
                    ex_ranges[cur_ex] = (start_p, p_idx - 1)
                cur_ex = norm_ex
                start_p = p_idx

    if cur_ex and start_p is not None and cur_ex not in ex_ranges:
        ex_ranges[cur_ex] = (start_p, len(doc) - 1)

    return ex_ranges

PARA_RE = re.compile(
    r'(?:PARAGRAPH|COMPREHENSION|PASSAGE)\s*(?:#\s*\d+)?\s*(?:FOR)?\s*\(?\s*(?:QUESTION|QUE\.?|Q\.?)?\s*(?:NOS?\.?)?\s*\(?\s*(?:Q\.?)?\s*(\d+)\s*(?:TO|&|-|AND)\s*(?:Q\.?)?\s*(\d+)\s*\)?',
    re.IGNORECASE
)
Q_NUM_RE = re.compile(r'^(?:Q\.?|Q)?(\d+)(?:\.([A-Za-z].*)|\.?)$')

def get_q_num_redact_rect(page, qw, rest):
    if not rest:
        return fitz.Rect(qw[0] - 2.0, qw[1] - 1.5, qw[2] + 2.0, qw[3] + 1.5)
    raw = page.get_text("rawdict")
    for b in raw.get("blocks", []):
        for l in b.get("lines", []):
            for s in l.get("spans", []):
                chars = s.get("chars", [])
                txt = "".join(c.get("c", "") for c in chars)
                if qw[4] in txt:
                    prefix = qw[4][:-len(rest)]
                    p_chars = [c for c in chars if qw[0] - 2 <= c["bbox"][0] and c["bbox"][1] <= qw[3] + 2]
                    if len(p_chars) >= len(prefix):
                        end_x = p_chars[len(prefix) - 1]["bbox"][2]
                        return fitz.Rect(qw[0] - 2.0, qw[1] - 1.5, end_x + 0.5, qw[3] + 1.5)
    ratio = (len(qw[4]) - len(rest)) / len(qw[4])
    end_x = qw[0] + (qw[2] - qw[0]) * ratio
    return fitz.Rect(qw[0] - 2.0, qw[1] - 1.5, end_x, qw[3] + 1.5)

def detect_pattern(text, current_pattern="single"):
    u = text.upper()
    if "MATCH THE COLUMN" in u or "MATRIX MATCH" in u or "COLUMN-I" in u:
        return "matrix"
    if "MORE THAN ONE" in u or "ONE OR MORE" in u:
        return "multi"
    if "COMPREHENSION" in u or "PASSAGE" in u or "PARAGRAPH" in u:
        return "paragraph"
    if "SINGLE CORRECT" in u or "STATEMENT TYPE" in u or "ASSERTION" in u:
        return "single"
    return current_pattern

def process_all_chapters():
    os.makedirs(SITE_DIR, exist_ok=True)
    zf = zipfile.ZipFile(OUT_ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED)

    all_questions = []
    total_processed = 0

    print("=" * 70, flush=True)
    print("ALLEN JEE O-1 & O-2 SEGMENTATION & VECTOR SVG PIPELINE", flush=True)
    print("=" * 70, flush=True)

    for sub_dir, pdf_file, chapter_title, subject in CHAPTER_INFO:
        pdf_path = os.path.join(BASE_DIR, sub_dir, "Exercise", pdf_file)
        if not os.path.exists(pdf_path):
            print(f"[SKIP] Not found: {pdf_path}", flush=True)
            continue

        doc = fitz.open(pdf_path)
        if len(doc) < 2:
            doc.close()
            continue

        # Check if vector
        sample_txt = sum(len(doc[p].get_text("text")) for p in range(1, min(4, len(doc))))
        if sample_txt < 200:
            print(f"[SKIP SCANNED] {chapter_title} ({pdf_file})", flush=True)
            doc.close()
            continue

        chapter_slug = make_slug(chapter_title)
        print(f"\nProcessing: {chapter_title} ({sub_dir}/{pdf_file}) - {len(doc)} pages", flush=True)

        clean_watermarks_from_doc(doc)
        ans_map = parse_answer_key_tables(doc)
        ex_ranges = find_exercise_ranges(doc)

        print(f"  O-1 Range: {ex_ranges.get('O-1')} | O-2 Range: {ex_ranges.get('O-2')}", flush=True)
        print(f"  O-1 Answer Keys: {len(ans_map['O-1'])} | O-2 Answer Keys: {len(ans_map['O-2'])}", flush=True)

        for ex_key in ("O-1", "O-2"):
            if ex_key not in ex_ranges:
                continue

            r_start, r_end = ex_ranges[ex_key]
            active_pattern = "single" if ex_key == "O-1" else "multi"
            ex_code_suffix = "o1" if ex_key == "O-1" else "o2"

            # Pre-scan O-2 pages for all paragraph / comprehension groups and extract passage SVGs
            para_groups = {}
            if ex_key == "O-2":
                for p_i in range(r_start, r_end + 1):
                    p_page = doc[p_i]
                    p_txt = p_page.get_text("text")
                    p_words = p_page.get_text("words")
                    for line in p_txt.split("\n"):
                        m = PARA_RE.search(line.strip())
                        if m:
                            q1, q2 = int(m.group(1)), int(m.group(2))
                            h_words = [w for w in p_words if any(k in w[4].upper() for k in ["PARAGRAPH", "COMPREHENSION", "PASSAGE"])]
                            q1_w = [w for w in p_words if (w[4] in (f"{q1}.", f"Q.{q1}", f"Q{q1}", str(q1))) and w[0] < 70]
                            if h_words and q1_w:
                                h_y0 = min(w[1] for w in h_words)
                                q1_y0 = min(w[1] for w in q1_w)
                                comp_w = [w for w in p_words if "COMPREHENSION" in w[4].upper() and 0 <= h_y0 - w[1] <= 35]
                                if comp_w:
                                    h_y0 = min(w[1] for w in comp_w)
                                p_clip = fitz.Rect(COL_X0, max(HEADER_Y_CUT, h_y0 - 4.0), COL_X1, q1_y0 - 2.0)
                                if p_clip.height > 15:
                                    para_id = f"allenjee_{chapter_slug}_{ex_code_suffix}_para_{q1}_{q2}"
                                    p_filename = f"{para_id}_passage.svg"

                                    tdoc = fitz.open()
                                    tdoc.insert_pdf(doc, from_page=p_i, to_page=p_i)
                                    tp = tdoc[0]
                                    tp.set_cropbox(p_clip)
                                    p_svg = tp.get_svg_image(text_as_path=1)
                                    tdoc.close()
                                    ins_pos = p_svg.find(">") + 1
                                    if ins_pos > 0:
                                        p_svg = p_svg[:ins_pos] + '<rect width="100%" height="100%" fill="#ffffff"/>' + p_svg[ins_pos:]
                                    zf.writestr(p_filename, p_svg)

                                    p_text = p_page.get_text("text", clip=p_clip).strip()
                                    para_groups[(q1, q2)] = {
                                        "para_id": para_id,
                                        "passage_filename": p_filename,
                                        "passage_header": f"(Paragraph for Questions {q1} to {q2})",
                                        "passage_text": p_text
                                    }
                        elif "TABLE TYPE QUESTION" in line.upper():
                            q1, q2 = 16, 18
                            h_words = [w for w in p_words if "TABLE" in w[4].upper()]
                            q1_w = [w for w in p_words if (w[4] in (f"{q1}.", f"Q.{q1}", f"Q{q1}", str(q1))) and w[0] < 70]
                            if h_words and q1_w:
                                h_y0 = min(w[1] for w in h_words)
                                q1_y0 = min(w[1] for w in q1_w)
                                p_clip = fitz.Rect(COL_X0, max(HEADER_Y_CUT, h_y0 - 4.0), COL_X1, q1_y0 - 2.0)
                                if p_clip.height > 15:
                                    para_id = f"allenjee_{chapter_slug}_{ex_code_suffix}_para_{q1}_{q2}"
                                    p_filename = f"{para_id}_passage.svg"

                                    tdoc = fitz.open()
                                    tdoc.insert_pdf(doc, from_page=p_i, to_page=p_i)
                                    tp = tdoc[0]
                                    tp.set_cropbox(p_clip)
                                    p_svg = tp.get_svg_image(text_as_path=1)
                                    tdoc.close()
                                    ins_pos = p_svg.find(">") + 1
                                    if ins_pos > 0:
                                        p_svg = p_svg[:ins_pos] + '<rect width="100%" height="100%" fill="#ffffff"/>' + p_svg[ins_pos:]
                                    zf.writestr(p_filename, p_svg)

                                    p_text = p_page.get_text("text", clip=p_clip).strip()
                                    para_groups[(q1, q2)] = {
                                        "para_id": para_id,
                                        "passage_filename": p_filename,
                                        "passage_header": f"(Table / Comprehension for Questions {q1} to {q2})",
                                        "passage_text": p_text
                                    }

            for page_idx in range(r_start, r_end + 1):
                page = doc[page_idx]
                words = page.get_text("words")

                # Detect section pattern switches on this page
                p_text = page.get_text("text")
                for line in p_text.split("\n"):
                    if any(k in line.upper() for k in ["SINGLE CORRECT", "MORE THAN ONE", "ONE OR MORE", "MATCH THE COLUMN", "COMPREHENSION"]):
                        active_pattern = detect_pattern(line, active_pattern)

                # Locate all question number markers: w[4] == '1.', '2.', etc. with w[0] near left margin
                q_words = []
                code_words = []

                for w in words:
                    # Question start number
                    if 42.0 <= w[0] <= 60.0 and w[1] < FOOTER_Y_CUT:
                        m_q = Q_NUM_RE.match(w[4])
                        if m_q:
                            q_words.append((int(m_q.group(1)), w, m_q.group(2)))
                    # Question code: e.g. CK0214, AS0076, etc.
                    elif len(w[4]) == 6 and w[4][:2].isupper() and w[4][2:].isdigit():
                        code_words.append(w)

                if not q_words:
                    continue

                q_words.sort(key=lambda item: item[1][1])  # sort by y0

                # Redact codes and original question numbers upfront on this page
                for cw in code_words:
                    page.draw_rect(fitz.Rect(cw[0] - 1.5, cw[1] - 1.5, cw[2] + 1.5, cw[3] + 1.5), color=None, fill=(1, 1, 1))

                for q_num, qw, rest in q_words:
                    page.draw_rect(get_q_num_redact_rect(page, qw, rest), color=None, fill=(1, 1, 1))

                # Segment each question into SVG
                for i in range(len(q_words)):
                    q_num, qw, rest = q_words[i]
                    # Calculate vertical boundary
                    y0 = max(HEADER_Y_CUT, qw[1] - 5.0)

                    if i + 1 < len(q_words):
                        next_qw = q_words[i + 1][1]
                        y1 = next_qw[1] - 4.0
                    else:
                        # Last question on page: extend to cover its content or bottom code
                        max_y = qw[3] + 40.0
                        for cw in code_words:
                            if cw[1] > qw[1]:
                                max_y = max(max_y, cw[3] + 4.0)
                        for b in page.get_text("blocks"):
                            if b[1] >= qw[1] - 10.0 and b[3] <= FOOTER_Y_CUT:
                                max_y = max(max_y, b[3] + 6.0)
                        y1 = min(FOOTER_Y_CUT, max_y)

                    if y1 <= y0 + 10.0:
                        y1 = min(FOOTER_Y_CUT, y0 + 40.0)

                    clip_rect = fitz.Rect(COL_X0, y0, COL_X1, y1)

                    # Create dedicated 1-page document for pristine SVG extraction
                    tdoc = fitz.open()
                    tdoc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
                    tp = tdoc[0]
                    tp.set_cropbox(clip_rect)

                    svg = tp.get_svg_image(text_as_path=1)
                    tdoc.close()

                    # Prepend opaque white background rect
                    insert_pos = svg.find(">") + 1
                    if insert_pos > 0:
                        bg_rect = '<rect width="100%" height="100%" fill="#ffffff"/>'
                        svg = svg[:insert_pos] + bg_rect + svg[insert_pos:]

                    # Question text snippet for search / indexing
                    q_text_snippet = page.get_text("text", clip=clip_rect).strip()

                    # Matched code
                    matched_code = None
                    for cw in code_words:
                        if y0 - 10.0 <= cw[1] <= y1 + 10.0:
                            matched_code = cw[4]
                            break

                    qid = f"allenjee_{chapter_slug}_{ex_code_suffix}_p{page_idx+1}_q{q_num}"
                    svg_filename = f"{qid}.svg"

                    zf.writestr(svg_filename, svg)

                    # Determine exact segregated pattern type
                    matched_para = None
                    if ex_key == "O-2":
                        for (pq1, pq2), pdata in para_groups.items():
                            if pq1 <= q_num <= pq2:
                                matched_para = pdata
                                break

                    ans = ans_map[ex_key].get(q_num, "")
                    if matched_para:
                        q_type = "paragraph"
                    elif ex_key == "O-1":
                        q_type = "single"
                    else:
                        if ";" in ans or ("-" in ans and not ans.startswith("-")):
                            q_type = "matrix"
                        elif "," in ans:
                            q_type = "multi"
                        elif active_pattern == "matrix":
                            q_type = "matrix"
                        elif active_pattern == "multi":
                            q_type = "multi"
                        else:
                            q_type = "single"

                    q_record = {
                        "id": qid,
                        "chapter": chapter_title,
                        "subject": "Chemistry",
                        "branch": subject,
                        "paper": "allen_jee",
                        "exercise": ex_key,
                        "bank": ex_key,
                        "type": q_type,
                        "paragraph": bool(matched_para),
                        "paragraphId": matched_para["para_id"] if matched_para else None,
                        "passageHeader": matched_para["passage_header"] if matched_para else None,
                        "passageText": matched_para["passage_text"] if matched_para else None,
                        "passageImages": [f"zipimg:allenjee_images.zip#{matched_para['passage_filename']}"] if matched_para else [],
                        "questionNumber": q_num,
                        "answer": ans,
                        "allenCode": matched_code,
                        "pdfName": os.path.relpath(pdf_path, ROOT_DIR).replace("\\", "/"),
                        "page": page_idx + 1,
                        "segments": [[page_idx + 1, float(COL_X0), float(y0), float(COL_X1), float(y1)]],
                        "text": q_text_snippet,
                        "images": [f"zipimg:allenjee_images.zip#{svg_filename}"],
                        "paperTitle": f"Allen JEE Chemistry - {chapter_title} ({ex_key})"
                    }
                    all_questions.append(q_record)
                    total_processed += 1

        doc.close()

    zf.close()
    print(f"\nCreated ZIP: {OUT_ZIP_PATH} ({os.path.getsize(OUT_ZIP_PATH) / 1024 / 1024:.2f} MB)", flush=True)

    # Copy ZIP to aitsver2-main/allenjee_images.zip
    import shutil
    shutil.copyfile(OUT_ZIP_PATH, OUT_SITE_ZIP_PATH)
    print(f"Copied ZIP to: {OUT_SITE_ZIP_PATH}", flush=True)

    # Populate companion paragraphGroup lists
    para_map = {}
    for q in all_questions:
        if q.get("paragraphId"):
            para_map.setdefault(q["paragraphId"], []).append(q["id"])
    for q in all_questions:
        if q.get("paragraphId"):
            q["paragraphGroup"] = para_map.get(q["paragraphId"], [])

    # Save database JSON
    db_payload = {
        "ok": True,
        "totalQuestions": len(all_questions),
        "source": "Allen JEE Chemistry Modules (O-1 & O-2)",
        "questions": all_questions
    }

    with open(OUT_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db_payload, f, indent=2)
    with open(OUT_SITE_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db_payload, f, indent=2)

    print(f"Saved DB to {OUT_DB_PATH} and {OUT_SITE_DB_PATH}", flush=True)
    print(f"TOTAL QUESTIONS EXTRACTED: {len(all_questions)}", flush=True)

    o1_count = sum(1 for q in all_questions if q["bank"] == "O-1")
    o2_count = sum(1 for q in all_questions if q["bank"] == "O-2")
    ans_count = sum(1 for q in all_questions if q["answer"])
    print(f"  O-1 Questions: {o1_count}", flush=True)
    print(f"  O-2 Questions: {o2_count}", flush=True)
    print(f"  With Answer Key: {ans_count} ({ans_count / max(len(all_questions), 1) * 100:.1f}%)", flush=True)

if __name__ == "__main__":
    process_all_chapters()
