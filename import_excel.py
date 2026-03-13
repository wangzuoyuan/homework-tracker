import pandas as pd
import sqlite3
import argparse
import sys
import os

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homework.db")

def import_students_from_excel(excel_path):
    try:
        df = pd.read_excel(excel_path)
    except Exception as e:
        print(f"Error reading Excel file {excel_path}: {e}")
        sys.exit(1)
        
    print(f"Detected columns: {', '.join(df.columns.astype(str))}")
    
    # Try to find common column names for id, name, gender
    col_id = next((col for col in df.columns if str(col).strip() in ['学号', '学生学号', 'ID']), None)
    col_name = next((col for col in df.columns if str(col).strip() in ['姓名', '学生姓名', '名字', 'Name']), None)
    col_gender = next((col for col in df.columns if str(col).strip() in ['性别', '男女', 'Gender']), None)
    
    if not col_name:
        print("Error: Could not find a '姓名' (Name) column.")
        sys.exit(1)
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    added = 0
    updated = 0
    
    for index, row in df.iterrows():
        name = str(row[col_name]).strip() if pd.notna(row[col_name]) else ''
        if not name:
            continue
            
        student_no = str(row[col_id]).strip() if col_id and pd.notna(row[col_id]) else None
        # Convert float like 20250601.0 to 20250601
        if student_no and student_no.endswith('.0'):
            student_no = student_no[:-2]
            
        gender = str(row[col_gender]).strip() if col_gender and pd.notna(row[col_gender]) else None
        
        try:
            cursor.execute('INSERT INTO students (student_no, name, gender) VALUES (?, ?, ?)', 
                          (student_no, name, gender))
            added += 1
        except sqlite3.IntegrityError:
            # If student exists, update their info
            cursor.execute('UPDATE students SET student_no = ?, gender = ? WHERE name = ?', 
                          (student_no, gender, name))
            updated += 1
            
    conn.commit()
    conn.close()
    print(f"Successfully imported {added} new students. Updated {updated} existing students from {excel_path}.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Import students from Excel")
    parser.add_argument('excel_path', help="Path to the Excel file")
    
    args = parser.parse_args()
    import_students_from_excel(args.excel_path)
