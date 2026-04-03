from flask import Flask, jsonify, render_template
import sqlite3
import os
import re
from datetime import datetime
from collections import defaultdict
from tracker import export_daily_report

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "homework.db")


def ensure_excluded_column():
    """确保 students 表有 excluded 列"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("PRAGMA table_info(students)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'excluded' not in columns:
        conn.execute("ALTER TABLE students ADD COLUMN excluded INTEGER DEFAULT 0")
        # 迁移硬编码的排除名单
        for name in ['王伦锋', '李说从', '张歆怡']:
            conn.execute("UPDATE students SET excluded = 1 WHERE name = ?", (name,))
        conn.commit()
    conn.close()


ensure_excluded_column()


def ensure_special_records_table():
    """确保 special_records 表存在"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS special_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            note TEXT,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    ''')
    conn.commit()
    conn.close()


ensure_special_records_table()

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


def is_subject_item(item):
    """Returns True if item contains a recognized subject keyword."""
    item = item.strip()
    for _, keywords in SUBJECT_GROUPS:
        for keyword in keywords:
            if keyword in item:
                return True
    return False


def get_excluded_students():
    """从数据库获取排除名单"""
    conn = get_db_connection()
    rows = conn.execute("SELECT name FROM students WHERE excluded = 1").fetchall()
    conn.close()
    return [row['name'] for row in rows]


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
    subject = request.args.get('subject', '')

    conditions = ["(r.remark IS NULL OR r.remark = '')", "r.subject != '全科'"]
    params = []

    if start_date and end_date:
        conditions.append("r.date BETWEEN ? AND ?")
        params.extend([start_date, end_date])

    if student:
        conditions.append("s.name LIKE ?")
        params.append(f"%{student}%")
    else:
        excluded = get_excluded_students()
        if excluded:
            placeholders = ','.join(['?'] * len(excluded))
            conditions.append(f"s.name NOT IN ({placeholders})")
            params.extend(excluded)

    if subject:
        # 找到该学科对应的所有关键词，匹配原始 subject 字段
        keywords = []
        for canonical_name, kws in SUBJECT_GROUPS:
            if canonical_name == subject:
                keywords = kws
                break
        if keywords:
            # 匹配原始值包含任一关键词的记录
            kw_conditions = ' OR '.join(['r.subject LIKE ?' for _ in keywords])
            conditions.append(f"({kw_conditions})")
            params.extend([f"%{kw}%" for kw in keywords])
        else:
            conditions.append("r.subject = ?")
            params.append(subject)

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
    mode = data.get('mode', 'by_student')  # 'by_student' or 'by_subject'

    if not raw_text:
        return jsonify({"success": False, "message": "请输入记录内容"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    added_count = 0
    errors = []

    if mode == 'by_subject':
        # 按科目/情况录入：数学：卜一轩、张曦 或 迟到：卜一轩、吴辰轩
        for line in lines:
            match = re.split(r'[:：]', line, maxsplit=1)
            if len(match) < 2:
                errors.append(f"格式错误: {line}")
                continue

            subject_raw = match[0].strip()
            names_raw = match[1].strip()
            names = [n.strip() for n in re.split(r'[，,；;、\s]+', names_raw) if n.strip()]

            if not is_subject_item(subject_raw):
                # 非科目关键词 → 作为特殊情况类型保存
                for name in names:
                    cursor.execute("SELECT id FROM students WHERE name = ?", (name,))
                    student_row = cursor.fetchone()
                    if not student_row:
                        errors.append(f"找不到学生: {name}")
                        continue
                    cursor.execute(
                        "INSERT INTO special_records (student_id, date, type, note) VALUES (?, ?, ?, ?)",
                        (student_row['id'], date, subject_raw, None)
                    )
                    added_count += 1
            else:
                parsed = parse_homework_item(subject_raw)
                if not parsed:
                    errors.append(f"无法识别科目: {subject_raw}")
                    continue
                subj, content, remark = parsed
                for name in names:
                    cursor.execute("SELECT id FROM students WHERE name = ?", (name,))
                    student_row = cursor.fetchone()
                    if not student_row:
                        errors.append(f"找不到学生: {name}")
                        continue
                    cursor.execute(
                        "INSERT INTO records (student_id, date, subject, content, remark) VALUES (?, ?, ?, ?, ?)",
                        (student_row['id'], date, subj, content, remark)
                    )
                    added_count += 1
    else:
        # 按学生录入：张三: 英语粉书、数学 或 卜一轩：请假、迟到
        for line in lines:
            match = re.split(r'[:：]', line, maxsplit=1)
            if len(match) < 2:
                errors.append(f"格式错误: {line}")
                continue

            name = match[0].strip()
            subjects_raw = match[1].strip()

            cursor.execute("SELECT id FROM students WHERE name = ?", (name,))
            student_row = cursor.fetchone()

            if not student_row:
                errors.append(f"找不到学生: {name}")
                continue

            student_id = student_row['id']
            items = [s.strip() for s in re.split(r'[，,；;、\s]+', subjects_raw) if s.strip()]

            for item in items:
                if not is_subject_item(item):
                    # 非科目关键词 → 特殊情况
                    cursor.execute(
                        "INSERT INTO special_records (student_id, date, type, note) VALUES (?, ?, ?, ?)",
                        (student_id, date, item, None)
                    )
                    added_count += 1
                else:
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


@app.route('/config')
def config_page():
    return render_template('config.html')


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
    records = [dict(row) | {'is_special': False} for row in rows]

    # 同时查询特殊记录
    sp_conditions = []
    sp_params = []
    if start_date and end_date:
        sp_conditions.append("sr.date BETWEEN ? AND ?")
        sp_params.extend([start_date, end_date])
    elif date:
        sp_conditions.append("sr.date = ?")
        sp_params.append(date)
    if student:
        sp_conditions.append("s.name LIKE ?")
        sp_params.append(f"%{student}%")

    sp_where = " WHERE " + " AND ".join(sp_conditions) if sp_conditions else ""
    sp_query = f"""
        SELECT sr.id, s.name, sr.date, sr.type, sr.note
        FROM special_records sr JOIN students s ON sr.student_id = s.id
        {sp_where}
        ORDER BY sr.date DESC, s.name ASC
        LIMIT 200
    """
    sp_rows = conn.execute(sp_query, sp_params).fetchall()
    special_records = [
        {'id': row['id'], 'name': row['name'], 'date': row['date'],
         'subject': '', 'content': row['note'] or '', 'remark': row['type'],
         'is_special': True}
        for row in sp_rows
    ]
    conn.close()

    all_records = sorted(records + special_records, key=lambda x: (x['date'], x['name']), reverse=True)
    return jsonify(all_records)


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


@app.route('/students')
def students_page():
    return render_template('students.html')


@app.route('/api/students')
def api_list_students():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT s.id, s.student_no, s.name, s.gender, s.excluded, "
        "(SELECT COUNT(*) FROM records WHERE student_id = s.id) as record_count "
        "FROM students s ORDER BY s.excluded ASC, s.student_no ASC"
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route('/api/students', methods=['POST'])
def api_add_student():
    data = request.json
    name = data.get('name', '').strip()
    student_no = data.get('student_no', '').strip()
    gender = data.get('gender', '').strip()

    if not name:
        return jsonify({"success": False, "message": "姓名不能为空"}), 400

    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM students WHERE name = ?", (name,)).fetchone()
    if existing:
        conn.close()
        return jsonify({"success": False, "message": f"学生 {name} 已存在"}), 400

    conn.execute(
        "INSERT INTO students (student_no, name, gender, excluded) VALUES (?, ?, ?, 0)",
        (student_no or None, name, gender or None)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route('/api/students/<int:student_id>', methods=['DELETE'])
def api_delete_student(student_id):
    conn = get_db_connection()
    # 获取关联记录的日期（用于重新导出）
    dates = conn.execute("SELECT DISTINCT date FROM records WHERE student_id = ?", (student_id,)).fetchall()
    affected_dates = [row['date'] for row in dates]

    conn.execute("DELETE FROM records WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()

    for d in affected_dates:
        export_daily_report(d)

    return jsonify({"success": True, "deleted_records": len(affected_dates)})


@app.route('/api/students/<int:student_id>/toggle-excluded', methods=['PUT'])
def api_toggle_excluded(student_id):
    conn = get_db_connection()
    row = conn.execute("SELECT excluded FROM students WHERE id = ?", (student_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"success": False, "message": "学生不存在"}), 404
    new_val = 0 if row['excluded'] else 1
    conn.execute("UPDATE students SET excluded = ? WHERE id = ?", (new_val, student_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "excluded": new_val})


@app.route('/api/special_records', methods=['POST'])
def add_special_records():
    data = request.json
    raw_text = data.get('raw_text', '')
    date = data.get('date', datetime.now().strftime('%Y-%m-%d'))
    mode = data.get('mode', 'by_student')  # 'by_student' or 'by_type'

    if not raw_text:
        return jsonify({"success": False, "message": "请输入记录内容"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
    added_count = 0
    errors = []

    for line in lines:
        match = re.split(r'[:：]', line, maxsplit=1)
        if len(match) < 2:
            errors.append(f"格式错误: {line}")
            continue

        left = match[0].strip()
        right = match[1].strip()

        if mode == 'by_type':
            # 格式：情况：学生1、学生2
            record_type = left
            names = [n.strip() for n in re.split(r'[，,；;、\s]+', right) if n.strip()]
            for name in names:
                cursor.execute("SELECT id FROM students WHERE name = ?", (name,))
                student_row = cursor.fetchone()
                if not student_row:
                    errors.append(f"找不到学生: {name}")
                    continue
                cursor.execute(
                    "INSERT INTO special_records (student_id, date, type, note) VALUES (?, ?, ?, ?)",
                    (student_row['id'], date, record_type, None)
                )
                added_count += 1
        else:
            # 格式：学生：情况（可以逗号分隔多个情况）
            name = left
            cursor.execute("SELECT id FROM students WHERE name = ?", (name,))
            student_row = cursor.fetchone()
            if not student_row:
                errors.append(f"找不到学生: {name}")
                continue
            types = [t.strip() for t in re.split(r'[，,；;、\s]+', right) if t.strip()]
            for record_type in types:
                cursor.execute(
                    "INSERT INTO special_records (student_id, date, type, note) VALUES (?, ?, ?, ?)",
                    (student_row['id'], date, record_type, None)
                )
                added_count += 1

    conn.commit()
    conn.close()

    return jsonify({"success": True, "added_count": added_count, "errors": errors})


@app.route('/api/special_records', methods=['GET'])
def get_special_records():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    conn = get_db_connection()
    rows = conn.execute(
        """SELECT sr.id, s.name, sr.date, sr.type, sr.note
           FROM special_records sr JOIN students s ON sr.student_id = s.id
           WHERE sr.date = ?
           ORDER BY sr.type, s.name""",
        (date,)
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route('/api/special_records/<int:record_id>', methods=['DELETE'])
def delete_special_record(record_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM special_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


if __name__ == '__main__':
    port = int(os.environ.get("BOARD_PORT", "5050"))
    app.run(debug=True, port=port)
