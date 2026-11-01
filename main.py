
"""
Student Performance & Academic Management System (simple version)
Run:  pip install -r requirements.txt
      uvicorn main:app --reload
Docs: http://127.0.0.1:8000/docs
"""
import sqlite3
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DB = "academics.db"
app = FastAPI(title="Student Performance & Academic Management System")

# ---------------- DATABASE ----------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    student_id INTEGER PRIMARY KEY AUTOINCREMENT,
    roll_no    TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    email      TEXT,
    department TEXT,
    semester   INTEGER
);
CREATE TABLE IF NOT EXISTS subjects (
    subject_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    faculty_name TEXT
);
CREATE TABLE IF NOT EXISTS attendance (
    attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    INTEGER NOT NULL REFERENCES students(student_id),
    subject_id    INTEGER NOT NULL REFERENCES subjects(subject_id),
    date          TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('Present','Absent')),
    UNIQUE (student_id, subject_id, date)
);
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id    INTEGER NOT NULL REFERENCES subjects(subject_id),
    title         TEXT NOT NULL,
    type          TEXT NOT NULL CHECK (type IN ('Assignment','Exam')),
    max_marks     INTEGER NOT NULL,
    due_date      TEXT
);
CREATE TABLE IF NOT EXISTS marks (
    mark_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     INTEGER NOT NULL REFERENCES students(student_id),
    assessment_id  INTEGER NOT NULL REFERENCES assessments(assessment_id),
    marks_obtained REAL NOT NULL,
    UNIQUE (student_id, assessment_id)
);
"""

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def seed(conn):
    """Insert small demo data only if DB is empty."""
    if conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]:
        return
    conn.executemany("INSERT INTO students (roll_no,name,email,department,semester) VALUES (?,?,?,?,?)", [
        ("AIML001", "Aarav Sharma", "aarav@college.edu", "AIML", 5),
        ("AIML002", "Priya Patel",  "priya@college.edu", "AIML", 5),
        ("AIML003", "Rohan Gupta",  "rohan@college.edu", "AIML", 5),
    ])
    conn.executemany("INSERT INTO subjects (code,name,faculty_name) VALUES (?,?,?)", [
        ("ML101", "Machine Learning", "Dr. Rao"),
        ("DB102", "Database Systems", "Prof. Mehta"),
    ])
    conn.executemany("INSERT INTO assessments (subject_id,title,type,max_marks,due_date) VALUES (?,?,?,?,?)", [
        (1, "ML Assignment 1", "Assignment", 20, "2026-09-10"),
        (1, "ML Internal Exam", "Exam", 50, "2026-10-01"),
        (2, "DB Assignment 1", "Assignment", 20, "2026-09-15"),
        (2, "DB Internal Exam", "Exam", 50, "2026-10-05"),
    ])
    # (student, assessment, marks): Rohan is weak on purpose
    conn.executemany("INSERT INTO marks (student_id,assessment_id,marks_obtained) VALUES (?,?,?)", [
        (1,1,18),(1,2,44),(1,3,17),(1,4,42),
        (2,1,16),(2,2,38),(2,3,15),(2,4,40),
        (3,1,6), (3,2,15),(3,3,5), (3,4,12),
    ])
    days = ["2026-10-06","2026-10-07","2026-10-08","2026-10-09","2026-10-10"]
    rows = []
    for sid, absent_days in [(1, 0), (2, 1), (3, 3)]:
        for subj in (1, 2):
            for i, d in enumerate(days):
                rows.append((sid, subj, d, "Absent" if i < absent_days else "Present"))
    conn.executemany("INSERT INTO attendance (student_id,subject_id,date,status) VALUES (?,?,?,?)", rows)

@app.on_event("startup")
def startup():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        seed(conn)

# ---------------- REQUEST MODELS ----------------
class StudentIn(BaseModel):
    roll_no: str
    name: str
    email: Optional[str] = None
    department: Optional[str] = None
    semester: Optional[int] = None

class SubjectIn(BaseModel):
    code: str
    name: str
    faculty_name: Optional[str] = None

class AttendanceIn(BaseModel):
    student_id: int
    subject_id: int
    date: str          # YYYY-MM-DD
    status: str        # Present / Absent

class AssessmentIn(BaseModel):
    subject_id: int
    title: str
    type: str          # Assignment / Exam
    max_marks: int
    due_date: Optional[str] = None

class MarkIn(BaseModel):
    student_id: int
    assessment_id: int
    marks_obtained: float

def insert(table: str, data: dict):
    cols = ", ".join(data)
    qs = ", ".join("?" * len(data))
    try:
        with get_conn() as conn:
            cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(data.values()))
            return {"message": f"Record added to {table}", "id": cur.lastrowid}
    except sqlite3.IntegrityError as e:
        raise HTTPException(400, f"Could not save record: {e}")

# ---------------- CRUD ENDPOINTS ----------------
@app.post("/students")
def add_student(s: StudentIn): return insert("students", s.model_dump())

@app.get("/students")
def list_students():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM students")]

@app.post("/subjects")
def add_subject(s: SubjectIn): return insert("subjects", s.model_dump())

@app.get("/subjects")
def list_subjects():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM subjects")]

@app.post("/attendance")
def mark_attendance(a: AttendanceIn): return insert("attendance", a.model_dump())

@app.post("/assessments")
def add_assessment(a: AssessmentIn): return insert("assessments", a.model_dump())

@app.post("/marks")
def add_marks(m: MarkIn):
    with get_conn() as conn:
        mx = conn.execute("SELECT max_marks FROM assessments WHERE assessment_id=?",
                          (m.assessment_id,)).fetchone()
    if not mx:
        raise HTTPException(404, "Assessment not found")
    if m.marks_obtained > mx["max_marks"]:
        raise HTTPException(400, f"Marks cannot exceed maximum marks ({mx['max_marks']})")
    return insert("marks", m.model_dump())

# ---------------- REPORTS ----------------
@app.get("/students/{student_id}/report")
def student_report(student_id: int):
    """Student view: attendance % and average score per subject."""
    with get_conn() as conn:
        st = conn.execute("SELECT * FROM students WHERE student_id=?", (student_id,)).fetchone()
        if not st:
            raise HTTPException(404, "Student not found")
        att = conn.execute("""
            SELECT sub.name AS subject,
                   ROUND(100.0 * SUM(a.status='Present') / COUNT(*), 1) AS attendance_pct
            FROM attendance a JOIN subjects sub ON sub.subject_id = a.subject_id
            WHERE a.student_id = ? GROUP BY sub.subject_id""", (student_id,)).fetchall()
        perf = conn.execute("""
            SELECT sub.name AS subject,
                   ROUND(100.0 * SUM(m.marks_obtained) / SUM(asm.max_marks), 1) AS score_pct
            FROM marks m
            JOIN assessments asm ON asm.assessment_id = m.assessment_id
            JOIN subjects sub    ON sub.subject_id = asm.subject_id
            WHERE m.student_id = ? GROUP BY sub.subject_id""", (student_id,)).fetchall()
    return {"student": dict(st),
            "attendance": [dict(r) for r in att],
            "performance": [dict(r) for r in perf]}

@app.get("/reports/at-risk")
def at_risk(min_attendance: float = 75, min_score: float = 40):
    """Faculty view: students with low attendance OR low overall score."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT s.student_id, s.roll_no, s.name,
              (SELECT ROUND(100.0 * SUM(status='Present') / COUNT(*), 1)
                 FROM attendance WHERE student_id = s.student_id) AS attendance_pct,
              (SELECT ROUND(100.0 * SUM(m.marks_obtained) / SUM(a.max_marks), 1)
                 FROM marks m JOIN assessments a ON a.assessment_id = m.assessment_id
                 WHERE m.student_id = s.student_id) AS score_pct
            FROM students s""").fetchall()
    out = []
    for r in map(dict, rows):
        reasons = []
        if r["attendance_pct"] is not None and r["attendance_pct"] < min_attendance:
            reasons.append("Low attendance")
        if r["score_pct"] is not None and r["score_pct"] < min_score:
            reasons.append("Low score")
        if reasons:
            r["reasons"] = reasons
            out.append(r)
    return out

@app.get("/reports/subject-summary")
def subject_summary():
    """Admin view: class average per subject."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT sub.name AS subject, sub.faculty_name,
                   ROUND(100.0 * SUM(m.marks_obtained) / SUM(a.max_marks), 1) AS class_avg_pct
            FROM marks m
            JOIN assessments a ON a.assessment_id = m.assessment_id
            JOIN subjects sub  ON sub.subject_id = a.subject_id
            GROUP BY sub.subject_id""").fetchall()
    return [dict(r) for r in rows]
