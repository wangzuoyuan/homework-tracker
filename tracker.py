import sqlite3
import argparse
from datetime import datetime
import json
import os

# DB file in the same directory as the script
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homework.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no TEXT UNIQUE,
            name TEXT NOT NULL,
            gender TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            subject TEXT NOT NULL,
            content TEXT,
            remark TEXT,
            FOREIGN KEY (student_id) REFERENCES students(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_students(names):
    # This function is kept for backward compatibility if you still want to add by name only
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    added = 0
    for name in names:
        try:
            cursor.execute('INSERT INTO students (name) VALUES (?)', (name,))
            added += 1
        except Exception:
            print(f"Failed to add {name}.")
    conn.commit()
    conn.close()
    print(f"Added {added} students.")

def add_record(name, date, subject, content="缺交", remark=""):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM students WHERE name = ?', (name,))
    row = cursor.fetchone()
    if not row:
        print(f"Error: Student {name} not found.")
        return
    student_id = row[0]
    cursor.execute('INSERT INTO records (student_id, date, subject, content, remark) VALUES (?, ?, ?, ?, ?)',
                   (student_id, date, subject, content, remark))
    conn.commit()
    conn.close()
    
    msg = f"Recorded: {name} on {date} - {subject}: {content}"
    if remark:
        msg += f" (Note: {remark})"
    print(msg)
    
    # Automatically export report for the date after adding a record
    export_daily_report(date)

def export_daily_report(target_date):
    try:
        import pandas as pd
    except ImportError:
        print("Pandas not installed. Cannot export to Excel. Please run: pip install pandas openpyxl")
        return

    conn = sqlite3.connect(DB_FILE)
    query = '''
        SELECT students.student_no as '学号', students.name as '姓名', records.subject as '缺交科目', records.content as '说明', records.remark as '特殊情况'
        FROM records
        JOIN students ON records.student_id = students.id
        WHERE records.date = ?
    '''
    df = pd.read_sql_query(query, conn, params=(target_date,))

    # Query special records for this date
    special_query = '''
        SELECT students.student_no as '学号', students.name as '姓名', special_records.type as '特殊情况'
        FROM special_records
        JOIN students ON special_records.student_id = students.id
        WHERE special_records.date = ?
    '''
    try:
        special_df = pd.read_sql_query(special_query, conn, params=(target_date,))
    except Exception:
        special_df = pd.DataFrame(columns=['学号', '姓名', '特殊情况'])
    conn.close()

    if df.empty and special_df.empty:
        return

    # Group by student to merge subjects (deduplicated)
    def unique_join(series):
        seen = []
        for v in series:
            if v and v not in seen:
                seen.append(v)
        return '、'.join(seen)

    def nonempty_join(series):
        seen = []
        for v in series.dropna():
            if v and v not in seen:
                seen.append(v)
        return '、'.join(seen)

    if not df.empty:
        grouped_df = df.groupby(['学号', '姓名']).agg({
            '缺交科目': unique_join,
            '说明': nonempty_join,
            '特殊情况': nonempty_join,
        }).reset_index()
    else:
        grouped_df = pd.DataFrame(columns=['学号', '姓名', '缺交科目', '说明', '特殊情况'])

    # Merge special records into grouped_df
    if not special_df.empty:
        special_grouped = special_df.groupby(['学号', '姓名'])['特殊情况'].apply(
            lambda s: '、'.join(v for v in s.dropna() if v)
        ).reset_index()
        special_grouped.columns = ['学号', '姓名', '特殊情况_special']

        grouped_df = grouped_df.merge(special_grouped, on=['学号', '姓名'], how='outer')

        def merge_special(row):
            parts = []
            if pd.notna(row.get('特殊情况')) and row['特殊情况']:
                parts.append(row['特殊情况'])
            if pd.notna(row.get('特殊情况_special')) and row['特殊情况_special']:
                parts.append(row['特殊情况_special'])
            return '、'.join(parts)

        grouped_df['特殊情况'] = grouped_df.apply(merge_special, axis=1)
        grouped_df = grouped_df.drop(columns=['特殊情况_special'])
        grouped_df = grouped_df.fillna('')
    
    # Sort by student_no
    try:
        grouped_df['学号_num'] = pd.to_numeric(grouped_df['学号'])
        grouped_df = grouped_df.sort_values('学号_num').drop('学号_num', axis=1)
    except Exception:
        grouped_df = grouped_df.sort_values('学号')

    dt = datetime.strptime(target_date, '%Y-%m-%d')
    base_dir = os.path.dirname(os.path.abspath(__file__))
    year_dir = os.path.join(base_dir, str(dt.year))
    month_dir = os.path.join(year_dir, f'{dt.month:02d}月')
    
    os.makedirs(month_dir, exist_ok=True)
    
    file_path = os.path.join(month_dir, f'{target_date}缺交记录.xlsx')
    try:
        grouped_df.to_excel(file_path, index=False)
        print(f"Auto-exported daily report to: {file_path}")
    except Exception as e:
        print(f"Failed to export Excel: {e}")

def query_records(name, start_date=None, end_date=None, subject=None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    query = '''
        SELECT records.date, records.subject, records.content, records.remark
        FROM records 
        JOIN students ON records.student_id = students.id 
        WHERE students.name = ?
    '''
    params = [name]
    
    if start_date:
        query += ' AND records.date >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND records.date <= ?'
        params.append(end_date)
    if subject:
        query += ' AND records.subject = ?'
        params.append(subject)
        
    query += ' ORDER BY records.date ASC'
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        print(f"No missing homework records found for {name}.")
        return
        
    print(f"--- 缺交作业记录: {name} ---")
    subject_counts = {}
    for r_date, r_subject, r_content, r_remark in rows:
        msg = f"[{r_date}] {r_subject}: {r_content}"
        if r_remark:
            msg += f" (特殊情况: {r_remark})"
        print(msg)
        subject_counts[r_subject] = subject_counts.get(r_subject, 0) + 1
        
    print(f"\\n--- 统计 ---")
    for subj, count in subject_counts.items():
        print(f"{subj}: 缺交 {count} 次")

def show_all_students():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT student_no, name, gender FROM students')
    rows = cursor.fetchall()
    conn.close()
    for r in rows:
        print(f"学号: {r[0] or '-'}, 姓名: {r[1]}, 性别: {r[2] or '-'}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Homework Tracker")
    parser.add_argument('action', choices=['init', 'add_students', 'add_record', 'query', 'list_students', 'export'])
    parser.add_argument('--names', nargs='+')
    parser.add_argument('--name', type=str)
    parser.add_argument('--date', type=str, default=datetime.now().strftime('%Y-%m-%d'))
    parser.add_argument('--subject', type=str)
    parser.add_argument('--content', type=str, default="缺交")
    parser.add_argument('--remark', type=str, default="")
    parser.add_argument('--start', type=str)
    parser.add_argument('--end', type=str)
    
    args = parser.parse_args()
    
    if args.action == 'init':
        init_db()
        print("Database initialized.")
    elif args.action == 'add_students':
        if args.names:
            add_students(args.names)
        else:
            print("Please provide --names")
    elif args.action == 'add_record':
        if args.name and args.subject:
            add_record(args.name, args.date, args.subject, args.content, args.remark)
        else:
            print("Please provide --name and --subject")
    elif args.action == 'query':
        if args.name:
            query_records(args.name, args.start, args.end, args.subject)
        else:
            print("Please provide --name")
    elif args.action == 'list_students':
        show_all_students()
    elif args.action == 'export':
        export_daily_report(args.date)

