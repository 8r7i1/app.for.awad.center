import os
import io
import sqlite3
import hashlib
import secrets
import shutil
import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "center_management.db"
BACKUP_DIR = APP_DIR / "backups"


def get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def add_column_if_missing(conn, table, column, definition):
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    BACKUP_DIR.mkdir(exist_ok=True)

    conn = get_connection()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_code TEXT UNIQUE,
            name TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            notes TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_code TEXT UNIQUE,
            name TEXT NOT NULL,
            subject TEXT,
            phone TEXT,
            hourly_rate REAL NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            subject_id INTEGER,
            teacher_id INTEGER,
            fee REAL NOT NULL DEFAULT 0,
            total_sessions INTEGER NOT NULL DEFAULT 0,
            start_date TEXT,
            end_date TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(subject_id) REFERENCES subjects(id),
            FOREIGN KEY(teacher_id) REFERENCES teachers(id)
        );

        CREATE TABLE IF NOT EXISTS enrollments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER NOT NULL,
            agreed_fee REAL NOT NULL DEFAULT 0,
            enrolled_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            UNIQUE(student_id, course_id),
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(course_id) REFERENCES courses(id)
        );

        CREATE TABLE IF NOT EXISTS student_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id INTEGER,
            teacher_id INTEGER,
            date TEXT NOT NULL,
            check_in TEXT,
            status TEXT NOT NULL DEFAULT 'حاضر',
            notes TEXT,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(course_id) REFERENCES courses(id),
            FOREIGN KEY(teacher_id) REFERENCES teachers(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS teacher_hours (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            check_in TEXT,
            check_out TEXT,
            hours_worked REAL NOT NULL DEFAULT 0,
            notes TEXT,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(teacher_id) REFERENCES teachers(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS student_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            teacher_id INTEGER,
            course_id INTEGER,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            transaction_number TEXT,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            created_by INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(student_id) REFERENCES students(id),
            FOREIGN KEY(teacher_id) REFERENCES teachers(id),
            FOREIGN KEY(course_id) REFERENCES courses(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'كاش',
            reference TEXT,
            status TEXT NOT NULL DEFAULT 'completed',
            created_by INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS teacher_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'كاش',
            notes TEXT,
            created_by INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(teacher_id) REFERENCES teachers(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS cashbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            opening_balance REAL NOT NULL DEFAULT 0,
            cash_in REAL NOT NULL DEFAULT 0,
            cash_out REAL NOT NULL DEFAULT 0,
            counted_cash REAL,
            difference REAL,
            notes TEXT,
            closed_by INTEGER,
            closed_at TEXT,
            UNIQUE(date),
            FOREIGN KEY(closed_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            table_name TEXT,
            record_id INTEGER,
            details TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """
    )

    # Compatibility with the original database structure.
    add_column_if_missing(conn, "students", "student_code", "TEXT")
    add_column_if_missing(conn, "students", "address", "TEXT")
    add_column_if_missing(conn, "students", "notes", "TEXT")
    add_column_if_missing(conn, "students", "active", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(conn, "students", "created_at", "TEXT")

    add_column_if_missing(conn, "teachers", "teacher_code", "TEXT")
    add_column_if_missing(conn, "teachers", "phone", "TEXT")
    add_column_if_missing(conn, "teachers", "hourly_rate", "REAL NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "teachers", "active", "INTEGER NOT NULL DEFAULT 1")
    add_column_if_missing(conn, "teachers", "created_at", "TEXT")

    add_column_if_missing(conn, "teacher_hours", "notes", "TEXT")
    add_column_if_missing(conn, "teacher_hours", "created_by", "INTEGER")
    add_column_if_missing(conn, "teacher_hours", "created_at", "TEXT")

    add_column_if_missing(conn, "student_payments", "course_id", "INTEGER")
    add_column_if_missing(conn, "student_payments", "notes", "TEXT")
    add_column_if_missing(conn, "student_payments", "status", "TEXT NOT NULL DEFAULT 'completed'")
    add_column_if_missing(conn, "student_payments", "created_by", "INTEGER")
    add_column_if_missing(conn, "student_payments", "created_at", "TEXT")

    now = dt.datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE students SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL",
        (now,),
    )
    conn.execute(
        "UPDATE teachers SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL",
        (now,),
    )
    conn.execute(
        "UPDATE teacher_hours SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL",
        (now,),
    )
    conn.execute(
        "UPDATE student_payments SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL",
        (now,),
    )
    conn.execute(
        "UPDATE student_payments SET status = 'completed' WHERE status IS NULL OR status = ''"
    )

    # Generate codes for records imported from the old version.
    students = conn.execute(
        "SELECT id FROM students WHERE student_code IS NULL OR student_code = ''"
    ).fetchall()
    for row in students:
        conn.execute(
            "UPDATE students SET student_code = ? WHERE id = ?",
            (f"STU-{row['id']:06d}", row["id"]),
        )

    teachers = conn.execute(
        "SELECT id FROM teachers WHERE teacher_code IS NULL OR teacher_code = ''"
    ).fetchall()
    for row in teachers:
        conn.execute(
            "UPDATE teachers SET teacher_code = ? WHERE id = ?",
            (f"TCH-{row['id']:06d}", row["id"]),
        )

    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bankak_transaction_unique
        ON student_payments(transaction_number)
        WHERE payment_method = 'بنكك'
        AND transaction_number IS NOT NULL
        AND transaction_number <> ''
        AND status = 'completed'
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_payments_date ON student_payments(date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_attendance_date ON student_attendance(date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_teacher_hours_date ON teacher_hours(date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)"
    )

    conn.commit()
    conn.close()


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    try:
        salt, digest = stored.split("$", 1)
        check = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
        ).hex()
        return secrets.compare_digest(check, digest)
    except ValueError:
        return False


def current_user():
    return st.session_state.get("user")


def has_role(*roles):
    user = current_user()
    return bool(user and user["role"] in roles)


def log_action(action, table_name=None, record_id=None, details=None):
    user = current_user()
    user_id = user["id"] if user else None
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO audit_logs
        (user_id, action, table_name, record_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            action,
            table_name,
            record_id,
            details,
            dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def get_user_count():
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    conn.close()
    return count


def login_user(username, password):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? AND active = 1",
        (username.strip(),),
    ).fetchone()
    conn.close()

    if row and verify_password(password, row["password_hash"]):
        st.session_state.user = dict(row)
        log_action("تسجيل دخول")
        return True
    return False


def logout():
    if current_user():
        log_action("تسجيل خروج")
    st.session_state.pop("user", None)
    st.rerun()


def format_money(value):
    try:
        return f"{float(value):,.0f} SDG"
    except (TypeError, ValueError):
        return "0 SDG"


def today():
    return dt.date.today()


def now_text():
    return dt.datetime.now().isoformat(timespec="seconds")


def generate_code(prefix, table):
    conn = get_connection()
    row = conn.execute(f"SELECT id FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    next_id = (row["id"] if row else 0) + 1
    return f"{prefix}-{next_id:06d}"


def dataframe_query(query, params=()):
    conn = get_connection()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def execute(query, params=(), return_id=False):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(query, params)
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id if return_id else None


def create_backup():
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = BACKUP_DIR / f"center_management_{stamp}.db"

    source = get_connection()
    destination_conn = sqlite3.connect(str(destination))
    source.backup(destination_conn)
    destination_conn.close()
    source.close()
    return destination


def download_excel(df, filename="report.xlsx"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Report")
    output.seek(0)
    st.download_button(
        "تحميل Excel",
        data=output,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def login_screen():
    st.title("نظام إدارة المركز التعليمي")

    if get_user_count() == 0:
        st.subheader("إنشاء حساب المدير")
        st.info("هذه الشاشة تظهر مرة واحدة عند أول تشغيل للنظام.")

        with st.form("first_admin"):
            full_name = st.text_input("اسم المدير")
            username = st.text_input("اسم المستخدم")
            password = st.text_input("كلمة المرور", type="password")
            password2 = st.text_input("تأكيد كلمة المرور", type="password")
            submitted = st.form_submit_button("إنشاء الحساب")

        if submitted:
            if not full_name.strip() or not username.strip() or not password:
                st.error("أكمل جميع البيانات المطلوبة.")
            elif len(password) < 6:
                st.error("كلمة المرور يجب أن تكون 6 أحرف على الأقل.")
            elif password != password2:
                st.error("كلمتا المرور غير متطابقتين.")
            else:
                execute(
                    """
                    INSERT INTO users
                    (username, password_hash, full_name, role, active, created_at)
                    VALUES (?, ?, ?, 'admin', 1, ?)
                    """,
                    (
                        username.strip(),
                        hash_password(password),
                        full_name.strip(),
                        now_text(),
                    ),
                )
                st.success("تم إنشاء حساب المدير. يمكنك تسجيل الدخول الآن.")
                st.rerun()
        return

    st.subheader("تسجيل الدخول")
    with st.form("login_form"):
        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة المرور", type="password")
        submitted = st.form_submit_button("دخول")

    if submitted:
        if login_user(username, password):
            st.rerun()
        st.error("اسم المستخدم أو كلمة المرور غير صحيحة.")


def page_dashboard():
    st.subheader("لوحة التحكم")

    selected_date = st.date_input("التاريخ", today(), key="dashboard_date")
    date_str = str(selected_date)

    payments = dataframe_query(
        """
        SELECT amount, payment_method
        FROM student_payments
        WHERE date = ? AND status = 'completed'
        """,
        (date_str,),
    )
    expenses = dataframe_query(
        """
        SELECT amount, payment_method
        FROM expenses
        WHERE date = ? AND status = 'completed'
        """,
        (date_str,),
    )
    attendance = dataframe_query(
        """
        SELECT status
        FROM student_attendance
        WHERE date = ?
        """,
        (date_str,),
    )

    total_income = payments["amount"].sum() if not payments.empty else 0
    total_expense = expenses["amount"].sum() if not expenses.empty else 0
    cash_income = (
        payments.loc[payments["payment_method"] == "كاش", "amount"].sum()
        if not payments.empty
        else 0
    )
    bank_income = (
        payments.loc[payments["payment_method"] == "بنكك", "amount"].sum()
        if not payments.empty
        else 0
    )
    present = (
        len(attendance[attendance["status"] == "حاضر"])
        if not attendance.empty
        else 0
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("إيراد اليوم", format_money(total_income))
    c2.metric("مصروفات اليوم", format_money(total_expense))
    c3.metric("صافي اليوم", format_money(total_income - total_expense))
    c4.metric("حضور الطلاب", f"{present:,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("كاش", format_money(cash_income))
    c6.metric("بنكك", format_money(bank_income))
    c7.metric("عمليات الدفع", f"{len(payments):,}")
    c8.metric("عمليات المصروفات", f"{len(expenses):,}")

    st.markdown("### ملخص آخر 30 يوماً")
    monthly = dataframe_query(
        """
        SELECT date,
               SUM(amount) AS income
        FROM student_payments
        WHERE status = 'completed'
          AND date >= date('now', '-29 day')
        GROUP BY date
        ORDER BY date
        """
    )

    if not monthly.empty:
        monthly["date"] = pd.to_datetime(monthly["date"])
        chart = monthly.set_index("date")[["income"]]
        st.line_chart(chart)
    else:
        st.info("لا توجد بيانات كافية لعرض الرسم البياني.")


def page_students():
    st.subheader("إدارة الطلاب")

    tab_add, tab_list = st.tabs(["إضافة طالب", "قائمة الطلاب"])

    with tab_add:
        with st.form("add_student"):
            name = st.text_input("اسم الطالب الكامل")
            phone = st.text_input("رقم الهاتف")
            address = st.text_input("العنوان")
            notes = st.text_area("ملاحظات")
            save = st.form_submit_button("حفظ الطالب")

        if save:
            if not name.strip():
                st.error("اسم الطالب مطلوب.")
            else:
                code = generate_code("STU", "students")
                try:
                    student_id = execute(
                        """
                        INSERT INTO students
                        (student_code, name, phone, address, notes, active, created_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            code,
                            name.strip(),
                            phone.strip(),
                            address.strip(),
                            notes.strip(),
                            now_text(),
                        ),
                        return_id=True,
                    )
                    log_action("إضافة طالب", "students", student_id, name.strip())
                    st.success(f"تم حفظ الطالب. الرقم: {code}")
                except sqlite3.IntegrityError:
                    st.error("تعذر حفظ الطالب. تحقق من البيانات.")

    with tab_list:
        search = st.text_input("بحث بالاسم أو الرقم أو الهاتف", key="student_search")
        term = f"%{search.strip()}%"
        df = dataframe_query(
            """
            SELECT id AS 'ID',
                   student_code AS 'رقم الطالب',
                   name AS 'اسم الطالب',
                   phone AS 'الهاتف',
                   address AS 'العنوان',
                   CASE WHEN active = 1 THEN 'نشط' ELSE 'موقوف' END AS 'الحالة'
            FROM students
            WHERE name LIKE ?
               OR student_code LIKE ?
               OR phone LIKE ?
            ORDER BY id DESC
            """,
            (term, term, term),
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
        if not df.empty:
            download_excel(df, "students.xlsx")


def page_teachers():
    st.subheader("إدارة الأساتذة")

    tab_add, tab_list = st.tabs(["إضافة أستاذ", "قائمة الأساتذة"])

    with tab_add:
        with st.form("add_teacher"):
            name = st.text_input("اسم الأستاذ الكامل")
            subject = st.text_input("المادة / التخصص")
            phone = st.text_input("رقم الهاتف")
            rate = st.number_input("سعر الساعة", min_value=0.0, step=100.0)
            save = st.form_submit_button("حفظ الأستاذ")

        if save:
            if not name.strip():
                st.error("اسم الأستاذ مطلوب.")
            else:
                code = generate_code("TCH", "teachers")
                teacher_id = execute(
                    """
                    INSERT INTO teachers
                    (teacher_code, name, subject, phone, hourly_rate, active, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        code,
                        name.strip(),
                        subject.strip(),
                        phone.strip(),
                        rate,
                        now_text(),
                    ),
                    return_id=True,
                )
                log_action("إضافة أستاذ", "teachers", teacher_id, name.strip())
                st.success(f"تم حفظ الأستاذ. الرقم: {code}")

    with tab_list:
        search = st.text_input("بحث بالاسم أو الرقم أو المادة", key="teacher_search")
        term = f"%{search.strip()}%"
        df = dataframe_query(
            """
            SELECT id AS 'ID',
                   teacher_code AS 'رقم الأستاذ',
                   name AS 'اسم الأستاذ',
                   subject AS 'المادة',
                   phone AS 'الهاتف',
                   hourly_rate AS 'سعر الساعة',
                   CASE WHEN active = 1 THEN 'نشط' ELSE 'موقوف' END AS 'الحالة'
            FROM teachers
            WHERE name LIKE ?
               OR teacher_code LIKE ?
               OR subject LIKE ?
            ORDER BY id DESC
            """,
            (term, term, term),
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
        if not df.empty:
            download_excel(df, "teachers.xlsx")


def page_subjects_courses():
    st.subheader("المواد والكورسات")

    tab_subject, tab_course, tab_enroll = st.tabs(
        ["المواد", "الكورسات", "تسجيل طالب في كورس"]
    )

    with tab_subject:
        with st.form("add_subject"):
            name = st.text_input("اسم المادة")
            description = st.text_area("الوصف")
            save = st.form_submit_button("حفظ المادة")

        if save:
            if not name.strip():
                st.error("اسم المادة مطلوب.")
            else:
                try:
                    subject_id = execute(
                        "INSERT INTO subjects (name, description, active) VALUES (?, ?, 1)",
                        (name.strip(), description.strip()),
                        return_id=True,
                    )
                    log_action("إضافة مادة", "subjects", subject_id, name.strip())
                    st.success("تم حفظ المادة.")
                except sqlite3.IntegrityError:
                    st.error("هذه المادة موجودة بالفعل.")

        st.dataframe(
            dataframe_query(
                """
                SELECT id AS 'ID', name AS 'المادة', description AS 'الوصف'
                FROM subjects
                WHERE active = 1
                ORDER BY name
                """
            ),
            use_container_width=True,
            hide_index=True,
        )

    with tab_course:
        subjects = dataframe_query(
            "SELECT id, name FROM subjects WHERE active = 1 ORDER BY name"
        )
        teachers = dataframe_query(
            "SELECT id, name FROM teachers WHERE active = 1 ORDER BY name"
        )

        if subjects.empty or teachers.empty:
            st.info("أضف مادة وأستاذاً أولاً.")
        else:
            subject_options = dict(zip(subjects["name"], subjects["id"]))
            teacher_options = dict(zip(teachers["name"], teachers["id"]))

            with st.form("add_course"):
                course_name = st.text_input("اسم الكورس")
                selected_subject = st.selectbox(
                    "المادة", list(subject_options.keys())
                )
                selected_teacher = st.selectbox(
                    "الأستاذ", list(teacher_options.keys())
                )
                fee = st.number_input("رسوم الكورس", min_value=0.0, step=100.0)
                sessions = st.number_input(
                    "عدد الحصص", min_value=0, step=1, value=0
                )
                start_date = st.date_input("بداية الكورس", today())
                end_date = st.date_input("نهاية الكورس", today())
                save = st.form_submit_button("حفظ الكورس")

            if save:
                if not course_name.strip():
                    st.error("اسم الكورس مطلوب.")
                elif end_date < start_date:
                    st.error("نهاية الكورس لا يمكن أن تكون قبل البداية.")
                else:
                    course_id = execute(
                        """
                        INSERT INTO courses
                        (name, subject_id, teacher_id, fee, total_sessions,
                         start_date, end_date, active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            course_name.strip(),
                            subject_options[selected_subject],
                            teacher_options[selected_teacher],
                            fee,
                            sessions,
                            str(start_date),
                            str(end_date),
                        ),
                        return_id=True,
                    )
                    log_action("إضافة كورس", "courses", course_id, course_name)
                    st.success("تم حفظ الكورس.")

            courses = dataframe_query(
                """
                SELECT c.id AS 'ID',
                       c.name AS 'الكورس',
                       s.name AS 'المادة',
                       t.name AS 'الأستاذ',
                       c.fee AS 'الرسوم',
                       c.total_sessions AS 'عدد الحصص',
                       c.start_date AS 'البداية',
                       c.end_date AS 'النهاية'
                FROM courses c
                LEFT JOIN subjects s ON s.id = c.subject_id
                LEFT JOIN teachers t ON t.id = c.teacher_id
                WHERE c.active = 1
                ORDER BY c.id DESC
                """
            )
            st.dataframe(courses, use_container_width=True, hide_index=True)

    with tab_enroll:
        students = dataframe_query(
            "SELECT id, name, student_code FROM students WHERE active = 1 ORDER BY name"
        )
        courses = dataframe_query(
            "SELECT id, name, fee FROM courses WHERE active = 1 ORDER BY name"
        )

        if students.empty or courses.empty:
            st.info("أضف طلاباً وكورسات أولاً.")
        else:
            student_options = {
                f"{r['student_code']} - {r['name']}": r["id"]
                for _, r in students.iterrows()
            }
            course_options = {
                f"{r['name']} - {format_money(r['fee'])}": r["id"]
                for _, r in courses.iterrows()
            }

            with st.form("enroll_student"):
                selected_student = st.selectbox(
                    "الطالب", list(student_options.keys())
                )
                selected_course = st.selectbox(
                    "الكورس", list(course_options.keys())
                )
                agreed_fee = st.number_input(
                    "الرسوم المتفق عليها", min_value=0.0, step=100.0
                )
                enrolled_date = st.date_input("تاريخ التسجيل", today())
                save = st.form_submit_button("تسجيل الطالب")

            if save:
                try:
                    enrollment_id = execute(
                        """
                        INSERT INTO enrollments
                        (student_id, course_id, agreed_fee, enrolled_date, status)
                        VALUES (?, ?, ?, ?, 'active')
                        """,
                        (
                            student_options[selected_student],
                            course_options[selected_course],
                            agreed_fee,
                            str(enrolled_date),
                        ),
                        return_id=True,
                    )
                    log_action(
                        "تسجيل طالب في كورس",
                        "enrollments",
                        enrollment_id,
                        selected_student,
                    )
                    st.success("تم تسجيل الطالب في الكورس.")
                except sqlite3.IntegrityError:
                    st.error("الطالب مسجل بالفعل في هذا الكورس.")


def page_student_attendance():
    st.subheader("حضور الطلاب")

    students = dataframe_query(
        """
        SELECT id, student_code, name
        FROM students
        WHERE active = 1
        ORDER BY name
        """
    )
    courses = dataframe_query(
        """
        SELECT id, name, teacher_id
        FROM courses
        WHERE active = 1
        ORDER BY name
        """
    )

    if students.empty:
        st.info("لا يوجد طلاب مسجلون.")
        return

    student_options = {
        f"{r['student_code']} - {r['name']}": r["id"]
        for _, r in students.iterrows()
    }

    course_options = {"بدون كورس": None}
    course_teacher = {}
    for _, row in courses.iterrows():
        course_options[row["name"]] = row["id"]
        course_teacher[row["id"]] = row["teacher_id"]

    with st.form("student_attendance_form"):
        col1, col2 = st.columns(2)
        with col1:
            selected_student = st.selectbox(
                "الطالب", list(student_options.keys())
            )
            attendance_date = st.date_input("التاريخ", today())
        with col2:
            selected_course = st.selectbox(
                "الكورس", list(course_options.keys())
            )
            status = st.selectbox(
                "الحالة", ["حاضر", "غائب", "متأخر", "اعتذر"]
            )

        check_in = st.time_input("وقت الحضور", dt.time(8, 0))
        notes = st.text_input("ملاحظات")
        save = st.form_submit_button("تسجيل الحضور")

    if save:
        student_id = student_options[selected_student]
        course_id = course_options[selected_course]
        teacher_id = course_teacher.get(course_id) if course_id else None

        attendance_id = execute(
            """
            INSERT INTO student_attendance
            (student_id, course_id, teacher_id, date, check_in, status,
             notes, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                course_id,
                teacher_id,
                str(attendance_date),
                str(check_in),
                status,
                notes.strip(),
                current_user()["id"],
                now_text(),
            ),
            return_id=True,
        )
        log_action(
            "تسجيل حضور طالب",
            "student_attendance",
            attendance_id,
            selected_student,
        )
        st.success("تم تسجيل الحضور.")

    selected_date = st.date_input(
        "عرض حضور يوم", today(), key="attendance_report_date"
    )
    df = dataframe_query(
        """
        SELECT a.id AS 'ID',
               s.student_code AS 'رقم الطالب',
               s.name AS 'الطالب',
               c.name AS 'الكورس',
               t.name AS 'الأستاذ',
               a.check_in AS 'وقت الحضور',
               a.status AS 'الحالة',
               a.notes AS 'ملاحظات'
        FROM student_attendance a
        JOIN students s ON s.id = a.student_id
        LEFT JOIN courses c ON c.id = a.course_id
        LEFT JOIN teachers t ON t.id = a.teacher_id
        WHERE a.date = ?
        ORDER BY a.id DESC
        """,
        (str(selected_date),),
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def page_payment():
    st.subheader("تسجيل دفع طالب")

    students = dataframe_query(
        """
        SELECT id, student_code, name
        FROM students
        WHERE active = 1
        ORDER BY name
        """
    )
    courses = dataframe_query(
        """
        SELECT c.id, c.name, c.teacher_id, c.fee, t.name AS teacher_name
        FROM courses c
        LEFT JOIN teachers t ON t.id = c.teacher_id
        WHERE c.active = 1
        ORDER BY c.name
        """
    )

    if students.empty:
        st.info("أضف طلاباً أولاً.")
        return

    student_options = {
        f"{r['student_code']} - {r['name']}": r["id"]
        for _, r in students.iterrows()
    }

    course_options = {"بدون كورس": None}
    course_data = {}
    for _, row in courses.iterrows():
        label = f"{row['name']} - {row['teacher_name'] or 'بدون أستاذ'}"
        course_options[label] = row["id"]
        course_data[row["id"]] = row

    with st.form("payment_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            selected_student = st.selectbox(
                "الطالب", list(student_options.keys())
            )
            amount = st.number_input(
                "المبلغ", min_value=0.0, step=100.0
            )
            payment_date = st.date_input("التاريخ", today())

        with col2:
            selected_course = st.selectbox(
                "الكورس", list(course_options.keys())
            )
            method = st.selectbox("طريقة الدفع", ["كاش", "بنكك"])

        transaction_number = ""
        if method == "بنكك":
            transaction_number = st.text_input("رقم عملية بنكك")

        notes = st.text_input("ملاحظات")
        save = st.form_submit_button("حفظ العملية")

    if save:
        if amount <= 0:
            st.error("المبلغ يجب أن يكون أكبر من صفر.")
            return

        if method == "بنكك" and not transaction_number.strip():
            st.error("رقم عملية بنكك مطلوب.")
            return

        if method == "بنكك":
            existing = dataframe_query(
                """
                SELECT id FROM student_payments
                WHERE payment_method = 'بنكك'
                  AND transaction_number = ?
                  AND status = 'completed'
                """,
                (transaction_number.strip(),),
            )
            if not existing.empty:
                st.error("رقم عملية بنكك مستخدم من قبل.")
                return

        student_id = student_options[selected_student]
        course_id = course_options[selected_course]
        teacher_id = (
            int(course_data[course_id]["teacher_id"])
            if course_id and pd.notna(course_data[course_id]["teacher_id"])
            else None
        )

        try:
            payment_id = execute(
                """
                INSERT INTO student_payments
                (student_id, teacher_id, course_id, date, amount,
                 payment_method, transaction_number, notes, status,
                 created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
                """,
                (
                    student_id,
                    teacher_id,
                    course_id,
                    str(payment_date),
                    amount,
                    method,
                    transaction_number.strip(),
                    notes.strip(),
                    current_user()["id"],
                    now_text(),
                ),
                return_id=True,
            )
            log_action(
                "تسجيل دفع",
                "student_payments",
                payment_id,
                f"{selected_student} - {format_money(amount)}",
            )
            st.success("تم تسجيل العملية بنجاح.")
            st.info(
                f"المبلغ: {format_money(amount)} | طريقة الدفع: {method}"
            )
        except sqlite3.IntegrityError:
            st.error("تعذر حفظ العملية. قد يكون رقم بنكك مستخدماً بالفعل.")


def page_student_balances():
    st.subheader("أرصدة الطلاب")

    df = dataframe_query(
        """
        SELECT
            s.id,
            s.student_code AS 'رقم الطالب',
            s.name AS 'اسم الطالب',
            COALESCE(e.total_fee, 0) AS 'الرسوم',
            COALESCE(p.paid, 0) AS 'المدفوع',
            COALESCE(e.total_fee, 0) - COALESCE(p.paid, 0) AS 'المتبقي'
        FROM students s
        LEFT JOIN (
            SELECT student_id, SUM(agreed_fee) AS total_fee
            FROM enrollments
            WHERE status = 'active'
            GROUP BY student_id
        ) e ON e.student_id = s.id
        LEFT JOIN (
            SELECT student_id, SUM(amount) AS paid
            FROM student_payments
            WHERE status = 'completed'
            GROUP BY student_id
        ) p ON p.student_id = s.id
        WHERE s.active = 1
        ORDER BY s.name
        """
    )

    st.dataframe(df.drop(columns=["id"]), use_container_width=True, hide_index=True)

    if not df.empty:
        download_excel(df.drop(columns=["id"]), "student_balances.xlsx")


def page_teacher_hours():
    st.subheader("ساعات عمل الأساتذة")

    teachers = dataframe_query(
        """
        SELECT id, teacher_code, name, hourly_rate
        FROM teachers
        WHERE active = 1
        ORDER BY name
        """
    )

    if teachers.empty:
        st.info("أضف أساتذة أولاً.")
        return

    teacher_options = {
        f"{r['teacher_code']} - {r['name']}": r["id"]
        for _, r in teachers.iterrows()
    }

    with st.form("teacher_hours_form", clear_on_submit=True):
        selected_teacher = st.selectbox(
            "الأستاذ", list(teacher_options.keys())
        )
        work_date = st.date_input("التاريخ", today())

        col1, col2 = st.columns(2)
        with col1:
            check_in = st.time_input("وقت الدخول", dt.time(8, 0))
        with col2:
            check_out = st.time_input("وقت الخروج", dt.time(14, 0))

        notes = st.text_input("ملاحظات")
        save = st.form_submit_button("تسجيل الساعات")

    if save:
        start = dt.datetime.combine(work_date, check_in)
        end = dt.datetime.combine(work_date, check_out)

        if end <= start:
            st.error("وقت الخروج يجب أن يكون بعد وقت الدخول.")
            return

        hours = round((end - start).total_seconds() / 3600, 2)

        hour_id = execute(
            """
            INSERT INTO teacher_hours
            (teacher_id, date, check_in, check_out, hours_worked,
             notes, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                teacher_options[selected_teacher],
                str(work_date),
                str(check_in),
                str(check_out),
                hours,
                notes.strip(),
                current_user()["id"],
                now_text(),
            ),
            return_id=True,
        )
        log_action(
            "تسجيل ساعات أستاذ",
            "teacher_hours",
            hour_id,
            selected_teacher,
        )
        st.success(f"تم تسجيل {hours:.2f} ساعة.")

    selected_date = st.date_input(
        "عرض الساعات ليوم", today(), key="teacher_hours_date"
    )
    df = dataframe_query(
        """
        SELECT h.id AS 'ID',
               t.teacher_code AS 'رقم الأستاذ',
               t.name AS 'الأستاذ',
               h.check_in AS 'الدخول',
               h.check_out AS 'الخروج',
               h.hours_worked AS 'الساعات',
               h.hours_worked * t.hourly_rate AS 'المستحق'
        FROM teacher_hours h
        JOIN teachers t ON t.id = h.teacher_id
        WHERE h.date = ?
        ORDER BY h.id DESC
        """,
        (str(selected_date),),
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def page_teacher_payroll():
    st.subheader("مستحقات الأساتذة")

    start_date = st.date_input(
        "من تاريخ", today().replace(day=1), key="payroll_start"
    )
    end_date = st.date_input(
        "إلى تاريخ", today(), key="payroll_end"
    )

    if end_date < start_date:
        st.error("الفترة غير صحيحة.")
        return

    df = dataframe_query(
        """
        SELECT
            t.id,
            t.teacher_code AS 'رقم الأستاذ',
            t.name AS 'الأستاذ',
            t.hourly_rate AS 'سعر الساعة',
            COALESCE(SUM(h.hours_worked), 0) AS 'الساعات',
            COALESCE(SUM(h.hours_worked * t.hourly_rate), 0) AS 'المستحق',
            COALESCE((
                SELECT SUM(tp.amount)
                FROM teacher_payments tp
                WHERE tp.teacher_id = t.id
                  AND tp.date BETWEEN ? AND ?
            ), 0) AS 'المدفوع'
        FROM teachers t
        LEFT JOIN teacher_hours h
            ON h.teacher_id = t.id
           AND h.date BETWEEN ? AND ?
        WHERE t.active = 1
        GROUP BY t.id
        ORDER BY t.name
        """,
        (str(start_date), str(end_date), str(start_date), str(end_date)),
    )

    if df.empty:
        st.info("لا توجد بيانات.")
        return

    df["المتبقي"] = df["المستحق"] - df["المدفوع"]
    st.dataframe(
        df.drop(columns=["id"]),
        use_container_width=True,
        hide_index=True,
    )

    if has_role("admin", "accountant"):
        teachers = dataframe_query(
            """
            SELECT id, teacher_code, name
            FROM teachers
            WHERE active = 1
            ORDER BY name
            """
        )
        options = {
            f"{r['teacher_code']} - {r['name']}": r["id"]
            for _, r in teachers.iterrows()
        }

        st.markdown("### تسجيل دفعة لأستاذ")
        with st.form("teacher_payment_form"):
            selected_teacher = st.selectbox("الأستاذ", list(options.keys()))
            payment_date = st.date_input("تاريخ الدفع", today())
            amount = st.number_input(
                "المبلغ المدفوع", min_value=0.0, step=100.0
            )
            method = st.selectbox(
                "طريقة الدفع", ["كاش", "بنكك", "تحويل بنكي"]
            )
            notes = st.text_input("ملاحظات")
            save = st.form_submit_button("تسجيل الدفع")

        if save:
            if amount <= 0:
                st.error("المبلغ يجب أن يكون أكبر من صفر.")
            else:
                payment_id = execute(
                    """
                    INSERT INTO teacher_payments
                    (teacher_id, date, amount, payment_method, notes,
                     created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        options[selected_teacher],
                        str(payment_date),
                        amount,
                        method,
                        notes.strip(),
                        current_user()["id"],
                        now_text(),
                    ),
                    return_id=True,
                )
                log_action(
                    "دفع مستحق أستاذ",
                    "teacher_payments",
                    payment_id,
                    selected_teacher,
                )
                st.success("تم تسجيل الدفع.")


def page_expenses():
    st.subheader("المصروفات")

    categories = [
        "إيجار",
        "كهرباء",
        "مياه",
        "إنترنت",
        "رواتب",
        "صيانة",
        "أدوات",
        "تسويق",
        "مواصلات",
        "أخرى",
    ]

    with st.form("expense_form", clear_on_submit=True):
        expense_date = st.date_input("التاريخ", today())
        category = st.selectbox("البند", categories)
        description = st.text_input("وصف المصروف")
        amount = st.number_input("المبلغ", min_value=0.0, step=100.0)
        method = st.selectbox(
            "طريقة الدفع", ["كاش", "بنكك", "تحويل بنكي"]
        )
        reference = st.text_input("المرجع / رقم العملية")
        save = st.form_submit_button("حفظ المصروف")

    if save:
        if not description.strip():
            st.error("وصف المصروف مطلوب.")
        elif amount <= 0:
            st.error("المبلغ يجب أن يكون أكبر من صفر.")
        else:
            expense_id = execute(
                """
                INSERT INTO expenses
                (date, category, description, amount, payment_method,
                 reference, status, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?)
                """,
                (
                    str(expense_date),
                    category,
                    description.strip(),
                    amount,
                    method,
                    reference.strip(),
                    current_user()["id"],
                    now_text(),
                ),
                return_id=True,
            )
            log_action(
                "إضافة مصروف",
                "expenses",
                expense_id,
                description.strip(),
            )
            st.success("تم حفظ المصروف.")

    selected_date = st.date_input(
        "عرض مصروفات يوم", today(), key="expense_report_date"
    )
    df = dataframe_query(
        """
        SELECT e.id AS 'ID',
               e.category AS 'البند',
               e.description AS 'الوصف',
               e.amount AS 'المبلغ',
               e.payment_method AS 'طريقة الدفع',
               e.reference AS 'المرجع'
        FROM expenses e
        WHERE e.date = ? AND e.status = 'completed'
        ORDER BY e.id DESC
        """,
        (str(selected_date),),
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        st.metric("إجمالي المصروفات", format_money(df["المبلغ"].sum()))


def page_cashbox():
    st.subheader("الخزينة والإقفال اليومي")

    selected_date = st.date_input("تاريخ الإقفال", today(), key="cashbox_date")
    date_str = str(selected_date)

    income = dataframe_query(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM student_payments
        WHERE date = ?
          AND payment_method = 'كاش'
          AND status = 'completed'
        """,
        (date_str,),
    )["total"].iloc[0]

    expense = dataframe_query(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM expenses
        WHERE date = ?
          AND payment_method = 'كاش'
          AND status = 'completed'
        """,
        (date_str,),
    )["total"].iloc[0]

    teacher_paid = dataframe_query(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM teacher_payments
        WHERE date = ?
          AND payment_method = 'كاش'
        """,
        (date_str,),
    )["total"].iloc[0]

    row = dataframe_query(
        "SELECT * FROM cashbox WHERE date = ?", (date_str,)
    )

    opening = float(row["opening_balance"].iloc[0]) if not row.empty else 0
    expected = opening + income - expense - teacher_paid

    c1, c2, c3 = st.columns(3)
    c1.metric("إيرادات الكاش", format_money(income))
    c2.metric("مصروفات الكاش", format_money(expense + teacher_paid))
    c3.metric("الرصيد المتوقع", format_money(expected))

    with st.form("cashbox_form"):
        opening_balance = st.number_input(
            "الرصيد الافتتاحي",
            min_value=0.0,
            value=opening,
            step=100.0,
        )
        counted_cash = st.number_input(
            "النقد الفعلي الموجود",
            min_value=0.0,
            step=100.0,
        )
        notes = st.text_input("ملاحظات")
        close_day = st.form_submit_button("إقفال اليوم")

    if close_day:
        actual_expected = opening_balance + income - expense - teacher_paid
        difference = counted_cash - actual_expected

        conn = get_connection()
        conn.execute(
            """
            INSERT INTO cashbox
            (date, opening_balance, cash_in, cash_out,
             counted_cash, difference, notes, closed_by, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                opening_balance = excluded.opening_balance,
                cash_in = excluded.cash_in,
                cash_out = excluded.cash_out,
                counted_cash = excluded.counted_cash,
                difference = excluded.difference,
                notes = excluded.notes,
                closed_by = excluded.closed_by,
                closed_at = excluded.closed_at
            """,
            (
                date_str,
                opening_balance,
                income,
                expense + teacher_paid,
                counted_cash,
                difference,
                notes.strip(),
                current_user()["id"],
                now_text(),
            ),
        )
        conn.commit()
        conn.close()

        log_action(
            "إقفال الخزينة",
            "cashbox",
            None,
            f"{date_str} - الفرق {difference}",
        )

        if difference == 0:
            st.success("تم إقفال الخزينة. الرصيد الفعلي مطابق.")
        else:
            st.warning(
                f"تم الإقفال. يوجد فرق في الخزينة: {format_money(difference)}"
            )


def page_reports():
    st.subheader("التقارير")

    tab_daily, tab_period, tab_audit = st.tabs(
        ["تقرير يومي", "تقرير فترة", "سجل العمليات"]
    )

    with tab_daily:
        selected_date = st.date_input("التاريخ", today(), key="reports_date")
        date_str = str(selected_date)

        payments = dataframe_query(
            """
            SELECT p.id AS 'رقم العملية',
                   s.student_code AS 'رقم الطالب',
                   s.name AS 'الطالب',
                   c.name AS 'الكورس',
                   t.name AS 'الأستاذ',
                   p.amount AS 'المبلغ',
                   p.payment_method AS 'طريقة الدفع',
                   p.transaction_number AS 'رقم بنكك',
                   p.status AS 'الحالة'
            FROM student_payments p
            JOIN students s ON s.id = p.student_id
            LEFT JOIN courses c ON c.id = p.course_id
            LEFT JOIN teachers t ON t.id = p.teacher_id
            WHERE p.date = ?
            ORDER BY p.id DESC
            """,
            (date_str,),
        )

        expenses = dataframe_query(
            """
            SELECT id AS 'رقم المصروف',
                   category AS 'البند',
                   description AS 'الوصف',
                   amount AS 'المبلغ',
                   payment_method AS 'طريقة الدفع',
                   reference AS 'المرجع'
            FROM expenses
            WHERE date = ?
            ORDER BY id DESC
            """,
            (date_str,),
        )

        total_income = (
            payments.loc[
                payments["الحالة"] == "completed", "المبلغ"
            ].sum()
            if not payments.empty
            else 0
        )
        total_expense = (
            expenses["المبلغ"].sum() if not expenses.empty else 0
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("الإيراد", format_money(total_income))
        c2.metric("المصروف", format_money(total_expense))
        c3.metric("الصافي", format_money(total_income - total_expense))

        st.markdown("### المدفوعات")
        st.dataframe(payments, use_container_width=True, hide_index=True)

        if not payments.empty:
            download_excel(payments, f"payments_{date_str}.xlsx")

        st.markdown("### المصروفات")
        st.dataframe(expenses, use_container_width=True, hide_index=True)

    with tab_period:
        start_date = st.date_input(
            "من", today().replace(day=1), key="period_start"
        )
        end_date = st.date_input("إلى", today(), key="period_end")

        if end_date < start_date:
            st.error("الفترة غير صحيحة.")
        else:
            income = dataframe_query(
                """
                SELECT date, SUM(amount) AS income
                FROM student_payments
                WHERE date BETWEEN ? AND ?
                  AND status = 'completed'
                GROUP BY date
                ORDER BY date
                """,
                (str(start_date), str(end_date)),
            )
            expense = dataframe_query(
                """
                SELECT date, SUM(amount) AS expense
                FROM expenses
                WHERE date BETWEEN ? AND ?
                  AND status = 'completed'
                GROUP BY date
                ORDER BY date
                """,
                (str(start_date), str(end_date)),
            )

            report = pd.merge(
                income,
                expense,
                on="date",
                how="outer",
            ).fillna(0)

            if report.empty:
                st.info("لا توجد عمليات في هذه الفترة.")
            else:
                report["net"] = report["income"] - report["expense"]
                report["date"] = pd.to_datetime(report["date"])
                st.dataframe(
                    report,
                    use_container_width=True,
                    hide_index=True,
                )
                st.line_chart(
                    report.set_index("date")[["income", "expense", "net"]]
                )
                download_excel(report, "period_report.xlsx")

    with tab_audit:
        if not has_role("admin"):
            st.info("سجل العمليات متاح للمدير فقط.")
        else:
            df = dataframe_query(
                """
                SELECT a.id AS 'ID',
                       COALESCE(u.username, 'system') AS 'المستخدم',
                       a.action AS 'العملية',
                       a.table_name AS 'الجدول',
                       a.record_id AS 'رقم السجل',
                       a.details AS 'التفاصيل',
                       a.created_at AS 'التاريخ والوقت'
                FROM audit_logs a
                LEFT JOIN users u ON u.id = a.user_id
                ORDER BY a.id DESC
                LIMIT 1000
                """
            )
            st.dataframe(df, use_container_width=True, hide_index=True)


def page_users():
    st.subheader("المستخدمون والصلاحيات")

    roles = {
        "admin": "مدير",
        "accountant": "محاسب",
        "staff": "موظف",
    }

    with st.form("add_user"):
        full_name = st.text_input("الاسم الكامل")
        username = st.text_input("اسم المستخدم")
        password = st.text_input("كلمة المرور", type="password")
        role_label = st.selectbox("الصلاحية", list(roles.values()))
        save = st.form_submit_button("إضافة المستخدم")

    if save:
        if not full_name.strip() or not username.strip() or not password:
            st.error("أكمل البيانات المطلوبة.")
        elif len(password) < 6:
            st.error("كلمة المرور يجب أن تكون 6 أحرف على الأقل.")
        else:
            role = next(k for k, v in roles.items() if v == role_label)
            try:
                user_id = execute(
                    """
                    INSERT INTO users
                    (username, password_hash, full_name, role, active, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (
                        username.strip(),
                        hash_password(password),
                        full_name.strip(),
                        role,
                        now_text(),
                    ),
                    return_id=True,
                )
                log_action("إضافة مستخدم", "users", user_id, username)
                st.success("تم إنشاء المستخدم.")
            except sqlite3.IntegrityError:
                st.error("اسم المستخدم مستخدم بالفعل.")

    df = dataframe_query(
        """
        SELECT id AS 'ID',
               username AS 'اسم المستخدم',
               full_name AS 'الاسم',
               role AS 'الصلاحية',
               CASE WHEN active = 1 THEN 'نشط' ELSE 'موقوف' END AS 'الحالة',
               created_at AS 'تاريخ الإنشاء'
        FROM users
        ORDER BY id DESC
        """
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def page_database_tools():
    st.subheader("إعدادات النظام والنسخ الاحتياطي")

    st.write(f"ملف قاعدة البيانات: {DB_PATH.name}")
    st.write(f"مجلد النسخ الاحتياطية: {BACKUP_DIR.name}")

    if st.button("إنشاء نسخة احتياطية الآن"):
        path = create_backup()
        log_action("إنشاء نسخة احتياطية", None, None, path.name)
        st.success(f"تم إنشاء النسخة: {path.name}")

    backups = sorted(BACKUP_DIR.glob("*.db"), reverse=True)
    if backups:
        st.markdown("### النسخ الاحتياطية الموجودة")
        backup_df = pd.DataFrame(
            [
                {
                    "الملف": p.name,
                    "الحجم": f"{p.stat().st_size / 1024:.1f} KB",
                    "التاريخ": dt.datetime.fromtimestamp(
                        p.stat().st_mtime
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                }
                for p in backups[:50]
            ]
        )
        st.dataframe(
            backup_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("لا توجد نسخ احتياطية حتى الآن.")


def apply_css():
    st.markdown(
        """
        <style>
        .main {
            background-color: #f4f6f8;
            color: #333333;
        }

        div.stButton > button {
            background-color: #1a2a3a;
            color: #ffffff;
            border-radius: 4px;
            border: none;
            padding: 9px 18px;
            font-weight: 600;
        }

        div.stButton > button:hover {
            background-color: #2b4c7e;
            color: #ffffff;
        }

        h1, h2, h3 {
            color: #1a2a3a;
        }

        [data-testid="stMetricValue"] {
            font-size: 1.45rem;
        }

        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(
        page_title="نظام إدارة المركز التعليمي",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    init_db()
    apply_css()

    if not current_user():
        login_screen()
        return

    user = current_user()

    st.sidebar.title("نظام إدارة المركز")
    st.sidebar.write(user["full_name"])
    st.sidebar.caption(f"الصلاحية: {user['role']}")

    if st.sidebar.button("تسجيل الخروج"):
        logout()

    menu = ["لوحة التحكم"]

    if has_role("admin", "accountant", "staff"):
        menu += [
            "الطلاب",
            "الأساتذة",
            "المواد والكورسات",
            "حضور الطلاب",
            "تسجيل دفع",
            "أرصدة الطلاب",
            "ساعات الأساتذة",
        ]

    if has_role("admin", "accountant"):
        menu += [
            "مستحقات الأساتذة",
            "المصروفات",
            "الخزينة",
            "التقارير",
        ]

    if has_role("admin"):
        menu += [
            "المستخدمون",
            "النسخ الاحتياطي",
        ]

    choice = st.sidebar.radio("القائمة", menu)

    if choice == "لوحة التحكم":
        page_dashboard()
    elif choice == "الطلاب":
        page_students()
    elif choice == "الأساتذة":
        page_teachers()
    elif choice == "المواد والكورسات":
        page_subjects_courses()
    elif choice == "حضور الطلاب":
        page_student_attendance()
    elif choice == "تسجيل دفع":
        page_payment()
    elif choice == "أرصدة الطلاب":
        page_student_balances()
    elif choice == "ساعات الأساتذة":
        page_teacher_hours()
    elif choice == "مستحقات الأساتذة":
        page_teacher_payroll()
    elif choice == "المصروفات":
        page_expenses()
    elif choice == "الخزينة":
        page_cashbox()
    elif choice == "التقارير":
        page_reports()
    elif choice == "المستخدمون":
        page_users()
    elif choice == "النسخ الاحتياطي":
        page_database_tools()


if __name__ == "__main__":
    main()
