from flask import Flask, jsonify, render_template
import sqlite3
import os
import re
from datetime import datetime
from collections import defaultdict
from tracker import export_daily_report

app = Flask(__name__)
DB_PATH = '/Users/monster/Documents/Monster/班主任/作业跟踪/homework.db'

SUBJECT_GROUPS = [
    ("语文", ["语文"]),
    ("数学", ["数学"]),
    ("英语", ["英语"]),
    ("物理", ["物理"]),
    ("化学", ["化学"]),
    ("生物", ["生物"]),
    ("历史", ["历史"]),
    ("地理", ["地理"]),
    ("政治", ["政治", "道法", "道德与法治"]),
    ("全科", ["全科"]),
]

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_subject(subject):
    if not subject:
        return "未分类"

    normalized = str(subject).strip().replace(" ", "")
    if not normalized:
        return "未分类"

    for canonical_name, keywords in SUBJECT_GROUPS:
        if any(keyword in normalized for keyword in keywords):
            return canonical_name

    return normalized


def aggregate_subject_counts(rows, subject_key="subject", count_key="count"):
    aggregated = defaultdict(int)
    for row in rows:
        subject_name = normalize_subject(row[subject_key])
        aggregated[subject_name] += row[count_key]
    return aggregated

from flask import request


def parse_homework_item(item):
    """解析单个作业项，返回 (subject, content, remark)。

    - '请假' → ('全科', None, '请假')
    - '英语粉书' → ('英语', '英语粉书', None)
    - '数学' → ('数学', None, None)
    """
    item = item.strip()
    if not item:
        return None

    if item == '请假':
        return ('全科', None, '请假')

    for canonical_name, keywords in SUBJECT_GROUPS:
        for keyword in keywords:
            if keyword in item:
                content = item if item != keyword else None
                return (canonical_name, content, None)

    # 无法识别学科，原样作为学科名
    return (item, None, None)


EXCLUDED_STUDENTS = ['王伦锋', '李说从', '张歆怡']


def get_semester_config():
    conn = get_db_connection()
    rows = conn.execute("SELECT key, value FROM settings WHERE key IN ('semester_start', 'semester_end', 'semester_name')").fetchall()
    conn.close()
    config = {row['key']: row['value'] for row in rows}
    return {
        'semester_start': config.get('semester_start', '2026-02-17'),
        'semester_end': config.get('semester_end', '2026-07-04'),
        'semester_name': config.get('semester_name', ''),
    }


def get_filter_conditions():
    semester = get_semester_config()
    start_date = request.args.get('start_date', semester['semester_start'])
    end_date = request.args.get('end_date', semester['semester_end'])
    student = request.args.get('student', '')

    conditions = ["(r.remark IS NULL OR r.remark = '')", "r.subject != '全科'"]
    params = []

    if start_date and end_date:
        conditions.append("r.date BETWEEN ? AND ?")
        params.extend([start_date, end_date])

    if student:
        conditions.append("s.name LIKE ?")
        params.append(f"%{student}%")
    else:
        placeholders = ','.join(['?'] * len(EXCLUDED_STUDENTS))
        conditions.append(f"s.name NOT IN ({placeholders})")
        params.extend(EXCLUDED_STUDENTS)

    where_clause = " WHERE " + " AND ".join(conditions)
    return where_clause, params

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/kpi')
def get_kpi():
    conn = get_db_connection()
    where_clause, params = get_filter_conditions()
    
    # Needs join with students for student filter
    base_query_join = "FROM records r JOIN students s ON r.student_id = s.id"
    
    # 本月总缺交人次
    total_misses = conn.execute(f"SELECT COUNT(r.id) {base_query_join} {where_clause}", params).fetchone()[0]
    
    # 最差学科
    worst_subj_query = f"SELECT r.subject, COUNT(r.id) as count {base_query_join} {where_clause} GROUP BY r.subject"
    worst_subj_rows = conn.execute(worst_subj_query, params).fetchall()
    aggregated_subjects = aggregate_subject_counts(worst_subj_rows)
    if aggregated_subjects:
        worst_name, worst_count = max(aggregated_subjects.items(), key=lambda item: item[1])
        worst_subject = {"name": worst_name, "count": worst_count}
    else:
        worst_subject = {"name": "无", "count": 0}
    
    # 缺交最多学生（前5名）
    worst_students_query = f"SELECT s.name, COUNT(r.id) as count {base_query_join} {where_clause} GROUP BY s.name ORDER BY count DESC LIMIT 5"
    worst_students = conn.execute(worst_students_query, params).fetchall()
    top_students = [{"name": row['name'], "count": row['count']} for row in worst_students]

    conn.close()
    return jsonify({
        "total_misses": total_misses,
        "worst_subject": worst_subject,
        "top_students": top_students
    })

@app.route('/api/trend')
def get_trend():
    conn = get_db_connection()
    where_clause, params = get_filter_conditions()
    base_query_join = "FROM records r JOIN students s ON r.student_id = s.id"
    
    trend_query = f"SELECT r.date, COUNT(r.id) as count {base_query_join} {where_clause} GROUP BY r.date ORDER BY r.date ASC"
    trend_data = conn.execute(trend_query, params).fetchall()
    
    dates = [row['date'] for row in trend_data]
    counts = [row['count'] for row in trend_data]
    conn.close()
    return jsonify({"dates": dates, "counts": counts})

