#!/usr/bin/env python3
"""Build chapterwise question sheets by cropping questions (vector) out of source PDFs.

Usage: build_sheets.py DATA_JSON OUT_DIR PDF_OR_FOLDER [...] [--solutions SOLUTIONS_FOLDER]
(a folder is searched including all its subfolders; question papers and ...-SOL.pdf solutions
may be mixed anywhere inside it, so --solutions is optional)

With --solutions, each sheet ends with an answer key followed by the worked solutions,
cropped from the "...-SOL.pdf" files and numbered to match the sheet.
"""
import json, re, sys, os, collections
import pymupdf as fitz

NAVY = (0x1A / 255, 0x3A / 255, 0x5C / 255)
RULE = (0xB0 / 255, 0xC4 / 255, 0xD8 / 255)
TINT = (0xEB / 255, 0xF2 / 255, 0xFA / 255)
GREY = (0.45, 0.45, 0.45)

PW, PH = 595.0, 842.0
MX, TOP, BOT = 50.0, 50.0, 800.0
LABEL_W = 46.0
CROP_X0, CROP_X1 = 98.0, 545.0          # source columns kept (drops the printed number)
SRC_TOP, SRC_BOT = 56.0, 733.0          # source content band (between header and footer rules)
GAP = 10.0
MANIFEST_NAME = "questions.json"


def question_segments(src, subject_start_page_hint=None):
    """Return {qno: [(page_index, y0, y1), ...]} for every numbered question in the PDF."""
    starts = []  # (page, y, qno)
    stops = collections.defaultdict(list)  # page -> y of section headers (stop continuation)
    for pi, page in enumerate(src):
        for w in page.get_text("words"):
            if re.fullmatch(r"\d{1,3}\.?", w[4]) and 55 < w[0] < 88 and SRC_TOP < w[1] < SRC_BOT:
                num_str = w[4].rstrip(".")
                if num_str.isdigit():
                    starts.append((pi, w[1], int(num_str)))
            if w[4] in ("Physics", "Chemistry", "Mathematics") and w[1] < 100 and w[3] - w[1] > 10:
                stops[pi].append(w[1] - 2)
    starts.sort()
    segs = {}
    for i, (pi, y, q) in enumerate(starts):
        parts = []
        y0 = y - 4
        if i + 1 < len(starts):
            npi, ny, _ = starts[i + 1]
        else:
            npi, ny = len(src) - 1, SRC_BOT
        p = pi
        while True:
            if p == npi:
                end = ny - 4
                parts.append((p, y0, end))
                break
            parts.append((p, y0, SRC_BOT))
            p += 1
            y0 = SRC_TOP
            if p == npi:
                # next question starts on this page: if a section header sits above it, stop there
                hs = [h for h in stops.get(p, []) if h < ny]
                end = (min(hs) if hs else ny - 4)
                parts.append((p, y0, end))
                break
        # trim whitespace; drop empty continuation parts
        trimmed = []
        for (pp, a, b) in parts:
            ta = tight(src[pp], a, b)
            if ta is not None:
                trimmed.append((pp, a, ta))
        segs.setdefault(q, trimmed)
    return segs


def tight(page, y0, y1):
    """Shrink bottom of [y0,y1] to the lowest ink (text/image/drawing); None if no ink."""
    clip = fitz.Rect(CROP_X0, y0, CROP_X1, y1)
    low = None
    for w in page.get_text("words"):
        r = fitz.Rect(w[:4])
        if r.intersects(clip) and r.y0 >= y0 - 1:
            low = max(low or 0, min(r.y1, y1))
    for im in page.get_image_info():
        r = fitz.Rect(im["bbox"])
        if r.intersects(clip):
            low = max(low or 0, min(r.y1, y1))
    for dr in page.get_drawings():
        r = dr["rect"]
        if r.intersects(clip) and r.width < 440:
            low = max(low or 0, min(r.y1, y1))
    return None if low is None else min(y1, low + 3)


