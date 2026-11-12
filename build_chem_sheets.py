#!/usr/bin/env python3
"""JEE Advanced CHEMISTRY version of build_sheets_adv.py.

Reads chem1_database.json (fields: chapter, type single/multi/numerical, questionNumber, answer,
paperTitle, zipName, year, subject) and builds one sheet per chapter by cropping the questions
out of the local Advanced question-paper PDFs, with the same Sheet layout as the physics sheets.
Inside each sheet the questions are grouped by type:

    Single Correct (MCQ)  ->  One or More Correct (MSQ)  ->  Numerical / Integer (NAT)

then come an answer key (taken from the JSON) and, if "...-SOL.pdf" files are supplied, the
worked solutions.

Usage:
    python3 build_chem_sheets.py chem1_database.json OUT_DIR PDF_OR_FOLDER [...]
                                 [--solutions SOLUTIONS_FOLDER] [--chapter TEXT] [--keep-no-answer]

A folder is searched with all its subfolders. Question papers and ...-SOL.pdf solutions may be
mixed anywhere inside it. Needs build_sheets.py (the newest one) in the same folder.
  --keep-no-answer keep questions that have no answer in the JSON (by default they are left out)
  --chapter TEXT   only build chapters whose name contains TEXT (repeatable), handy for a trial run
Questions listed in OUT_DIR/removed_questions.json (written by remove_questions.py) are left out.
"""
import argparse, collections, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from build_sheets import (CROP_X0, CROP_X1, SOL_RE, SRC_BOT, SRC_TOP, Sheet, open_pdf, slug,  # noqa: E402
                              tight, walk_pdfs)
    if not hasattr(Sheet, "begin_section"):
        raise ImportError("old Sheet class")
except ImportError as ex:
    sys.exit(f"Error: cannot use build_sheets.py ({ex}). Put the newest build_sheets.py (the one with "
             "Sheet.begin_section) in the same folder as this script and make sure pymupdf is installed.")

# sheet sections, in this order
TYPE_ORDER = [("MCQ", "Single Correct (MCQ)"),
              ("MSQ", "One or More Correct (MSQ)"),
              ("NAT", "Numerical / Integer Answer (NAT)")]
TYPE_NAME = dict(TYPE_ORDER)
QTYPE = {"single": "MCQ", "multi": "MSQ", "numerical": "NAT"}     # chem1_database.json -> sheet types

# the tagging produced a few short spellings of the same chapter; fold them together
CHAPTER_ALIASES = {
    "p-Block: Group 17 & 18": "p-Block Elements: Group 17 (Halogens) & Group 18 (Noble gases)",
    "p-Block: Group 15 & 16": "p-Block Elements: Group 15 (Nitrogen family) & Group 16 (Oxygen family)",
    "p-Block: Group 13 & 14": "p-Block Elements: Group 13 (Boron family) & Group 14 (Carbon family)",
    "Metallurgy": "Principles & Processes of Isolation of Metals (Metallurgy)",
    "Isomerism": "Isomerism (Structural & Stereoisomerism)",
}

# chapter order used for the file-name prefixes (unknown chapters follow, alphabetically)
CHAPTER_ORDER = [
    "Some Basic Concepts of Chemistry", "Atomic Structure", "Periodic Table & Periodicity",
    "Chemical Bonding & Molecular Structure", "Gaseous State", "Solid State",
    "Thermodynamics (Chemical)", "Thermochemistry", "Chemical Equilibrium", "Ionic Equilibrium",
    "Redox Reactions", "Electrochemistry", "Chemical Kinetics", "Liquid Solutions & Colligative Properties",
    "Surface Chemistry", "Nuclear Chemistry", "Hydrogen", "s-Block Elements",
    "p-Block Elements: Group 13 (Boron family) & Group 14 (Carbon family)",
    "p-Block Elements: Group 15 (Nitrogen family) & Group 16 (Oxygen family)",
    "p-Block Elements: Group 17 (Halogens) & Group 18 (Noble gases)",
    "d- and f-Block Elements", "Coordination Compounds",
    "Principles & Processes of Isolation of Metals (Metallurgy)", "Qualitative Salt Analysis",
    "General Organic Chemistry (GOC)", "Isomerism (Structural & Stereoisomerism)", "Hydrocarbons",
    "Haloalkanes & Haloarenes", "Alcohols, Phenols & Ethers", "Aldehydes, Ketones & Carboxylic Acids",
    "Amines & Diazonium Salts", "Biomolecules", "Polymers", "Chemistry in Everyday Life",
]
REQUIRED = ("paperTitle", "zipName", "year", "questionNumber", "type", "chapter")
SUBJECT = "chemistry"


