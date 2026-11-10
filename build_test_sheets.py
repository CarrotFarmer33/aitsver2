#!/usr/bin/env python3
"""Build custom chapter-wise test sheets in the exact build_sheets format.

Usage:
    python build_test_sheets.py --chapters "Rotational Motion" --count 15 --out test.pdf
    python build_test_sheets.py --chapters "Kinematics & Motion in 1D/2D" --count 30 --pattern adv --out test.pdf

Features:
- 100% Native Vector PDF output (selectable/copyable text, crisp math, zero raster pixelation on zoom)
- Exact build_sheets layout (Navy double lines, Q margin labels, metadata tags)
- Exact Answer Key grid (5 Q/Ans pairs per row, alternating rows)
- Solutions section with worked solutions
- Automatic FIITJEE watermark and footer removal
"""
import argparse, sys
from build_vector_test import build_test_pdf

def main():
    parser = argparse.ArgumentParser(description="Build custom chapter-wise test sheets.")
    parser.add_argument("--chapters", nargs="*", default=[], help="Chapters to include")
    parser.add_argument("--subjects", nargs="*", default=[], help="Subjects to include")
    parser.add_argument("--count", type=int, default=30, help="Number of questions")
    parser.add_argument("--pattern", choices=["adv", "main", "custom"], default="adv", help="Exam pattern")
    parser.add_argument("--title", default="JEE ADVANCED PRACTICE TEST", help="Test paper title")
    parser.add_argument("--subtitle", default="Chapter-wise Practice Sheet | Questions cropped from source papers", help="Subtitle")
    parser.add_argument("--out", default="out/custom_test_sheet.pdf", help="Output PDF path")
    parser.add_argument("--no-solutions", action="store_true", help="Omit worked solutions")
    parser.add_argument("--no-watermark-removal", action="store_true", help="Keep source watermarks")
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
        remove_watermark=not args.no_watermark_removal,
        out_pdf=args.out
    )
    print(f"Successfully generated: {res['out_pdf']} ({res['total_questions']} Qs, {res['total_pages']} pages)")

if __name__ == "__main__":
    main()
