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
SESSION_TIMEOUT_SECONDS = 1800  # 30 دقيقة


# ============================================================
# قاعدة البيانات
# ============================================================
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
    )

    # توافق مع البنية القديمة
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

    # توليد أكواد للسجلات القديمة
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_payments_date ON student_payments(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON student_attendance(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_teacher_hours_date ON teacher_hours(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)")

    conn.executescript(
        """
        CREATE TRIGGER IF NOT EXISTS prevent_duplicate_student
        BEFORE INSERT ON students
        WHEN EXISTS (SELECT 1 FROM students WHERE lower(trim(name)) = lower(trim(NEW.name)))
        BEGIN SELECT RAISE(ABORT, 'DUPLICATE_STUDENT'); END;

        CREATE TRIGGER IF NOT EXISTS prevent_duplicate_teacher
        BEFORE INSERT ON teachers
        WHEN EXISTS (SELECT 1 FROM teachers WHERE lower(trim(name)) = lower(trim(NEW.name)))
        BEGIN SELECT RAISE(ABORT, 'DUPLICATE_TEACHER'); END;

        CREATE TRIGGER IF NOT EXISTS prevent_duplicate_course
        BEFORE INSERT ON courses
        WHEN EXISTS (
            SELECT 1 FROM courses
            WHERE lower(trim(name)) = lower(trim(NEW.name))
              AND COALESCE(subject_id, 0) = COALESCE(NEW.subject_id, 0)
              AND COALESCE(teacher_id, 0) = COALESCE(NEW.teacher_id, 0)
        )
        BEGIN SELECT RAISE(ABORT, 'DUPLICATE_COURSE'); END;

        CREATE TRIGGER IF NOT EXISTS prevent_payment_closed_day
        BEFORE INSERT ON student_payments
        WHEN EXISTS (SELECT 1 FROM day_closures WHERE date = NEW.date AND status='closed')
        BEGIN SELECT RAISE(ABORT, 'DAY_CLOSED'); END;

        CREATE TRIGGER IF NOT EXISTS prevent_expense_closed_day
        BEFORE INSERT ON expenses
        WHEN EXISTS (SELECT 1 FROM day_closures WHERE date = NEW.date AND status='closed')
        BEGIN SELECT RAISE(ABORT, 'DAY_CLOSED'); END;

        CREATE TRIGGER IF NOT EXISTS prevent_teacher_payment_closed_day
        BEFORE INSERT ON teacher_payments
        WHEN EXISTS (SELECT 1 FROM day_closures WHERE date = NEW.date AND status='closed')
        BEGIN SELECT RAISE(ABORT, 'DAY_CLOSED'); END;

        CREATE TRIGGER IF NOT EXISTS prevent_teacher_hours_closed_day
        BEFORE INSERT ON teacher_hours
        WHEN EXISTS (SELECT 1 FROM day_closures WHERE date = NEW.date AND status='closed')
        BEGIN SELECT RAISE(ABORT, 'DAY_CLOSED'); END;

        CREATE TRIGGER IF NOT EXISTS prevent_attendance_closed_day
        BEFORE INSERT ON student_attendance
        WHEN EXISTS (SELECT 1 FROM day_closures WHERE date = NEW.date AND status='closed')
        BEGIN SELECT RAISE(ABORT, 'DAY_CLOSED'); END;
        """
    )

    conn.commit()
    conn.close()


# ============================================================
# الأمان والمصادقة
# ============================================================
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
    """يعيد بيانات المستخدم الحالي مع التحقق من قاعدته كل مرة."""
    user = st.session_state.get("user")
    if not user:
        return None
    # التحقق من أن المستخدم لا يزال نشطاً وموجوداً
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM users WHERE id = ? AND active = 1", (user["id"],)
    ).fetchone()
    conn.close()
    if not row:
        st.session_state.pop("user", None)
        return None
    return dict(row)


def has_role(*roles):
    user = current_user()
    return bool(user and user["role"] in roles)


def user_scope_filter():
    """يعيد id المستخدم لعزل البيانات، أو None للمدير والمحاسب."""
    user = current_user()
    if not user:
        return None
    if user["role"] in ("admin", "accountant"):
        return None
    return user["id"]


def scope_clause(column="created_by"):
    """يبني جملة WHERE لعزل البيانات."""
    scope = user_scope_filter()
    if scope is None:
        return "", ()
    return f" AND {column} = ? ", (scope,)


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
            user_id, action, table_name, record_id, details,
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
        st.session_state.login_time = dt.datetime.now().isoformat()
        log_action("تسجيل دخول")
        return True
    return False


def logout():
    if current_user():
        log_action("تسجيل خروج")
    st.session_state.pop("user", None)
    st.session_state.pop("login_time", None)
    st.rerun()


def check_session_timeout():
    """يتحقق من انتهاء الجلسة ويعيد True إذا انتهت."""
    if not current_user():
        return False
    last = st.session_state.get("login_time")
    if not last:
        return False
    try:
        elapsed = (
            dt.datetime.now() - dt.datetime.fromisoformat(last)
        ).total_seconds()
    except ValueError:
        return False
    return elapsed > SESSION_TIMEOUT_SECONDS


# ============================================================
# أدوات مساعدة
# ============================================================
def format_money(value):
    try:
        return f"{float(value):,.0f} SDG"
    except (TypeError, ValueError):
        return "0 SDG"


def today():
    return dt.date.today()


def now_text():
    return dt.datetime.now().isoformat(timespec="seconds")


def is_day_closed(date_value):
    date_str = str(date_value)
    conn = get_connection()
    row = conn.execute(
        "SELECT status FROM day_closures WHERE date = ? AND status = 'closed'",
        (date_str,),
    ).fetchone()
    conn.close()
    return row is not None


def day_lock_message(date_value):
    return (
        f"اليوم {date_value} مقفل. لا يمكن تسجيل عملية جديدة لهذا التاريخ. "
        "إذا كان هناك خطأ، يجب على المدير فتح اليوم أولاً من شاشة الخزينة."
    )


def require_day_open(date_value):
    if is_day_closed(date_value):
        st.error(day_lock_message(date_value))
        return False
    return True


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


def reset_all_data(keep_users=True):
    """حذف جميع البيانات التجريبية مع الاحتفاظ بحسابات المستخدمين (اختياري)."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA foreign_keys = OFF")
        tables_to_clear = [
            "student_attendance",
            "teacher_hours",
            "student_payments",
            "teacher_payments",
            "expenses",
            "cashbox",
            "day_closures",
            "enrollments",
            "courses",
            "subjects",
            "students",
            "teachers",
            "audit_logs",
        ]
        if not keep_users:
            tables_to_clear.append("users")

        for table in tables_to_clear:
            cur.execute(f"DELETE FROM {table}")
            cur.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))

        conn.commit()
        cur.execute("PRAGMA foreign_keys = ON")
        return True
    except Exception as exc:
        conn.rollback()
        st.error(f"فشل المسح: {exc}")
        return False
    finally:
        conn.close()


def download_excel(df, filename="report.xlsx"):
    try:
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
    except ImportError:
        st.error("مكتبة openpyxl غير مثبتة. نفذ: pip install openpyxl")


# ============================================================
# شاشة الدخول
# ============================================================
def login_screen():
    st.markdown('<div class="login-shell">', unsafe_allow_html=True)
    st.markdown(
        '<div class="login-brand brand-ruqaa">مركز عوض</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="login-title">نظام إدارة المركز التعليمي</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="login-subtitle">تسجيل الدخول إلى لوحة الإدارة</div>',
        unsafe_allow_html=True,
    )

    if get_user_count() == 0:
        st.info("أنشئ حساب المدير أولاً. هذه الشاشة تظهر في أول تشغيل فقط.")
        with st.form("first_admin"):
            full_name = st.text_input("اسم المدير", placeholder="الاسم الكامل")
            username = st.text_input("اسم المستخدم", placeholder="اسم الدخول")
            password = st.text_input("كلمة المرور", type="password", placeholder="6 أحرف على الأقل")
            password2 = st.text_input("تأكيد كلمة المرور", type="password", placeholder="أعد كتابة كلمة المرور")
            confirmed = st.checkbox("أؤكد أن بيانات الحساب صحيحة")
            submitted = st.form_submit_button("إنشاء الحساب", use_container_width=True)
        if submitted:
            if not full_name.strip() or not username.strip() or not password:
                st.error("أكمل جميع البيانات المطلوبة.")
            elif not confirmed:
                st.warning("ضع علامة التأكيد قبل إنشاء الحساب.")
            elif len(password) < 6:
                st.error("كلمة المرور يجب أن تكون 6 أحرف على الأقل.")
            elif password != password2:
                st.error("كلمتا المرور غير متطابقتين.")
            else:
                execute(
                    """INSERT INTO users (username, password_hash, full_name, role, active, created_at)
                    VALUES (?, ?, ?, 'admin', 1, ?)""",
                    (username.strip(), hash_password(password), full_name.strip(), now_text()),
                )
                st.success("تم إنشاء حساب المدير. يمكنك تسجيل الدخول الآن.")
                st.rerun()
    else:
        with st.form("login_form"):
            username = st.text_input("اسم المستخدم", placeholder="اكتب اسم المستخدم")
            password = st.text_input("كلمة المرور", type="password", placeholder="اكتب كلمة المرور")
            submitted = st.form_submit_button("دخول", use_container_width=True)
        if submitted:
            if login_user(username, password):
                st.rerun()
            st.error("اسم المستخدم أو كلمة المرور غير صحيحة.")

    st.markdown('</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="dev-credit" style="max-width:520px;margin:18px auto 0;">'
        '<span class="dev-icon">◆</span> '
        'تطوير <strong>HASSAN ELNOUSH</strong> '
        '<span class="dev-icon">◆</span>'
        '</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# لوحة التحكم
# ============================================================
def page_dashboard():
    st.subheader("لوحة التحكم")
    st.markdown(
        '<div class="section-note">نظرة سريعة على حركة المركز في اليوم والفترة الأخيرة.</div>',
        unsafe_allow_html=True,
    )

    selected_date = st.date_input("التاريخ", today(), key="dashboard_date")
    date_str = str(selected_date)

    scope_sql, scope_params = scope_clause("created_by")

    payments = dataframe_query(
        f"""
        SELECT amount, payment_method
        FROM student_payments
        WHERE date = ? AND status = 'completed' {scope_sql}
        """,
        (date_str,) + scope_params,
    )
    expenses = dataframe_query(
        f"""
        SELECT amount, payment_method
        FROM expenses
        WHERE date = ? AND status = 'completed' {scope_sql}
        """,
        (date_str,) + scope_params,
    )
    attendance = dataframe_query(
        f"""
        SELECT status
        FROM student_attendance
        WHERE date = ? {scope_sql}
        """,
        (date_str,) + scope_params,
    )

    total_income = payments["amount"].sum() if not payments.empty else 0
    total_expense = expenses["amount"].sum() if not expenses.empty else 0
    cash_income = (
        payments.loc[payments["payment_method"] == "كاش", "amount"].sum()
        if not payments.empty else 0
    )
    bank_income = (
        payments.loc[payments["payment_method"] == "بنكك", "amount"].sum()
        if not payments.empty else 0
    )
    present = (
        len(attendance[attendance["status"] == "حاضر"])
        if not attendance.empty else 0
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
        SELECT date, SUM(amount) AS income
        FROM student_payments
        WHERE status = 'completed'
          AND date >= date('now', '-29 day')
        GROUP BY date
        ORDER BY date
        """
    )

    if not monthly.empty:
        monthly["date"] = pd.to_datetime(monthly["date"])
        # ملء الأيام الناقصة بـ 0
        full_range = pd.date_range(
            end=pd.Timestamp.today().normalize(),
            periods=30,
            freq="D",
        )
        monthly = (
            monthly.set_index("date")
            .reindex(full_range, fill_value=0)
            .rename_axis("date")
            .reset_index()
        )
        chart = monthly.set_index("date")[["income"]]
        st.bar_chart(
            chart,
            color="#176b87",
            use_container_width=True,
            height=320,
        )
    else:
        st.info("لا توجد بيانات كافية لعرض الرسم البياني.")