# ----------------------------------------------------------------------------- PDF cropping
def _lines(words):
    """Group words into text lines: {rounded y0: [words]}."""
    out = collections.defaultdict(list)
    for w in words:
        out[round(w[1])].append(w)
    return out


def chem_segments(src):
    """({(subject, qno): [(page, y0, y1), ...]}, {qno: [...]}) for an Advanced paper.

    Same method as adv_segments in build_sheets_adv.py: question starts are the numbers printed in
    the left margin, kept only if they run 1, 2, 3, ... in reading order; "Space for Rough work",
    section headings with their instructions and the Physics/Chemistry/Mathematics part headings
    are cut off. Differences for chemistry:
      * a numbering that starts again at 1 right after a new subject heading is accepted (some papers
        number every subject from 1), and
      * every question remembers which subject heading it sits under, so Chemistry Q5 and
        Physics Q5 of such a paper are told apart.
    """
    # Footer cutoff: anything at or below this y is treated as a running footer/page number
    # and excluded from question content.  718 catches most FIITJEE running footers
    # (paper title, page number, branding) while keeping all question text.
    FOOTER_CUT = 718.0

    cands, stops, term_stops, footer_stops, has_instr, heads = [], collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list), [], []
    for pi, page in enumerate(src):
        ws = page.get_text("words")
        for w in ws:
            if re.fullmatch(r"\d{1,3}\.?", w[4]) and 60 < w[0] < 92 and SRC_TOP < w[1] < SRC_BOT:
                cands.append((pi, w[1], int(w[4].rstrip(".")), w[0]))
            if w[4].lower() in ("physics", "chemistry", "mathematics", "maths") and w[1] < 160 and w[3] - w[1] > 9:
                stops[pi].append(w[1] - 2)
                term_stops[pi].append(w[1] - 2)
                sub_norm = "mathematics" if w[4].lower() in ("mathematics", "maths") else w[4].lower()
                heads.append((pi, w[1], sub_norm))
            # Detect running footer text near the bottom of the page (page numbers,
            # paper title repeats, "FIITJEE" branding) and register as a stop so they
            # never bleed into the preceding question's crop.
            if w[1] >= FOOTER_CUT and CROP_X0 <= w[0] <= CROP_X1:
                stops[pi].append(FOOTER_CUT - 2)
                footer_stops[pi].append(FOOTER_CUT - 2)
        for i in range(len(ws) - 2):
            a, b, c = ws[i], ws[i + 1], ws[i + 2]
            if (a[4], b[4], c[4]) == ("Space", "for", "Rough"):
                stops[pi].append(a[1] - 2)                        # end of this page's content
                term_stops[pi].append(a[1] - 2)
            if (a[4], b[4], c[4]) == ("This", "section", "contains") and a[0] < 80:
                has_instr.append(pi)
                lines = _lines([w for w in ws if a[1] - 70 <= w[1] < a[1] - 2])
                top = a[1]
                for y, lw in lines.items():
                    lw.sort(key=lambda w: w[0])
                    first, last = lw[0][4], lw[-1][4]
                    is_sub = first.startswith("(") and last.endswith(")") and "type" in " ".join(
                        w[4] for w in lw).lower()
                    is_head = any(w[4] == "SECTION" and w[0] > 150 for w in lw)
                    if (is_sub or is_head) and a[1] - 45 <= y < a[1]:
                        top = min(top, min(w[1] for w in lw))
                stops[pi].append(top - 3)
                term_stops[pi].append(top - 3)
    for pi in stops:
        stops[pi] = sorted(set(stops[pi]))   # deduplicate: footer stops may be added multiple times
    for pi in term_stops:
        term_stops[pi] = sorted(set(term_stops[pi]))
    for pi in footer_stops:
        footer_stops[pi] = sorted(set(footer_stops[pi]))
    heads.sort()

    # keep only the 1,2,3,... chain, starting on the first page with questions
    first_page = min(has_instr) if has_instr else 0
    cands = sorted(c for c in cands if c[0] >= first_page)
    chain, prev, prev_pos = [], None, None
    for i, (pi, y, n, q_x0) in enumerate(cands):
        take = False
        if prev is None:
            take = n == 1
        elif prev + 1 <= n <= prev + 3:                        # tolerate a number that failed to print
            take = True
        elif n == 1 and prev >= 2 and any(c[2] == 2 for c in cands[i + 1:i + 4]) \
                and any(prev_pos < (h[0], h[1]) < (pi, y) for h in heads):
            take = True                                        # new subject, numbering starts again
        if take:
            chain.append((pi, y, n, q_x0)); prev, prev_pos = n, (pi, y)

    def subject_at(pi, y):
        cur = None
        for h in heads:
            if (h[0], h[1]) <= (pi, y):
                cur = h[2]
        return cur

    page_data = {}
    for pi, page in enumerate(src):
        ws = page.get_text("words")
        drs = page.get_drawings()
        page_data[pi] = (ws, drs)

    # PASS 1: Compute clean, exact question start boundaries using interval gap analysis
    start_tops = {}
    MATH_LOOKBACK = 75
    for k, (pi, y, n, q_x0) in enumerate(chain):
        prev_q = chain[k - 1] if k > 0 else None
        
        # Determine strict floor on page pi (above which this question cannot reach)
        prior_floor = prev_q[1] + 4 if (prev_q and prev_q[0] == pi) else SRC_TOP
        prior_stops = [s for s in stops.get(pi, []) if s < y - 4]
        if prior_stops:
            prior_floor = max(prior_floor, max(prior_stops) + 2)

        ws, drs = page_data[pi]
        body_x0 = q_x0 + 8

        # If there is a previous question on the same page, find the exact whitespace gap
        # between the bottom of the previous question and the top of this question's equation/ink.
        if prev_q and prev_q[0] == pi:
            intervals = []
            for w in ws:
                if 60 <= w[0] <= 550 and prev_q[1] <= w[1] <= y + 4:
                    intervals.append((w[1], w[3]))
            for d in drs:
                r = d["rect"]
                if r.width < 450 and 60 <= r.x0 <= 550 and prev_q[1] <= r.y0 <= y + 4:
                    intervals.append((r.y0, r.y1))
            intervals.sort()
            merged = []
            for top, bot in intervals:
                if merged and top <= merged[-1][1] + 2:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], bot))
                else:
                    merged.append((top, bot))
            
            # If multiple ink clusters exist between prev_q and y, the last cluster belongs
            # to this question (e.g. reagents like CH3COONa above an arrow), and the gap before
            # it marks the true boundary dividing the questions.
            if len(merged) >= 2:
                gap_bot = merged[-2][1]
                gap_top = merged[-1][0]
                if gap_top - gap_bot >= 3:
                    start_tops[k] = (gap_bot + gap_top) / 2
                    continue

        tall_words = [
            w[1] for w in ws
            if w[0] > body_x0 and prior_floor <= w[1] <= y + 2 and w[1] >= y - MATH_LOOKBACK
        ]
        tall_drawings = [
            d["rect"].y0 for d in drs
            if d["rect"].x0 > body_x0 and d["rect"].width < 450
            and prior_floor <= d["rect"].y0 <= y + 2 and d["rect"].y0 >= y - MATH_LOOKBACK
        ]
        candidates = tall_words + tall_drawings + [y]
        start_tops[k] = max(prior_floor, min(candidates) - 4)

    # PASS 2: Crop questions with zero equation clipping and zero previous-question bleed
    segs, segs_any = {}, {}
    page_last_ink = {}
    for k, (pi, y, n, q_x0) in enumerate(chain):
        nxt = chain[k + 1] if k + 1 < len(chain) else None
        
        y0 = start_tops[k]
        if pi in page_last_ink:
            y0 = max(y0, page_last_ink[pi] + 1)

        parts, p = [], pi
        while True:
            nq_here = nxt is not None and nxt[0] == p
            if nq_here:
                lim = start_tops[k + 1]
            else:
                lim = SRC_BOT

            f_hits = [s for s in footer_stops.get(p, []) if y0 < s < lim]
            page_lim = min(lim, min(f_hits)) if f_hits else lim

            t_hits = [s for s in term_stops.get(p, []) if y0 < s < page_lim]
            if t_hits:                                            # rough-work / section header: question ends
                parts.append((p, y0, min(t_hits)))
                break
            parts.append((p, y0, page_lim))
            if nq_here or p + 1 >= len(src):
                break
            p, y0 = p + 1, SRC_TOP
        trimmed = []
        for (pp, a, b) in parts:
            t = tight(src[pp], a, b)
            if t is not None:
                trimmed.append((pp, a, t))
                page_last_ink[pp] = max(page_last_ink.get(pp, 0), t)
        segs.setdefault((subject_at(pi, y), n), trimmed)
        segs_any.setdefault(n, trimmed)
    return segs, segs_any


