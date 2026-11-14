#!/usr/bin/env python3
"""server.py - Full-stack HTTP Server for AITS Practice Portal with Vector Test Sheet Generator.

Serves static assets from aitsver2-main and provides the /api/build-test endpoint
which crops native vector questions and solutions directly from source PDFs
using PyMuPDF with zero rasterization, crisp selectable text, and clean watermark removal.
"""

import http.server
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.parse

from build_vector_test import build_test_pdf, QuestionManager
from build_sheets import CROP_X0, CROP_X1, remove_watermarks, open_pdf
import pymupdf as fitz

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.join(ROOT_DIR, "aitsver2-main")
if not os.path.isdir(SITE_DIR):
    SITE_DIR = ROOT_DIR
GENERATED_DIR = os.path.join(SITE_DIR, "generated_tests")
os.makedirs(GENERATED_DIR, exist_ok=True)

# Pre-load question manager in background thread on startup
threading.Thread(target=QuestionManager.get_instance, daemon=True).start()

class AitsRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SITE_DIR, **kwargs)

    def translate_path(self, path):
        orig = super().translate_path(path)
        if not os.path.exists(orig):
            rel = os.path.relpath(orig, self.directory)
            pub_cand = os.path.join(self.directory, "public", rel)
            if os.path.exists(pub_cand):
                return pub_cand
        return orig

    def end_headers(self):
        # Enable CORS for local testing
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/health", "/api/health"):
            self.send_json({
                "ok": True,
                "service": "AITS Practice Portal Server",
                "status": "online",
                "timestamp": int(time.time())
            })
            return
        elif path == "/api/status":
            self.handle_status()
            return
        elif path == "/api/chapters":
            self.handle_chapters()
            return
        elif path.startswith("/api/question-svg/"):
            qid = path.split("/api/question-svg/")[1].strip()
            self.handle_question_svg(qid)
            return

        # Serve static files from SITE_DIR (and fallback to public/ via translate_path)
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/build-test" or path == "/api/build-sheet":
            self.handle_build_test()
            return

        self.send_error(404, "Endpoint not found")

    def handle_status(self):
        qm = QuestionManager.get_instance()
        payload = {
            "ok": True,
            "totalQuestions": len(qm.questions),
            "questionPdfs": len(qm.pdfs),
            "solutionPdfs": len(qm.sol_files)
        }
        self.send_json(payload)

    def handle_chapters(self):
        qm = QuestionManager.get_instance()
        by_sub = {}
        for q in qm.questions:
            sub = q.get("subject") or "Physics"
            ch = q.get("chapter") or "General"
            by_sub.setdefault(sub, set()).add(ch)
        
        result = {sub: sorted(list(chs)) for sub, chs in by_sub.items()}
        self.send_json({"ok": True, "subjects": result})

    def handle_question_svg(self, qid):
        if qid.startswith("mschouhan_"):
            try:
                import sheet_engine
                db_path = os.path.join(ROOT_DIR, "mschouhan_database.json")
                with open(db_path, "r", encoding="utf-8") as f:
                    ms_db = json.load(f)
                ms_q = next((q for q in ms_db["questions"] if q["id"] == qid), None)
                if not ms_q:
                    self.send_error(404, "MS Chouhan question not found")
                    return
                pdf_path = os.path.join(ROOT_DIR, ms_q["pdfName"].replace("/", os.sep))
                doc = fitz.open(pdf_path)
                sheet_engine.redact_printed_numerals(doc)
                parts = ms_q["segments"]
                w = 445.0 - 15.0
                tot_h = sum(p[4] - p[2] for p in parts)
                tdoc = fitz.open()
                tp = tdoc.new_page(width=w, height=tot_h)
                cur_y = 0.0
                for pno, x0, y0, x1, y1 in parts:
                    h = y1 - y0
                    tp.show_pdf_page(fitz.Rect(0, cur_y, w, cur_y + h), doc, pno - 1, clip=fitz.Rect(15.0, y0, 445.0, y1))
                    cur_y += h
                svg = tp.get_svg_image(text_as_path=1)
                tdoc.close()
                doc.close()
                insert_pos = svg.find(">") + 1
                if insert_pos > 0:
                    svg = svg[:insert_pos] + '<rect width="100%" height="100%" fill="#ffffff"/>' + svg[insert_pos:]
                body = svg.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
                return
            except Exception as e:
                self.send_error(500, f"Error rendering MS Chouhan SVG: {e}")
                return

        if qid.startswith("allenjee_"):
            try:
                import build_allenjee_sheet as baj
                with open(baj.DB_PATH, "r", encoding="utf-8") as f:
                    allen_db = json.load(f)
                allen_q = next((q for q in allen_db["questions"] if q["id"] == qid), None)
                if not allen_q:
                    self.send_error(404, "Allen JEE question not found")
                    return
                pdf_path = os.path.join(ROOT_DIR, allen_q["pdfName"].replace("/", os.sep))
                doc = fitz.open(pdf_path)
                baj.clean_source_doc(doc)
                seg = allen_q["segments"][0]
                pno, x0, y0, x1, y1 = seg
                clip_r = fitz.Rect(baj.COL_X0, max(y0, baj.HEADER_Y_CUT), baj.COL_X1, min(y1, baj.FOOTER_Y_CUT))
                tdoc = fitz.open()
                tdoc.insert_pdf(doc, from_page=pno - 1, to_page=pno - 1)
                tp = tdoc[0]
                tp.set_cropbox(clip_r)
                svg = tp.get_svg_image(text_as_path=1)
                tdoc.close()
                doc.close()
                insert_pos = svg.find(">") + 1
                if insert_pos > 0:
                    svg = svg[:insert_pos] + '<rect width="100%" height="100%" fill="#ffffff"/>' + svg[insert_pos:]
                body = svg.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
                return
            except Exception as e:
                self.send_error(500, f"Error rendering Allen JEE SVG: {e}")
                return

        if qid.startswith("allenchem_"):
            try:
                import build_allenchem_sheet as bas
                with open(bas.DB_PATH, "r", encoding="utf-8") as f:
                    allen_db = json.load(f)
                allen_q = next((q for q in allen_db["questions"] if q["id"] == qid), None)
                if not allen_q:
                    self.send_error(404, "Allen question not found")
                    return
                pdf_path = os.path.join(bas.CHAPTER_DIR, allen_q["pdfName"])
                doc = fitz.open(pdf_path)
                bas.clean_source_document(doc)
                seg = allen_q["segments"][0]
                pno, x0, y0, x1, y1 = seg
                clip_x0 = 48.5 if x0 < 150 else 301.5
                clip_x1 = 295.0 if x0 < 150 else 548.0
                clip_r = fitz.Rect(clip_x0, max(y0, 70.0), clip_x1, min(y1, 770.0))
                temp_doc = fitz.open()
                temp_page = temp_doc.new_page(width=clip_r.width, height=clip_r.height)
                temp_page.show_pdf_page(fitz.Rect(0, 0, clip_r.width, clip_r.height), doc, pno - 1, clip=clip_r)
                svg = temp_page.get_svg_image(text_as_path=1)
                temp_doc.close()
                doc.close()
                body = svg.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(body)
                return
            except Exception as e:
                self.send_error(500, f"Error rendering Allen SVG: {e}")
                return

        import build_vector_test as bvt
        qm = QuestionManager.get_instance()
        q = qm.q_by_id.get(qid)
        if not q:
            self.send_error(404, "Question not found")
            return
        key = qm.find_pdf_key(q)
        if not key or key not in qm.pdfs:
            self.send_error(404, "PDF paper not found for question")
            return
        q_cache = qm.segments_cache.get("questions", {}).get(key, {})
        by_sub = q_cache.get("by_sub", {})
        by_no = q_cache.get("by_no", {})
        qno = q.get("questionNumber") or q.get("number") or 1
        sub_name = str(q.get("subject", "")).strip().lower()
        parts = bvt.find_question_parts(by_sub, by_no, sub_name, qno)
        if not parts:
            self.send_error(404, "Crop parts not found for question")
            return
        doc = open_pdf(qm.pdfs[key])
        if not doc:
            self.send_error(500, "Could not open source PDF")
            return
        try:
            remove_watermarks(doc)
            w = CROP_X1 - CROP_X0
            tot_h = sum(b - a for _, a, b in parts)
            temp_doc = fitz.open()
            temp_page = temp_doc.new_page(width=w, height=tot_h)
            cur_y = 0
            for pno, a, b in parts:
                h = b - a
                clip_r = fitz.Rect(CROP_X0, a, CROP_X1, b)
                target_r = fitz.Rect(0, cur_y, w, cur_y + h)
                temp_page.show_pdf_page(target_r, doc, pno, clip=clip_r)
                cur_y += h
            # Use text_as_path=1 to preserve the authentic original exam typography,
            # exact font shapes, equations, and serif glyphs from the paper.
            svg = temp_page.get_svg_image(text_as_path=1)
            temp_doc.close()

            # Ensure crisp opaque white background card so text is never transparent against dark modals/surfaces
            insert_pos = svg.find(">") + 1
            if insert_pos > 0:
                bg_rect = f'<rect width="{w}" height="{tot_h}" fill="#ffffff"/>'
                svg = svg[:insert_pos] + bg_rect + svg[insert_pos:]
            
            body = svg.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_error(500, f"Error rendering SVG: {e}")
        finally:
            doc.close()

    def handle_build_test(self):
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            self.send_json({"ok": False, "error": "Empty request body"}, 400)
            return

        body = self.rfile.read(content_len).decode("utf-8")
        try:
            req = json.loads(body)
        except Exception as e:
            self.send_json({"ok": False, "error": f"Invalid JSON: {e}"}, 400)
            return

        chapters = req.get("chapters", [])
        subjects = req.get("subjects", [])
        pattern = req.get("pattern", "adv")
        paper = req.get("paper", "all")
        subjects = req.get("subjects", [])
        num_subjs = len(subjects) if subjects else 3
        default_count = (num_subjs * 25) if pattern == "main" else 30
        count = int(req.get("count") or default_count)
        title = req.get("title", "JEE ADVANCED PRACTICE TEST")
        subtitle = req.get("subtitle", "Chapter-wise Practice Sheet | Questions cropped from source papers")
        include_sol = bool(req.get("includeSolutions", True))
        remove_wm = bool(req.get("removeWatermark", True))
        selected_qids = req.get("qids", None)

        ts = int(time.time() * 1000)
        out_filename = f"test_{ts}.pdf"
        out_pdf = os.path.join(GENERATED_DIR, out_filename)

        # Check if Multi-Source or MS Chouhan is requested
        has_ms = bool(selected_qids and any(str(qid).startswith("mschouhan_") for qid in selected_qids))
        has_allen_jee = bool(selected_qids and any(str(qid).startswith("allenjee_") for qid in selected_qids))
        has_allen_chem = bool(selected_qids and any(str(qid).startswith("allenchem_") for qid in selected_qids))
        has_fiitjee = bool(selected_qids and any(not str(qid).startswith("allen") and not str(qid).startswith("mschouhan") for qid in selected_qids))
        sources_count = sum([has_ms, has_allen_jee, has_allen_chem, has_fiitjee])
        is_mixed = sources_count > 1

        if has_ms or is_mixed or (paper == "mschouhan"):
            try:
                import build_unified_sheet as bus
                if not selected_qids:
                    # Load default from mschouhan_database.json
                    with open(os.path.join(ROOT_DIR, "mschouhan_database.json"), "r", encoding="utf-8") as f:
                        ms_db = json.load(f)
                    selected_qids = [q["id"] for q in ms_db.get("questions", []) if q.get("selected")][:count]

                res = bus.generate_multi_source_test(
                    selected_qids=selected_qids,
                    out_pdf_path=out_pdf,
                    title=title,
                    subtitle=subtitle,
                    cand_name=req.get("candName"),
                    time_limit=req.get("timeLimit", 90)
                )
                pdf_url = f"/generated_tests/{out_filename}"
                latest_url = "/generated_tests/latest_test.pdf"
                latest_path = os.path.join(GENERATED_DIR, "latest_test.pdf")
                try:
                    import shutil
                    shutil.copyfile(out_pdf, latest_path)
                except Exception:
                    pass

                # Separate Student Copy (questions only) and Answer Key (key only)
                student_filename = f"student_{out_filename}"
                student_path = os.path.join(GENERATED_DIR, student_filename)
                key_filename = f"key_{out_filename}"
                key_path = os.path.join(GENERATED_DIR, key_filename)

                try:
                    full_doc = fitz.open(out_pdf)
                    if len(full_doc) > 1:
                        std_doc = fitz.open(out_pdf)
                        std_doc.delete_page(len(std_doc) - 1)
                        std_doc.save(student_path)
                        std_doc.close()

                        k_doc = fitz.open(out_pdf)
                        k_doc.select([len(k_doc) - 1])
                        k_doc.save(key_path)
                        k_doc.close()
                    else:
                        import shutil
                        shutil.copyfile(out_pdf, student_path)
                        shutil.copyfile(out_pdf, key_path)
                    full_doc.close()
                except Exception as split_err:
                    print("Error splitting student copy and key:", split_err)

                self.send_json({
                    "ok": True,
                    "pdfUrl": pdf_url,
                    "studentPdfUrl": f"/generated_tests/{student_filename}",
                    "keyPdfUrl": f"/generated_tests/{key_filename}",
                    "latestUrl": latest_url,
                    "filename": out_filename,
                    "totalQuestions": res["total_questions"],
                    "totalPages": res["total_pages"],
                    "answerCount": res["total_questions"]
                })
                return
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"ok": False, "error": f"Multi-source test generation failed: {e}"}, 500)
                return

        # Check if Allen JEE or Allen Chemistry is requested
        is_allen_jee = False
        if selected_qids and any(str(qid).startswith("allenjee_") for qid in selected_qids):
            is_allen_jee = True
        elif paper in ("allen_jee", "allen_o1", "allen_o2") or (isinstance(req.get("papers"), list) and any(str(p).startswith("allen_") for p in req.get("papers"))):
            is_allen_jee = True

        if is_allen_jee:
            try:
                import build_allenjee_sheet as baj
                bank_choice = "both"
                if paper == "allen_o1" or (isinstance(req.get("papers"), list) and req.get("papers") == ["allen_o1"]):
                    bank_choice = "O-1"
                elif paper == "allen_o2" or (isinstance(req.get("papers"), list) and req.get("papers") == ["allen_o2"]):
                    bank_choice = "O-2"

                res = baj.generate_custom_test(
                    chapter_name=chapters[0] if (chapters and len(chapters) == 1) else None,
                    question_count=count,
                    out_pdf_path=out_pdf,
                    bank=bank_choice,
                    selected_qids=selected_qids,
                    title=title,
                    subtitle=subtitle,
                    cand_name=req.get("candName"),
                    time_limit=req.get("timeLimit", 90)
                )
                pdf_url = f"/generated_tests/{out_filename}"
                latest_url = "/generated_tests/latest_test.pdf"
                latest_path = os.path.join(GENERATED_DIR, "latest_test.pdf")
                try:
                    import shutil
                    shutil.copyfile(out_pdf, latest_path)
                except Exception:
                    pass

                # Separate Student Copy (questions only) and Answer Key (key only)
                student_filename = f"student_{out_filename}"
                student_path = os.path.join(GENERATED_DIR, student_filename)
                key_filename = f"key_{out_filename}"
                key_path = os.path.join(GENERATED_DIR, key_filename)

                try:
                    full_doc = fitz.open(out_pdf)
                    if len(full_doc) > 1:
                        std_doc = fitz.open(out_pdf)
                        std_doc.delete_page(len(std_doc) - 1)
                        std_doc.save(student_path)
                        std_doc.close()

                        k_doc = fitz.open(out_pdf)
                        k_doc.select([len(k_doc) - 1])
                        k_doc.save(key_path)
                        k_doc.close()
                    else:
                        import shutil
                        shutil.copyfile(out_pdf, student_path)
                        shutil.copyfile(out_pdf, key_path)
                    full_doc.close()
                except Exception as split_err:
                    print("Error splitting student copy and key:", split_err)

                self.send_json({
                    "ok": True,
                    "pdfUrl": pdf_url,
                    "studentPdfUrl": f"/generated_tests/{student_filename}",
                    "keyPdfUrl": f"/generated_tests/{key_filename}",
                    "latestUrl": latest_url,
                    "filename": out_filename,
                    "totalQuestions": res["total_questions"],
                    "totalPages": res["total_pages"],
                    "answerCount": res["total_questions"]
                })
                return
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"ok": False, "error": f"Allen JEE test generation failed: {e}"}, 500)
                return

        is_pure_allen = False
        if selected_qids and all(str(qid).startswith("allenchem_") for qid in selected_qids):
            is_pure_allen = True
        elif paper == "allen" or (isinstance(req.get("papers"), list) and req.get("papers") == ["allen"]):
            is_pure_allen = True

        if is_pure_allen:
            try:
                import build_allenchem_sheet as bas
                res = bas.generate_custom_test(
                    chapter_name=chapters[0] if (chapters and len(chapters) == 1) else None,
                    question_count=count,
                    out_pdf_path=out_pdf,
                    selected_qids=selected_qids,
                    title=title,
                    subtitle=subtitle,
                    cand_name=req.get("candName"),
                    time_limit=req.get("timeLimit")
                )
                pdf_url = f"/generated_tests/{out_filename}"
                latest_url = "/generated_tests/latest_test.pdf"
                latest_path = os.path.join(GENERATED_DIR, "latest_test.pdf")
                try:
                    import shutil
                    shutil.copyfile(out_pdf, latest_path)
                except Exception:
                    pass

                # Separate Student Copy (questions only) and Answer Key (key only)
                student_filename = f"student_{out_filename}"
                student_path = os.path.join(GENERATED_DIR, student_filename)
                key_filename = f"key_{out_filename}"
                key_path = os.path.join(GENERATED_DIR, key_filename)

                try:
                    full_doc = fitz.open(out_pdf)
                    if len(full_doc) > 1:
                        std_doc = fitz.open(out_pdf)
                        std_doc.delete_page(len(std_doc) - 1)
                        std_doc.save(student_path)
                        std_doc.close()

                        k_doc = fitz.open(out_pdf)
                        k_doc.select([len(k_doc) - 1])
                        k_doc.save(key_path)
                        k_doc.close()
                    else:
                        import shutil
                        shutil.copyfile(out_pdf, student_path)
                        shutil.copyfile(out_pdf, key_path)
                    full_doc.close()
                except Exception as split_err:
                    print("Error splitting student copy and key:", split_err)

                self.send_json({
                    "ok": True,
                    "pdfUrl": pdf_url,
                    "studentPdfUrl": f"/generated_tests/{student_filename}",
                    "keyPdfUrl": f"/generated_tests/{key_filename}",
                    "latestUrl": latest_url,
                    "filename": out_filename,
                    "totalQuestions": res["total_questions"],
                    "totalPages": res["total_pages"],
                    "answerCount": res["total_questions"]
                })
                return
            except Exception as e:
                import traceback
                traceback.print_exc()
                self.send_json({"ok": False, "error": f"Allen test generation failed: {e}"}, 500)
                return

        try:
            res = build_test_pdf(
                chapters=chapters,
                subjects=subjects,
                count=count,
                pattern=pattern,
                paper=paper,
                title=title,
                subtitle=subtitle,
                include_solutions=include_sol,
                remove_watermark=remove_wm,
                selected_qids=selected_qids,
                out_pdf=out_pdf,
                shuffle=True
            )

            pdf_url = f"/generated_tests/{out_filename}"
            latest_url = "/generated_tests/latest_test.pdf"

            student_filename = f"student_{out_filename}"
            student_path = os.path.join(GENERATED_DIR, student_filename)
            key_filename = f"key_{out_filename}"
            key_path = os.path.join(GENERATED_DIR, key_filename)

            try:
                full_doc = fitz.open(out_pdf)
                if len(full_doc) > 1:
                    std_doc = fitz.open(out_pdf)
                    std_doc.delete_page(len(std_doc) - 1)
                    std_doc.save(student_path)
                    std_doc.close()

                    k_doc = fitz.open(out_pdf)
                    k_doc.select([len(k_doc) - 1])
                    k_doc.save(key_path)
                    k_doc.close()
                else:
                    import shutil
                    shutil.copyfile(out_pdf, student_path)
                    shutil.copyfile(out_pdf, key_path)
                full_doc.close()
            except Exception as split_err:
                print("Error splitting student copy and key:", split_err)

            self.send_json({
                "ok": True,
                "pdfUrl": pdf_url,
                "studentPdfUrl": f"/generated_tests/{student_filename}",
                "keyPdfUrl": f"/generated_tests/{key_filename}",
                "latestUrl": latest_url,
                "filename": out_filename,
                "totalQuestions": res["total_questions"],
                "totalPages": res["total_pages"],
                "answerCount": res["answer_count"]
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_json({"ok": False, "error": str(e)}, 500)

    def send_json(self, data, status_code=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

def run(port=8000):
    mimetypes.add_type("application/pdf", ".pdf")
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("application/json", ".json")

    server_address = ("", port)
    httpd = http.server.ThreadingHTTPServer(server_address, AitsRequestHandler)
    print(f"AITS Practice Portal Server running at http://localhost:{port}/")
    print(f"Serving site from: {SITE_DIR}")
    print(f"Generated PDFs stored in: {GENERATED_DIR}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run(port)
