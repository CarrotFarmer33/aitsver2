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
GENERATED_DIR = os.path.join(SITE_DIR, "generated_tests")
os.makedirs(GENERATED_DIR, exist_ok=True)

# Pre-load question manager in background thread on startup
threading.Thread(target=QuestionManager.get_instance, daemon=True).start()

class AitsRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SITE_DIR, **kwargs)

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

        # Serve static files from SITE_DIR
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
            svg = temp_page.get_svg_image(text_as_path=0)
            temp_doc.close()
            
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

            self.send_json({
                "ok": True,
                "pdfUrl": pdf_url,
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