def get_ink_bounds(page, y0, y1, x0=CROP_X0, x1=CROP_X1):
    """Return (min_x, max_x) of ink inside [x0, y0, x1, y1]."""
    clip = fitz.Rect(x0, y0, x1, y1)
    max_x = x0 + 80
    min_x = x1
    for w in page.get_text("words"):
        r = fitz.Rect(w[:4])
        if r.intersects(clip):
            max_x = max(max_x, min(r.x1, x1))
            min_x = min(min_x, max(r.x0, x0))
    for dr in page.get_drawings():
        r = dr["rect"]
        if r.intersects(clip) and r.width < 440:
            max_x = max(max_x, min(r.x1, x1))
            min_x = min(min_x, max(r.x0, x0))
    for im in page.get_image_info():
        r = fitz.Rect(im["bbox"])
        if r.intersects(clip):
            max_x = max(max_x, min(r.x1, x1))
            min_x = min(min_x, max(r.x0, x0))
    return min_x, max_x


def detect_vertical_big_options(src, parts, x0=CROP_X0, x1=CROP_X1):
    """Detect if question has 1-column vertically-stacked big options (A)-(D).
    Returns (stem_parts, opt_slices) if so, else None.
    """
    all_cand_opts = []
    for pi, y0, y1 in parts:
        page = src[pi]
        for w in page.get_text("words"):
            if (y0 - 2 <= w[1] <= y1 + 2) and (x0 - 5 <= w[0] <= x1):
                m = re.fullmatch(r"\(([A-D])\)", w[4])
                if m:
                    all_cand_opts.append((pi, m.group(1), w[0], w[1], w[2], w[3]))
    
    by_letter = {}
    for item in all_cand_opts:
        by_letter.setdefault(item[1], []).append(item)
    if not all(k in by_letter for k in ("A", "B", "C", "D")):
        return None
    
    # Find strictly ordered combo (A, B, C, D)
    best_combo = None
    for a in by_letter["A"]:
        for b in by_letter["B"]:
            if (b[0], b[3]) <= (a[0], a[3] + 5): continue
            for c in by_letter["C"]:
                if (c[0], c[3]) <= (b[0], b[3] + 5): continue
                for d in by_letter["D"]:
                    if (d[0], d[3]) <= (c[0], c[3] + 5): continue
                    xs = [a[2], b[2], c[2], d[2]]
                    # 1-column layout: all option labels aligned near left edge
                    if max(xs) - min(xs) < 30 and max(xs) < 220:
                        best_combo = (a, b, c, d)
                        break
                if best_combo: break
            if best_combo: break
        if best_combo: break
        
    if not best_combo:
        return None
    
    a, b, c, d = best_combo
    opts_raw = [("A", a), ("B", b), ("C", c), ("D", d)]
    opt_slices = []
    for idx, (letter, item) in enumerate(opts_raw):
        pi = item[0]
        y_top = item[3] - 1
        if idx + 1 < len(opts_raw):
            next_item = opts_raw[idx + 1][1]
            if next_item[0] == pi:
                y_bot = next_item[3] - 1
            else:
                part_pi = next((p for p in parts if p[0] == pi), None)
                y_bot = part_pi[2] if part_pi else item[5] + 50
        else:
            part_pi = next((p for p in reversed(parts) if p[0] == pi), None)
            y_bot = part_pi[2] if part_pi else item[5] + 50
        
        h = max(0, y_bot - y_top)
        min_x, max_x = get_ink_bounds(src[pi], y_top, y_bot, x0, x1)
        opt_slices.append({
            "letter": letter,
            "pi": pi,
            "y0": y_top,
            "y1": y_bot,
            "h": h,
            "min_x": min_x,
            "max_x": max_x,
            "w": max(80, max_x - x0 + 10)
        })
    
    max_h = max(s["h"] for s in opt_slices)
    tot_h = sum(s["h"] for s in opt_slices)
    max_w = max(s["w"] for s in opt_slices)
    
    # Must be "big" options (structures/tall), and option width must fit nicely into half-column (w <= 270)
    if (max_h > 35 or tot_h > 120) and max_w <= 270:
        stem_parts = []
        for p in parts:
            if p[0] < a[0]:
                stem_parts.append(p)
            elif p[0] == a[0]:
                if p[1] < a[3] - 1:
                    stem_parts.append((p[0], p[1], min(p[2], a[3] - 1)))
        return stem_parts, opt_slices
    
    return None


