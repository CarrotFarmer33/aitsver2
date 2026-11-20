#!/usr/bin/env python3
"""build_db_meta.py - Generate lightweight fast-loading metadata manifest for question bank."""

import json
import os
import re

CHEM_ALIAS = {
    'Isomerism': 'Isomerism (Structural & Stereoisomerism)',
    'Metallurgy': 'Principles & Processes of Isolation of Metals (Metallurgy)',
    'General Principles and Processes of Isolation of Metals (Metallurgy)': 'Principles & Processes of Isolation of Metals (Metallurgy)',
    'p-Block: Group 13 & 14': 'p-Block Elements: Group 13 (Boron family) & Group 14 (Carbon family)',
    'p-Block: Group 15 & 16': 'p-Block Elements: Group 15 (Nitrogen family) & Group 16 (Oxygen family)',
    'p-Block: Group 17 & 18': 'p-Block Elements: Group 17 (Halogens) & Group 18 (Noble gases)',
    'p-Block Elements: Group 13 to Group 18': 'p-Block Elements: Group 15 (Nitrogen family) & Group 16 (Oxygen family)',
    'Environmental Chemistry': 'Chemistry in Everyday Life',
    'Organic Compounds Containing Oxygen (Alcohols, Phenols, Ethers, Aldehydes, Ketones, Carboxylic Acids)': 'Aldehydes, Ketones & Carboxylic Acids',
    'Equilibrium': 'Chemical Equilibrium',
    'Chemical Thermodynamics': 'Thermodynamics (Chemical)',
    'Solutions': 'Liquid Solutions & Colligative Properties',
    'Purification and Characterisation of Organic Compounds & General Organic Chemistry (GOC)': 'General Organic Chemistry (GOC)',
    'Redox Reactions & Electrochemistry': 'Electrochemistry',
    'Principles Related to Practical Chemistry (Salt Analysis)': 'Qualitative Salt Analysis',
    'Organic Compounds Containing Halogens (Haloalkanes & Haloarenes)': 'Haloalkanes & Haloarenes',
    'Organic Compounds Containing Nitrogen (Amines & Diazonium Salts)': 'Amines & Diazonium Salts',
    's-Block Elements (Alkali and Alkaline Earth Metals)': 's-Block Elements',
    'Classification of Elements & Periodicity in Properties': 'Periodic Table & Periodicity'
}

def norm_subj(s):
    s = str(s or '').strip()
    if not s: return 'Physics'
    if 'chem' in s.lower(): return 'Chemistry'
    if 'math' in s.lower(): return 'Mathematics'
    return 'Physics'

def paper_of(s):
    s = str(s or '')
    m = bool(re.search(r'(\bJM\b|JEE[\s_-]?M\b|JEEM|\bMains?\b|_Mains?\b)', s, re.I))
    a = bool(re.search(r'(\bJA\b|JEE[\s_-]?A\b|JEEA|\bAdv)', s, re.I))
    if m and not a: return 'main'
    if a and not m: return 'adv'
    if m and a: return 'main' if re.search(r'\bMain\b', s, re.I) else 'adv'
    if re.search(r'Paper[- _]?(1|2|I{1,2})\b|\bP[- ]?[12]\b', s, re.I): return 'adv'
    return 'other'

def get_paper(q, def_subj, def_paper):
    qid = str(q.get('id') or '')
    if q.get('paper') == 'qrp' or qid.startswith('qrp_'):
        return 'qrp'
    if q.get('paper') == 'neeraj' or qid.startswith('nk_'):
        return 'neeraj'
    if q.get('paper') == 'mschouhan' or qid.startswith('mschouhan_'):
        return 'mschouhan'
    if q.get('paper') == 'allen_jee' or qid.startswith('allenjee_'):
        return 'allen_jee'
    if q.get('paper') == 'allen' or qid.startswith('allenchem_') or 'allen' in str(q.get('source', '')).lower():
        return 'allen'
    if def_paper in ('qrp', 'neeraj', 'allen', 'allen_jee', 'mschouhan', 'main', 'adv'):
        return def_paper
    exam = q.get('exam')
    if exam:
        if re.search(r'adv', str(exam), re.I): return 'adv'
        if re.search(r'main', str(exam), re.I): return 'main'
    p = paper_of(str(q.get('source', '')) + ' ' + str(q.get('paperTitle', '') or q.get('paper_title', '')) + ' ' + qid)
    if p != 'other':
        return p
    return 'adv'

