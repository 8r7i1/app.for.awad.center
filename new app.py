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
    conn.execute("UPDATE students SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL", (now,))
    conn.execute("UPDATE teachers SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL", (now,))
    conn.execute("UPDATE teacher_hours SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL", (now,))
    conn.execute("UPDATE student_payments SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL", (now,))
    conn.execute("UPDATE student_payments SET status = 'completed' WHERE status IS NULL OR status = ''")

    students = conn.execute("SELECT id FROM students WHERE student_code IS NULL OR student_code = ''").fetchall()
    for row in students:
        conn.execute("UPDATE students SET student_code = ? WHERE id = ?", (f"STU-{row['id']:06d}", row["id"]))

    teachers = conn.execute("SELECT id FROM teachers WHERE teacher_code IS NULL OR teacher_code = ''").fetchall()
    for row in teachers:
        conn.execute("UPDATE teachers SET teacher_code = ? WHERE id = ?", (f"TCH-{row['id']:06d}", row["id"]))

    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_bankak_transaction_unique
        ON student_payments(transaction_number)
        WHERE payment_method = 'بنكك'
        AND transaction_number IS NOT NULL
        AND transaction_number <> ''
        AND status = 'completed'
    """)
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

    def check_session_timeout():
        """يتحقق من انتهاء الجلسة."""
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
                "student_attendance", "teacher_hours", "student_payments",
                "teacher_payments", "expenses", "cashbox", "day_closures",
                "enrollments", "courses", "subjects", "students",
                "teachers", "audit_logs",
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
            f"""SELECT amount, payment_method FROM student_payments
                WHERE date = ? AND status = 'completed' {scope_sql}""",
            (date_str,) + scope_params,
        )
        expenses = dataframe_query(
            f"""SELECT amount, payment_method FROM expenses
                WHERE date = ? AND status = 'completed' {scope_sql}""",
            (date_str,) + scope_params,
        )
        attendance = dataframe_query(
            f"""SELECT status FROM student_attendance
                WHERE date = ? {scope_sql}""",
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

        tab_add, tab_list = st.tabs(["إضافة أستاذ", "قائمة الأساتذة"])
        with tab_add:
            with st.form("add_teacher", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    name = st.text_input("اسم الأستاذ الكامل", placeholder="مثال: أ. أحمد محمد")
                    subject = st.text_input("المادة / التخصص")
                with col2:
                    phone = st.text_input("رقم الهاتف")
                    rate = st.number_input("أجر الساعة", min_value=0.0, step=100.0)
                confirmed = st.checkbox("أؤكد أن الأستاذ غير مسجل مسبقاً")
                save = st.form_submit_button("حفظ الأستاذ", use_container_width=True)
            if save:
                if not name.strip():
                    st.error("اسم الأستاذ مطلوب.")
                elif not confirmed:
                    st.warning("ضع علامة التأكيد قبل حفظ الأستاذ.")
                else:
                    code = generate_code("TCH", "teachers")
                    try:
                        teacher_id = execute(
                            """INSERT INTO teachers
                            (teacher_code, name, subject, phone, hourly_rate, active, created_at)
                            VALUES (?, ?, ?, ?, ?, 1, ?)""",
                            (code, name.strip(), subject.strip(), phone.strip(), rate, now_text()),
                            return_id=True,
                        )
                        log_action("إضافة أستاذ", "teachers", teacher_id, name.strip())
                        st.success(f"تم حفظ الأستاذ بنجاح — الرقم: {code}")
                        st.toast("تم حفظ الأستاذ بنجاح")
                    except sqlite3.IntegrityError as exc:
                        if "DUPLICATE_TEACHER" in str(exc):
                            st.error("هذا الأستاذ مسجل بالفعل. استخدم قائمة الأساتذة.")
                        else:
                            st.error("تعذر حفظ الأستاذ. تحقق من البيانات.")

        with tab_list:
            search = st.text_input(
                "بحث بالاسم أو الرقم أو المادة",
                key="teacher_search",
                placeholder="اكتب جزءاً من الاسم",
            )
            term = f"%{search.strip()}%"
            df = dataframe_query(
                """SELECT id AS 'ID', teacher_code AS 'رقم الأستاذ', name AS 'اسم الأستاذ',
                       subject AS 'المادة', phone AS 'الهاتف', hourly_rate AS 'أجر الساعة',
                       CASE WHEN active = 1 THEN 'نشط' ELSE 'موقوف' END AS 'الحالة'
                FROM teachers WHERE name LIKE ? OR teacher_code LIKE ? OR subject LIKE ?
                ORDER BY id DESC""",
                (term, term, term),
            )
            st.dataframe(df, use_container_width=True, hide_index=True)
            if not df.empty:
                download_excel(df, "teachers.xlsx")

            if has_role("admin") and not df.empty:
                st.markdown("### تعديل بيانات الأستاذ")
                teacher_rows = dataframe_query(
                    "SELECT id, teacher_code, name FROM teachers ORDER BY name"
                )
                options = {
                    f"{r['teacher_code']} - {r['name']}": int(r['id'])
                    for _, r in teacher_rows.iterrows()
                }
                selected = st.selectbox(
                    "اختر الأستاذ المراد تعديله",
                    list(options.keys()),
                    key="edit_teacher_select",
                )
                row = dataframe_query(
                    "SELECT * FROM teachers WHERE id = ?", (options[selected],)
                ).iloc[0]
                with st.form("edit_teacher_form"):
                    c1, c2 = st.columns(2)
                    with c1:
                        edit_name = st.text_input("اسم الأستاذ", value=str(row.get("name") or ""))
                        edit_subject = st.text_input("المادة / التخصص", value=str(row.get("subject") or ""))
                    with c2:
                        edit_phone = st.text_input("رقم الهاتف", value=str(row.get("phone") or ""))
                        edit_rate = st.number_input(
                            "أجر الساعة", min_value=0.0, step=100.0,
                            value=float(row.get("hourly_rate") or 0),
                        )
                    edit_active = st.checkbox("الأستاذ نشط", value=bool(row.get("active", 1)))
                    confirm_edit = st.checkbox("أؤكد حفظ التعديل", key="confirm_teacher_edit")
                    update = st.form_submit_button("حفظ تعديل الأستاذ", use_container_width=True)
                if update:
                    if not confirm_edit:
                        st.warning("ضع علامة التأكيد أولاً.")
                    elif not edit_name.strip():
                        st.error("اسم الأستاذ مطلوب.")
                    else:
                        try:
                            execute(
                                """UPDATE teachers SET name=?, subject=?, phone=?, hourly_rate=?, active=?
                                   WHERE id=?""",
                                (edit_name.strip(), edit_subject.strip(), edit_phone.strip(),
                                 edit_rate, int(edit_active), int(row["id"])),
                            )
                            log_action(
                                "تعديل أستاذ", "teachers", int(row["id"]),
                                f"{edit_name.strip()} | أجر الساعة: {edit_rate:g}",
                            )
                            st.success("تم تعديل بيانات الأستاذ وأجره.")
                            st.toast("تم تحديث بيانات الأستاذ")
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("تعذر التعديل. قد يكون الاسم مستخدماً لأستاذ آخر.")
            elif not has_role("admin"):
                st.info("تعديل بيانات الأساتذة وأجورهم متاح للمدير فقط.")

    # ============================================================
    # المواد والكورسات
    # ============================================================
    def page_subjects_courses():
        st.subheader("المواد والكورسات")
        st.caption("يمكن إنشاء المادة أو الكورس بشكل مستقل. لا يلزم تسجيل أي طالب داخل الكورس عند إنشائه.")

        tab_subject, tab_course = st.tabs(["المواد", "الكورسات"])

        with tab_subject:
            with st.form("add_subject", clear_on_submit=True):
                col1, col2 = st.columns([1, 2])
                with col1:
                    name = st.text_input("اسم المادة", placeholder="مثال: محاسبة متوسطة")
                with col2:
                    description = st.text_area("وصف المادة", height=90)
                confirmed = st.checkbox("أؤكد أن المادة غير مسجلة مسبقاً", key="confirm_subject")
                save = st.form_submit_button("حفظ المادة", use_container_width=True)

            if save:
                if not name.strip():
                    st.error("اسم المادة مطلوب.")
                elif not confirmed:
                    st.warning("ضع علامة التأكيد قبل حفظ المادة.")
                else:
                    try:
                        subject_id = execute(
                            "INSERT INTO subjects (name, description, active) VALUES (?, ?, 1)",
                            (name.strip(), description.strip()), return_id=True,
                        )
                        log_action("إضافة مادة", "subjects", subject_id, name.strip())
                        st.success("تم حفظ المادة.")
                        st.toast("تم حفظ المادة")
                    except sqlite3.IntegrityError:
                        st.error("هذه المادة موجودة بالفعل.")

            st.dataframe(
                dataframe_query(
                    """SELECT id AS 'ID', name AS 'المادة', description AS 'الوصف'
                    FROM subjects WHERE active = 1 ORDER BY name"""
                ),
                use_container_width=True, hide_index=True,
            )

        with tab_course:
            subjects = dataframe_query("SELECT id, name FROM subjects WHERE active = 1 ORDER BY name")
            teachers = dataframe_query("SELECT id, name FROM teachers WHERE active = 1 ORDER BY name")

            if subjects.empty:
                st.warning("أضف مادة أولاً حتى تتمكن من إنشاء الكورس.")
            elif teachers.empty:
                st.warning("أضف أستاذاً أولاً حتى تتمكن من إنشاء الكورس.")
            else:
                subject_options = dict(zip(subjects["name"], subjects["id"]))
                teacher_options = dict(zip(teachers["name"], teachers["id"]))

                with st.form("add_course", clear_on_submit=True):
                    col1, col2 = st.columns(2)
                    with col1:
                        course_name = st.text_input("اسم الكورس", placeholder="مثال: كورس المحاسبة المتوسطة")
                        selected_subject = st.selectbox("المادة", list(subject_options.keys()))
                        selected_teacher = st.selectbox("الأستاذ", list(teacher_options.keys()))
                    with col2:
                        fee = st.number_input("رسوم الكورس", min_value=0.0, step=100.0)
                        sessions = st.number_input("عدد الحصص", min_value=0, step=1, value=0)
                        start_date = st.date_input("بداية الكورس", today())
                        end_date = st.date_input("نهاية الكورس", today())
                    confirmed = st.checkbox("أؤكد أن هذا الكورس غير مسجل مسبقاً", key="confirm_course")
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
                            course_id = execute(
                                """INSERT INTO courses
                                (name, subject_id, teacher_id, fee, total_sessions, start_date, end_date, active)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                                (course_name.strip(), subject_options[selected_subject],
                                 teacher_options[selected_teacher],
                                 fee, sessions, str(start_date), str(end_date)),
                                return_id=True,
                            )
                            log_action("إضافة كورس", "courses", course_id, course_name.strip())
                            st.success("تم حفظ الكورس بنجاح. لم يتم تسجيل أي طالب فيه.")
                            st.toast("تم إنشاء الكورس")
                        except sqlite3.IntegrityError as exc:
                            if "DUPLICATE_COURSE" in str(exc):
                                st.error("هذا الكورس مسجل بالفعل بنفس المادة والأستاذ.")
                            else:
                                st.error("تعذر حفظ الكورس. تحقق من البيانات.")

                courses = dataframe_query(
                    """SELECT c.id AS 'ID', c.name AS 'الكورس',
                        s.name AS 'المادة', t.name AS 'الأستاذ', c.fee AS 'الرسوم',
                        c.total_sessions AS 'عدد الحصص', c.start_date AS 'البداية', c.end_date AS 'النهاية'
                        FROM courses c LEFT JOIN subjects s ON s.id=c.subject_id
                        LEFT JOIN teachers t ON t.id=c.teacher_id
                        WHERE c.active=1 ORDER BY c.id DESC"""
                )
                st.dataframe(courses, use_container_width=True, hide_index=True)
                if not courses.empty:
                    download_excel(courses, "courses.xlsx")

                    # ============================================================
                    # حضور الطلاب
                    # ============================================================
                    def page_student_attendance():
                        st.subheader("حضور الطلاب")

                        students = dataframe_query(
                            "SELECT id, student_code, name FROM students WHERE active = 1 ORDER BY name"
                        )
                        courses = dataframe_query(
                            "SELECT id, name, teacher_id FROM courses WHERE active = 1 ORDER BY name"
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
                                selected_student = st.selectbox("الطالب", list(student_options.keys()))
                                attendance_date = st.date_input("التاريخ", today())
                            with col2:
                                selected_course = st.selectbox("الكورس", list(course_options.keys()))
                                status = st.selectbox("الحالة", ["حاضر", "غائب", "متأخر", "اعتذر"])

                            check_in = st.time_input("وقت الحضور", dt.time(8, 0))
                            notes = st.text_input("ملاحظات")
                            save = st.form_submit_button("تسجيل الحضور")

                        if save:
                            if not require_day_open(attendance_date):
                                return
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
                                    student_id, course_id, teacher_id, str(attendance_date),
                                    str(check_in), status, notes.strip(),
                                    current_user()["id"], now_text(),
                                ),
                                return_id=True,
                            )
                            log_action("تسجيل حضور طالب", "student_attendance", attendance_id, selected_student)
                            st.success("تم تسجيل الحضور.")

                        selected_date = st.date_input("عرض حضور يوم", today(), key="attendance_report_date")
                        scope_sql, scope_params = scope_clause("a.created_by")
                        df = dataframe_query(
                            f"""
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
                            WHERE a.date = ? {scope_sql}
                            ORDER BY a.id DESC
                            """,
                            (str(selected_date),) + scope_params,
                        )
                        st.dataframe(df, use_container_width=True, hide_index=True)

                    # ============================================================
                    # تسجيل دفع
                    # ============================================================
                    def page_payment():
                        st.subheader("تسجيل دفع طالب")
                        st.caption("الكورس اختياري. يمكنك تسجيل الدفعة للطالب بدون ربطها بكورس.")

                        students = dataframe_query(
                            """SELECT id, student_code, name, phone
                               FROM students WHERE active = 1 ORDER BY name"""
                        )
                        courses = dataframe_query(
                            """SELECT c.id, c.name, c.teacher_id, c.fee, t.name AS teacher_name
                               FROM courses c LEFT JOIN teachers t ON t.id = c.teacher_id
                               WHERE c.active = 1 ORDER BY c.name"""
                        )

                        if students.empty:
                            st.info("أضف طلاباً أولاً.")
                            return

                        st.markdown("### 🔍 اختيار الطالب")
                        search_term = st.text_input(
                            "ابحث عن الطالب بالاسم أو الرقم أو الهاتف",
                            placeholder="اكتب جزءاً من الاسم أو رقم الطالب أو رقم الهاتف...",
                            key="payment_student_search",
                        ).strip()

                        filtered = students.copy()
                        if search_term:
                            mask = (
                                    filtered["name"].astype(str).str.contains(search_term, case=False, na=False)
                                    | filtered["student_code"].astype(str).str.contains(search_term, case=False,
                                                                                        na=False)
                                    | filtered["phone"].fillna("").astype(str).str.contains(search_term, case=False,
                                                                                            na=False)
                            )
                            filtered = filtered[mask]

                        if filtered.empty:
                            st.warning("لا يوجد طالب مطابق للبحث.")
                            return

                        student_options = {
                            f"{r['student_code']} - {r['name']}"
                            + (f" ({r['phone']})" if r.get("phone") else ""): int(r["id"])
                            for _, r in filtered.iterrows()
                        }

                        course_options = {"بدون كورس": None}
                        course_data = {}
                        for _, row in courses.iterrows():
                            label = f"{row['name']} - {row['teacher_name'] or 'بدون أستاذ'}"
                            course_options[label] = int(row['id'])
                            course_data[int(row['id'])] = row

                        method = st.radio(
                            "طريقة الدفع", ["كاش", "بنكك"], horizontal=True, key="payment_method"
                        )
                        if method == "بنكك":
                            st.markdown(
                                '<div class="bankak-box">'
                                '<div class="bankak-title">دفع عبر بنكك</div>'
                                '<div class="bankak-note">أدخل رقم العملية كما هو ظاهر في إشعار بنكك. الرقم مطلوب قبل الحفظ.</div>'
                                '</div>',
                                unsafe_allow_html=True,
                            )
                            transaction_number = st.text_input(
                                "رقم عملية بنكك",
                                placeholder="أدخل رقم العملية هنا",
                                key="bankak_transaction",
                            )
                        else:
                            transaction_number = ""

                        with st.form("payment_form", clear_on_submit=True):
                            col1, col2 = st.columns(2)
                            with col1:
                                selected_student = st.selectbox("الطالب المحدد", list(student_options.keys()))
                                amount = st.number_input("المبلغ", min_value=0.0, step=100.0)
                                payment_date = st.date_input("التاريخ", today())
                            with col2:
                                selected_course = st.selectbox("الكورس", list(course_options.keys()))
                                notes = st.text_input("ملاحظات")
                            confirm = st.checkbox("أؤكد أن بيانات الدفعة صحيحة")
                            save = st.form_submit_button("حفظ العملية", use_container_width=True)

                        if save:
                            if not confirm:
                                st.warning("ضع علامة التأكيد قبل حفظ العملية.")
                                return
                            if not require_day_open(payment_date):
                                return
                            if amount <= 0:
                                st.error("المبلغ يجب أن يكون أكبر من صفر.")
                                return
                            if method == "بنكك" and not transaction_number.strip():
                                st.error("رقم عملية بنكك مطلوب.")
                                return

                            if method == "بنكك":
                                existing = dataframe_query(
                                    """SELECT id FROM student_payments
                                       WHERE payment_method='بنكك' AND transaction_number=?
                                       AND status='completed'""",
                                    (transaction_number.strip(),),
                                )
                                if not existing.empty:
                                    st.error("رقم عملية بنكك مستخدم من قبل.")
                                    return

                            student_id = student_options[selected_student]
                            course_id = course_options[selected_course]
                            teacher_id = None
                            if course_id and pd.notna(course_data[course_id]["teacher_id"]):
                                teacher_id = int(course_data[course_id]["teacher_id"])

                            try:
                                payment_id = execute(
                                    """INSERT INTO student_payments
                                       (student_id, teacher_id, course_id, date, amount, payment_method,
                                        transaction_number, notes, status, created_by, created_at)
                                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)""",
                                    (
                                        student_id, teacher_id, course_id, str(payment_date),
                                        amount, method, transaction_number.strip(),
                                        notes.strip(), current_user()["id"], now_text(),
                                    ),
                                    return_id=True,
                                )
                                log_action(
                                    "تسجيل دفع", "student_payments", payment_id,
                                    f"{selected_student} - {format_money(amount)} - {method}"
                                )
                                if "bankak_transaction" in st.session_state:
                                    st.session_state.bankak_transaction = ""
                                st.success("تم تسجيل العملية بنجاح.")
                                st.toast("تم حفظ الدفعة بنجاح")
                                st.info(f"المبلغ: {format_money(amount)} | طريقة الدفع: {method}")
                            except sqlite3.IntegrityError:
                                st.error("تعذر حفظ العملية. قد يكون رقم بنكك مستخدماً بالفعل.")

                    # ============================================================
                    # أرصدة الطلاب
                    # ============================================================
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
                                MAX(0, COALESCE(e.total_fee, 0) - COALESCE(p.paid, 0)) AS 'المتبقي'
                            FROM students s
                            LEFT JOIN (
                                SELECT student_id, SUM(agreed_fee) AS total_fee
                                FROM enrollments WHERE status = 'active' GROUP BY student_id
                            ) e ON e.student_id = s.id
                            LEFT JOIN (
                                SELECT student_id, SUM(amount) AS paid
                                FROM student_payments WHERE status = 'completed' GROUP BY student_id
                            ) p ON p.student_id = s.id
                            WHERE s.active = 1
                            ORDER BY s.name
                            """
                        )

                        st.dataframe(df.drop(columns=["id"]), use_container_width=True, hide_index=True)
                        if not df.empty:
                            download_excel(df.drop(columns=["id"]), "student_balances.xlsx")

                    # ============================================================
                    # ساعات الأساتذة
                    # ============================================================
                    def page_teacher_hours():
                        st.subheader("ساعات عمل الأساتذة")

                        teachers = dataframe_query(
                            "SELECT id, teacher_code, name, hourly_rate FROM teachers WHERE active = 1 ORDER BY name"
                        )
                        if teachers.empty:
                            st.info("أضف أساتذة أولاً.")
                            return

                        teacher_options = {
                            f"{r['teacher_code']} - {r['name']}": r["id"]
                            for _, r in teachers.iterrows()
                        }

                        with st.form("teacher_hours_form", clear_on_submit=True):
                            selected_teacher = st.selectbox("الأستاذ", list(teacher_options.keys()))
                            work_date = st.date_input("التاريخ", today())
                            col1, col2 = st.columns(2)
                            with col1:
                                check_in = st.time_input("وقت الدخول", dt.time(8, 0))
                            with col2:
                                check_out = st.time_input("وقت الخروج", dt.time(14, 0))
                            notes = st.text_input("ملاحظات")
                            save = st.form_submit_button("تسجيل الساعات")

                        if save:
                            if not require_day_open(work_date):
                                return
                            start = dt.datetime.combine(work_date, check_in)
                            end = dt.datetime.combine(work_date, check_out)
                            if end <= start:
                                st.error("وقت الخروج يجب أن يكون بعد وقت الدخول.")
                                return
                            hours = round((end - start).total_seconds() / 3600, 2)

                            hour_id = execute(
                                """INSERT INTO teacher_hours
                                (teacher_id, date, check_in, check_out, hours_worked,
                                 notes, created_by, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                (teacher_options[selected_teacher], str(work_date),
                                 str(check_in), str(check_out), hours, notes.strip(),
                                 current_user()["id"], now_text()),
                                return_id=True,
                            )
                            log_action("تسجيل ساعات أستاذ", "teacher_hours", hour_id, selected_teacher)
                            st.success(f"تم تسجيل {hours:.2f} ساعة.")

                        selected_date = st.date_input("عرض الساعات ليوم", today(), key="teacher_hours_date")
                        scope_sql, scope_params = scope_clause("h.created_by")
                        df = dataframe_query(
                            f"""
                            SELECT h.id AS 'ID',
                                   t.teacher_code AS 'رقم الأستاذ',
                                   t.name AS 'الأستاذ',
                                   h.check_in AS 'الدخول',
                                   h.check_out AS 'الخروج',
                                   h.hours_worked AS 'الساعات',
                                   h.hours_worked * t.hourly_rate AS 'المستحق'
                            FROM teacher_hours h
                            JOIN teachers t ON t.id = h.teacher_id
                            WHERE h.date = ? {scope_sql}
                            ORDER BY h.id DESC
                            """,
                            (str(selected_date),) + scope_params,
                        )
                        st.dataframe(df, use_container_width=True, hide_index=True)

                    # ============================================================
                    # مستحقات الأساتذة
                    # ============================================================
                    def page_teacher_payroll():
                        st.subheader("مستحقات الأساتذة")

                        start_date = st.date_input("من تاريخ", today().replace(day=1), key="payroll_start")
                        end_date = st.date_input("إلى تاريخ", today(), key="payroll_end")
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
                                    SELECT SUM(tp.amount) FROM teacher_payments tp
                                    WHERE tp.teacher_id = t.id AND tp.date BETWEEN ? AND ?
                                ), 0) AS 'المدفوع'
                            FROM teachers t
                            LEFT JOIN teacher_hours h
                                ON h.teacher_id = t.id AND h.date BETWEEN ? AND ?
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
                        st.dataframe(df.drop(columns=["id"]), use_container_width=True, hide_index=True)

                        if has_role("admin", "accountant"):
                            teachers = dataframe_query(
                                "SELECT id, teacher_code, name FROM teachers WHERE active = 1 ORDER BY name"
                            )
                            options = {
                                f"{r['teacher_code']} - {r['name']}": r["id"]
                                for _, r in teachers.iterrows()
                            }

                            st.markdown("### تسجيل دفعة لأستاذ")
                            with st.form("teacher_payment_form"):
                                selected_teacher = st.selectbox("الأستاذ", list(options.keys()))
                                payment_date = st.date_input("تاريخ الدفع", today())
                                amount = st.number_input("المبلغ المدفوع", min_value=0.0, step=100.0)
                                method = st.selectbox("طريقة الدفع", ["كاش", "بنكك", "تحويل بنكي"])
                                notes = st.text_input("ملاحظات")
                                save = st.form_submit_button("تسجيل الدفع")

                            if save:
                                if not require_day_open(payment_date):
                                    return
                                if amount <= 0:
                                    st.error("المبلغ يجب أن يكون أكبر من صفر.")
                                else:
                                    payment_id = execute(
                                        """INSERT INTO teacher_payments
                                        (teacher_id, date, amount, payment_method, notes,
                                         created_by, created_at)
                                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                        (options[selected_teacher], str(payment_date), amount, method,
                                         notes.strip(), current_user()["id"], now_text()),
                                        return_id=True,
                                    )
                                    log_action("دفع مستحق أستاذ", "teacher_payments", payment_id, selected_teacher)
                                    st.success("تم تسجيل الدفع.")

                    # ============================================================
                    # المصروفات
                    # ============================================================
                    def page_expenses():
                        st.subheader("المصروفات")

                        categories = [
                            "إيجار", "كهرباء", "مياه", "إنترنت", "رواتب",
                            "صيانة", "أدوات", "تسويق", "مواصلات", "أخرى",
                        ]

                        with st.form("expense_form", clear_on_submit=True):
                            expense_date = st.date_input("التاريخ", today())
                            category = st.selectbox("البند", categories)
                            description = st.text_input("وصف المصروف")
                            amount = st.number_input("المبلغ", min_value=0.0, step=100.0)
                            method = st.selectbox("طريقة الدفع", ["كاش", "بنكك", "تحويل بنكي"])
                            reference = st.text_input("المرجع / رقم العملية")
                            save = st.form_submit_button("حفظ المصروف")

                        if save:
                            if not require_day_open(expense_date):
                                return
                            if not description.strip():
                                st.error("وصف المصروف مطلوب.")
                            elif amount <= 0:
                                st.error("المبلغ يجب أن يكون أكبر من صفر.")
                            else:
                                expense_id = execute(
                                    """INSERT INTO expenses
                                    (date, category, description, amount, payment_method,
                                     reference, status, created_by, created_at)
                                    VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?)""",
                                    (str(expense_date), category, description.strip(), amount, method,
                                     reference.strip(), current_user()["id"], now_text()),
                                    return_id=True,
                                )
                                log_action("إضافة مصروف", "expenses", expense_id, description.strip())
                                st.success("تم حفظ المصروف.")

                        selected_date = st.date_input("عرض مصروفات يوم", today(), key="expense_report_date")
                        scope_sql, scope_params = scope_clause("e.created_by")
                        df = dataframe_query(
                            f"""
                            SELECT e.id AS 'ID', e.category AS 'البند', e.description AS 'الوصف',
                                   e.amount AS 'المبلغ', e.payment_method AS 'طريقة الدفع',
                                   e.reference AS 'المرجع'
                            FROM expenses e
                            WHERE e.date = ? AND e.status = 'completed' {scope_sql}
                            ORDER BY e.id DESC
                            """,
                            (str(selected_date),) + scope_params,
                        )
                        st.dataframe(df, use_container_width=True, hide_index=True)
                        if not df.empty:
                            st.metric("إجمالي المصروفات", format_money(df["المبلغ"].sum()))

                    # ============================================================
                    # الخزينة
                    # ============================================================
                    def page_cashbox():
                        st.subheader("الخزينة والإقفال اليومي")
                        st.caption(
                            "الإقفال يمنع إضافة أي حركة مالية أو حضور أو ساعات لذلك اليوم حتى يتم فتحه من المدير.")

                        selected_date = st.date_input("تاريخ اليوم", today(), key="cashbox_date")
                        date_str = str(selected_date)
                        closed = is_day_closed(date_str)

                        income = float(dataframe_query(
                            """SELECT COALESCE(SUM(amount), 0) AS total FROM student_payments
                               WHERE date = ? AND payment_method = 'كاش' AND status = 'completed'""",
                            (date_str,))["total"].iloc[0])

                        expense = float(dataframe_query(
                            """SELECT COALESCE(SUM(amount), 0) AS total FROM expenses
                               WHERE date = ? AND payment_method = 'كاش' AND status = 'completed'""",
                            (date_str,))["total"].iloc[0])

                        teacher_paid = float(dataframe_query(
                            """SELECT COALESCE(SUM(amount), 0) AS total FROM teacher_payments
                               WHERE date = ? AND payment_method = 'كاش'""",
                            (date_str,))["total"].iloc[0])

                        bankak_income = float(dataframe_query(
                            """SELECT COALESCE(SUM(amount), 0) AS total FROM student_payments
                               WHERE date = ? AND payment_method = 'بنكك' AND status = 'completed'""",
                            (date_str,))["total"].iloc[0])

                        row = dataframe_query("SELECT * FROM cashbox WHERE date = ?", (date_str,))
                        opening = float(row["opening_balance"].iloc[0]) if not row.empty else 0.0
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

                        if not closed:
                            with st.form("cashbox_form"):
                                opening_balance = st.number_input(
                                    "الرصيد الافتتاحي", min_value=0.0, value=opening, step=100.0
                                )
                                counted_cash = st.number_input(
                                    "النقد الفعلي الموجود عند الإقفال", min_value=0.0, step=100.0
                                )
                                notes = st.text_input("ملاحظات الإقفال")
                                confirm_close = st.checkbox("أؤكد أنني راجعت عمليات اليوم وأريد إقفاله نهائياً")
                                close_day = st.form_submit_button("إقفال اليوم", use_container_width=True)

                            if close_day:
                                if not confirm_close:
                                    st.warning("ضع علامة التأكيد قبل إقفال اليوم.")
                                elif not has_role("admin", "accountant"):
                                    st.error("ليس لديك صلاحية إقفال اليوم.")
                                else:
                                    actual_expected = opening_balance + income - expense - teacher_paid
                                    difference = counted_cash - actual_expected
                                    conn = get_connection()
                                    try:
                                        conn.execute(
                                            """
                                            INSERT INTO cashbox
                                            (date, opening_balance, cash_in, cash_out, counted_cash,
                                             difference, notes, closed_by, closed_at)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                            ON CONFLICT(date) DO UPDATE SET
                                                opening_balance=excluded.opening_balance,
                                                cash_in=excluded.cash_in,
                                                cash_out=excluded.cash_out,
                                                counted_cash=excluded.counted_cash,
                                                difference=excluded.difference,
                                                notes=excluded.notes,
                                                closed_by=excluded.closed_by,
                                                closed_at=excluded.closed_at
                                            """,
                                            (date_str, opening_balance, income, expense + teacher_paid,
                                             counted_cash, difference, notes.strip(),
                                             current_user()["id"], now_text()),
                                        )
                                        conn.execute(
                                            """
                                            INSERT INTO day_closures (date, closed_by, closed_at, status, notes)
                                            VALUES (?, ?, ?, 'closed', ?)
                                            ON CONFLICT(date) DO UPDATE SET
                                                closed_by=excluded.closed_by,
                                                closed_at=excluded.closed_at,
                                                reopened_by=NULL, reopened_at=NULL,
                                                status='closed', notes=excluded.notes
                                            """,
                                            (date_str, current_user()["id"], now_text(), notes.strip()),
                                        )
                                        conn.commit()
                                    except sqlite3.IntegrityError:
                                        conn.rollback()
                                        st.error("تعذر إقفال اليوم. تحقق من البيانات.")
                                        return
                                    finally:
                                        conn.close()

                                    log_action("إقفال اليوم", "day_closures", None, f"{date_str} - الفرق {difference}")
                                    if difference == 0:
                                        st.success("تم إقفال اليوم بنجاح والرصيد مطابق.")
                                    else:
                                        st.warning(f"تم إقفال اليوم. يوجد فرق: {format_money(difference)}")
                                    st.rerun()

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
                                    conn = get_connection()
                                    conn.execute(
                                        """
                                        UPDATE day_closures
                                        SET status='reopened', reopened_by=?, reopened_at=?, notes=COALESCE(notes,'') || ?
                                        WHERE date=? AND status='closed'
                                        """,
                                        (current_user()["id"], now_text(),
                                         f" | فتح: {reason.strip()}", date_str),
                                    )
                                    conn.commit()
                                    conn.close()
                                    log_action("فتح يوم مقفل", "day_closures", None, f"{date_str} - {reason.strip()}")
                                    st.success("تم فتح اليوم. يمكنك الآن تصحيح أو إضافة العمليات.")
                                    st.rerun()

                        st.markdown("### سجل الإقفال")
                        closure_df = dataframe_query(
                            """
                            SELECT d.date AS 'التاريخ',
                                   CASE WHEN d.status='closed' THEN 'مقفل' ELSE 'مفتوح بعد الإقفال' END AS 'الحالة',
                                   u.full_name AS 'أقفل بواسطة',
                                   d.closed_at AS 'وقت الإقفال',
                                   ru.full_name AS 'فتح بواسطة',
                                   d.reopened_at AS 'وقت الفتح',
                                   d.notes AS 'الملاحظات'
                            FROM day_closures d
                            LEFT JOIN users u ON u.id=d.closed_by
                            LEFT JOIN users ru ON ru.id=d.reopened_by
                            ORDER BY d.date DESC LIMIT 100
                            """
                        )
                        st.dataframe(closure_df, use_container_width=True, hide_index=True)

                    # ============================================================
                    # التقارير
                    # ============================================================
                    def page_reports():
                        st.subheader("التقارير")
                        st.caption(
                            "اختر التقرير المطلوب. كل التقارير تستخدم نفس قاعدة البيانات وبها رقم بنكك عند الدفع ببنكك.")

                        tab_daily, tab_period, tab_attendance, tab_cash, tab_audit = st.tabs(
                            ["التقرير اليومي", "تقرير الفترة", "الحضور والساعات", "الخزينة", "سجل العمليات"]
                        )

                        with tab_daily:
                            selected_date = st.date_input("التاريخ", today(), key="reports_date")
                            date_str = str(selected_date)

                            payments = dataframe_query(
                                """
                                SELECT p.id AS 'رقم العملية', s.student_code AS 'رقم الطالب',
                                       s.name AS 'الطالب', c.name AS 'الكورس', t.name AS 'الأستاذ',
                                       p.amount AS 'المبلغ', p.payment_method AS 'طريقة الدفع',
                                       COALESCE(NULLIF(p.transaction_number,''), '-') AS 'رقم بنكك',
                                       p.date AS 'التاريخ', p.status AS 'الحالة'
                                FROM student_payments p
                                JOIN students s ON s.id=p.student_id
                                LEFT JOIN courses c ON c.id=p.course_id
                                LEFT JOIN teachers t ON t.id=p.teacher_id
                                WHERE p.date=? ORDER BY p.id DESC
                                """, (date_str,)
                            )
                            expenses = dataframe_query(
                                """
                                SELECT e.id AS 'رقم المصروف', e.category AS 'البند',
                                       e.description AS 'الوصف', e.amount AS 'المبلغ',
                                       e.payment_method AS 'طريقة الدفع',
                                       COALESCE(NULLIF(e.reference,''), '-') AS 'المرجع', e.date AS 'التاريخ'
                                FROM expenses e WHERE e.date=? ORDER BY e.id DESC
                                """, (date_str,)
                            )
                            teacher_payments = dataframe_query(
                                """
                                SELECT tp.id AS 'رقم الدفع', t.teacher_code AS 'رقم الأستاذ',
                                       t.name AS 'الأستاذ', tp.amount AS 'المبلغ',
                                       tp.payment_method AS 'طريقة الدفع', tp.notes AS 'ملاحظات', tp.date AS 'التاريخ'
                                FROM teacher_payments tp JOIN teachers t ON t.id=tp.teacher_id
                                WHERE tp.date=? ORDER BY tp.id DESC
                                """, (date_str,)
                            )
                            attendance = dataframe_query(
                                """
                                SELECT a.id AS 'ID', s.student_code AS 'رقم الطالب', s.name AS 'الطالب',
                                       c.name AS 'الكورس', t.name AS 'الأستاذ', a.check_in AS 'وقت الحضور',
                                       a.status AS 'الحالة', a.notes AS 'ملاحظات'
                                FROM student_attendance a JOIN students s ON s.id=a.student_id
                                LEFT JOIN courses c ON c.id=a.course_id
                                LEFT JOIN teachers t ON t.id=a.teacher_id
                                WHERE a.date=? ORDER BY a.id DESC
                                """, (date_str,)
                            )
                            teacher_hours = dataframe_query(
                                """
                                SELECT h.id AS 'ID', t.teacher_code AS 'رقم الأستاذ', t.name AS 'الأستاذ',
                                       h.check_in AS 'الدخول', h.check_out AS 'الخروج', h.hours_worked AS 'الساعات',
                                       h.hours_worked*t.hourly_rate AS 'المستحق'
                                FROM teacher_hours h JOIN teachers t ON t.id=h.teacher_id
                                WHERE h.date=? ORDER BY h.id DESC
                                """, (date_str,)
                            )

                            total_income = float(payments.loc[payments[
                                                                  'الحالة'] == 'completed', 'المبلغ'].sum()) if not payments.empty else 0
                            total_expense = float(expenses['المبلغ'].sum()) if not expenses.empty else 0
                            total_teacher = float(teacher_payments['المبلغ'].sum()) if not teacher_payments.empty else 0
                            cash_income = float(payments.loc[(payments['الحالة'] == 'completed') & (
                                        payments['طريقة الدفع'] == 'كاش'), 'المبلغ'].sum()) if not payments.empty else 0
                            bankak_income = float(payments.loc[(payments['الحالة'] == 'completed') & (payments[
                                                                                                          'طريقة الدفع'] == 'بنكك'), 'المبلغ'].sum()) if not payments.empty else 0

                            c1, c2, c3, c4, c5 = st.columns(5)
                            c1.metric("إيرادات", format_money(total_income))
                            c2.metric("مصروفات", format_money(total_expense))
                            c3.metric("دفع الأساتذة", format_money(total_teacher))
                            c4.metric("كاش", format_money(cash_income))
                            c5.metric("بنكك", format_money(bankak_income))

                            st.markdown("### مدفوعات الطلاب")
                            if payments.empty:
                                st.info("لا توجد مدفوعات في هذا اليوم.")
                            else:
                                st.dataframe(payments, use_container_width=True, hide_index=True)
                                download_excel(payments, f"daily_payments_{date_str}.xlsx")

                            st.markdown("### المصروفات")
                            if expenses.empty:
                                st.info("لا توجد مصروفات في هذا اليوم.")
                            else:
                                st.dataframe(expenses, use_container_width=True, hide_index=True)
                                download_excel(expenses, f"daily_expenses_{date_str}.xlsx")

                            st.markdown("### مدفوعات الأساتذة")
                            st.dataframe(teacher_payments, use_container_width=True, hide_index=True)

                            st.markdown("### حضور الطلاب")
                            st.dataframe(attendance, use_container_width=True, hide_index=True)

                            st.markdown("### ساعات الأساتذة")
                            st.dataframe(teacher_hours, use_container_width=True, hide_index=True)

                        with tab_period:
                            start_date = st.date_input("من", today().replace(day=1), key="period_start")
                            end_date = st.date_input("إلى", today(), key="period_end")
                            if end_date < start_date:
                                st.error("الفترة غير صحيحة.")
                            else:
                                income = dataframe_query(
                                    """SELECT date, SUM(amount) AS income FROM student_payments
                                       WHERE date BETWEEN ? AND ? AND status='completed' GROUP BY date""",
                                    (str(start_date), str(end_date)))
                                expenses = dataframe_query(
                                    """SELECT date, SUM(amount) AS expense FROM expenses
                                       WHERE date BETWEEN ? AND ? AND status='completed' GROUP BY date""",
                                    (str(start_date), str(end_date)))
                                teacher_paid = dataframe_query(
                                    """SELECT date, SUM(amount) AS teacher_paid FROM teacher_payments
                                       WHERE date BETWEEN ? AND ? GROUP BY date""",
                                    (str(start_date), str(end_date)))
                                report = pd.DataFrame({'date': pd.date_range(start_date, end_date)})
                                for part in (income, expenses, teacher_paid):
                                    if not part.empty:
                                        part['date'] = pd.to_datetime(part['date'])
                                        report = report.merge(part, on='date', how='left')
                                for col in ('income', 'expense', 'teacher_paid'):
                                    if col not in report.columns: report[col] = 0
                                    report[col] = report[col].fillna(0)
                                report['net'] = report['income'] - report['expense'] - report['teacher_paid']
                                st.dataframe(report, use_container_width=True, hide_index=True)
                                st.bar_chart(
                                    report.set_index('date')[['income', 'expense', 'teacher_paid']],
                                    color=["#176b87", "#c95757", "#d49a2a"],
                                    use_container_width=True,
                                    height=340,
                                )
                                st.line_chart(
                                    report.set_index('date')[['net']],
                                    color="#238b67",
                                    use_container_width=True,
                                    height=220,
                                )
                                st.metric("إجمالي الإيرادات", format_money(report['income'].sum()))
                                st.metric("إجمالي صافي الفترة", format_money(report['net'].sum()))
                                download_excel(report, "period_report.xlsx")

                        with tab_attendance:
                            selected_date = st.date_input("التاريخ", today(), key="report_attendance_date")
                            date_str = str(selected_date)
                            attendance = dataframe_query("""SELECT s.student_code AS 'رقم الطالب