def parse_answers(path):
    """{qno: 'B'} read from an Answers/Hints/Solutions PDF: the token(s) after 'N.' before 'Sol.'"""
    out = {}
    doc = open_pdf(path)
    if doc is None:
        return out
    for page in doc:
        ws = page.get_text("words")
        for w in ws:
            if re.fullmatch(r"\d{1,3}\.", w[4]) and 68 < w[0] < 78 and SRC_TOP < w[1] < SRC_BOT:
                line = sorted((x for x in ws if abs(x[1] - w[1]) < 4 and x[0] > w[2]), key=lambda x: x[0])
                toks = []
                for x in line:
                    if x[4].startswith("Sol"):
                        break
                    toks.append(x[4])
                if toks:
                    out.setdefault(int(w[4][:-1]), " ".join(toks))
    return out


class Sheet:
    def __init__(self, title, subtitle):
        self.doc = fitz.open()
        self.title, self.subtitle = title, subtitle
        self.page = None
        self.y = 0
        self.entries = []   # one dict per placed question (see add_question)

    def new_page(self):
        pg = self.doc.new_page(width=PW, height=PH)
        self.page = pg
        n = len(self.doc)
        pg.insert_text((PW / 2 - 4, PH - 24), str(n), fontsize=8.5, fontname="helv", color=GREY)
        self.y = TOP
        return pg

    def cover(self, nq, papers):
        pg = self.new_page()
        pg.insert_text((MX, TOP + 12), self.title, fontsize=24, fontname="hebo", color=(0, 0, 0))
        self.y = TOP + 40

    def section(self, text, need=60):
        if self.page is None or self.y + need > BOT:
            self.new_page()
        self.page.draw_line((MX, self.y), (PW - MX, self.y), color=NAVY, width=1.6)
        self.page.draw_line((MX, self.y + 3), (PW - MX, self.y + 3), color=NAVY, width=0.5)
        self.page.insert_text((MX, self.y + 20), text, fontsize=12, fontname="hebo", color=NAVY)
        self.y += 32

    def begin_section(self, text):
        """Section heading inside the question list (kept together with the question after it)."""
        self.section(text, need=200)

    def _place(self, label, tag, src, parts, x0=CROP_X0, x1=CROP_X1):
        """Draw the clips of `src` (columns x0..x1) under a margin label; return where they landed."""
        CW = x1 - x0
        x_left = MX + LABEL_W
        col_gap = 14.0
        col_w = (CW - col_gap) / 2

        # 1. Check for 1-column vertical big options -> 2x2 grid reflow + scaling
        opt_info = detect_vertical_big_options(src, parts, x0, x1)
        if opt_info:
            stem_parts, opt_slices = opt_info
            stem_heights = [b - a for (_, a, b) in stem_parts]
            stem_tot = sum(stem_heights)
            stem_scale = max(0.75, min(1.0, 200.0 / stem_tot)) if stem_tot > 200 else 1.0
            
            hA, hB, hC, hD = [s["h"] for s in opt_slices]
            max_opt_h = max(hA, hB, hC, hD)
            opt_scale = max(0.68, min(0.80, 85.0 / max_opt_h))
            
            row1_h = max(hA, hB) * opt_scale
            row2_h = max(hC, hD) * opt_scale
            
            tot_needed = (stem_tot * stem_scale) + row1_h + row2_h + 16.0
            if self.page is None or self.y + min(tot_needed, 120) > BOT:
                self.new_page()
            
            lab_pno = len(self.doc) - 1
            lab_y = self.y
            segs = []
            start_y = self.y
            
            # Place stem
            for (pi, a, b), sh in zip(stem_parts, stem_heights):
                scaled_h = sh * stem_scale
                if self.y + scaled_h > BOT:
                    self.new_page()
                rect = fitz.Rect(x_left, self.y, x_left + CW * stem_scale, self.y + scaled_h)
                self.page.show_pdf_page(rect, src, pi, clip=fitz.Rect(x0, a, x1, b))
                self.y += scaled_h
            if stem_parts:
                self.y += 6.0
                
            # Place Row 1: Option A and Option B
            if self.y + row1_h > BOT:
                self.new_page()
            sA = opt_slices[0]
            wA = min(col_w, sA["w"] * opt_scale)
            rect_A = fitz.Rect(x_left, self.y, x_left + wA, self.y + sA["h"] * opt_scale)
            self.page.show_pdf_page(rect_A, src, sA["pi"], clip=fitz.Rect(x0, sA["y0"], x0 + sA["w"], sA["y1"]))

            sB = opt_slices[1]
            wB = min(col_w, sB["w"] * opt_scale)
            rect_B = fitz.Rect(x_left + col_w + col_gap, self.y, x_left + col_w + col_gap + wB, self.y + sB["h"] * opt_scale)
            self.page.show_pdf_page(rect_B, src, sB["pi"], clip=fitz.Rect(x0, sB["y0"], x0 + sB["w"], sB["y1"]))
            self.y += row1_h + 6.0
            
            # Place Row 2: Option C and Option D
            if self.y + row2_h > BOT:
                self.new_page()
            sC = opt_slices[2]
            wC = min(col_w, sC["w"] * opt_scale)
            rect_C = fitz.Rect(x_left, self.y, x_left + wC, self.y + sC["h"] * opt_scale)
            self.page.show_pdf_page(rect_C, src, sC["pi"], clip=fitz.Rect(x0, sC["y0"], x0 + sC["w"], sC["y1"]))

            sD = opt_slices[3]
            wD = min(col_w, sD["w"] * opt_scale)
            rect_D = fitz.Rect(x_left + col_w + col_gap, self.y, x_left + col_w + col_gap + wD, self.y + sD["h"] * opt_scale)
            self.page.show_pdf_page(rect_D, src, sD["pi"], clip=fitz.Rect(x0, sD["y0"], x0 + sD["w"], sD["y1"]))
            self.y += row2_h + GAP
            
            segs.append([len(self.doc) - 1, round(start_y, 2), round(self.y, 2)])
            self.doc[lab_pno].insert_text((MX, lab_y + 11), label, fontsize=10.5, fontname="hebo", color=NAVY)
            self.doc[lab_pno].insert_text((MX, lab_y + 21), tag, fontsize=5.5, fontname="helv", color=GREY)
            return segs

        # 2. Otherwise: Standard placement with auto-scale for oversized questions
        heights = [b - a for (_, a, b) in parts]
        tot_h = sum(heights)
        q_scale = max(0.72, min(1.0, 210.0 / tot_h)) if tot_h > 210.0 else 1.0
        
        scaled_heights = [h * q_scale for h in heights]
        total = sum(scaled_heights) + GAP
        if self.page is None or self.y + min(total, 120) > BOT:
            self.new_page()
            
        lab_pno = len(self.doc) - 1
        lab_y = self.y
        first = True
        segs = []
        for (pi, a, b), h in zip(parts, scaled_heights):
            if self.y + h > BOT:
                self.new_page()
                if first:
                    lab_pno = len(self.doc) - 1
                    lab_y = self.y
            if first:
                lab_pno = len(self.doc) - 1
                lab_y = self.y
                first = False
            rect = fitz.Rect(x_left, self.y, x_left + CW * q_scale, self.y + h)
            self.page.show_pdf_page(rect, src, pi, clip=fitz.Rect(x0, a, x1, b))
            segs.append([len(self.doc) - 1, round(self.y, 2), round(self.y + h, 2)])
            self.y += h
            
        self.doc[lab_pno].insert_text((MX, lab_y + 11), label, fontsize=10.5, fontname="hebo", color=NAVY)
        self.doc[lab_pno].insert_text((MX, lab_y + 21), tag, fontsize=5.5, fontname="helv", color=GREY)
        self.y += GAP
        return segs

    def add_question(self, label, tag, src, parts, x0=CROP_X0, x1=CROP_X1, meta=None):
        """Place a question and record where it landed, so the finished sheet can be edited
        later (remove_questions.py) without the source papers."""
        segs = self._place(label, tag, src, parts, x0, x1)
        self.entries.append({**(meta or {}), "tag": tag, "segs": segs})
        return self.entries[-1]

    def add_solutions(self, rows):
        """Solutions section on fresh pages. rows: (entry, label, src, parts, x0, x1); the
        landing spot is stored on the entry as entry["sol"]."""
        self.new_page()
        self.section("Solutions")
        for entry, label, src, parts, x0, x1 in rows:
            entry["sol"] = self._place(label, entry["tag"], src, parts, x0, x1)

    def save(self, path):
        manifest = {"version": 1, "title": self.title, "subtitle": self.subtitle,
                    "x0": MX + LABEL_W, "x1": MX + LABEL_W + (CROP_X1 - CROP_X0),
                    "entries": self.entries}
        self.doc.embfile_add(MANIFEST_NAME, json.dumps(manifest).encode("utf-8"),
                             desc="question layout (used by remove_questions.py)")
        self.doc.save(path, deflate=True, garbage=3)

    def answer_key(self, rows):
        """rows: list of (label, ans). Black-outlined grid, 5 Q/Ans pairs per row; header light
        grey, body rows alternating white / light grey."""
        self.new_page()
        self.section("Answer Key")
        cols = 5
        cw = (PW - 2 * MX) / (cols * 2)
        rh = 20
        BLACK, HEAD, ALT = (0, 0, 0), (0.80, 0.80, 0.80), (0.93, 0.93, 0.93)

        def cell(x, fill, text="", bold=False):
            self.page.draw_rect(fitz.Rect(x, self.y, x + cw, self.y + rh), color=BLACK, fill=fill, width=0.6)
            if text:
                fn, fs = ("hebo" if bold else "helv"), 9.0
                while fs > 5 and fitz.get_text_length(text, fontname=fn, fontsize=fs) > cw - 12:
                    fs -= 0.5
                self.page.insert_text((x + 8, self.y + 14), text, fontsize=fs, fontname=fn, color=BLACK)

        def header():
            for c in range(cols):
                x = MX + c * 2 * cw
                cell(x, HEAD, "Q", True)
                cell(x + cw, HEAD, "Ans", True)
            self.y += rh

        header()
        for i in range(0, len(rows), cols):
            if self.y + rh > BOT:
                self.new_page(); header()
            fill = (1, 1, 1) if (i // cols) % 2 == 0 else ALT
            chunk = rows[i:i + cols]
            for c in range(cols):
                x = MX + c * 2 * cw
                lab, ans = chunk[c] if c < len(chunk) else ("", "")
                cell(x, fill, lab, True)
                cell(x + cw, fill, ans)
            self.y += rh


SOL_RE = re.compile(r"[-_ ]*SOL(UTION)?S?$", re.I)   # "...-SOL" marks a solutions PDF


REQUIRED = ("zipName", "paperTitle", "chapterIndex", "chapterTitle", "year", "questionNumber")


def clean_records(raw):
    """Accept the JSON as a list (or a dict holding the list); repair what can be repaired and
    skip, with a report, records that lack a field the sheets need."""
    if isinstance(raw, dict):
        lists = [v for v in raw.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if not lists:
            sys.exit("Error: the JSON is an object with no list of question records inside.")
        raw = max(lists, key=len)
    good, missing, example = [], collections.Counter(), None
    for x in raw:
        if not isinstance(x, dict):
            missing["(not an object)"] += 1
            continue
        if "questionNumber" not in x:            # recover it from "...zip#26#Phy Sec 2__--__26__--__1.png"
            m = re.search(r"#(\d+)#", str(x.get("questionKey", "")))
            if m:
                x["questionNumber"] = int(m.group(1))
        try:
            x["questionNumber"] = int(x["questionNumber"])
        except (KeyError, TypeError, ValueError):
            pass
        miss = [k for k in REQUIRED if k not in x or x[k] in (None, "")]
        if miss:
            for k in miss:
                missing[k] += 1
            example = example or x
            continue
        good.append(x)
    if missing:
        print(f"WARNING: skipped {len(raw) - len(good)} of {len(raw)} JSON records that lack required fields: "
              + ", ".join(f"{k} ({n})" for k, n in missing.items()))
        if example:
            print("  example of a skipped record's fields:", sorted(example))
    return good


fitz.TOOLS.mupdf_display_errors(False)   # MuPDF's own repair chatter; real failures are reported below

WATERMARK_WORDS = (
    "fiitjee", "@fiitjee", "kalu sarai", "sarvapriya vihar", "www.fiitjee.com",
    "total selections", "in top 100", "in top 200", "in top 500",
    "classroom / integrated", "for more join"
)

def remove_watermarks(doc):
    """Remove FIITJEE watermarks, footer text, telegram promotions, and diagonal grey pattern watermarks."""
    if doc is None:
        return
    for page in doc:
        has_redaction = False
        try:
            for b in page.get_text("blocks"):
                text_lower = b[4].lower()
                if any(w in text_lower for w in WATERMARK_WORDS):
                    page.add_redact_annot(fitz.Rect(b[:4]), fill=False)
                    has_redaction = True
            for annot in page.annots():
                info = annot.info or {}
                content = (str(info.get("content", "")) + " " + str(info.get("title", ""))).lower()
                if any(w in content for w in WATERMARK_WORDS):
                    page.delete_annot(annot)
            if has_redaction:
                page.apply_redactions()
        except Exception:
            pass

        # Clean diagonal grey /Pattern watermark blocks and Telegram banner streams
        try:
            for xref in page.get_contents():
                stream = doc.xref_stream(xref).decode('latin1', errors='ignore')
                if any(w in stream.lower() for w in ("@fiitjee", "for more join")):
                    doc.update_stream(xref, b"")
                    continue
                if "/Pattern cs" in stream and "/Pattern" in stream:
                    # Clean all diagonal FIITJEE vector watermark pattern fills safely by disabling path fill ('n' = no-op path end)
                    cleaned_stream = re.sub(r'/Pattern\s+cs\s+/Pattern[0-9A-Za-z_]+\s+scn[\s\S]*?f\*', 'n', stream)
                    if cleaned_stream != stream:
                        doc.update_stream(xref, cleaned_stream.encode('latin1'))
        except Exception:
            pass


def open_pdf(path):
    """Open a PDF; a damaged one ("broken xref table" etc.) is repaired if possible, otherwise
    reported by name and skipped (returns None) so the rest of the run still goes through."""
    try:
        doc = fitz.open(path)
        if doc.is_repaired:
            print(f"NOTE: {os.path.basename(path)} is damaged and was repaired while opening; "
                  f"check the questions taken from it.")
        if len(doc) == 0:
            raise ValueError("no pages")
        remove_watermarks(doc)
        return doc
    except Exception as ex:
        print(f"ERROR: cannot read {path}: {ex}. This file is skipped; re-download or re-save it as PDF.")
        return None


def walk_pdfs(folder, skip=None):
    """Every .pdf under `folder`, including all subfolders (the output folder is skipped)."""
    skip = os.path.abspath(skip) if skip else None
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not (skip and os.path.abspath(os.path.join(root, d)) == skip))
        for f in sorted(files):
            if f.lower().endswith(".pdf"):
                yield os.path.join(root, f)


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def main():
    args = sys.argv[1:]
    answers = {}
    if "--answers" in args:
        i = args.index("--answers")
        answers = json.load(open(args[i + 1]))
        del args[i:i + 2]
    sol_dir = None
    if "--solutions" in args:
        i = args.index("--solutions")
        sol_dir = args[i + 1]
        del args[i:i + 2]
    data_path, out_dir, *inputs = args
    os.makedirs(out_dir, exist_ok=True)
    data = clean_records(json.load(open(data_path)))
    pdfs = {}        # question-paper stem -> path
    sol_files = []   # solutions PDFs (name ends in -SOL), from any folder given
    def add_pdf(path):
        stem = os.path.splitext(os.path.basename(path))[0]
        if SOL_RE.search(stem):
            sol_files.append(path)
        else:
            pdfs[stem] = path
    for inp in inputs:
        if "=" in inp:                      # manual override: KEY=PDF
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
    sol_files = sorted({os.path.abspath(p) for p in sol_files})   # same file reached twice counts once
    print(f"{len(pdfs)} question PDF(s), {len(sol_files)} solutions PDF(s) given")
    removed = set()   # (paperTitle, qno) taken out earlier with remove_questions.py
    rm_path = os.path.join(out_dir, "removed_questions.json")
    if os.path.exists(rm_path):
        removed = {(r["pid"], r["q"]) for r in json.load(open(rm_path))}
        print(f"{len(removed)} question(s) excluded via removed_questions.json")
    skipped_bad = {}   # unreadable question PDFs -> number of JSON records left out
    srcs, segs = {}, {}
    by_ch = collections.defaultdict(list)
    for x in data:
        cands = [k for k in pdfs if k in x["zipName"] or k in x["paperTitle"]]
        key = max(cands, key=len) if cands else None
        if key is None or (x["paperTitle"], x["questionNumber"]) in removed:
            continue
        if key not in srcs:
            srcs[key], segs[key] = open_pdf(pdfs[key]), None
            if srcs[key] is not None:
                try:
                    segs[key] = question_segments(srcs[key])
                except Exception as ex:
                    print(f"ERROR: cannot find the questions in {pdfs[key]}: {ex}. This file is skipped.")
        if segs[key] is None:
            skipped_bad[key] = skipped_bad.get(key, 0) + 1
            continue
        by_ch[(x["chapterIndex"], x["chapterTitle"])].append((key, x))
    sol_ans = {}   # question-pdf stem -> {qno: answer}
    sol_paths = {}  # question-pdf stem -> solutions PDF path
    sol_open = {}   # stem -> (opened PDF, {qno: segments})
    for path in sol_files:
        stem = SOL_RE.sub("", os.path.splitext(os.path.basename(path))[0])
        if stem in pdfs:
            tgt = stem
        else:
            near = [k for k in pdfs if k in stem or stem in k]
            tgt = min(near, key=lambda k: abs(len(k) - len(stem))) if near else None
        if tgt is None:
            print(f"NOTE: solutions file {os.path.basename(path)} matches none of the question PDFs")
            continue
        sol_paths[tgt] = path
        sol_ans[tgt] = parse_answers(path)
    def solution_for(key, q):
        if key not in sol_paths:
            return None
        if key not in sol_open:
            doc, sg = open_pdf(sol_paths[key]), None
            if doc is not None:
                try:
                    sg = question_segments(doc)
                except Exception as ex:
                    print(f"ERROR: cannot find the solutions in {sol_paths[key]}: {ex}. Skipped.")
            sol_open[key] = (doc, sg) if sg is not None else False
        return sol_open[key] or None
    report = []
    unmatched = sorted({k for k in pdfs if not any(k in x["zipName"] or k in x["paperTitle"] for x in data)})
    for k in unmatched:
        report.append(f"NOTE: no JSON records matched PDF '{k}'")
    for (ci, ct), items in sorted(by_ch.items()):
        items.sort(key=lambda t: (t[1]["year"], t[1]["paperTitle"], t[1]["questionNumber"]))
        papers = sorted({x["paperTitle"] for _, x in items})
        sh = Sheet(ct, "JEE Main practice sheet | questions cropped from the source papers")
        sh.cover(len(items), len(papers))
        sh.new_page() if sh.y > 600 else None
        key_rows, placed = [], []
        for key, x in items:
            q = x["questionNumber"]
            parts = segs[key].get(q)
            if not parts:
                report.append(f"MISSING crop: {ct} {x['paperTitle']} Q{q}")
                continue
            a = sol_ans.get(key, {}).get(q)
            if a is None:
                a = (answers.get(x["paperTitle"], {}).get(str(q)) or {}).get("ans")
            if a is None:
                report.append(f"NO ANSWER: {ct} {x['paperTitle']} Q{q}")
            n = len(key_rows) + 1
            e = sh.add_question(f"Q{n}", f"{x['year']} | Q{q}", srcs[key], parts,
                                meta={"pid": x["paperTitle"], "q": q, "ans": a})
            placed.append((e, f"Q{n}", key, q, x))
            key_rows.append((f"Q{n}", a or "-"))
        if any(a != "-" for _, a in key_rows):
            sh.answer_key(key_rows)
        sol_rows = []
        for e, label, key, q, x in placed:
            so = solution_for(key, q)
            if so is None:
                continue
            ss = so[1].get(q)
            if ss:
                sol_rows.append((e, label, so[0], ss, CROP_X0, CROP_X1))
            else:
                report.append(f"NO SOLUTION: {ct} {x['paperTitle']} Q{q}")
        if sol_rows:
            sh.add_solutions(sol_rows)
        out = os.path.join(out_dir, f"{ci:02d}_{slug(ct)}.pdf")
        sh.save(out)
        report.append(f"{out}: {len(key_rows)} questions, {len(sh.doc)} pages")
    for k, n in skipped_bad.items():
        report.append(f"WARNING: {n} question(s) from unreadable PDF '{k}' are missing from the sheets")
    print("\n".join(report))


if __name__ == "__main__":
    main()