def find_parts(seg_pair, q):
    """Chemistry question q: the one under a Chemistry heading if there is one, else by number."""
    segs, segs_any = seg_pair
    return segs.get((SUBJECT, q)) or segs_any.get(q)


# ----------------------------------------------------------------------------- data helpers
def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def clean_records(raw):
    """chem1_database.json records -> records with the fields the sheet code uses
    (number, qtype MCQ/MSQ/NAT, assignedChapter), so the rest mirrors build_sheets_adv.py."""
    if isinstance(raw, dict):
        lists = [v for v in raw.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if not lists:
            sys.exit("Error: the JSON is an object with no list of question records inside.")
        raw = max(lists, key=len)
    good, missing = [], collections.Counter()
    for x in raw:
        if not isinstance(x, dict):
            missing["(not an object)"] += 1
            continue
        miss = [k for k in REQUIRED if k not in x or x[k] in (None, "")]
        try:
            x["number"] = int(x["questionNumber"])
        except (KeyError, TypeError, ValueError):
            miss.append("questionNumber")
        if x.get("type") not in QTYPE and "type" not in miss:
            missing[f"type={x.get('type')!r}"] += 1
            continue
        if miss:
            for k in miss:
                missing[k] += 1
            continue
        ch = str(x["chapter"]).strip()
        x["assignedChapter"] = CHAPTER_ALIASES.get(ch, ch)
        x["qtype"] = QTYPE[x["type"]]
        good.append(x)
    if missing:
        print(f"WARNING: skipped {len(raw) - len(good)} of {len(raw)} JSON records that lack required fields: "
              + ", ".join(f"{k} ({n})" for k, n in missing.items()))
    return good


def fmt_answer(x):
    """Answer text for the key, or "-" when the JSON has none or one that cannot be right for the
    question type (single: A-D; multi: A-D list; numerical: a number)."""
    a = str(x.get("answer", "") or "").strip()
    t = x.get("qtype")
    if t == "MSQ":
        if re.fullmatch(r"[A-Da-d]{2,4}", a):                  # "ABD" -> "A,B,D"
            a = ",".join(a)
        a = ",".join(p.strip().upper() for p in re.split(r"[,\s;]+", a) if p.strip())
        ok = re.fullmatch(r"[A-D](,[A-D])*", a)
    elif t == "MCQ":
        a = a.upper()
        ok = re.fullmatch(r"[A-D]", a)
    elif t == "NAT":
        ok = re.fullmatch(r"-?\d+(\.\d+)?", a)
        if ok and re.fullmatch(r"-?\d+\.0+", a):
            a = a.split(".")[0]
    else:
        ok = bool(a)
    return a if ok else "-"


def chapter_rank(name):
    return (CHAPTER_ORDER.index(name), "") if name in CHAPTER_ORDER else (len(CHAPTER_ORDER), name.lower())


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Chapter-wise JEE Advanced chemistry sheets from chem1_database.json")
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("inputs", nargs="+", help="question/solution PDFs or folders")
    ap.add_argument("--solutions")
    ap.add_argument("--chapter", action="append", default=[])
    ap.add_argument("--keep-no-answer", action="store_true",
                    help="keep questions that have no usable answer in the JSON (default: leave them out)")
    a = ap.parse_args()
    data_path, out_dir, inputs, sol_dir = a.data, a.out, a.inputs, a.solutions
    os.makedirs(out_dir, exist_ok=True)
    data = clean_records(json.load(open(data_path, encoding="utf-8")))
    if a.chapter:
        data = [x for x in data if any(s.lower() in x["assignedChapter"].lower() for s in a.chapter)]
        print(f"{len(data)} question(s) in the selected chapter(s)")

    no_answer = 0
    if not a.keep_no_answer:                          # leave out questions without an answer key entry
        before = len(data)
        data = [x for x in data if fmt_answer(x) != "-"]
        no_answer = before - len(data)
        print(f"{no_answer} question(s) without a usable answer in the JSON left out; {len(data)} remain")

    pdfs, sol_files = {}, []          # question stem -> path ; solution PDF paths

    def add_pdf(path):
        stem = os.path.splitext(os.path.basename(path))[0]
        if SOL_RE.search(stem):
            sol_files.append(path)
        else:
            pdfs[stem] = path
    for inp in inputs:
        if "=" in inp:                                # manual override: KEY=PDF
            k, v = inp.split("=", 1); pdfs[k] = v
        elif os.path.isdir(inp):
            for p in walk_pdfs(inp, out_dir):
                add_pdf(p)
        else:
            add_pdf(inp)
    if sol_dir:
        for p in walk_pdfs(sol_dir, out_dir):
            if SOL_RE.search(os.path.splitext(os.path.basename(p))[0]):
                sol_files.append(p)
    sol_files = sorted({os.path.abspath(p) for p in sol_files})
    print(f"{len(pdfs)} question PDF(s), {len(sol_files)} solutions PDF(s) given")

    nkeys = {k: norm(k) for k in pdfs}

    def find_key(x):
        hay = (norm(x["zipName"]), norm(x["paperTitle"]))
        c = [k for k, nk in nkeys.items() if nk and (nk in hay[0] or nk in hay[1])]
        return max(c, key=lambda k: len(nkeys[k])) if c else None

    sol_paths = {}
    for p in sol_files:
        stem = norm(SOL_RE.sub("", os.path.splitext(os.path.basename(p))[0]))
        c = [k for k, nk in nkeys.items() if nk == stem] or \
            [k for k, nk in nkeys.items() if nk in stem or stem in nk]
        if not c:
            print(f"NOTE: solutions file {os.path.basename(p)} matches none of the question PDFs")
            continue
        sol_paths[min(c, key=lambda k: abs(len(nkeys[k]) - len(stem)))] = p

    removed = set()
    rm_path = os.path.join(out_dir, "removed_questions.json")
    if os.path.exists(rm_path):
        removed = {(r["pid"], r["q"]) for r in json.load(open(rm_path))}
        print(f"{len(removed)} question(s) excluded via removed_questions.json")

    skipped_bad, no_pdf, dupes = {}, 0, 0
    srcs, segs, by_ch, used, seen = {}, {}, collections.defaultdict(list), set(), set()
    for x in data:
        key = find_key(x)
        if key is None:
            no_pdf += 1
            continue
        if (x["paperTitle"], x["number"]) in removed:
            continue
        if (key, x["number"]) in seen:                # same paper listed under two titles -> same question
            dupes += 1
            continue
        seen.add((key, x["number"]))
        used.add(key)
        if key not in srcs:
            srcs[key], segs[key] = open_pdf(pdfs[key]), None
            if srcs[key] is not None:
                try:
                    segs[key] = chem_segments(srcs[key])
                except Exception as ex:
                    print(f"ERROR: cannot find the questions in {pdfs[key]}: {ex}. This file is skipped.")
            if len(srcs) % 25 == 0:
                print(f"  ... {len(srcs)} paper PDFs read", flush=True)
        if segs[key] is None:
            skipped_bad[key] = skipped_bad.get(key, 0) + 1
            continue
        by_ch[x["assignedChapter"]].append((key, x))
    print(f"{len(srcs)} paper PDFs read; building {len(by_ch)} chapter sheet(s)", flush=True)
    report = [f"NOTE: no JSON records matched PDF '{k}'" for k in sorted(set(pdfs) - used)]
    if no_answer:
        report.append(f"NOTE: {no_answer} question(s) were left out because the JSON has no answer for them "
                      "(use --keep-no-answer to include them)")
    if no_pdf:
        report.append(f"NOTE: {no_pdf} JSON record(s) have no matching question PDF and are not in the sheets")
    if dupes:
        report.append(f"NOTE: {dupes} duplicate record(s) (same paper PDF and question number under two "
                      "titles) were counted once")
    sol_open = {}

    def solution_for(key):
        if key not in sol_paths:
            return None
        if key not in sol_open:
            doc, sg = open_pdf(sol_paths[key]), None
            if doc is not None:
                try:
                    sg = chem_segments(doc)
                except Exception as ex:
                    print(f"ERROR: cannot find the solutions in {sol_paths[key]}: {ex}. Skipped.")
            sol_open[key] = (doc, sg) if sg is not None else False
        return sol_open[key] or None

    noans = []
    rank = {t: i for i, (t, _) in enumerate(TYPE_ORDER)}
    ordered = sorted(by_ch.items(), key=lambda kv: chapter_rank(kv[0]))
    for ci, (ch, items) in enumerate(ordered, 1):
        items.sort(key=lambda t: (rank.get(t[1]["qtype"], 99), t[1]["year"], t[1]["paperTitle"], t[1]["number"]))
        sh = Sheet(ch, "JEE Advanced chemistry practice sheet")
        sh.cover(len(items), 0)
        placed, rows, sec = [], [], None
        for key, x in items:
            q = x["number"]
            parts = find_parts(segs[key], q)
            if not parts:
                report.append(f"MISSING crop: {ch} | {x['paperTitle']} Q{q}")
                continue
            if x["qtype"] != sec:
                sec = x["qtype"]
                sh.begin_section(TYPE_NAME.get(sec, str(sec)))
            ans = fmt_answer(x)
            if ans == "-":
                noans.append(f"{ch} | {x['paperTitle']} | Q{q} ({x['qtype']}, JSON answer: {x.get('answer')!r})")
            n = len(rows) + 1
            e = sh.add_question(f"Q{n}", f"{x['year']} | Q{q}", srcs[key], parts,
                                meta={"pid": x["paperTitle"], "q": q, "ans": ans, "sec": TYPE_NAME.get(sec, str(sec))})
            placed.append((e, f"Q{n}", key, q, x))
            rows.append((f"Q{n}", ans))
        if any(ans != "-" for _, ans in rows):
            sh.answer_key(rows)
        sol_rows = []
        for e, label, key, q, x in placed:
            so = solution_for(key)
            if so is None:
                continue
            ss = find_parts(so[1], q)
            if ss:
                sol_rows.append((e, label, so[0], ss, CROP_X0, CROP_X1))
            else:
                report.append(f"NO SOLUTION: {ch} | {x['paperTitle']} Q{q}")
        if sol_rows:
            sh.add_solutions(sol_rows)
        out = os.path.join(out_dir, f"{ci:02d}_{slug(ch)}.pdf")
        sh.save(out)
        counts = collections.Counter(e["sec"] for e in sh.entries)
        detail = ", ".join(f"{n} {s.split(' (')[1].rstrip(')')}" for s, n in
                           sorted(counts.items(), key=lambda kv: [v for _, v in TYPE_ORDER].index(kv[0])
                                  if kv[0] in TYPE_NAME.values() else 99))
        line = f"{out}: {len(rows)} questions ({detail}), {len(sol_rows)} solutions, {len(sh.doc)} pages"
        report.append(line)
        print(f"[{ci}/{len(ordered)}] {line}", flush=True)
    for k, n in skipped_bad.items():
        report.append(f"WARNING: {n} question(s) from unreadable PDF '{k}' are missing from the sheets")
    if noans:
        report.append(f"WARNING: {len(noans)} question(s) have no usable answer in the JSON (shown as '-' in the key), e.g.:")
        report += ["    " + n for n in noans[:8]]
    print("\n".join(report))


if __name__ == "__main__":
    main()