# ============================================================
# الطلاب
# ============================================================
def page_students():
    st.subheader("إدارة الطلاب")
    st.caption("إضافة الطلاب والبحث عنهم. تعديل بيانات الطالب متاح للمدير فقط.")

    tab_add, tab_list = st.tabs(["إضافة طالب", "قائمة الطلاب"])

    with tab_add:
        with st.form("add_student", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("اسم الطالب الكامل", placeholder="مثال: محمد أحمد علي")
                phone = st.text_input("رقم الهاتف", placeholder="01XXXXXXXXX")
            with col2:
                address = st.text_input("العنوان")
                notes = st.text_area("ملاحظات", height=90)
            confirmed = st.checkbox("أؤكد أن الطالب غير مسجل مسبقاً بهذه البيانات")
            save = st.form_submit_button("حفظ الطالب", use_container_width=True)

        if save:
            if not name.strip():
                st.error("اسم الطالب مطلوب.")
            elif not confirmed:
                st.warning("ضع علامة التأكيد قبل حفظ الطالب.")
            else:
                code = generate_code("STU", "students")
                try:
                    student_id = execute(
                        """INSERT INTO students
                        (student_code, name, phone, address, notes, active, created_at)
                        VALUES (?, ?, ?, ?, ?, 1, ?)""",
                        (code, name.strip(), phone.strip(), address.strip(),
                         notes.strip(), now_text()),
                        return_id=True,
                    )
                    log_action("إضافة طالب", "students", student_id, name.strip())
                    st.success(f"تم حفظ الطالب بنجاح — الرقم: {code}")
                    st.toast("تم حفظ الطالب بنجاح")
                except sqlite3.IntegrityError as exc:
                    if "DUPLICATE_STUDENT" in str(exc):
                        st.error("هذا الطالب مسجل بالفعل. استخدم البحث في قائمة الطلاب.")
                    else:
                        st.error("تعذر حفظ الطالب. تحقق من البيانات.")

    with tab_list:
        search = st.text_input(
            "بحث بالاسم أو الرقم أو الهاتف",
            key="student_search",
            placeholder="اكتب جزءاً من الاسم أو الرقم",
        )
        term = f"%{search.strip()}%"
        df = dataframe_query(
            """SELECT id AS 'ID', student_code AS 'رقم الطالب', name AS 'اسم الطالب',
                   phone AS 'الهاتف', address AS 'العنوان', notes AS 'ملاحظات',
                   CASE WHEN active = 1 THEN 'نشط' ELSE 'موقوف' END AS 'الحالة'
            FROM students WHERE name LIKE ? OR student_code LIKE ? OR phone LIKE ?
            ORDER BY id DESC""",
            (term, term, term),
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
        if not df.empty:
            download_excel(df, "students.xlsx")

        if has_role("admin") and not df.empty:
            st.markdown("### تعديل بيانات طالب")
            student_rows = dataframe_query(
                "SELECT id, student_code, name FROM students ORDER BY name"
            )
            if student_rows.empty:
                st.info("لا يوجد طلاب.")
                return
            options = {
                f"{r['student_code']} - {r['name']}": int(r['id'])
                for _, r in student_rows.iterrows()
            }
            selected = st.selectbox(
                "اختر الطالب المراد تعديله",
                list(options.keys()),
                key="edit_student_select",
            )
            row = dataframe_query(
                "SELECT * FROM students WHERE id = ?", (options[selected],)
            ).iloc[0]
            with st.form("edit_student_form"):
                c1, c2 = st.columns(2)
                with c1:
                    edit_name = st.text_input("اسم الطالب", value=str(row.get("name") or ""))
                    edit_phone = st.text_input("رقم الهاتف", value=str(row.get("phone") or ""))
                with c2:
                    edit_address = st.text_input("العنوان", value=str(row.get("address") or ""))
                    edit_notes = st.text_area("ملاحظات", value=str(row.get("notes") or ""), height=90)
                edit_active = st.checkbox("الطالب نشط", value=bool(row.get("active", 1)))
                confirm_edit = st.checkbox("أؤكد حفظ التعديل", key="confirm_student_edit")
                update = st.form_submit_button("حفظ تعديل الطالب", use_container_width=True)
            if update:
                if not confirm_edit:
                    st.warning("ضع علامة التأكيد أولاً.")
                elif not edit_name.strip():
                    st.error("اسم الطالب مطلوب.")
                else:
                    try:
                        execute(
                            """UPDATE students SET name=?, phone=?, address=?, notes=?, active=?
                               WHERE id=?""",
                            (edit_name.strip(), edit_phone.strip(),
                             edit_address.strip(), edit_notes.strip(),
                             int(edit_active), int(row["id"])),
                        )
                        log_action("تعديل طالب", "students", int(row["id"]), edit_name.strip())
                        st.success("تم تعديل بيانات الطالب.")
                        st.toast("تم تحديث بيانات الطالب")
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("تعذر التعديل. قد يكون الاسم مستخدماً لطالب آخر.")
        elif not has_role("admin"):
            st.info("تعديل بيانات الطلاب متاح للمدير فقط.")


# ============================================================
# الأساتذة
# ============================================================
def page_teachers():
    st.subheader("إدارة الأساتذة")
    st.caption("إضافة الأستاذ وربطه بالكورسات. تعديل بيانات الأستاذ وأجره متاح للمدير فقط.")

    tab_add, tab