def year_of(q):
    try:
        y = int(q.get('year'))
        if 1990 <= y <= 2100:
            return str(y)
    except:
        pass
    m = re.search(r'\b(19|20)\d{2}\b', str(q.get('source', '')) + ' ' + str(q.get('paperTitle', '') or q.get('paper_title', '')) + ' ' + str(q.get('id', '')))
    return m.group(0) if m else 'Unknown'

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
        (os.path.join(root, 'qrp_database.json'), 'Physics', 'qrp'),
        (os.path.join(root, 'chemistry_database.json'), 'Chemistry', 'aits'),
        (os.path.join(root, 'maths_advanced_database.json'), 'Mathematics', 'adv'),
        (os.path.join(root, 'maths_main_database.json'), 'Mathematics', 'main'),
        (os.path.join(root, 'allenchem_database.json'), 'Chemistry', 'allen'),
        (os.path.join(root, 'allenjee_database.json'), 'Physics', 'allen_jee'),
        (os.path.join(root, 'mschouhan_database.json'), 'Chemistry', 'mschouhan'),
        (os.path.join(root, 'neeraj_database.json'), 'Chemistry', 'neeraj')
    ]

    questions = []
    seen = set()

    for path, def_subj, def_paper in db_files:
        if not os.path.exists(path):
            print(f"Skipping non-existent: {path}")
            continue
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        qs = data if isinstance(data, list) else data.get('questions', [])
        count_for_file = 0
        for q in qs:
            qid = q.get('id')
            if not qid or qid in seen:
                continue
            seen.add(qid)
            count_for_file += 1
            subj = norm_subj(q.get('subject') or def_subj)
            chap = str(q.get('chapter') or 'Unsorted').strip() or 'Unsorted'
            if subj == 'Chemistry' and chap in CHEM_ALIAS:
                chap = CHEM_ALIAS[chap]
            qtype = q.get('type') or 'single'
            year = year_of(q)
            paper = get_paper(q, subj, def_paper)
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

            ans = q.get('ans')
            if ans is None:
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
            if q.get('source'): item['source'] = q['source']
            if q.get('paperTitle'): item['paperTitle'] = q['paperTitle']
            elif q.get('paper_title'): item['paperTitle'] = q['paper_title']
            if q.get('exam'): item['exam'] = q['exam']
            if q.get('branch'): item['branch'] = q['branch']
            if q.get('star'): item['star'] = q['star']
            if q.get('selected'): item['selected'] = True
            if q.get('isLevel1'): item['isLevel1'] = True
            if q.get('exercise'): item['exercise'] = q['exercise']
            if q.get('bank'): item['bank'] = q['bank']
            if q.get('subSource'): item['subSource'] = q['subSource']
            if q.get('qrpNumber'): item['qrpNumber'] = q['qrpNumber']
            if q.get('questionNumber'): item['questionNumber'] = q['questionNumber']
            if q.get('paragraph') or q.get('paragraph_id'): item['paragraph'] = True
            if q.get('rawType'): item['rawType'] = q['rawType']
            if q.get('options') and isinstance(q.get('options'), list):
                item['options'] = q.get('options')
            if q.get('images'): item['images'] = q.get('images')
            if q.get('solution_images'): item['solImages'] = q.get('solution_images')
            if q.get('segments'): item['segments'] = q.get('segments')
            if q.get('height'): item['height'] = q.get('height')
            if q.get('width'): item['width'] = q.get('width')

            questions.append(item)
        print(f"Loaded {count_for_file} questions from {os.path.basename(path)}")

    out_files = [
        os.path.join(root, 'db_meta.json'),
        os.path.join(root, 'public', 'db_meta.json'),
        os.path.join(os.path.dirname(root), 'db_meta.json')
    ]
    for out_p in out_files:
        os.makedirs(os.path.dirname(out_p), exist_ok=True)
        with open(out_p, 'w', encoding='utf-8') as f:
            json.dump(questions, f, separators=(',', ':'))
        print(f'Wrote {len(questions)} items to {out_p} ({os.path.getsize(out_p)/(1024*1024):.2f} MB)')

if __name__ == '__main__':
    build_meta()
