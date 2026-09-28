"""
نظام إدارة المركز التعليمي - النسخة المعدلة
المتطلبات: streamlit >= 1.30 , pandas , openpyxl
التشغيل:   streamlit run app.py
"""
import io
import re
import html
import sqlite3
import hashlib
import secrets
import datetime as dt
from pathlib import Path
from contextlib import contextmanager

import pandas as pd
import streamlit as st


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "center_management.db"
BACKUP_DIR = APP_DIR / "backups"

PBKDF2_ITERATIONS = 600_000
LEGACY_ITERATIONS = 120_000
MIN_PASSWORD_LEN = 8
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 5
KEEP_BACKUPS = 30

ROLES = {"admin": "مدير", "accountant": "محاسب", "staff": "موظف"}


# ---------------------------------------------------------------------------
# قاعدة البيانات
# ---------------------------------------------------------------------------
@contextmanager
def db(immediate=False):
    """اتصال آمن: commit عند النجاح، rollback عند الخطأ، وإغلاق دائماً."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_text():
    return dt.datetime.now().isoformat(timespec="seconds")


def today():
    return dt.date.today()


def audit(conn, action, table_name=None, record_id=None, details=None):
    """تسجيل العملية داخل نفس transaction العملية الأصلية."""
    user = st.session_state.get("user")
    conn.execute(
        """INSERT INTO audit_logs (user_id, action, table_name, record_id, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user["id"] if user else None, action, table_name, record_id, details, now_text()),
    )


def log_action(action, table_name=None, record_id=None, details=None):
    with db() as conn:
        audit(conn, action, table_name, record_id, details)


def execute(query, params=(), return_id=False, audit_info=None):
    """
    audit_info = (action, table, details) أو (action, table, details, record_id)
    يُسجَّل في نفس الـ transaction.
    """
    with db() as conn:
        cur = conn.execute(query, params)
        row_id = cur.lastrowid
        if audit_info:
            action, table_name, details = audit_info[:3]
            rec_id = audit_info[3] if len(audit_info) > 3 else row_id
            audit(conn, action, table_name, rec_id, details)
    return row_id if return_id else None


def insert_with_code(query, params, table, code_col, prefix, audit_action, details):
    """إدخال سجل ثم توليد الكود من الـ id نفسه (بدون تضارب بين مستخدمين)."""
    with db() as conn:
        cur = conn.execute(query, params)
        rid = cur.lastrowid
        code = f"{prefix}-{rid:06d}"
        conn.execute(f"UPDATE {table} SET {code_col} = ? WHERE id = ?", (code, rid))
        audit(conn, audit_action, table, rid, details)
    return rid, code


def dataframe_query(query, params=()):
    with db() as conn:
        return pd.read_sql_query(query, conn, params=params)


def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def add_column_if_missing(conn, table, column, definition):
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


SCHEMA = """
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
    rate REAL,
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
    void_reason TEXT,
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

CREATE TABLE IF NOT EXISTS day_closures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    closed_by INTEGER NOT NULL,
    closed_at TEXT NOT NULL,
    reopened_by INTEGER,
    reopened_at TEXT,
    status TEXT NOT NULL DEFAULT 'closed',
    notes TEXT,
    FOREIGN KEY(closed_by) REFERENCES users(id),
    FOREIGN KEY(reopened_by) REFERENCES users(id)
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

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS prevent_duplicate_student
BEFORE INSERT ON students
WHEN EXISTS (SELECT 1 FROM students WHERE lower(trim(name)) = lower(trim(NEW.name)))
BEGIN SELECT RAISE(ABORT, 'DUPLICATE_STUDENT'); END;

CREATE TRIGGER IF NOT EXISTS prevent_duplicate_teacher
BEFORE INSERT ON teachers
WHEN EXISTS (SELECT 1 FROM teachers WHERE lower(trim(name)) = lower(trim(NEW.name)))
BEGIN SELECT RAISE(ABORT, 'DUPLICATE_TEACHER'); END;

DROP TRIGGER IF EXISTS prevent_duplicate_course;
CREATE TRIGGER prevent_duplicate_course
BEFORE INSERT ON courses
WHEN EXISTS (
    SELECT 1 FROM courses
    WHERE lower(trim(name)) = lower(trim(NEW.name))
      AND COALESCE(subject_id, 0) = COALESCE(NEW.subject_id, 0)
      AND COALESCE(teacher_id, 0) = COALESCE(NEW.teacher_id, 0)
      AND COALESCE(start_date, '') = COALESCE(NEW.start_date, '')
)
BEGIN SELECT RAISE(ABORT, 'DUPLICATE_COURSE'); END;
"""


def init_db():
    BACKUP_DIR.mkdir(exist_ok=True)
    with db() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)

        # توافق مع قواعد البيانات القديمة
        for table, column, definition in [
            ("students", "student_code", "TEXT"),
            ("students", "address", "TEXT"),
            ("students", "notes", "TEXT"),
            ("students", "active", "INTEGER NOT NULL DEFAULT 1"),
            ("students", "created_at", "TEXT"),
            ("teachers", "teacher_code", "TEXT"),
            ("teachers", "phone", "TEXT"),
            ("teachers", "hourly_rate", "REAL NOT NULL DEFAULT 0"),
            ("teachers", "active", "INTEGER NOT NULL DEFAULT 1"),
            ("teachers", "created_at", "TEXT"),
            ("teacher_hours", "notes", "TEXT"),
            ("teacher_hours", "created_by", "INTEGER"),
            ("teacher_hours", "created_at", "TEXT"),
            ("teacher_hours", "rate", "REAL"),
            ("student_payments", "course_id", "INTEGER"),
            ("student_payments", "notes", "TEXT"),
            ("student_payments", "status", "TEXT NOT NULL DEFAULT 'completed'"),
            ("student_payments", "void_reason", "TEXT"),
            ("student_payments", "created_by", "INTEGER"),
            ("student_payments", "created_at", "TEXT"),
        ]:
            add_column_if_missing(conn, table, column, definition)

        now = now_text()
        for table in ("students", "teachers", "teacher_hours", "student_payments"):
            conn.execute(f"UPDATE {table} SET created_at = ? WHERE created_at IS NULL", (now,))
        conn.execute("UPDATE student_payments SET status = 'completed' WHERE status IS NULL OR status = ''")

        for row in conn.execute(
            "SELECT id FROM students WHERE student_code IS NULL OR student_code = ''"
        ).fetchall():
            conn.execute("UPDATE students SET student_code = ? WHERE id = ?",
                         (f"STU-{row['id']:06d}", row["id"]))
        for row in conn.execute(
            "SELECT id FROM teachers WHERE teacher_code IS NULL OR teacher_code = ''"
        ).fetchall():
            conn.execute("UPDATE teachers SET teacher_code = ? WHERE id = ?",
                         (f"TCH-{row['id']:06d}", row["id"]))

        # فهارس فريدة (قد تفشل لو في بيانات قديمة مكررة، فلا نوقف التطبيق)
        for sql in (
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_bankak_transaction_unique
               ON student_payments(transaction_number)
               WHERE payment_method = 'بنكك' AND transaction_number IS NOT NULL
                 AND transaction_number <> '' AND status = 'completed'""",
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_unique
               ON student_attendance(student_id, COALESCE(course_id, 0), date)""",
        ):
            try:
                conn.execute(sql)
            except sqlite3.IntegrityError:
                pass

        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_payments_date ON student_payments(date)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_date ON student_attendance(date)",
            "CREATE INDEX IF NOT EXISTS idx_teacher_hours_date ON teacher_hours(date)",
            "CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)",
            "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at)",
        ):
            conn.execute(sql)

        conn.executescript(TRIGGERS)


@st.cache_resource
def setup_database():
    init_db()
    return True


# ---------------------------------------------------------------------------
# كلمات المرور والمستخدمون
# ---------------------------------------------------------------------------
def hash_password(password, salt=None, iterations=PBKDF2_ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def _parse_hash(stored):
    parts = stored.split("$")
    if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
        return int(parts[1]), parts[2], parts[3]
    if len(parts) == 2:  # الصيغة القديمة salt$digest
        return LEGACY_ITERATIONS, parts[0], parts[1]
    raise ValueError("bad hash")


def verify_password(password, stored):
    try:
        iterations, salt, digest = _parse_hash(stored)
        check = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
        ).hex()
        return secrets.compare_digest(check, digest)
    except (ValueError, TypeError):
        return False


def needs_rehash(stored):
    try:
        return _parse_hash(stored)[0] < PBKDF2_ITERATIONS
    except ValueError:
        return True


def password_problem(password, username=""):
    if len(password) < MIN_PASSWORD_LEN:
        return f"كلمة المرور يجب أن تكون {MIN_PASSWORD_LEN} أحرف على الأقل."
    if not (re.search(r"[A-Za-z\u0621-\u064A]", password) and re.search(r"\d", password)):
        return "كلمة المرور يجب أن تحتوي على حروف وأرقام."
    if username and password.lower() == username.strip().lower():
        return "كلمة المرور لا يجب أن تطابق اسم المستخدم."
    return None


def current_user():
    return st.session_state.get("user")


def has_role(*roles):
    user = current_user()
    return bool(user and user["role"] in roles)


def require_role(*roles):
    if not has_role(*roles):
        st.error("ليس لديك صلاحية لهذه الصفحة.")
        return False
    return True


def refresh_user():
    """إعادة التحقق من المستخدم مع كل تشغيل (لو تم إيقافه أو تغيّرت صلاحيته)."""
    user = current_user()
    if not user:
        return None
    df = dataframe_query(
        "SELECT id, username, full_name, role FROM users WHERE id = ? AND active = 1",
        (user["id"],),
    )
    if df.empty:
        st.session_state.pop("user", None)
        return None
    st.session_state.user = df.iloc[0].to_dict()
    st.session_state.user["id"] = int(st.session_state.user["id"])
    return st.session_state.user


def get_user_count():
    return int(dataframe_query("SELECT COUNT(*) AS c FROM users")["c"].iloc[0])


def is_locked_out(username):
    cutoff = (dt.datetime.now() - dt.timedelta(minutes=LOCKOUT_MINUTES)).isoformat(timespec="seconds")
    df = dataframe_query(
        """SELECT COUNT(*) AS c FROM audit_logs
           WHERE action = 'فشل تسجيل دخول' AND details = ? AND created_at >= ?""",
        (username.strip().lower(), cutoff),
    )
    return int(df["c"].iloc[0]) >= MAX_FAILED_LOGINS


