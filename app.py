from flask import Flask, jsonify, render_template
import sqlite3
import os
from collections import defaultdict

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

def get_filter_conditions():
    start_date = request.args.get('start_date', '2026-03-01')
    end_date = request.args.get('end_date', '2026-03-31')
    student = request.args.get('student', '')
    
    conditions = []
    params = []
    
    if start_date and end_date:
        conditions.append("r.date BETWEEN ? AND ?")
        params.extend([start_date, end_date])
        
    if student:
        conditions.append("s.name LIKE ?")
        params.append(f"%{student}%")
        
    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
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
    
    # 缺交最多学生（前5名，排除王伦锋、李说从、张歆怡）
    excluded_students = ['王伦锋', '李说从', '张歆怡']
    excluded_condition = " AND s.name NOT IN (?, ?, ?)"
    kpi_where_clause = where_clause + excluded_condition if where_clause else " WHERE 1=1 " + excluded_condition
    kpi_params = params + excluded_students
    
    worst_students_query = f"SELECT s.name, COUNT(r.id) as count {base_query_join} {kpi_where_clause} GROUP BY s.name ORDER BY count DESC LIMIT 5"
    worst_students = conn.execute(worst_students_query, kpi_params).fetchall()
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
    subjects = [
        {"name": name, "value": count}
        for name, count in sorted(aggregated_subjects.items(), key=lambda item: item[1], reverse=True)
    ]
    conn.close()
    return jsonify(subjects)

@app.route('/api/rankings')
def get_rankings():
    conn = get_db_connection()
    where_clause, params = get_filter_conditions()
    base_query_join = "FROM records r JOIN students s ON r.student_id = s.id"
    
    ranking_query = f"SELECT s.name, COUNT(r.id) as count {base_query_join} {where_clause} GROUP BY s.name ORDER BY count ASC LIMIT 10"
    ranking_data = conn.execute(ranking_query, params).fetchall()
    
    names = [row['name'] for row in ranking_data]
    counts = [row['count'] for row in ranking_data]
    conn.close()
    return jsonify({"names": names, "counts": counts})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
