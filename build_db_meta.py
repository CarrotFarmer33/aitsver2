#!/usr/bin/env python3
"""build_db_meta.py - Generate lightweight fast-loading metadata manifest for question bank."""

import json
import os

CHEM_ALIAS = {
    'Isomerism': 'Isomerism (Structural & Stereoisomerism)',
    'Metallurgy': 'Principles & Processes of Isolation of Metals (Metallurgy)',
    'General Principles and Processes of Isolation of Metals (Metallurgy)': 'Principles & Processes of Isolation of Metals (Metallurgy)',
    'p-Block: Group 13 & 14': 'p-Block Elements: Group 13 (Boron family) & Group 14 (Carbon family)',
    'p-Block: Group 15 & 16': 'p-Block Elements: Group 15 (Nitrogen family) & Group 16 (Oxygen family)',
    'p-Block: Group 17 & 18': 'p-Block Elements: Group 17 (Halogens) & Group 18 (Noble gases)',
}

def norm_subj(s):
    s = str(s or '').strip()
    if not s: return 'Physics'
    if 'chem' in s.lower(): return 'Chemistry'
    if 'math' in s.lower(): return 'Mathematics'
    return 'Physics'

def parse_choice(raw):
    if not raw: return None
    s = str(raw).strip().upper()
    indices = []
    for ch in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
        if ch in s:
            indices.append(ord(ch) - ord('A'))
    if not indices:
        for d in ['1', '2', '3', '4']:
            if d in s:
                indices.append(int(d) - 1)
    return indices if indices else None

def build_meta():
    root = os.path.dirname(os.path.abspath(__file__))
    db_files = [
        (os.path.join(root, 'database.json'), 'Physics', 'aits'),
        (os.path.join(root, 'chemistry_database.json'), 'Chemistry', 'aits'),
        (os.path.join(root, 'maths_advanced_database.json'), 'Mathematics', 'adv'),
        (os.path.join(root, 'maths_main_database.json'), 'Mathematics', 'main'),
        (os.path.join(root, 'allenchem_database.json'), 'Chemistry', 'allen'),
        (os.path.join(root, 'allenjee_database.json'), 'Physics', 'allen_jee'),
        (os.path.join(root, 'mschouhan_database.json'), 'Chemistry', 'mschouhan')
    ]

    questions = []
    seen = set()

    for path, def_subj, def_paper in db_files:
        if not os.path.exists(path):
            continue
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        qs = data if isinstance(data, list) else data.get('questions', [])
        for q in qs:
            qid = q.get('id')
            if not qid or qid in seen:
                continue
            seen.add(qid)
            subj = norm_subj(q.get('subject') or def_subj)
            chap = str(q.get('chapter') or 'Unsorted').strip() or 'Unsorted'
            if subj == 'Chemistry' and chap in CHEM_ALIAS:
                chap = CHEM_ALIAS[chap]
            qtype = q.get('type') or 'single'
            year = str(q.get('year') or 'Unknown')
            paper = q.get('paper') or def_paper
            raw_ans = q.get('answer') or q.get('correct_answer') or q.get('key') or q.get('ans')

            p_text = q.get('previewText')
            if not p_text and q.get('stem'):
                p_text = q['stem'].strip().replace('\n', ' ')
            if not p_text and q.get('text'):
                p_text = q['text'].strip().replace('\n', ' ')
            if not p_text and q.get('question'):
                p_text = q['question'].strip().replace('\n', ' ')
            if p_text and len(p_text) > 90:
                p_text = p_text[:90] + '...'

            ans = None
            if qtype == 'numerical':
                try:
                    ans = float(str(raw_ans).strip())
                except:
                    ans = str(raw_ans).strip() if raw_ans is not None else None
            else:
                ans = parse_choice(raw_ans)

            item = {
                'id': str(qid),
                'subject': subj,
                'chapter': chap,
                'type': qtype,
                'year': year,
                'paper': paper,
                'keyOk': True,
                '_isNormalized': True,
                'answer': raw_ans,
                'ans': ans,
                'previewText': p_text or f'{paper} - {chap}'
            }
            if q.get('exam'): item['exam'] = q['exam']
            if q.get('branch'): item['branch'] = q['branch']
            if q.get('star'): item['star'] = q['star']
            if q.get('paragraph') or q.get('paragraph_id'): item['paragraph'] = True
            if q.get('rawType'): item['rawType'] = q['rawType']
            if q.get('options') and isinstance(q.get('options'), list):
                item['options'] = q.get('options')
            if q.get('images'): item['images'] = q.get('images')
            if q.get('solution_images'): item['solImages'] = q.get('solution_images')

            questions.append(item)

    out_files = [
        os.path.join(root, 'db_meta.json'),
        os.path.join(root, 'public', 'db_meta.json')
    ]
    for out_p in out_files:
        os.makedirs(os.path.dirname(out_p), exist_ok=True)
        with open(out_p, 'w', encoding='utf-8') as f:
            json.dump(questions, f, separators=(',', ':'))
        print(f'Wrote {len(questions)} items to {out_p} ({os.path.getsize(out_p)/(1024*1024):.2f} MB)')

if __name__ == '__main__':
    build_meta()
