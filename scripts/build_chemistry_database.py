#!/usr/bin/env python3
"""Build the AITS Chemistry bank from the classifier output and original CBT ZIPs.

Expected ZIP layout: each record's zipName exists under --zip-dir and each imageParts
filename is a member of that ZIP. This preserves image-backed questions exactly;
it never invents answer keys. Verified keys can be overlaid from answer_keys.json:
  {"<questionKey>": "A", "<questionKey>": 42, ...}
Answer values may be letters, lists of letters, or numeric values.
"""
import argparse
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classification", required=True, help="chem1.json")
    ap.add_argument("--zip-dir", help="Directory containing the original ZIPs (optional for manifest-only output)")
    ap.add_argument("--answer-keys", help="Optional JSON object mapping questionKey to verified answer")
    ap.add_argument("--output", default="chemistry.json")
    ap.add_argument("--manifest", default="chemistry_build_report.json")
    ap.add_argument("--image-base-url", help="Optional hosted ZIP base URL; filenames are URL-encoded")
    args = ap.parse_args()

    source = json.loads(Path(args.classification).read_text(encoding="utf-8"))
    records = source.get("records", [])
    keys = json.loads(Path(args.answer_keys).read_text(encoding="utf-8")) if args.answer_keys else {}
    zip_dir = Path(args.zip_dir) if args.zip_dir else None
    bank, missing_zip, missing_image, keyed = [], set(), [], 0

    for r in records:
        qkey = r.get("questionKey", "")
        zip_name = r.get("zipName", "")
        parts = r.get("imageParts") or []
        images = []
        zip_path = (zip_dir / zip_name) if zip_dir else None

        if args.image_base_url:
            base = args.image_base_url.rstrip("/")
            zip_url = base + "/" + quote(zip_name)
            images = ["zipimg:" + zip_url + "#" + quote(p, safe="/") for p in parts]
        elif zip_path and zip_path.is_file():
            images = ["zipimg:" + str(zip_path.resolve()) + "#" + quote(p, safe="/") for p in parts]
            try:
                with zipfile.ZipFile(zip_path) as z:
                    names = set(z.namelist())
                    for p in parts:
                        if p not in names and not any(n.endswith("/" + p) for n in names):
                            missing_image.append({"questionKey": qkey, "image": p, "zipName": zip_name})
            except zipfile.BadZipFile:
                missing_zip.add(zip_name)
        else:
            missing_zip.add(zip_name)

        answer = keys.get(qkey)
        if answer is not None:
            keyed += 1

        qtype = str(r.get("qtype", "MCQ")).upper()
        qtype = {"MCQ": "single", "MSQ": "multi", "NAT": "numerical"}.get(qtype, "single")
        bank.append({
            "id": qkey,
            "subject": "Chemistry",
            "chapter": r.get("chapterTitle") or r.get("chapterId") or "Unsorted",
            "type": qtype,
            "question": "",
            "options": None,
            "answer": answer,
            "solution": "",
            "images": images,
            "solution_images": [],
            "source": "AITS Chemistry",
            "paperTitle": r.get("paperTitle"),
            "year": r.get("year"),
            "questionNumber": r.get("questionNumber"),
            "zipName": zip_name,
            "imageParts": parts,
            "confidence": r.get("confidence"),
            "questionKey": qkey,
            "answerVerified": answer is not None,
        })

    Path(args.output).write_text(json.dumps({"questions": bank}, ensure_ascii=False), encoding="utf-8")
    report = {
        "records": len(bank),
        "distinctPapers": len({q["zipName"] for q in bank}),
        "chapters": len({q["chapter"] for q in bank}),
        "recordsWithVerifiedAnswerKey": keyed,
        "recordsMissingAnswerKey": len(bank) - keyed,
        "missingZipCount": len(missing_zip),
        "missingZipNames": sorted(missing_zip),
        "missingImageCount": len(missing_image),
        "missingImages": missing_image[:500],
        "note": "Classification metadata is not an answer key. Missing keys remain null; do not score these questions automatically."
    }
    Path(args.manifest).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("missingZipNames", "missingImages")}, indent=2))

if __name__ == "__main__":
    main()
