#!/usr/bin/env python3
"""Build the AITS Chemistry bank from classifier records, original ZIPs and verified answer keys.

Example:
  python scripts/build_chemistry_database.py --classification chem1.json --zip-dir ./source_zips --answer-keys answer_keys.json
For hosted ZIPs, pass --image-base-url with a URL prefix containing those ZIPs.
Answer-key JSON is an object mapping exact questionKey values to verified answers.
Missing answers stay null; they are never guessed.
"""
import argparse
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import quote

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classification", required=True)
    ap.add_argument("--zip-dir", help="Directory containing original source ZIPs")
    ap.add_argument("--answer-keys", help="JSON object mapping questionKey to verified answer")
    ap.add_argument("--output", default="chemistry.json")
    ap.add_argument("--manifest", default="chemistry_build_report.json")
    ap.add_argument("--image-base-url", help="Hosted ZIP URL prefix; ZIP names are appended")
    ap.add_argument("--image-dir", default="public/chemistry-images")
    args = ap.parse_args()

    source = json.loads(Path(args.classification).read_text(encoding="utf-8"))
    records = source.get("records", [])
    keys = json.loads(Path(args.answer_keys).read_text(encoding="utf-8")) if args.answer_keys else {}
    zip_dir = Path(args.zip_dir) if args.zip_dir else None
    image_dir = Path(args.image_dir)
    if zip_dir:
        image_dir.mkdir(parents=True, exist_ok=True)

    bank, missing_zip, missing_image, keyed = [], set(), [], 0
    for r in records:
        qkey = r.get("questionKey", "")
        zip_name = r.get("zipName", "")
        parts = r.get("imageParts") or []
        images = []
        zip_path = zip_dir / zip_name if zip_dir else None

        if args.image_base_url:
            zip_url = args.image_base_url.rstrip("/") + "/" + quote(zip_name)
            images = ["zipimg:" + zip_url + "#" + quote(p, safe="/") for p in parts]
        elif zip_path and zip_path.is_file():
            try:
                with zipfile.ZipFile(zip_path) as z:
                    names = z.namelist()
                    for p in parts:
                        member = p if p in names else next((n for n in names if n.endswith("/" + p)), None)
                        if member is None:
                            missing_image.append({"questionKey": qkey, "image": p, "zipName": zip_name})
                            continue
                        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", zip_name[:-4] + "__" + Path(p).name)
                        target = image_dir / safe_name
                        if not target.exists():
                            target.write_bytes(z.read(member))
                        images.append("/" + str(target).replace("\\", "/").lstrip("/"))
            except zipfile.BadZipFile:
                missing_zip.add(zip_name)
        else:
            missing_zip.add(zip_name)

        answer = keys.get(qkey)
        if answer is not None:
            keyed += 1
        qtype = {"MCQ": "single", "MSQ": "multi", "NAT": "numerical"}.get(str(r.get("qtype", "MCQ")).upper(), "single")
        bank.append({
            "id": qkey, "subject": "Chemistry",
            "chapter": r.get("chapterTitle") or r.get("chapterId") or "Unsorted",
            "type": qtype, "question": "", "options": None, "answer": answer,
            "solution": "", "images": images, "solution_images": [],
            "source": "AITS Chemistry", "paperTitle": r.get("paperTitle"),
            "year": r.get("year"), "questionNumber": r.get("questionNumber"),
            "zipName": zip_name, "imageParts": parts, "confidence": r.get("confidence"),
            "questionKey": qkey, "answerVerified": answer is not None
        })

    Path(args.output).write_text(json.dumps({"questions": bank}, ensure_ascii=False), encoding="utf-8")
    report = {
        "records": len(bank), "distinctPapers": len({q["zipName"] for q in bank}),
        "chapters": len({q["chapter"] for q in bank}),
        "recordsWithVerifiedAnswerKey": keyed, "recordsMissingAnswerKey": len(bank) - keyed,
        "missingZipCount": len(missing_zip), "missingZipNames": sorted(missing_zip),
        "missingImageCount": len(missing_image), "missingImages": missing_image[:500],
        "note": "Classification metadata is not an answer key. Missing keys remain null."
    }
    Path(args.manifest).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("missingZipNames", "missingImages")}, indent=2))

if __name__ == "__main__":
    main()