def login_user(username, password):
    """يرجع: ok / bad / locked"""
    username = username.strip()
    if is_locked_out(username):
        return "locked"
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?) AND active = 1", (username,)
        ).fetchone()
    if row and verify_password(password, row["password_hash"]):
        if needs_rehash(row["password_hash"]):
            execute("UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(password), row["id"]))
        st.session_state.user = {
            "id": int(row["id"]), "username": row["username"],
            "full_name": row["full_name"], "role": row["role"],
        }
        log_action("تسجيل دخول")
        return "ok"
    log_action("فشل تسجيل دخول", details=username.lower())
    return "bad"


def logout():
    if current_user():
        log_action("تسجيل خروج")
    st.session_state.pop("user", None)
    st.rerun()


# ---------------------------------------------------------------------------
# أدوات مساعدة
# ---------------------------------------------------------------------------
def format_money(value):
    try:
        return f"{float(value):,.0f} SDG"
    except (TypeError, ValueError):
        return "0 SDG"


def like_term(text):
    text = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{text}%"


def valid_phone(phone):
    phone = phone.strip()
    if not phone:
        return True
    digits = re.sub(r"[\s\-+()]", "", phone)
    return digits.isdigit() and 8 <= len(digits) <= 15


def is_day_closed(date_value):
    df = dataframe_query(
        "SELECT 1 FROM day_closures WHERE date = ? AND status = 'closed'", (str(date_value),)
    )
    return not df.empty


def require_day_open(date_value):
    if is_day_closed(date_value):
        st.error(
            f"اليوم {date_value} مقفل. لا يمكن تسجيل عملية جديدة لهذا التاريخ. "
            "إذا كان هناك خطأ، يجب على المدير فتح اليوم أولاً من شاشة الخزينة."
        )
        return False
    return True


def safe_cell(value):
    """منع حقن المعادلات عند فتح ملف Excel."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def download_excel(df, filename="report.xlsx"):
    clean = df.copy()
    for col in clean.columns:
        if clean[col].dtype == object:
            clean[col] = clean[col].map(safe_cell)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        clean.to_excel(writer, index=False, sheet_name="Report")
    st.download_button(
        "تحميل Excel",
        data=output.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"dl_{filename}",
    )


def create_backup():
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = BACKUP_DIR / f"center_management_{stamp}.db"
    source = sqlite3.connect(str(DB_PATH), timeout=30)
    target = sqlite3.connect(str(destination))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    # الاحتفاظ بآخر KEEP_BACKUPS نسخة فقط
    old = sorted(BACKUP_DIR.glob("*.db"), reverse=True)[KEEP_BACKUPS:]
    for p in old:
        p.unlink(missing_ok=True)
    return destination


def cash_totals(conn, date_str):
    def total(sql):
        return float(conn.execute(sql, (date_str,)).fetchone()["t"])

    income = total("""SELECT COALESCE(SUM(amount),0) AS t FROM student_payments
                      WHERE date=? AND payment_method='كاش' AND status='completed'""")
    expense = total("""SELECT COALESCE(SUM(amount),0) AS t FROM expenses
                       WHERE date=? AND payment_method='كاش' AND status='completed'""")
    teacher = total("""SELECT COALESCE(SUM(amount),0) AS t FROM teacher_payments
                       WHERE date=? AND payment_method='كاش'""")
    bankak = total("""SELECT COALESCE(SUM(amount),0) AS t FROM student_payments
                      WHERE date=? AND payment_method='بنكك' AND status='completed'""")
    return income, expense, teacher, bankak


# ---------------------------------------------------------------------------
# تسجيل الدخول
# ---------------------------------------------------------------------------
def login_screen():
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.container(border=True):
            st.markdown('<div class="login-brand">مركز التعليم</div>', unsafe_allow_html=True)
            st.markdown('<div class="login-title">نظام إدارة المركز</div>', unsafe_allow_html=True)
            st.markdown('<div class="login-subtitle">تسجيل الدخول إلى لوحة الإدارة</div>',
                        unsafe_allow_html=True)

            flash = st.session_state.pop("flash", None)
            if flash:
                st.success(flash)

            if get_user_count() == 0:
                st.info("أنشئ حساب المدير أولاً. هذه الشاشة تظهر في أول تشغيل فقط.")
                with st.form("first_admin"):
                    full_name = st.text_input("اسم المدير", placeholder="الاسم الكامل")
                    username = st.text_input("اسم المستخدم", placeholder="اسم الدخول")
                    password = st.text_input("كلمة المرور", type="password",
                                             placeholder=f"{MIN_PASSWORD_LEN} أحرف على الأقل (حروف وأرقام)")
                    password2 = st.text_input("تأكيد كلمة المرور", type="password")
                    confirmed = st.checkbox("أؤكد أن بيانات الحساب صحيحة")
                    submitted = st.form_submit_button("إنشاء الحساب", use_container_width=True)
                if submitted:
                    problem = password_problem(password, username)
                    if not full_name.strip() or not username.strip() or not password:
                        st.error("أكمل جميع البيانات المطلوبة.")
                    elif not confirmed:
                        st.warning("ضع علامة التأكيد قبل إنشاء الحساب.")
                    elif problem:
                        st.error(problem)
                    elif password != password2:
                        st.error("كلمتا المرور غير متطابقتين.")
                    else:
                        try:
                            with db(immediate=True) as conn:
                                if conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] > 0:
                                    raise RuntimeError("exists")
                                conn.execute(
                                    """INSERT INTO users (username, password_hash, full_name, role, active, created_at)
                                       VALUES (?, ?, ?, 'admin', 1, ?)""",
                                    (username.strip(), hash_password(password), full_name.strip(), now_text()),
                                )
                            st.session_state.flash = "تم إنشاء حساب المدير. يمكنك تسجيل الدخول الآن."
                            st.rerun()
                        except RuntimeError:
                            st.error("تم إنشاء حساب مدير بالفعل. حدّث الصفحة.")
                        except sqlite3.IntegrityError:
                            st.error("تعذر إنشاء الحساب. تحقق من البيانات.")
            else:
                with st.form("login_form"):
                    username = st.text_input("اسم المستخدم", placeholder="اكتب اسم المستخدم")
                    password = st.text_input("كلمة المرور", type="password", placeholder="اكتب كلمة المرور")
                    submitted = st.form_submit_button("دخول", use_container_width=True)
                if submitted:
                    result = login_user(username, password)
                    if result == "ok":
                        st.rerun()
                    elif result == "locked":
                        st.error(f"تم إيقاف الدخول مؤقتاً بسبب محاولات فاشلة. حاول بعد {LOCKOUT_MINUTES} دقائق.")
                    else:
                        st.error("اسم المستخدم أو كلمة المرور غير صحيحة.")


# ---------------------------------------------------------------------------
# لوحة التحكم
# ---------------------------------------------------------------------------
def page_dashboard():
    st.subheader("لوحة التحكم")
    st.markdown('<div class="section-note">نظرة سريعة على حركة المركز في اليوم والفترة الأخيرة.</div>',
                unsafe_allow_html=True)

    selected_date = st.date_input("التاريخ", today(), key="dashboard_date")
    date_str = str(selected_date)

    payments = dataframe_query(
        "SELECT amount, payment_method FROM student_payments WHERE date = ? AND status = 'completed'",
        (date_str,))
    expenses = dataframe_query(
        "SELECT amount, payment_method FROM expenses WHERE date = ? AND status = 'completed'",
        (date_str,))
    teacher_paid = dataframe_query(
        "SELECT amount FROM teacher_payments WHERE date = ?", (date_str,))
    attendance = dataframe_query(
        "SELECT status FROM student_attendance WHERE date = ?", (date_str,))

    total_income = float(payments["amount"].sum()) if not payments.empty else 0
    total_expense = float(expenses["amount"].sum()) if not expenses.empty else 0
    total_teacher = float(teacher_paid["amount"].sum()) if not teacher_paid.empty else 0
    cash_income = float(payments.loc[payments["payment_method"] == "كاش", "amount"].sum()) if not payments.empty else 0
    bank_income = float(payments.loc[payments["payment_method"] == "بنكك", "amount"].sum()) if not payments.empty else 0
    present = int((attendance["status"] == "حاضر").sum()) if not attendance.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("إيراد اليوم", format_money(total_income))
    c2.metric("مصروفات اليوم", format_money(total_expense))
    c3.metric("صافي اليوم", format_money(total_income - total_expense - total_teacher))
    c4.metric("حضور الطلاب", f"{present:,}")
    st.caption("صافي اليوم = الإيراد − المصروفات − مدفوعات الأساتذة.")

    c5, c6, c7, c8, c9 = st.columns(5)
    c5.metric("كاش", format_money(cash_income))
    c6.metric("بنكك", format_money(bank_income))
    c7.metric("دفع الأساتذة", format_money(total_teacher))
    c8.metric("عمليات الدفع", f"{len(payments):,}")
    c9.metric("عمليات المصروفات", f"{len(expenses):,}")

    st.markdown("### ملخص آخر 30 يوماً")
    since = str(today() - dt.timedelta(days=29))
    monthly = dataframe_query(
        """SELECT date, SUM(amount) AS income FROM student_payments
           WHERE status = 'completed' AND date >= ? GROUP BY date ORDER BY date""",
        (since,))
    if not monthly.empty:
        monthly["date"] = pd.to_datetime(monthly["date"])
        st.line_chart(monthly.set_index("date")[["income"]])
    else:
        st.info("لا توجد بيانات كافية لعرض الرسم البياني.")


# ---------------------------------------------------------------------------
# الطلاب
# ---------------------------------------------------------------------------
def page_students():
    st.subheader("إدارة الطلاب")
    st.caption("إضافة طالب جديد أو البحث عن طالب مسجل بدون تكرار.")

    tab_add, tab_list, tab_edit = st.tabs(["إضافة طالب", "قائمة الطلاب", "تعديل / إيقاف"])

    with tab_add:
        with st.form("add_student"):
            name = st.text_input("اسم الطالب الكامل", placeholder="مثال: محمد أحمد علي")
            phone = st.text_input("رقم الهاتف", placeholder="09XXXXXXXX")
            address = st.text_input("العنوان")
            notes = st.text_area("ملاحظات", height=90)
            confirmed = st.checkbox("أؤكد أن الطالب غير مسجل مسبقاً بهذه البيانات")
            save = st.form_submit_button("حفظ الطالب", use_container_width=True)
        if save:
            if not name.strip():
                st.error("اسم الطالب مطلوب.")
            elif not valid_phone(phone):
                st.error("رقم الهاتف غير صحيح.")
            elif not confirmed:
                st.warning("ضع علامة التأكيد قبل حفظ الطالب.")
            else:
                try:
                    _, code = insert_with_code(
                        """INSERT INTO students (name, phone, address, notes, active, created_at)
                           VALUES (?, ?, ?, ?, 1, ?)""",
                        (name.strip(), phone.strip(), address.strip(), notes.strip(), now_text()),
                        "students", "student_code", "STU", "إضافة طالب", name.strip())
                    st.success(f"تم حفظ الطالب بنجاح — الرقم: {code}")
                except sqlite3.IntegrityError as exc:
                    if "DUPLICATE_STUDENT" in str(exc):
                        st.error("هذا الطالب مسجل بالفعل. استخدم البحث في قائمة الطلاب.")
                    else:
                        st.error("تعذر حفظ الطالب. تحقق من البيانات.")

    with tab_list:
        search = st.text_input("بحث بالاسم أو الرقم أو الهاتف", key="student_search",
                               placeholder="اكتب جزءاً من الاسم أو الرقم")
        term = like_term(search)
        df = dataframe_query(
            """SELECT id AS 'ID', student_code AS 'رقم الطالب', name AS 'اسم الطالب',
                      phone AS 'الهاتف', address AS 'العنوان',
                      CASE WHEN active = 1 THEN 'نشط' ELSE 'موقوف' END AS 'الحالة'
               FROM students
               WHERE name LIKE ? ESCAPE '\\' OR student_code LIKE ? ESCAPE '\\' OR phone LIKE ? ESCAPE '\\'
               ORDER BY id DESC""",
            (term, term, term))
        st.dataframe(df, use_container_width=True, hide_index=True)
        if not df.empty:
            download_excel(df, "students.xlsx")

    with tab_edit:
        students = dataframe_query("SELECT id, student_code, name FROM students ORDER BY name")
        if students.empty:
            st.info("لا يوجد طلاب.")
        else:
            options = {f"{r['student_code']} - {r['name']}": int(r["id"]) for _, r in students.iterrows()}
            label = st.selectbox("اختر الطالب", list(options.keys()), key="edit_student_pick")
            sid = options[label]
            cur = dataframe_query("SELECT * FROM students WHERE id = ?", (sid,)).iloc[0]
            with st.form(f"edit_student_{sid}"):
                name = st.text_input("الاسم", value=cur["name"] or "")
                phone = st.text_input("الهاتف", value=cur["phone"] or "")
                address = st.text_input("العنوان", value=cur["address"] or "")
                notes = st.text_area("ملاحظات", value=cur["notes"] or "", height=90)
                active = st.checkbox("نشط", value=bool(cur["active"]))
                save = st.form_submit_button("حفظ التعديلات", use_container_width=True)
            if save:
                dup = dataframe_query(
                    "SELECT id FROM students WHERE lower(trim(name)) = lower(trim(?)) AND id <> ?",
                    (name, sid))
                if not name.strip():
                    st.error("الاسم مطلوب.")
                elif not valid_phone(phone):
                    st.error("رقم الهاتف غير صحيح.")
                elif not dup.empty:
                    st.error("يوجد طالب آخر بنفس الاسم.")
                else:
                    execute(
                        """UPDATE students SET name=?, phone=?, address=?, notes=?, active=? WHERE id=?""",
                        (name.strip(), phone.strip(), address.strip(), notes.strip(), int(active), sid),
                        audit_info=("تعديل طالب", "students", name.strip(), sid))
                    st.success("تم حفظ التعديلات.")
                    st.rerun()


# ---------------------------------------------------------------------------
# الأساتذة
# ---------------------------------------------------------------------------
def page_teachers():
    st.subheader("إدارة الأساتذة")
    st.caption("إضافة الأستاذ مرة واحدة ثم ربطه بالكورسات من شاشة الكورسات.")
    tab_add, tab_list, tab_edit = st.tabs(["إضافة أستاذ", "قائمة الأساتذة", "تعديل / إيقاف"])

    with tab_add:
        with st.form("add_teacher"):
            name = st.text_input("اسم الأستاذ الكامل", placeholder="مثال: أ. أحمد محمد")
            subject = st.text_input("المادة / التخصص")
            phone = st.text_input("رقم الهاتف")
            rate = st.number_input("سعر الساعة", min_value=0.0, step=100.0)
            confirmed = st.checkbox("أؤكد أن الأستاذ غير مسجل مسبقاً")
            save = st.form_submit_button("حفظ الأستاذ", use_container_width=True)
        if save:
            if not name.strip():
                st.error("اسم الأستاذ مطلوب.")
            elif not valid_phone(phone):
                st.error("رقم الهاتف غير صحيح.")
            elif not confirmed:
                st.warning("ضع علامة التأكيد قبل حفظ الأستاذ.")
            else:
                try:
                    _, code = insert_with_code(
                        """INSERT INTO teachers (name, subject, phone, hourly_rate, active, created_at)
                           VALUES (?, ?, ?, ?, 1, ?)""",
                        (name.strip(), subject.strip(), phone.strip(), rate, now_text()),
                        "teachers", "teacher_code", "TCH", "إضافة أستاذ", name.strip())
                    st.success(f"تم حفظ الأستاذ بنجاح — الرقم: {code}")
                except sqlite3.IntegrityError as exc:
                    if "DUPLICATE_TEACHER" in str(exc):
                        st.error("هذا الأستاذ مسجل بالفعل. استخدم قائمة الأساتذة.")
                    else:
                        st.error("تعذر حفظ الأستاذ. تحقق من البيانات.")

    with tab_list:
        search = st.text_input("بحث بالاسم أو الرقم أو المادة", key="teacher_search",
                               placeholder="اكتب جزءاً من الاسم")
        term = like_term(search)
        df = dataframe_query(
            """SELECT id AS 'ID', teacher_code AS 'رقم الأستاذ', name AS 'اسم الأستاذ',
                      subject AS 'المادة', phone AS 'الهاتف', hourly_rate AS 'سعر الساعة',
                      CASE WHEN active = 1 THEN 'نشط' ELSE 'موقوف' END AS 'الحالة'
               FROM teachers
               WHERE name LIKE ? ESCAPE '\\' OR teacher_code LIKE ? ESCAPE '\\' OR subject LIKE ? ESCAPE '\\'
               ORDER BY id DESC""",
            (term, term, term))
        st.dataframe(df, use_container_width=True, hide_index=True)
        if not df.empty:
            download_excel(df, "teachers.xlsx")

    with tab_edit:
        teachers = dataframe_query("SELECT id, teacher_code, name FROM teachers ORDER BY name")
        if teachers.empty:
            st.info("لا يوجد أساتذة.")
        else:
            options = {f"{r['teacher_code']} - {r['name']}": int(r["id"]) for _, r in teachers.iterrows()}
            label = st.selectbox("اختر الأستاذ", list(options.keys()), key="edit_teacher_pick")
            tid = options[label]
            cur = dataframe_query("SELECT * FROM teachers WHERE id = ?", (tid,)).iloc[0]
            with st.form(f"edit_teacher_{tid}"):
                name = st.text_input("الاسم", value=cur["name"] or "")
                subject = st.text_input("المادة", value=cur["subject"] or "")
                phone = st.text_input("الهاتف", value=cur["phone"] or "")
                rate = st.number_input("سعر الساعة", min_value=0.0, step=100.0,
                                       value=float(cur["hourly_rate"] or 0))
                active = st.checkbox("نشط", value=bool(cur["active"]))
                save = st.form_submit_button("حفظ التعديلات", use_container_width=True)
            st.caption("تغيير سعر الساعة يؤثر على الساعات المسجلة بعد التعديل فقط.")
            if save:
                dup = dataframe_query(
                    "SELECT id FROM teachers WHERE lower(trim(name)) = lower(trim(?)) AND id <> ?",
                    (name, tid))
                if not name.strip():
                    st.error("الاسم مطلوب.")
                elif not valid_phone(phone):
                    st.error("رقم الهاتف غير صحيح.")
                elif not dup.empty:
                    st.error("يوجد أستاذ آخر بنفس الاسم.")
                else:
                    execute(
                        "UPDATE teachers SET name=?, subject=?, phone=?, hourly_rate=?, active=? WHERE id=?",
                        (name.strip(), subject.strip(), phone.strip(), rate, int(active), tid),
                        audit_info=("تعديل أستاذ", "teachers", name.strip(), tid))
                    st.success("تم حفظ التعديلات.")
                    st.rerun()


# ---------------------------------------------------------------------------
# المواد والكورسات
# ---------------------------------------------------------------------------
def page_subjects_courses():
    st.subheader("المواد والكورسات")
    tab_subject, tab_course, tab_enroll = st.tabs(["المواد", "الكورسات", "تسجيل طالب في كورس"])

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
                    execute("INSERT INTO subjects (name, description, active) VALUES (?, ?, 1)",
                            (name.strip(), description.strip()),
                            audit_info=("إضافة مادة", "subjects", name.strip()))
                    st.success("تم حفظ المادة.")
                except sqlite3.IntegrityError:
                    st.error("هذه المادة موجودة بالفعل.")
        st.dataframe(
            dataframe_query("""SELECT id AS 'ID', name AS 'المادة', description AS 'الوصف'
                               FROM subjects WHERE active = 1 ORDER BY name"""),
            use_container_width=True, hide_index=True)

    with tab_course:
        subjects = dataframe_query("SELECT id, name FROM subjects WHERE active = 1 ORDER BY name")
        teachers = dataframe_query("SELECT id, name FROM teachers WHERE active = 1 ORDER BY name")

        if subjects.empty or teachers.empty:
            st.info("أضف مادة وأستاذاً أولاً.")
        else:
            subject_options = {r["name"]: int(r["id"]) for _, r in subjects.iterrows()}
            teacher_options = {r["name"]: int(r["id"]) for _, r in teachers.iterrows()}

            with st.form("add_course"):
                course_name = st.text_input("اسم الكورس")
                selected_subject = st.selectbox("المادة", list(subject_options.keys()))
                selected_teacher = st.selectbox("الأستاذ", list(teacher_options.keys()))
                fee = st.number_input("رسوم الكورس", min_value=0.0, step=100.0)
                sessions = st.number_input("عدد الحصص", min_value=0, step=1, value=0)
                start_date = st.date_input("بداية الكورس", today())
                end_date = st.date_input("نهاية الكورس", today())
                confirmed = st.checkbox("أؤكد أن هذا الكورس غير مسجل بنفس المادة والأستاذ وتاريخ البداية")
                save = st.form_submit_button("حفظ الكورس", use_container_width=True)

            if save:
                if not course_name.strip():
                    st.error("اسم الكورس مطلوب.")
                elif end_date < start_date:
                    st.error("نهاية الكورس لا يمكن أن تكون قبل البداية.")
                elif not confirmed:
                    st.warning("ضع علامة التأكيد قبل حفظ الكورس.")
                else:
                    try:
                        execute(
                            """INSERT INTO courses
                               (name, subject_id, teacher_id, fee, total_sessions, start_date, end_date, active)
                               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                            (course_name.strip(), subject_options[selected_subject],
                             teacher_options[selected_teacher], fee, int(sessions),
                             str(start_date), str(end_date)),
                            audit_info=("إضافة كورس", "courses", course_name.strip()))
                        st.success("تم حفظ الكورس.")
                    except sqlite3.IntegrityError as exc:
                        if "DUPLICATE_COURSE" in str(exc):
                            st.error("هذا الكورس مسجل بالفعل بنفس المادة والأستاذ وتاريخ البداية.")
                        else:
                            st.error("تعذر حفظ الكورس. تحقق من البيانات.")

        courses = dataframe_query(
            """SELECT c.id AS 'ID', c.name AS 'الكورس', s.name AS 'المادة', t.name AS 'الأستاذ',
                      c.fee AS 'الرسوم', c.total_sessions AS 'عدد الحصص',
                      c.start_date AS 'البداية', c.end_date AS 'النهاية',
                      CASE WHEN c.active = 1 THEN 'نشط' ELSE 'موقوف' END AS 'الحالة'
               FROM courses c
               LEFT JOIN subjects s ON s.id = c.subject_id
               LEFT JOIN teachers t ON t.id = c.teacher_id
               ORDER BY c.id DESC""")
        st.dataframe(courses, use_container_width=True, hide_index=True)

        if not courses.empty:
            with st.expander("إيقاف / تفعيل كورس"):
                opts = {f"#{r['ID']} - {r['الكورس']} ({r['الحالة']})": int(r["ID"])
                        for _, r in courses.iterrows()}
                pick = st.selectbox("الكورس", list(opts.keys()), key="course_toggle_pick")
                new_state = st.radio("الحالة الجديدة", ["نشط", "موقوف"], horizontal=True, key="course_toggle_state")
                if st.button("حفظ حالة الكورس"):
                    execute("UPDATE courses SET active = ? WHERE id = ?",
                            (1 if new_state == "نشط" else 0, opts[pick]),
                            audit_info=("تغيير حالة كورس", "courses", new_state, opts[pick]))
                    st.success("تم التحديث.")
                    st.rerun()

    with tab_enroll:
        students = dataframe_query(
            "SELECT id, name, student_code FROM students WHERE active = 1 ORDER BY name")
        courses = dataframe_query(
            "SELECT id, name, fee FROM courses WHERE active = 1 ORDER BY name")

        if students.empty or courses.empty:
            st.info("أضف طلاباً وكورسات أولاً.")
        else:
            student_options = {f"{r['student_code']} - {r['name']}": int(r["id"])
                               for _, r in students.iterrows()}
            course_options = {f"#{r['id']} - {r['name']} - {format_money(r['fee'])}": int(r["id"])
                              for _, r in courses.iterrows()}
            course_fees = {int(r["id"]): float(r["fee"]) for _, r in courses.iterrows()}

            with st.form("enroll_student"):
                selected_student = st.selectbox("الطالب", list(student_options.keys()))
                selected_course = st.selectbox("الكورس", list(course_options.keys()))
                agreed_fee = st.number_input("الرسوم المتفق عليها (اتركها 0 لاستخدام رسوم الكورس)",
                                             min_value=0.0, step=100.0)
                enrolled_date = st.date_input("تاريخ التسجيل", today())
                save = st.form_submit_button("تسجيل الطالب")

            if save:
                if require_day_open(enrolled_date):
                    course_id = course_options[selected_course]
                    fee_value = agreed_fee if agreed_fee > 0 else course_fees[course_id]
                    try:
                        execute(
                            """INSERT INTO enrollments (student_id, course_id, agreed_fee, enrolled_date, status)
                               VALUES (?, ?, ?, ?, 'active')""",
                            (student_options[selected_student], course_id, fee_value, str(enrolled_date)),
                            audit_info=("تسجيل طالب في كورس", "enrollments", selected_student))
                        st.success(f"تم تسجيل الطالب في الكورس بالرسوم: {format_money(fee_value)}")
                    except sqlite3.IntegrityError:
                        st.error("الطالب مسجل بالفعل في هذا الكورس.")