@app.route('/api/subjects')
def get_subjects():
    conn = get_db_connection()
    where_clause, params = get_filter_conditions()
    base_query_join = "FROM records r JOIN students s ON r.student_id = s.id"

    subj_query = f"SELECT r.subject, COUNT(r.id) as count {base_query_join} {where_clause} GROUP BY r.subject"
    subj_data = conn.execute(subj_query, params).fetchall()

    aggregated_subjects = aggregate_subject_counts(subj_data)

    # Per-subject student breakdown
    detail_query = f"SELECT r.subject, s.name, COUNT(r.id) as count {base_query_join} {where_clause} GROUP BY r.subject, s.name"
    detail_data = conn.execute(detail_query, params).fetchall()

    # Aggregate details by canonical subject name
    subject_students = defaultdict(list)
    student_map = defaultdict(lambda: defaultdict(int))
    for row in detail_data:
        canonical = normalize_subject(row['subject'])
        student_map[canonical][row['name']] += row['count']
    for subj, students in student_map.items():
        subject_students[subj] = sorted(students.items(), key=lambda x: x[1], reverse=True)

    subjects = [
        {
            "name": name,
            "value": count,
            "students": [{"name": s, "count": c} for s, c in subject_students.get(name, [])]
        }
        for name, count in sorted(aggregated_subjects.items(), key=lambda item: item[1], reverse=True)
    ]
    conn.close()
    return jsonify(subjects)

@app.route('/api/rankings')
def get_rankings():
    conn = get_db_connection()
    where_clause, params = get_filter_conditions()
    base_query_join = "FROM records r JOIN students s ON r.student_id = s.id"
    
    ranking_query = f"SELECT s.name, COUNT(r.id) as count {base_query_join} {where_clause} GROUP BY s.name ORDER BY count DESC LIMIT 10"
    ranking_data = conn.execute(ranking_query, params).fetchall()
    
    names = [row['name'] for row in ranking_data]
    counts = [row['count'] for row in ranking_data]
    conn.close()
    return jsonify({"names": names, "counts": counts})

@app.route('/api/records', methods=['POST'])
def add_records():
    data = request.json
    raw_text = data.get('raw_text', '')
    date = data.get('date', datetime.now().strftime('%Y-%m-%d'))
    
    if not raw_text:
        return jsonify({"success": False, "message": "请输入记录内容"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    
    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    added_count = 0
    errors = []
    
    for line in lines:
        # Match: Name: Subject, Subject OR Name：Subject、Subject
        match = re.split(r'[:：]', line, maxsplit=1)
        if len(match) < 2:
            errors.append(f"格式错误: {line}")
            continue
            
        name = match[0].strip()
        subjects_raw = match[1].strip()
        
        # Find student ID
        cursor.execute("SELECT id FROM students WHERE name = ?", (name,))
        student_row = cursor.fetchone()

        if not student_row:
            errors.append(f"找不到学生: {name}")
            continue

        student_id = student_row['id']

        # Split by comma/separator and parse each item
        items = [s.strip() for s in re.split(r'[，,；;、\s]+', subjects_raw) if s.strip()]

        for item in items:
            parsed = parse_homework_item(item)
            if not parsed:
                continue
            subj, content, remark = parsed
            cursor.execute(
                "INSERT INTO records (student_id, date, subject, content, remark) VALUES (?, ?, ?, ?, ?)",
                (student_id, date, subj, content, remark)
            )
            added_count += 1
            
    conn.commit()
    conn.close()
    
    # Trigger export
    if added_count > 0:
        export_daily_report(date)
        
    return jsonify({
        "success": True, 
        "added_count": added_count,
        "errors": errors
    })

@app.route('/student/<name>')
def student_page(name):
    return render_template('student.html', student_name=name)


@app.route('/manage')
def manage():
    return render_template('manage.html')


@app.route('/api/manage/records')
def manage_list_records():
    conn = get_db_connection()
    date = request.args.get('date', '')
    student = request.args.get('student', '')

    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    conditions = []
    params = []
    if start_date and end_date:
        conditions.append("r.date BETWEEN ? AND ?")
        params.extend([start_date, end_date])
    elif date:
        conditions.append("r.date = ?")
        params.append(date)
    if student:
        conditions.append("s.name LIKE ?")
        params.append(f"%{student}%")

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"""
        SELECT r.id, s.name, r.date, r.subject, r.content, r.remark
        FROM records r JOIN students s ON r.student_id = s.id
        {where_clause}
        ORDER BY r.date DESC, s.name ASC
        LIMIT 200
    """
    rows = conn.execute(query, params).fetchall()
    records = [dict(row) for row in rows]
    conn.close()
    return jsonify(records)


@app.route('/api/manage/records/<int:record_id>', methods=['PUT'])
def manage_update_record(record_id):
    data = request.json
    conn = get_db_connection()
    conn.execute(
        "UPDATE records SET subject = ?, content = ?, remark = ? WHERE id = ?",
        (data.get('subject', ''), data.get('content', ''), data.get('remark', ''), record_id)
    )
    conn.commit()

    # Re-export the report for this record's date
    row = conn.execute("SELECT date FROM records WHERE id = ?", (record_id,)).fetchone()
    conn.close()
    if row:
        export_daily_report(row['date'])

    return jsonify({"success": True})


@app.route('/api/manage/records/<int:record_id>', methods=['DELETE'])
def manage_delete_record(record_id):
    conn = get_db_connection()
    row = conn.execute("SELECT date FROM records WHERE id = ?", (record_id,)).fetchone()
    record_date = row['date'] if row else None
    conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()

    if record_date:
        export_daily_report(record_date)

    return jsonify({"success": True})


@app.route('/settings')
def settings_page():
    return render_template('settings.html')


@app.route('/api/semester', methods=['GET'])
def api_get_semester():
    return jsonify(get_semester_config())


@app.route('/api/semester', methods=['PUT'])
def api_set_semester():
    data = request.json
    conn = get_db_connection()
    for key in ('semester_start', 'semester_end', 'semester_name'):
        if key in data:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, data[key]))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