# ---------------------------------------------------------------------------
# حضور الطلاب
# ---------------------------------------------------------------------------
def page_student_attendance():
    st.subheader("حضور الطلاب")

    students = dataframe_query(
        "SELECT id, student_code, name FROM students WHERE active = 1 ORDER BY name")
    courses = dataframe_query(
        "SELECT id, name, teacher_id FROM courses WHERE active = 1 ORDER BY name")

    if students.empty:
        st.info("لا يوجد طلاب مسجلون.")
        return

    student_options = {f"{r['student_code']} - {r['name']}": int(r["id"]) for _, r in students.iterrows()}
    course_options = {"بدون كورس": None}
    course_teacher = {}
    for _, row in courses.iterrows():
        cid = int(row["id"])
        course_options[f"#{cid} - {row['name']}"] = cid
        course_teacher[cid] = int(row["teacher_id"]) if pd.notna(row["teacher_id"]) else None

    with st.form("student_attendance_form"):
        col1, col2 = st.columns(2)
        with col1:
            selected_student = st.selectbox("الطالب", list(student_options.keys()))
            attendance_date = st.date_input("التاريخ", today())
        with col2:
            selected_course = st.selectbox("الكورس", list(course_options.keys()))
            status = st.selectbox("الحالة", ["حاضر", "غائب", "متأخر", "اعتذر"])
        check_in = st.time_input("وقت الحضور (يُتجاهل للغائب)", dt.time(8, 0))
        notes = st.text_input("ملاحظات")
        save = st.form_submit_button("تسجيل الحضور")

    if save and require_day_open(attendance_date):
        student_id = student_options[selected_student]
        course_id = course_options[selected_course]
        teacher_id = course_teacher.get(course_id) if course_id else None

        enrolled = True
        if course_id:
            enrolled = not dataframe_query(
                "SELECT 1 FROM enrollments WHERE student_id=? AND course_id=? AND status='active'",
                (student_id, course_id)).empty
        duplicate = not dataframe_query(
            """SELECT 1 FROM student_attendance
               WHERE student_id=? AND COALESCE(course_id,0)=COALESCE(?,0) AND date=?""",
            (student_id, course_id, str(attendance_date))).empty

        if not enrolled:
            st.error("الطالب غير مسجل في هذا الكورس. سجّله أولاً من شاشة الكورسات.")
        elif duplicate:
            st.error("تم تسجيل حضور هذا الطالب لنفس الكورس في هذا اليوم من قبل.")
        else:
            try:
                execute(
                    """INSERT INTO student_attendance
                       (student_id, course_id, teacher_id, date, check_in, status, notes, created_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (student_id, course_id, teacher_id, str(attendance_date),
                     None if status == "غائب" else str(check_in), status, notes.strip(),
                     current_user()["id"], now_text()),
                    audit_info=("تسجيل حضور طالب", "student_attendance", selected_student))
                st.success("تم تسجيل الحضور.")
            except sqlite3.IntegrityError:
                st.error("تم تسجيل حضور هذا الطالب لنفس الكورس في هذا اليوم من قبل.")

    selected_date = st.date_input("عرض حضور يوم", today(), key="attendance_report_date")
    df = dataframe_query(
        """SELECT a.id AS 'ID', s.student_code AS 'رقم الطالب', s.name AS 'الطالب',
                  c.name AS 'الكورس', t.name AS 'الأستاذ', a.check_in AS 'وقت الحضور',
                  a.status AS 'الحالة', a.notes AS 'ملاحظات'
           FROM student_attendance a
           JOIN students s ON s.id = a.student_id
           LEFT JOIN courses c ON c.id = a.course_id
           LEFT JOIN teachers t ON t.id = a.teacher_id
           WHERE a.date = ? ORDER BY a.id DESC""",
        (str(selected_date),))
    st.dataframe(df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# المدفوعات
# ---------------------------------------------------------------------------
def page_payment():
    st.subheader("تسجيل دفع طالب")

    can_void = has_role("admin", "accountant")
    tabs = st.tabs(["تسجيل دفع", "إلغاء دفعة"] if can_void else ["تسجيل دفع"])

    with tabs[0]:
        students = dataframe_query(
            "SELECT id, student_code, name FROM students WHERE active = 1 ORDER BY name")
        courses = dataframe_query(
            """SELECT c.id, c.name, c.teacher_id, t.name AS teacher_name
               FROM courses c LEFT JOIN teachers t ON t.id = c.teacher_id
               WHERE c.active = 1 ORDER BY c.name""")

        if students.empty:
            st.info("أضف طلاباً أولاً.")
        else:
            student_options = {f"{r['student_code']} - {r['name']}": int(r["id"])
                               for _, r in students.iterrows()}
            course_options = {"بدون كورس": None}
            course_teacher = {}
            for _, row in courses.iterrows():
                cid = int(row["id"])
                course_options[f"#{cid} - {row['name']} - {row['teacher_name'] or 'بدون أستاذ'}"] = cid
                course_teacher[cid] = int(row["teacher_id"]) if pd.notna(row["teacher_id"]) else None

            with st.form("payment_form"):
                col1, col2 = st.columns(2)
                with col1:
                    selected_student = st.selectbox("الطالب", list(student_options.keys()))
                    amount = st.number_input("المبلغ", min_value=0.0, step=100.0)
                    payment_date = st.date_input("التاريخ", today())
                with col2:
                    selected_course = st.selectbox("الكورس", list(course_options.keys()))
                    method = st.selectbox("طريقة الدفع", ["كاش", "بنكك"])
                    transaction_number = st.text_input("رقم عملية بنكك (عند الدفع ببنكك)")
                notes = st.text_input("ملاحظات")
                save = st.form_submit_button("حفظ العملية")

            if save and require_day_open(payment_date):
                tx = transaction_number.strip()
                if amount <= 0:
                    st.error("المبلغ يجب أن يكون أكبر من صفر.")
                elif method == "بنكك" and not tx:
                    st.error("رقم عملية بنكك مطلوب.")
                elif method == "بنكك" and not dataframe_query(
                        """SELECT id FROM student_payments
                           WHERE payment_method='بنكك' AND transaction_number=? AND status='completed'""",
                        (tx,)).empty:
                    st.error("رقم عملية بنكك مستخدم من قبل.")
                else:
                    student_id = student_options[selected_student]
                    course_id = course_options[selected_course]
                    try:
                        execute(
                            """INSERT INTO student_payments
                               (student_id, teacher_id, course_id, date, amount, payment_method,
                                transaction_number, notes, status, created_by, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)""",
                            (student_id, course_teacher.get(course_id) if course_id else None,
                             course_id, str(payment_date), amount, method,
                             tx if method == "بنكك" else "", notes.strip(),
                             current_user()["id"], now_text()),
                            audit_info=("تسجيل دفع", "student_payments",
                                        f"{selected_student} - {format_money(amount)}"))
                        st.success("تم تسجيل العملية بنجاح.")
                        st.info(f"المبلغ: {format_money(amount)} | طريقة الدفع: {method}")

                        bal = dataframe_query(
                            """SELECT COALESCE((SELECT SUM(agreed_fee) FROM enrollments
                                                WHERE student_id=? AND status='active'),0)
                                    - COALESCE((SELECT SUM(amount) FROM student_payments
                                                WHERE student_id=? AND status='completed'),0) AS remaining""",
                            (student_id, student_id))["remaining"].iloc[0]
                        if bal < 0:
                            st.warning(f"تنبيه: إجمالي مدفوعات الطالب تجاوز رسومه بمقدار {format_money(-bal)}.")
                    except sqlite3.IntegrityError:
                        st.error("تعذر حفظ العملية. قد يكون رقم بنكك مستخدماً بالفعل.")

    if can_void:
        with tabs[1]:
            st.caption("الإلغاء لا يحذف العملية؛ يغيّر حالتها إلى ملغاة مع سبب، وتُستبعد من التقارير والأرصدة.")
            void_date = st.date_input("تاريخ العمليات", today(), key="void_date")
            recent = dataframe_query(
                """SELECT p.id, s.name AS student, p.amount, p.payment_method, p.transaction_number
                   FROM student_payments p JOIN students s ON s.id = p.student_id
                   WHERE p.date = ? AND p.status = 'completed' ORDER BY p.id DESC""",
                (str(void_date),))
            if recent.empty:
                st.info("لا توجد مدفوعات فعّالة في هذا التاريخ.")
            else:
                opts = {
                    f"#{r['id']} - {r['student']} - {format_money(r['amount'])} - {r['payment_method']}": int(r["id"])
                    for _, r in recent.iterrows()
                }
                with st.form("void_payment_form"):
                    pick = st.selectbox("العملية", list(opts.keys()))
                    reason = st.text_input("سبب الإلغاء")
                    confirm = st.checkbox("أؤكد إلغاء هذه العملية")
                    go = st.form_submit_button("إلغاء العملية")
                if go:
                    if not reason.strip():
                        st.error("سبب الإلغاء مطلوب.")
                    elif not confirm:
                        st.warning("ضع علامة التأكيد أولاً.")
                    elif require_day_open(void_date):
                        pid = opts[pick]
                        execute(
                            "UPDATE student_payments SET status='void', void_reason=? WHERE id=?",
                            (reason.strip(), pid),
                            audit_info=("إلغاء دفعة", "student_payments", reason.strip(), pid))
                        st.success("تم إلغاء العملية.")
                        st.rerun()


def page_student_balances():
    st.subheader("أرصدة الطلاب")
    df = dataframe_query(
        """SELECT s.id, s.student_code AS 'رقم الطالب', s.name AS 'اسم الطالب',
                  COALESCE(e.total_fee, 0) AS 'الرسوم',
                  COALESCE(p.paid, 0) AS 'المدفوع',
                  COALESCE(e.total_fee, 0) - COALESCE(p.paid, 0) AS 'المتبقي'
           FROM students s
           LEFT JOIN (SELECT student_id, SUM(agreed_fee) AS total_fee FROM enrollments
                      WHERE status = 'active' GROUP BY student_id) e ON e.student_id = s.id
           LEFT JOIN (SELECT student_id, SUM(amount) AS paid FROM student_payments
                      WHERE status = 'completed' GROUP BY student_id) p ON p.student_id = s.id
           WHERE s.active = 1 ORDER BY s.name""")
    view = df.drop(columns=["id"])
    st.dataframe(view, use_container_width=True, hide_index=True)
    if not view.empty:
        st.metric("إجمالي المتبقي على الطلاب", format_money(view["المتبقي"].clip(lower=0).sum()))
        download_excel(view, "student_balances.xlsx")


# ---------------------------------------------------------------------------
# الأساتذة: الساعات والمستحقات
# ---------------------------------------------------------------------------
def page_teacher_hours():
    st.subheader("ساعات عمل الأساتذة")

    teachers = dataframe_query(
        "SELECT id, teacher_code, name, hourly_rate FROM teachers WHERE active = 1 ORDER BY name")
    if teachers.empty:
        st.info("أضف أساتذة أولاً.")
        return

    teacher_options = {f"{r['teacher_code']} - {r['name']}": int(r["id"]) for _, r in teachers.iterrows()}
    rates = {int(r["id"]): float(r["hourly_rate"]) for _, r in teachers.iterrows()}

    with st.form("teacher_hours_form"):
        selected_teacher = st.selectbox("الأستاذ", list(teacher_options.keys()))
        work_date = st.date_input("التاريخ", today())
        col1, col2 = st.columns(2)
        with col1:
            check_in = st.time_input("وقت الدخول", dt.time(8, 0))
        with col2:
            check_out = st.time_input("وقت الخروج", dt.time(14, 0))
        notes = st.text_input("ملاحظات")
        save = st.form_submit_button("تسجيل الساعات")

    if save and require_day_open(work_date):
        start = dt.datetime.combine(work_date, check_in)
        end = dt.datetime.combine(work_date, check_out)
        teacher_id = teacher_options[selected_teacher]
        if end <= start:
            st.error("وقت الخروج يجب أن يكون بعد وقت الدخول.")
        elif not dataframe_query(
                """SELECT 1 FROM teacher_hours
                   WHERE teacher_id=? AND date=? AND check_in < ? AND check_out > ?""",
                (teacher_id, str(work_date), str(check_out), str(check_in))).empty:
            st.error("توجد فترة مسجلة لنفس الأستاذ تتداخل مع هذا الوقت.")
        else:
            hours = round((end - start).total_seconds() / 3600, 2)
            execute(
                """INSERT INTO teacher_hours
                   (teacher_id, date, check_in, check_out, hours_worked, rate, notes, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (teacher_id, str(work_date), str(check_in), str(check_out), hours,
                 rates[teacher_id], notes.strip(), current_user()["id"], now_text()),
                audit_info=("تسجيل ساعات أستاذ", "teacher_hours", selected_teacher))
            st.success(f"تم تسجيل {hours:.2f} ساعة.")

    selected_date = st.date_input("عرض الساعات ليوم", today(), key="teacher_hours_date")
    df = dataframe_query(
        """SELECT h.id AS 'ID', t.teacher_code AS 'رقم الأستاذ', t.name AS 'الأستاذ',
                  h.check_in AS 'الدخول', h.check_out AS 'الخروج', h.hours_worked AS 'الساعات',
                  h.hours_worked * COALESCE(h.rate, t.hourly_rate) AS 'المستحق'
           FROM teacher_hours h JOIN teachers t ON t.id = h.teacher_id
           WHERE h.date = ? ORDER BY h.id DESC""",
        (str(selected_date),))
    st.dataframe(df, use_container_width=True, hide_index=True)


def page_teacher_payroll():
    st.subheader("مستحقات الأساتذة")

    start_date = st.date_input("من تاريخ", today().replace(day=1), key="payroll_start")
    end_date = st.date_input("إلى تاريخ", today(), key="payroll_end")
    if end_date < start_date:
        st.error("الفترة غير صحيحة.")
        return

    df = dataframe_query(
        """SELECT t.id, t.teacher_code AS 'رقم الأستاذ', t.name AS 'الأستاذ',
                  t.hourly_rate AS 'سعر الساعة',
                  COALESCE(SUM(h.hours_worked), 0) AS 'الساعات',
                  COALESCE(SUM(h.hours_worked * COALESCE(h.rate, t.hourly_rate)), 0) AS 'المستحق',
                  COALESCE((SELECT SUM(tp.amount) FROM teacher_payments tp
                            WHERE tp.teacher_id = t.id AND tp.date BETWEEN ? AND ?), 0) AS 'المدفوع'
           FROM teachers t
           LEFT JOIN teacher_hours h ON h.teacher_id = t.id AND h.date BETWEEN ? AND ?
           WHERE t.active = 1 GROUP BY t.id ORDER BY t.name""",
        (str(start_date), str(end_date), str(start_date), str(end_date)))

    if df.empty:
        st.info("لا توجد بيانات.")
        return

    df["المتبقي"] = df["المستحق"] - df["المدفوع"]
    view = df.drop(columns=["id"])
    st.dataframe(view, use_container_width=True, hide_index=True)
    download_excel(view, "teacher_payroll.xlsx")

    if has_role("admin", "accountant"):
        options = {f"{r['رقم الأستاذ']} - {r['الأستاذ']}": int(r["id"]) for _, r in df.iterrows()}
        st.markdown("### تسجيل دفعة لأستاذ")
        with st.form("teacher_payment_form"):
            selected_teacher = st.selectbox("الأستاذ", list(options.keys()))
            payment_date = st.date_input("تاريخ الدفع", today())
            amount = st.number_input("المبلغ المدفوع", min_value=0.0, step=100.0)
            method = st.selectbox("طريقة الدفع", ["كاش", "بنكك", "تحويل بنكي"])
            notes = st.text_input("ملاحظات")
            save = st.form_submit_button("تسجيل الدفع")

        if save and require_day_open(payment_date):
            if amount <= 0:
                st.error("المبلغ يجب أن يكون أكبر من صفر.")
            else:
                execute(
                    """INSERT INTO teacher_payments
                       (teacher_id, date, amount, payment_method, notes, created_by, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (options[selected_teacher], str(payment_date), amount, method,
                     notes.strip(), current_user()["id"], now_text()),
                    audit_info=("دفع مستحق أستاذ", "teacher_payments", selected_teacher))
                st.success("تم تسجيل الدفع.")
                st.rerun()


# ---------------------------------------------------------------------------
# المصروفات
# ---------------------------------------------------------------------------
def page_expenses():
    st.subheader("المصروفات")
    categories = ["إيجار", "كهرباء", "مياه", "إنترنت", "رواتب", "صيانة",
                  "أدوات", "تسويق", "مواصلات", "أخرى"]

    with st.form("expense_form"):
        expense_date = st.date_input("التاريخ", today())
        category = st.selectbox("البند", categories)
        description = st.text_input("وصف المصروف")
        amount = st.number_input("المبلغ", min_value=0.0, step=100.0)
        method = st.selectbox("طريقة الدفع", ["كاش", "بنكك", "تحويل بنكي"])
        reference = st.text_input("المرجع / رقم العملية")
        save = st.form_submit_button("حفظ المصروف")

    if save and require_day_open(expense_date):
        if not description.strip():
            st.error("وصف المصروف مطلوب.")
        elif amount <= 0:
            st.error("المبلغ يجب أن يكون أكبر من صفر.")
        else:
            execute(
                """INSERT INTO expenses
                   (date, category, description, amount, payment_method, reference, status, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?)""",
                (str(expense_date), category, description.strip(), amount, method,
                 reference.strip(), current_user()["id"], now_text()),
                audit_info=("إضافة مصروف", "expenses", description.strip()))
            st.success("تم حفظ المصروف.")

    selected_date = st.date_input("عرض مصروفات يوم", today(), key="expense_report_date")
    df = dataframe_query(
        """SELECT id AS 'ID', category AS 'البند', description AS 'الوصف', amount AS 'المبلغ',
                  payment_method AS 'طريقة الدفع', reference AS 'المرجع'
           FROM expenses WHERE date = ? AND status = 'completed' ORDER BY id DESC""",
        (str(selected_date),))
    st.dataframe(df, use_container_width=True, hide_index=True)
    if not df.empty:
        st.metric("إجمالي المصروفات", format_money(df["المبلغ"].sum()))


# ---------------------------------------------------------------------------
# الخزينة والإقفال
# ---------------------------------------------------------------------------
def page_cashbox():
    st.subheader("الخزينة والإقفال اليومي")
    st.caption("الإقفال يمنع إضافة أي حركة مالية أو حضور أو ساعات أو تسجيل في الكورس لذلك اليوم حتى يتم فتحه من المدير.")

    selected_date = st.date_input("تاريخ اليوم", today(), key="cashbox_date")
    date_str = str(selected_date)
    closed = is_day_closed(date_str)

    with db() as conn:
        income, expense, teacher_paid, bankak_income = cash_totals(conn, date_str)
        row = conn.execute("SELECT opening_balance FROM cashbox WHERE date = ?", (date_str,)).fetchone()
        if row:
            opening = float(row["opening_balance"])
        else:  # الرصيد الافتتاحي = النقد الفعلي عند آخر إقفال سابق
            prev = conn.execute(
                """SELECT counted_cash FROM cashbox
                   WHERE date < ? AND counted_cash IS NOT NULL ORDER BY date DESC LIMIT 1""",
                (date_str,)).fetchone()
            opening = float(prev["counted_cash"]) if prev else 0.0

    expected = opening + income - expense - teacher_paid

    if closed:
        st.success(f"اليوم {date_str} مقفل بالفعل. لا توجد حركات جديدة مسموحة لهذا التاريخ.")
    else:
        st.info(f"اليوم {date_str} مفتوح للتسجيل.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("كاش داخل", format_money(income))
    c2.metric("بنكك", format_money(bankak_income))
    c3.metric("كاش خارج", format_money(expense + teacher_paid))
    c4.metric("الرصيد المتوقع", format_money(expected))

    if not closed and has_role("admin", "accountant"):
        with st.form(f"cashbox_form_{date_str}"):
            opening_balance = st.number_input("الرصيد الافتتاحي", min_value=0.0, value=opening, step=100.0)
            counted_cash = st.number_input("النقد الفعلي الموجود عند الإقفال (إلزامي)",
                                           min_value=0.0, value=None, step=100.0)
            notes = st.text_input("ملاحظات الإقفال")
            confirm_close = st.checkbox("أؤكد أنني راجعت عمليات اليوم وأريد إقفاله نهائياً")
            close_day = st.form_submit_button("إقفال اليوم", use_container_width=True)

        if close_day:
            if counted_cash is None:
                st.error("أدخل النقد الفعلي الموجود قبل الإقفال.")
            elif not confirm_close:
                st.warning("ضع علامة التأكيد قبل إقفال اليوم.")
            else:
                result = None
                try:
                    with db(immediate=True) as conn:
                        if conn.execute(
                                "SELECT 1 FROM day_closures WHERE date=? AND status='closed'",
                                (date_str,)).fetchone():
                            result = "already"
                        else:
                            # إعادة الحساب داخل نفس الـ transaction لتفادي الأرقام القديمة
                            inc, exp, tch, _ = cash_totals(conn, date_str)
                            difference = counted_cash - (opening_balance + inc - exp - tch)
                            uid, ts = current_user()["id"], now_text()
                            conn.execute(
                                """INSERT INTO cashbox
                                   (date, opening_balance, cash_in, cash_out, counted_cash, difference,
                                    notes, closed_by, closed_at)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                   ON CONFLICT(date) DO UPDATE SET
                                     opening_balance=excluded.opening_balance, cash_in=excluded.cash_in,
                                     cash_out=excluded.cash_out, counted_cash=excluded.counted_cash,
                                     difference=excluded.difference, notes=excluded.notes,
                                     closed_by=excluded.closed_by, closed_at=excluded.closed_at""",
                                (date_str, opening_balance, inc, exp + tch, counted_cash,
                                 difference, notes.strip(), uid, ts))
                            conn.execute(
                                """INSERT INTO day_closures (date, closed_by, closed_at, status, notes)
                                   VALUES (?, ?, ?, 'closed', ?)
                                   ON CONFLICT(date) DO UPDATE SET
                                     closed_by=excluded.closed_by, closed_at=excluded.closed_at,
                                     reopened_by=NULL, reopened_at=NULL, status='closed',
                                     notes=excluded.notes""",
                                (date_str, uid, ts, notes.strip()))
                            audit(conn, "إقفال اليوم", "day_closures", None,
                                  f"{date_str} - الفرق {difference}")
                            result = difference
                except sqlite3.Error:
                    st.error("تعذر إقفال اليوم. تحقق من البيانات.")
                    return

                if result == "already":
                    st.warning("اليوم مقفل بالفعل.")
                elif result == 0:
                    st.session_state.flash_main = ("success", "تم إقفال اليوم بنجاح والرصيد مطابق.")
                    st.rerun()
                else:
                    st.session_state.flash_main = (
                        "warning", f"تم إقفال اليوم. يوجد فرق: {format_money(result)}")
                    st.rerun()
    elif not closed:
        st.caption("إقفال اليوم متاح للمدير والمحاسب فقط.")

    if closed and has_role("admin"):
        st.markdown("### فتح اليوم")
        st.warning("فتح اليوم يسمح بإضافة حركات جديدة. استخدمه فقط إذا اكتشفت خطأ أو عملية ناقصة.")
        with st.form("reopen_day_form"):
            reason = st.text_input("سبب فتح اليوم", placeholder="مثال: تصحيح عملية بنكك")
            confirm_reopen = st.checkbox("أؤكد أنني أريد فتح هذا اليوم")
            reopen = st.form_submit_button("فتح اليوم للمدير", use_container_width=True)
        if reopen:
            if not reason.strip():
                st.error("سبب فتح اليوم مطلوب.")
            elif not confirm_reopen:
                st.warning("ضع علامة التأكيد أولاً.")
            else:
                with db() as conn:
                    conn.execute(
                        """UPDATE day_closures
                           SET status='reopened', reopened_by=?, reopened_at=?,
                               notes=COALESCE(notes,'') || ?
                           WHERE date=? AND status='closed'""",
                        (current_user()["id"], now_text(), f" | فتح: {reason.strip()}", date_str))
                    audit(conn, "فتح يوم مقفل", "day_closures", None, f"{date_str} - {reason.strip()}")
                st.session_state.flash_main = ("success", "تم فتح اليوم. يمكنك الآن تصحيح أو إضافة العمليات.")
                st.rerun()

    st.markdown("### سجل الإقفال")
    closure_df = dataframe_query(
        """SELECT d.date AS 'التاريخ',
                  CASE WHEN d.status='closed' THEN 'مقفل' ELSE 'مفتوح بعد الإقفال' END AS 'الحالة',
                  u.full_name AS 'أقفل بواسطة', d.closed_at AS 'وقت الإقفال',
                  ru.full_name AS 'فتح بواسطة', d.reopened_at AS 'وقت الفتح', d.notes AS 'الملاحظات'
           FROM day_closures d
           LEFT JOIN users u ON u.id = d.closed_by
           LEFT JOIN users ru ON ru.id = d.reopened_by
           ORDER BY d.date DESC LIMIT 100""")
    st.dataframe(closure_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# التقارير
# ---------------------------------------------------------------------------
def show_or_info(df, empty_msg):
    if df.empty:
        st.info(empty_msg)
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


def page_reports():
    st.subheader("التقارير")
    st.caption("اختر التقرير المطلوب. كل التقارير تستخدم نفس قاعدة البيانات وبها رقم بنكك عند الدفع ببنكك.")

    tab_daily, tab_period, tab_attendance, tab_cash, tab_audit = st.tabs(
        ["التقرير اليومي", "تقرير الفترة", "الحضور والساعات", "الخزينة", "سجل العمليات"])

    with tab_daily:
        selected_date = st.date_input("التاريخ", today(), key="reports_date")
        date_str = str(selected_date)

        payments = dataframe_query(
            """SELECT p.id AS 'رقم العملية', s.student_code AS 'رقم الطالب', s.name AS 'الطالب',
                      c.name AS 'الكورس', t.name AS 'الأستاذ', p.amount AS 'المبلغ',
                      p.payment_method AS 'طريقة الدفع',
                      COALESCE(NULLIF(p.transaction_number,''), '-') AS 'رقم بنكك',
                      p.date AS 'التاريخ', p.status AS 'الحالة'
               FROM student_payments p
               JOIN students s ON s.id = p.student_id
               LEFT JOIN courses c ON c.id = p.course_id
               LEFT JOIN teachers t ON t.id = p.teacher_id
               WHERE p.date = ? ORDER BY p.id DESC""", (date_str,))
        expenses = dataframe_query(
            """SELECT id AS 'رقم المصروف', category AS 'البند', description AS 'الوصف',
                      amount AS 'المبلغ', payment_method AS 'طريقة الدفع',
                      COALESCE(NULLIF(reference,''), '-') AS 'المرجع', date AS 'التاريخ'
               FROM expenses WHERE date = ? AND status = 'completed' ORDER BY id DESC""", (date_str,))
        teacher_payments = dataframe_query(
            """SELECT tp.id AS 'رقم الدفع', t.teacher_code AS 'رقم الأستاذ', t.name AS 'الأستاذ',
                      tp.amount AS 'المبلغ', tp.payment_method AS 'طريقة الدفع',
                      tp.notes AS 'ملاحظات', tp.date AS 'التاريخ'
               FROM teacher_payments tp JOIN teachers t ON t.id = tp.teacher_id
               WHERE tp.date = ? ORDER BY tp.id DESC""", (date_str,))
        attendance = dataframe_query(
            """SELECT a.id AS 'ID', s.student_code AS 'رقم الطالب', s.name AS 'الطالب',
                      c.name AS 'الكورس', t.name AS 'الأستاذ', a.check_in AS 'وقت الحضور',
                      a.status AS 'الحالة', a.notes AS 'ملاحظات'
               FROM student_attendance a JOIN students s ON s.id = a.student_id
               LEFT JOIN courses c ON c.id = a.course_id
               LEFT JOIN teachers t ON t.id = a.teacher_id
               WHERE a.date = ? ORDER BY a.id DESC""", (date_str,))
        teacher_hours = dataframe_query(
            """SELECT h.id AS 'ID', t.teacher_code AS 'رقم الأستاذ', t.name AS 'الأستاذ',
                      h.check_in AS 'الدخول', h.check_out AS 'الخروج', h.hours_worked AS 'الساعات',
                      h.hours_worked * COALESCE(h.rate, t.hourly_rate) AS 'المستحق'
               FROM teacher_hours h JOIN teachers t ON t.id = h.teacher_id
               WHERE h.date = ? ORDER BY h.id DESC""", (date_str,))

        done = payments[payments["الحالة"] == "completed"] if not payments.empty else payments
        total_income = float(done["المبلغ"].sum()) if not done.empty else 0
        cash_income = float(done.loc[done["طريقة الدفع"] == "كاش", "المبلغ"].sum()) if not done.empty else 0
        bankak_income = float(done.loc[done["طريقة الدفع"] == "بنكك", "المبلغ"].sum()) if not done.empty else 0
        total_expense = float(expenses["المبلغ"].sum()) if not expenses.empty else 0
        total_teacher = float(teacher_payments["المبلغ"].sum()) if not teacher_payments.empty else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("إيرادات", format_money(total_income))
        c2.metric("مصروفات", format_money(total_expense))
        c3.metric("دفع الأساتذة", format_money(total_teacher))
        c4.metric("كاش", format_money(cash_income))
        c5.metric("بنكك", format_money(bankak_income))

        st.markdown("### مدفوعات الطلاب")
        show_or_info(payments, "لا توجد مدفوعات في هذا اليوم.")
        if not payments.empty:
            download_excel(payments, f"daily_payments_{date_str}.xlsx")
        st.markdown("### المصروفات")
        show_or_info(expenses, "لا توجد مصروفات في هذا اليوم.")
        if not expenses.empty:
            download_excel(expenses, f"daily_expenses_{date_str}.xlsx")
        st.markdown("### مدفوعات الأساتذة")
        show_or_info(teacher_payments, "لا توجد مدفوعات للأساتذة في هذا اليوم.")
        st.markdown("### حضور الطلاب")
        show_or_info(attendance, "لا يوجد حضور مسجل.")
        st.markdown("### ساعات الأساتذة")
        show_or_info(teacher_hours, "لا توجد ساعات مسجلة.")

    with tab_period:
        start_date = st.date_input("من", today().replace(day=1), key="period_start")
        end_date = st.date_input("إلى", today(), key="period_end")
        if end_date < start_date:
            st.error("الفترة غير صحيحة.")
        else:
            rng = (str(start_date), str(end_date))
            parts = [
                dataframe_query("""SELECT date, SUM(amount) AS income FROM student_payments
                                   WHERE date BETWEEN ? AND ? AND status='completed' GROUP BY date""", rng),
                dataframe_query("""SELECT date, SUM(amount) AS expense FROM expenses
                                   WHERE date BETWEEN ? AND ? AND status='completed' GROUP BY date""", rng),
                dataframe_query("""SELECT date, SUM(amount) AS teacher_paid FROM teacher_payments
                                   WHERE date BETWEEN ? AND ? GROUP BY date""", rng),
            ]
            report = pd.DataFrame({"date": pd.date_range(start_date, end_date)})
            for part in parts:
                if not part.empty:
                    part["date"] = pd.to_datetime(part["date"])
                    report = report.merge(part, on="date", how="left")
            for col in ("income", "expense", "teacher_paid"):
                if col not in report.columns:
                    report[col] = 0
                report[col] = report[col].fillna(0)
            report["net"] = report["income"] - report["expense"] - report["teacher_paid"]

            st.line_chart(report.set_index("date")[["income", "expense", "teacher_paid", "net"]])
            shown = report.copy()
            shown["date"] = shown["date"].dt.strftime("%Y-%m-%d")
            st.dataframe(shown, use_container_width=True, hide_index=True)
            m1, m2, m3 = st.columns(3)
            m1.metric("إجمالي الإيرادات", format_money(report["income"].sum()))
            m2.metric("إجمالي المصروفات", format_money(report["expense"].sum() + report["teacher_paid"].sum()))
            m3.metric("صافي الفترة", format_money(report["net"].sum()))
            download_excel(shown, "period_report.xlsx")

    with tab_attendance:
        selected_date = st.date_input("التاريخ", today(), key="report_attendance_date")
        date_str = str(selected_date)
        attendance = dataframe_query(
            """SELECT s.student_code AS 'رقم الطالب', s.name AS 'الطالب', c.name AS 'الكورس',
                      t.name AS 'الأستاذ', a.check_in AS 'الحضور', a.status AS 'الحالة', a.notes AS 'ملاحظات'
               FROM student_attendance a JOIN students s ON s.id = a.student_id
               LEFT JOIN courses c ON c.id = a.course_id LEFT JOIN teachers t ON t.id = a.teacher_id
               WHERE a.date = ? ORDER BY a.id DESC""", (date_str,))
        hours = dataframe_query(
            """SELECT t.teacher_code AS 'رقم الأستاذ', t.name AS 'الأستاذ', h.check_in AS 'الدخول',
                      h.check_out AS 'الخروج', h.hours_worked AS 'الساعات',
                      h.hours_worked * COALESCE(h.rate, t.hourly_rate) AS 'المستحق'
               FROM teacher_hours h JOIN teachers t ON t.id = h.teacher_id
               WHERE h.date = ? ORDER BY h.id DESC""", (date_str,))
        left, right = st.columns(2)
        with left:
            st.markdown("### حضور الطلاب")
            show_or_info(attendance, "لا يوجد حضور مسجل.")
        with right:
            st.markdown("### ساعات الأساتذة")
            show_or_info(hours, "لا توجد ساعات مسجلة.")

    with tab_cash:
        selected_date = st.date_input("التاريخ", today(), key="report_cash_date")
        date_str = str(selected_date)
        cash = dataframe_query(
            """SELECT payment_method AS 'طريقة الدفع', SUM(amount) AS 'الإجمالي', COUNT(*) AS 'عدد العمليات'
               FROM student_payments WHERE date = ? AND status = 'completed' GROUP BY payment_method""",
            (date_str,))
        exp = dataframe_query(
            """SELECT payment_method AS 'طريقة الدفع', SUM(amount) AS 'الإجمالي', COUNT(*) AS 'عدد العمليات'
               FROM expenses WHERE date = ? AND status = 'completed' GROUP BY payment_method""",
            (date_str,))
        closure = dataframe_query(
            """SELECT d.date AS 'التاريخ',
                      CASE WHEN d.status='closed' THEN 'مقفل' ELSE 'مفتوح بعد الإقفال' END AS 'الحالة',
                      u.full_name AS 'أقفل بواسطة', d.closed_at AS 'وقت الإقفال',
                      ru.full_name AS 'فتح بواسطة', d.reopened_at AS 'وقت الفتح', d.notes AS 'الملاحظات'
               FROM day_closures d
               LEFT JOIN users u ON u.id = d.closed_by
               LEFT JOIN users ru ON ru.id = d.reopened_by
               WHERE d.date = ?""", (date_str,))
        st.markdown("### ملخص التحصيل")
        show_or_info(cash, "لا يوجد تحصيل.")
        st.markdown("### ملخص المصروفات")
        show_or_info(exp, "لا توجد مصروفات.")
        st.markdown("### حالة إقفال اليوم")
        show_or_info(closure, "لم يتم إقفال هذا اليوم.")

    with tab_audit:
        if not has_role("admin"):
            st.info("سجل العمليات متاح للمدير فقط.")
        else:
            df = dataframe_query(
                """SELECT a.id AS 'ID', COALESCE(u.username, 'system') AS 'المستخدم', a.action AS 'العملية',
                          a.table_name AS 'الجدول', a.record_id AS 'رقم السجل',
                          a.details AS 'التفاصيل', a.created_at AS 'التاريخ والوقت'
                   FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id
                   ORDER BY a.id DESC LIMIT 2000""")
            st.dataframe(df, use_container_width=True, hide_index=True)
            if not df.empty:
                download_excel(df, "audit_log.xlsx")


# ---------------------------------------------------------------------------
# المستخدمون
# ---------------------------------------------------------------------------
def page_users():
    st.subheader("المستخدمون والصلاحيات")
    if not require_role("admin"):
        return

    tab_add, tab_manage = st.tabs(["إضافة مستخدم", "إدارة المستخدمين"])

    with tab_add:
        with st.form("add_user"):
            full_name = st.text_input("الاسم الكامل")
            username = st.text_input("اسم المستخدم")
            password = st.text_input("كلمة المرور", type="password")
            role_label = st.selectbox("الصلاحية", list(ROLES.values()))
            save = st.form_submit_button("إضافة المستخدم")
        if save:
            problem = password_problem(password, username)
            if not full_name.strip() or not username.strip() or not password:
                st.error("أكمل البيانات المطلوبة.")
            elif problem:
                st.error(problem)
            elif not dataframe_query("SELECT 1 FROM users WHERE lower(username) = lower(?)",
                                     (username.strip(),)).empty:
                st.error("اسم المستخدم مستخدم بالفعل.")
            else:
                role = next(k for k, v in ROLES.items() if v == role_label)
                try:
                    execute(
                        """INSERT INTO users (username, password_hash, full_name, role, active, created_at)
                           VALUES (?, ?, ?, ?, 1, ?)""",
                        (username.strip(), hash_password(password), full_name.strip(), role, now_text()),
                        audit_info=("إضافة مستخدم", "users", username.strip()))
                    st.success("تم إنشاء المستخدم.")
                except sqlite3.IntegrityError:
                    st.error("اسم المستخدم مستخدم بالفعل.")

    with tab_manage:
        users = dataframe_query("SELECT id, username, full_name, role, active FROM users ORDER BY id")
        view = dataframe_query(
            """SELECT id AS 'ID', username AS 'اسم المستخدم', full_name AS 'الاسم', role AS 'الصلاحية',
                      CASE WHEN active = 1 THEN 'نشط' ELSE 'موقوف' END AS 'الحالة',
                      created_at AS 'تاريخ الإنشاء'
               FROM users ORDER BY id DESC""")
        st.dataframe(view, use_container_width=True, hide_index=True)

        options = {f"{r['username']} - {r['full_name']}": int(r["id"]) for _, r in users.iterrows()}
        label = st.selectbox("اختر المستخدم", list(options.keys()), key="manage_user_pick")
        uid = options[label]
        cur = users[users["id"] == uid].iloc[0]
        role_keys = list(ROLES.keys())

        with st.form(f"manage_user_{uid}"):
            new_role = st.selectbox("الصلاحية", role_keys, index=role_keys.index(cur["role"]),
                                    format_func=lambda k: ROLES[k])
            new_active = st.checkbox("نشط", value=bool(cur["active"]))
            new_password = st.text_input("كلمة مرور جديدة (اتركها فارغة لعدم التغيير)", type="password")
            save = st.form_submit_button("حفظ")
        if save:
            other_admins = int(dataframe_query(
                "SELECT COUNT(*) AS c FROM users WHERE role='admin' AND active=1 AND id<>?",
                (uid,))["c"].iloc[0])
            problem = password_problem(new_password, cur["username"]) if new_password else None
            if uid == current_user()["id"] and not new_active:
                st.error("لا يمكنك إيقاف حسابك الحالي.")
            elif cur["role"] == "admin" and (new_role != "admin" or not new_active) and other_admins == 0:
                st.error("لا يمكن إزالة آخر مدير نشط في النظام.")
            elif problem:
                st.error(problem)
            else:
                with db() as conn:
                    conn.execute("UPDATE users SET role=?, active=? WHERE id=?",
                                 (new_role, int(new_active), uid))
                    if new_password:
                        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                                     (hash_password(new_password), uid))
                    audit(conn, "تعديل مستخدم", "users", uid,
                          f"{cur['username']} | دور={new_role} | نشط={int(new_active)}"
                          + (" | تغيير كلمة المرور" if new_password else ""))
                st.success("تم الحفظ.")
                st.rerun()


# ---------------------------------------------------------------------------
# النسخ الاحتياطي
# ---------------------------------------------------------------------------
def page_database_tools():
    st.subheader("إعدادات النظام والنسخ الاحتياطي")
    if not require_role("admin"):
        return

    st.write(f"ملف قاعدة البيانات: {DB_PATH.name}")
    st.write(f"مجلد النسخ الاحتياطية: {BACKUP_DIR.name} (يُحتفظ بآخر {KEEP_BACKUPS} نسخة)")
    st.warning("النسخ داخل نفس الجهاز/السيرفر لا تكفي. حمّل نسخة دورياً واحفظها في مكان آخر. "
               "وإذا كان التطبيق على استضافة مؤقتة (مثل Streamlit Cloud) فقد تضيع البيانات عند إعادة التشغيل.")

    if st.button("إنشاء نسخة احتياطية الآن"):
        path = create_backup()
        log_action("إنشاء نسخة احتياطية", None, None, path.name)
        st.success(f"تم إنشاء النسخة: {path.name}")

    backups = sorted(BACKUP_DIR.glob("*.db"), reverse=True)
    if not backups:
        st.info("لا توجد نسخ احتياطية حتى الآن.")
        return

    st.markdown("### النسخ الاحتياطية الموجودة")
    st.dataframe(
        pd.DataFrame([
            {"الملف": p.name, "الحجم": f"{p.stat().st_size / 1024:.1f} KB",
             "التاريخ": dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
            for p in backups[:50]
        ]),
        use_container_width=True, hide_index=True)

    pick = st.selectbox("تحميل نسخة", [p.name for p in backups[:50]])
    chosen = BACKUP_DIR / pick
    if chosen.exists() and chosen.parent == BACKUP_DIR:
        st.download_button("تحميل النسخة المختارة", data=chosen.read_bytes(),
                           file_name=chosen.name, mime="application/octet-stream")


# ---------------------------------------------------------------------------
# التنسيق
# ---------------------------------------------------------------------------
def apply_css():
    st.markdown("""
    <style>
    :root { --brand:#1f6f78; --brand-dark:#174f56; --page:#f3f6f8; --text:#20303a; --muted:#6b7b84; --border:#dfe7eb; }
    .stApp { background:var(--page); direction:rtl; }
    .block-container { padding-top:1.6rem; padding-bottom:3rem; max-width:1450px; }
    [data-testid="stSidebar"] { background:linear-gradient(180deg,#173f46 0%,#1f5d64 58%,#174f56 100%); direction:rtl; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] .stCaption { color:#f5f8f9 !important; }
    [data-testid="stSidebar"] button, [data-testid="stSidebar"] button * { color:#173f46 !important; }
    [data-testid="stSidebar"] [data-testid="stRadio"] label { border-radius:9px; padding:7px 10px; transition:.18s ease; }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover { background:rgba(255,255,255,.09); }
    h1,h2,h3,h4 { color:var(--text) !important; letter-spacing:-.2px; }
    p,label,.stMarkdown,.stCaption { color:var(--text); }
    input,textarea,[data-baseweb="select"] > div { color:var(--text) !important; background:#fff !important; border-color:var(--border) !important; }
    input[type="number"], input[type="password"] { direction:ltr; text-align:left; }
    input::placeholder,textarea::placeholder { color:#8b989f !important; opacity:1 !important; }
    div.stButton > button { border-radius:9px; min-height:42px; font-weight:650; transition:transform .16s ease,box-shadow .16s ease; }
    div.stButton > button:hover { transform:translateY(-1px); box-shadow:0 7px 18px rgba(25,55,65,.12); }
    [data-testid="stForm"] { border:1px solid var(--border); border-radius:14px; background:rgba(255,255,255,.84); padding:8px 10px 2px; box-shadow:0 5px 18px rgba(32,48,58,.045); }
    [data-testid="stMetric"] { background:#fff; border:1px solid var(--border); border-radius:14px; padding:14px 16px; box-shadow:0 5px 16px rgba(32,48,58,.045); }
    [data-testid="stMetricValue"] { color:var(--brand-dark) !important; font-size:1.5rem !important; }
    [data-testid="stDataFrame"] { border-radius:12px; overflow:hidden; border:1px solid var(--border); }
    .app-header { background:linear-gradient(120deg,#1b5961 0%,#267b82 100%); color:white; border-radius:17px; padding:24px 28px; margin-bottom:22px; box-shadow:0 10px 28px rgba(24,75,83,.16); }
    .app-header h1 { color:white !important; margin:0 0 5px 0; font-size:1.8rem; }
    .app-header p { color:rgba(255,255,255,.82) !important; margin:0; }
    .login-brand { color:var(--brand); font-size:14px; font-weight:700; margin-bottom:8px; }
    .login-title { color:var(--text); font-size:28px; font-weight:800; }
    .login-subtitle { color:var(--muted); margin:4px 0 22px; font-size:14px; }
    .section-note { color:var(--muted); margin-top:-7px; margin-bottom:14px; }
    </style>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# الصفحة الرئيسية
# ---------------------------------------------------------------------------
PAGES = {
    "لوحة التحكم": (page_dashboard, ("admin", "accountant", "staff")),
    "الطلاب": (page_students, ("admin", "accountant", "staff")),
    "الأساتذة": (page_teachers, ("admin", "accountant", "staff")),
    "المواد والكورسات": (page_subjects_courses, ("admin", "accountant", "staff")),
    "حضور الطلاب": (page_student_attendance, ("admin", "accountant", "staff")),
    "تسجيل دفع": (page_payment, ("admin", "accountant", "staff")),
    "أرصدة الطلاب": (page_student_balances, ("admin", "accountant", "staff")),
    "ساعات الأساتذة": (page_teacher_hours, ("admin", "accountant", "staff")),
    "مستحقات الأساتذة": (page_teacher_payroll, ("admin", "accountant")),
    "المصروفات": (page_expenses, ("admin", "accountant")),
    "الخزينة": (page_cashbox, ("admin", "accountant")),
    "التقارير": (page_reports, ("admin", "accountant")),
    "المستخدمون": (page_users, ("admin",)),
    "النسخ الاحتياطي": (page_database_tools, ("admin",)),
}


def main():
    st.set_page_config(
        page_title="نظام إدارة المركز التعليمي",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    setup_database()
    apply_css()

    user = refresh_user()
    if not user:
        login_screen()
        return

    st.markdown(
        f"""<div class="app-header"><h1>نظام إدارة المركز التعليمي</h1>
        <p>مرحباً {html.escape(user["full_name"])} — إدارة الطلاب والكورسات والحضور والمدفوعات في مكان واحد.</p></div>""",
        unsafe_allow_html=True,
    )

    st.sidebar.markdown("### نظام إدارة المركز")
    st.sidebar.caption(f"المستخدم: {user['full_name']}")
    st.sidebar.caption(f"الصلاحية: {ROLES.get(user['role'], user['role'])}")

    if st.sidebar.button("تسجيل الخروج", use_container_width=True):
        logout()

    menu = [name for name, (_, roles) in PAGES.items() if user["role"] in roles]
    choice = st.sidebar.radio("القائمة الرئيسية", menu)

    flash = st.session_state.pop("flash_main", None)
    if flash:
        getattr(st, flash[0])(flash[1])

    page_func, roles = PAGES[choice]
    if user["role"] in roles:
        page_func()


if __name__ == "__main__":
    main()