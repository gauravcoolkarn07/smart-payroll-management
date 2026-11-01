from io import BytesIO

from flask import make_response
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)
import os
import sqlite3
from functools import wraps
import calendar
from datetime import date, timedelta

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash, g
)
from werkzeug.security import check_password_hash, generate_password_hash
import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv
load_dotenv()
def send_email(to_email, subject, body):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.getenv("MAIL_DEFAULT_SENDER")
        msg["To"] = to_email
        msg.set_content(body)

        with smtplib.SMTP(
            os.getenv("MAIL_SERVER"),
            int(os.getenv("MAIL_PORT", 587))
        ) as server:
            server.starttls()
            server.login(
                os.getenv("MAIL_USERNAME"),
                os.getenv("MAIL_PASSWORD")
            )
            server.send_message(msg)

        return True

    except Exception as e:
        print(f"Email sending failed: {e}")
        return False

app = Flask(__name__)

# Development fallback. Set SECRET_KEY in your environment
# before deploying the application.
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "dev-only-change-this-secret-before-deployment"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "database", "payroll.db")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view



def role_required(required_role):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            if session.get("role") != required_role:
                flash(
                    "You are not authorized to access that page.",
                    "error"
                )
                return redirect(url_for("dashboard"))

            return view(*args, **kwargs)

        # Give each decorated view a unique endpoint name.
        wrapped_view.__name__ = view.__name__
        return wrapped_view

    return decorator



@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Enter both username and password.", "error")
            return render_template("login.html")

        user = get_db().execute(
            """
            SELECT id, username, password_hash, role, is_active
            FROM users
            WHERE username = ?
            """,
            (username,)
        ).fetchone()

        if (
            user is None
            or not user["is_active"]
            or not check_password_hash(user["password_hash"], password)
        ):
            flash("Invalid username or password.", "error")
            return render_template("login.html")

        # Start a fresh session after successful authentication.
        session.clear()
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]

        flash("Login successful.", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    if session["role"] == "admin":
        return redirect(url_for("admin_dashboard"))

    if session["role"] == "employee":
        return redirect(url_for("employee_dashboard"))

    session.clear()
    flash("Please log in again.", "error")
    return redirect(url_for("login"))



@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    db = get_db()

    # Existing organization statistics
    employee_count = db.execute(
        "SELECT COUNT(*) FROM employees"
    ).fetchone()[0]

    task_count = db.execute(
        "SELECT COUNT(*) FROM tasks"
    ).fetchone()[0]

    pending_tasks = db.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = 'Pending'"
    ).fetchone()[0]

    pending_leaves = db.execute(
        "SELECT COUNT(*) FROM leave_requests WHERE status = 'Pending'"
    ).fetchone()[0]

    # Current month in YYYY-MM format
    current_month = date.today().strftime("%Y-%m")

    # Total net salary for the current month
    monthly_payroll = db.execute(
        """
        SELECT COALESCE(SUM(net_salary), 0)
        FROM payroll
        WHERE month = ?
        """,
        (current_month,)
    ).fetchone()[0]

    # Number of payroll records for the current month
    payroll_record_count = db.execute(
        """
        SELECT COUNT(*)
        FROM payroll
        WHERE month = ?
        """,
        (current_month,)
    ).fetchone()[0]

    # Payroll records that have not yet been paid
    pending_payments = db.execute(
        """
        SELECT COUNT(*)
        FROM payroll
        WHERE month = ? AND status != 'Paid'
        """,
        (current_month,)
    ).fetchone()[0]

    return render_template(
        "admin_dashboard.html",
        employee_count=employee_count,
        task_count=task_count,
        pending_tasks=pending_tasks,
        pending_leaves=pending_leaves,
        monthly_payroll=monthly_payroll,
        payroll_record_count=payroll_record_count,
        pending_payments=pending_payments,
        current_month=current_month
    )



@app.route("/employee")
@role_required("employee")
def employee_dashboard():
    employee = get_db().execute(
        """
        SELECT id, employee_code, full_name, department,
               designation, basic_salary
        FROM employees
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    if employee is None:
        return (
            "No employee profile is linked to this account. "
            "Please contact the administrator.",
            403
        )

    return render_template(
        "employee_dashboard.html",
        employee=employee
    )

@app.route("/admin/employees", methods=["GET", "POST"])
@role_required("admin")
def manage_employees():
    db = get_db()

    if request.method == "POST":
        employee_code = request.form.get("employee_code", "").strip()
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        department = request.form.get("department", "").strip()
        designation = request.form.get("designation", "").strip()
        basic_salary = request.form.get("basic_salary", "").strip()

        # New login fields
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not all([
            employee_code, full_name,email, department,
            designation, basic_salary, username, password
        ]):
            flash("Please fill in all employee details and login fields.", "error")

        elif len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")

        else:
            try:
                salary = float(basic_salary)

                if salary < 0:
                    flash("Salary cannot be negative.", "error")

                else:
                    # Store a hashed password, never the plain password
                    password_hash = generate_password_hash(password)

                    # Create the employee login account
                    cursor = db.execute(
                        """
                        INSERT INTO users (username, password_hash, role)
                        VALUES (?, ?, 'employee')
                        """,
                        (username, password_hash)
                    )
                    user_id = cursor.lastrowid

                    # Link the employee profile to that account
                    db.execute(
                        """
                        INSERT INTO employees
                        (user_id, employee_code, full_name, email, department,
                         designation, basic_salary)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            user_id, employee_code, full_name, email,
                            department, designation, salary
                        )
                    )

                    db.commit()

                    email_sent = send_email(
                        email,
                        "Welcome to the Smart Payroll Management System",
                        f"""Hello {full_name},

                    Congratulations! Your employee account has been created.

                    Employee Code: {employee_code}
                    Username: {username}

                    You can now log in to the Smart Payroll Management System
                    using your username and the password provided during account setup.

                    For security, please keep your password confidential.

                    Regards,
                    Administration Team
                    Smart Payroll Management System
                    """
                    )

                    if email_sent:
                        flash(
                            "Employee created successfully. Welcome email sent.",
                            "success"
                        )
                    else:
                        flash(
                            "Employee created successfully, but the welcome email could not be sent.",
                            "error"
                        )

                    return redirect(url_for("manage_employees"))


            except ValueError:
                db.rollback()
                flash("Please enter a valid salary.", "error")

            except sqlite3.IntegrityError:
                db.rollback()
                flash(
                    "Username or employee code already exists. "
                    "Please use unique values.",
                    "error"
                )

    employees = db.execute(
        """
        SELECT e.id, e.employee_code, e.full_name, e.department,
               e.designation, e.basic_salary, u.username
        FROM employees e
        LEFT JOIN users u ON e.user_id = u.id
        ORDER BY e.id DESC
        """
    ).fetchall()

    return render_template(
        "manage_employees.html",
        employees=employees
    )

@app.route("/admin/employees/delete/<int:employee_id>", methods=["POST"])
@role_required("admin")
def delete_employee(employee_id):
    db = get_db()

    employee = db.execute(
        "SELECT id FROM employees WHERE id = ?",
        (employee_id,)
    ).fetchone()

    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("manage_employees"))

    try:
        db.execute(
            "DELETE FROM employees WHERE id = ?",
            (employee_id,)
        )
        db.commit()
        flash("Employee deleted successfully.", "success")

    except sqlite3.IntegrityError:
        db.rollback()
        flash(
            "This employee has related records and cannot be deleted.",
            "error"
        )

    return redirect(url_for("manage_employees"))

@app.route("/admin/employees/edit/<int:employee_id>", methods=["GET", "POST"])
@role_required("admin")
def edit_employee(employee_id):
    db = get_db()

    employee = db.execute(
        "SELECT * FROM employees WHERE id = ?",
        (employee_id,)
    ).fetchone()

    if employee is None:
        flash("Employee not found.", "error")
        return redirect(url_for("manage_employees"))

    if request.method == "POST":
        employee_code = request.form.get("employee_code", "").strip()
        full_name = request.form.get("full_name", "").strip()
        department = request.form.get("department", "").strip()
        designation = request.form.get("designation", "").strip()
        basic_salary = request.form.get("basic_salary", "").strip()

        if not all([
            employee_code, full_name, department,
            designation, basic_salary
        ]):
            flash("Please fill in all fields.", "error")

        else:
            try:
                salary = float(basic_salary)

                if salary < 0:
                    flash("Salary cannot be negative.", "error")
                else:
                    db.execute(
                        """
                        UPDATE employees
                        SET employee_code = ?, full_name = ?,
                            department = ?, designation = ?,
                            basic_salary = ?
                        WHERE id = ?
                        """,
                        (
                            employee_code, full_name, department,
                            designation, salary, employee_id
                        )
                    )
                    db.commit()
                    flash("Employee updated successfully.", "success")
                    return redirect(url_for("manage_employees"))

            except ValueError:
                flash("Please enter a valid salary.", "error")

            except sqlite3.IntegrityError:
                db.rollback()
                flash("Employee code already exists.", "error")

            # Refresh the employee record after validation errors.
            employee = db.execute(
                "SELECT * FROM employees WHERE id = ?",
                (employee_id,)
            ).fetchone()

    return render_template("edit_employee.html", employee=employee)

from datetime import date

@app.route("/admin/attendance", methods=["GET", "POST"])
@role_required("admin")
def manage_attendance():
    db = get_db()

    if request.method == "POST":
        employee_id = request.form.get("employee_id", "").strip()
        attendance_date = request.form.get("attendance_date", "").strip()
        status = request.form.get("status", "").strip()

        if not employee_id or not attendance_date or not status:
            flash("Please fill in all required fields.", "error")

        elif status not in ("Present", "Absent", "Half Day", "Leave"):
            flash("Invalid attendance status.", "error")

        else:
            try:
                db.execute(
                    """
                    INSERT INTO attendance
                    (employee_id, attendance_date, status)
                    VALUES (?, ?, ?)
                    """,
                    (int(employee_id), attendance_date, status)
                )
                db.commit()
                flash("Attendance recorded successfully.", "success")
                return redirect(url_for("manage_attendance"))

            except ValueError:
                flash("Please select a valid employee.", "error")

            except sqlite3.IntegrityError:
                db.rollback()
                flash(
                    "Attendance already exists for this employee and date.",
                    "error"
                )

    employees = db.execute(
        """
        SELECT id, employee_code, full_name
        FROM employees
        ORDER BY full_name
        """
    ).fetchall()

    records = db.execute(
        """
        SELECT attendance.attendance_date,
               attendance.status,
               employees.employee_code,
               employees.full_name
        FROM attendance
        JOIN employees ON attendance.employee_id = employees.id
        ORDER BY attendance.attendance_date DESC, employees.full_name
        """
    ).fetchall()

    return render_template(
        "manage_attendance.html",
        employees=employees,
        records=records,
        today=date.today().isoformat()
    )

@app.route("/employee/leave", methods=["GET", "POST"])
@role_required("employee")
def employee_leave():
    db = get_db()

    employee = db.execute(
        "SELECT id FROM employees WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()

    if employee is None:
        return "Employee profile not found.", 403

    if request.method == "POST":
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        reason = request.form.get("reason", "").strip()

        if not start_date or not end_date or not reason:
            flash("Please fill in all fields.", "error")

        elif end_date < start_date:
            flash("End date cannot be before start date.", "error")

        else:
            db.execute(
                """
                INSERT INTO leave_requests
                (employee_id, start_date, end_date, reason)
                VALUES (?, ?, ?, ?)
                """,
                (employee["id"], start_date, end_date, reason)
            )
            db.commit()

            flash("Leave request submitted successfully.", "success")
            return redirect(url_for("employee_leave"))

    requests = db.execute(
        """
        SELECT start_date, end_date, reason, status, admin_comment
        FROM leave_requests
        WHERE employee_id = ?
        ORDER BY applied_at DESC
        """,
        (employee["id"],)
    ).fetchall()

    return render_template(
        "employee_leave.html",
        requests=requests
    )

@app.route("/admin/leaves", methods=["GET", "POST"])
@role_required("admin")
def manage_leaves():
    db = get_db()

    if request.method == "POST":
        leave_id = request.form.get("leave_id", "").strip()
        status = request.form.get("status", "").strip()
        admin_comment = request.form.get("admin_comment", "").strip()

        if status not in ("Approved", "Rejected"):
            flash("Invalid leave decision.", "error")
        else:
            leave = db.execute(
                "SELECT id FROM leave_requests WHERE id = ?",
                (leave_id,)
            ).fetchone()

            if leave is None:
                flash("Leave request not found.", "error")
            else:
                db.execute(
                    """
                    UPDATE leave_requests
                    SET status = ?, admin_comment = ?
                    WHERE id = ?
                    """,
                    (status, admin_comment, leave_id)
                )
                db.commit()
                flash("Leave request updated successfully.", "success")
                return redirect(url_for("manage_leaves"))

    requests = db.execute(
        """
        SELECT leave_requests.id,
               employees.employee_code,
               employees.full_name,
               leave_requests.start_date,
               leave_requests.end_date,
               leave_requests.reason,
               leave_requests.status,
               leave_requests.admin_comment
        FROM leave_requests
        JOIN employees ON leave_requests.employee_id = employees.id
        ORDER BY leave_requests.applied_at DESC
        """
    ).fetchall()

    return render_template("manage_leaves.html", requests=requests)

@app.route("/admin/tasks", methods=["GET", "POST"])
@role_required("admin")
def manage_tasks():
    db = get_db()

    if request.method == "POST":
        employee_id = request.form.get("employee_id")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        assigned_date = request.form.get("assigned_date")
        deadline = request.form.get("deadline") or None

        if not employee_id or not title or not assigned_date:
            flash("Please fill in all required fields.", "error")
        elif deadline and deadline < assigned_date:
            flash("Deadline cannot be before the assigned date.", "error")
        else:
            employee = db.execute(
                """
                SELECT id, full_name, email
                FROM employees
                WHERE id = ?
                """,
                (employee_id,)
            ).fetchone()
            print("Selected employee email:", repr(employee["email"]))

            if not employee:
                flash("Please select a valid employee.", "error")
            else:

                db.execute(
                    """
                    INSERT INTO tasks
                    (employee_id, title, description, assigned_date, deadline)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        employee_id,
                        title,
                        description,
                        assigned_date,
                        deadline
                    )
                )
                db.commit()

                if employee["email"]:
                    email_body = f"""Hello {employee['full_name']},

                A new task has been assigned to you.

                Task Title: {title}
                Description: {description or 'No description provided'}
                Assigned Date: {assigned_date}
                Deadline: {deadline or 'No deadline specified'}

                Please log in to the Smart Payroll Management System
                to review your task.

                Regards,
                Administration Team
                Smart Payroll Management System
                """

                    email_sent = send_email(
                        employee["email"],
                        "New Task Assigned - Smart Payroll Management System",
                        email_body
                    )

                    if email_sent:
                        flash("Task assigned successfully. Email notification sent!", "success")
                    else:
                        flash("Task assigned successfully, but the email could not be sent.", "error")
                else:
                    flash("Task assigned successfully, but the employee has no email address.", "error")

                return redirect(url_for("manage_tasks"))

    employees = db.execute(
        "SELECT id, employee_code, full_name FROM employees ORDER BY full_name"
    ).fetchall()

    tasks = db.execute(
        """
        SELECT tasks.*, employees.full_name, employees.employee_code
        FROM tasks
        JOIN employees ON tasks.employee_id = employees.id
        ORDER BY tasks.id DESC
        """
    ).fetchall()

    return render_template(
        "manage_tasks.html",
        employees=employees,
        tasks=tasks
    )

@app.route("/employee/tasks", methods=["GET", "POST"])
@role_required("employee")
def employee_tasks():
    db = get_db()

    employee = db.execute(
        "SELECT id FROM employees WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()

    if not employee:
        flash("Your employee profile was not found.", "error")
        return redirect(url_for("dashboard"))

    employee_id = employee["id"]

    if request.method == "POST":
        task_id = request.form.get("task_id")
        new_status = request.form.get("status")

        if new_status not in ("Pending", "In Progress", "Completed"):
            flash("Invalid task status.", "error")
        else:
            task = db.execute(
                """
                SELECT id FROM tasks
                WHERE id = ? AND employee_id = ?
                """,
                (task_id, employee_id)
            ).fetchone()

            if not task:
                flash("Task not found.", "error")
            else:
                completed_at = (
                    __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if new_status == "Completed"
                    else None
                )

                db.execute(
                    """
                    UPDATE tasks
                    SET status = ?, completed_at = ?
                    WHERE id = ? AND employee_id = ?
                    """,
                    (new_status, completed_at, task_id, employee_id)
                )
                db.commit()
                flash("Task status updated successfully!", "success")

        return redirect(url_for("employee_tasks"))

    tasks = db.execute(
        """
        SELECT id, title, description, assigned_date, deadline,
               status, completed_at
        FROM tasks
        WHERE employee_id = ?
        ORDER BY id DESC
        """,
        (employee_id,)
    ).fetchall()

    return render_template("employee_tasks.html", tasks=tasks)


@app.route("/admin/performance", methods=["GET", "POST"])
@role_required("admin")
def manage_performance():
    db = get_db()

    if request.method == "POST":
        employee_id = request.form.get("employee_id")
        month = request.form.get("month")
        attendance_score = request.form.get("attendance_score", type=float)
        task_score = request.form.get("task_score", type=float)
        punctuality_score = request.form.get("punctuality_score", type=float)

        if (
            not employee_id
            or not month
            or attendance_score is None
            or task_score is None
            or punctuality_score is None
        ):
            flash("Please fill in all required fields.", "error")
        elif any(
            score < 0 or score > 100
            for score in (
                attendance_score,
                task_score,
                punctuality_score
            )
        ):
            flash("Each score must be between 0 and 100.", "error")
        else:
            employee = db.execute(
                "SELECT id FROM employees WHERE id = ?",
                (employee_id,)
            ).fetchone()

            if not employee:
                flash("Please select a valid employee.", "error")
            else:
                # Equal weight for all three performance scores.
                total_score = round(
                    (attendance_score + task_score + punctuality_score) / 3,
                    2
                )

                if total_score >= 90:
                    grade = "A"
                    bonus = 2000
                elif total_score >= 75:
                    grade = "B"
                    bonus = 1000
                elif total_score >= 60:
                    grade = "C"
                    bonus = 500
                else:
                    grade = "D"
                    bonus = 0

                try:
                    db.execute(
                        """
                        INSERT INTO performance
                        (
                            employee_id, month, attendance_score,
                            task_score, punctuality_score,
                            total_score, grade, bonus
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            employee_id,
                            month,
                            attendance_score,
                            task_score,
                            punctuality_score,
                            total_score,
                            grade,
                            bonus
                        )
                    )
                    db.commit()
                    flash("Performance evaluation saved successfully!", "success")
                    return redirect(url_for("manage_performance"))

                except sqlite3.IntegrityError:
                    flash(
                        "This employee already has an evaluation for that month.",
                        "error"
                    )

    employees = db.execute(
        """
        SELECT id, employee_code, full_name
        FROM employees
        ORDER BY full_name
        """
    ).fetchall()

    evaluations = db.execute(
        """
        SELECT performance.*, employees.full_name, employees.employee_code
        FROM performance
        JOIN employees ON performance.employee_id = employees.id
        ORDER BY performance.month DESC, employees.full_name
        """
    ).fetchall()

    return render_template(
        "manage_performance.html",
        employees=employees,
        evaluations=evaluations
    )

@app.route("/employee/performance")
@role_required("employee")
def employee_performance():
    db = get_db()

    employee = db.execute(
        "SELECT id FROM employees WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()

    if not employee:
        flash("Your employee profile was not found.", "error")
        return redirect(url_for("dashboard"))

    records = db.execute(
        """
        SELECT month, attendance_score, task_score,
               punctuality_score, total_score, grade,
               bonus, evaluated_at
        FROM performance
        WHERE employee_id = ?
        ORDER BY month DESC
        """,
        (employee["id"],)
    ).fetchall()

    return render_template(
        "employee_performance.html",
        records=records
    )

@app.route("/admin/payroll", methods=["GET", "POST"])
@role_required("admin")
def manage_payroll():
    db = get_db()

    if request.method == "POST":
        employee_id = request.form.get("employee_id")
        month = request.form.get("month")
        other_deductions = request.form.get(
            "other_deductions", "0"
        ).strip()

        try:
            other_deductions = float(other_deductions)
        except ValueError:
            other_deductions = -1

        if not employee_id or not month:
            flash("Please select an employee and month.", "error")

        elif other_deductions < 0:
            flash("Other deductions cannot be negative.", "error")

        else:
            try:
                first_day = date.fromisoformat(month + "-01")
                last_day = date(
                    first_day.year,
                    first_day.month,
                    calendar.monthrange(
                        first_day.year, first_day.month
                    )[1]
                )

                employee = db.execute(
                    """
                    SELECT id, basic_salary
                    FROM employees
                    WHERE id = ?
                    """,
                    (employee_id,)
                ).fetchone()

                if not employee:
                    flash("Please select a valid employee.", "error")

                else:
                    basic_salary = float(employee["basic_salary"])

                    # Get the performance bonus for this month.
                    performance = db.execute(
                        """
                        SELECT bonus
                        FROM performance
                        WHERE employee_id = ? AND month = ?
                        """,
                        (employee_id, month)
                    ).fetchone()

                    bonus = (
                        float(performance["bonus"])
                        if performance else 0
                    )

                    # Find approved leaves overlapping this month.
                    leaves = db.execute(
                        """
                        SELECT start_date, end_date
                        FROM leave_requests
                        WHERE employee_id = ?
                          AND status = 'Approved'
                          AND start_date <= ?
                          AND end_date >= ?
                        """,
                        (
                            employee_id,
                            last_day.isoformat(),
                            first_day.isoformat()
                        )
                    ).fetchall()

                    # Count unique approved leave days.
                    # Sundays are excluded; Saturdays count as working days.
                    leave_days = set()

                    for leave in leaves:
                        start = max(
                            date.fromisoformat(leave["start_date"]),
                            first_day
                        )
                        end = min(
                            date.fromisoformat(leave["end_date"]),
                            last_day
                        )

                        current_day = start

                        while current_day <= end:
                            if current_day.weekday() != 6:
                                leave_days.add(current_day)

                            current_day += timedelta(days=1)

                    daily_salary = basic_salary / 26
                    leave_deduction = round(
                        daily_salary * len(leave_days), 2
                    )

                    # Sample project rule: 5% of basic salary.
                    tax_deduction = round(basic_salary * 0.05, 2)

                    net_salary = round(
                        basic_salary
                        + bonus
                        - tax_deduction
                        - leave_deduction
                        - other_deductions,
                        2
                    )

                    if net_salary < 0:
                        flash(
                            "Deductions exceed the available salary. "
                            "Please check the amounts.",
                            "error"
                        )

                    else:
                        try:
                            db.execute(
                                """
                                INSERT INTO payroll (
                                    employee_id, month, basic_salary,
                                    bonus, tax_deduction,
                                    leave_deduction, other_deductions,
                                    net_salary
                                )
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    employee_id,
                                    month,
                                    basic_salary,
                                    bonus,
                                    tax_deduction,
                                    leave_deduction,
                                    other_deductions,
                                    net_salary
                                )
                            )

                            db.commit()

                            flash(
                                "Payroll generated successfully!",
                                "success"
                            )
                            return redirect(url_for("manage_payroll"))

                        except sqlite3.IntegrityError:
                            flash(
                                "Payroll already exists for this employee "
                                "and month.",
                                "error"
                            )

            except ValueError:
                flash("Please enter a valid payroll month.", "error")

    employees = db.execute(
        """
        SELECT id, employee_code, full_name, basic_salary
        FROM employees
        ORDER BY full_name
        """
    ).fetchall()

    payroll_records = db.execute(
        """
        SELECT payroll.*, employees.employee_code,
               employees.full_name
        FROM payroll
        JOIN employees ON payroll.employee_id = employees.id
        ORDER BY payroll.month DESC, employees.full_name
        """
    ).fetchall()

    return render_template(
        "manage_payroll.html",
        employees=employees,
        payroll_records=payroll_records
    )

@app.route("/admin/payroll/status/<int:payroll_id>", methods=["POST"])
@role_required("admin")
def update_payroll_status(payroll_id):
    db = get_db()

    new_status = request.form.get("status")

    if new_status not in ("Finalized", "Paid"):
        flash("Invalid payroll status.", "error")
        return redirect(url_for("manage_payroll"))

    payroll = db.execute(
        "SELECT status FROM payroll WHERE id = ?",
        (payroll_id,)
    ).fetchone()

    if not payroll:
        flash("Payroll record not found.", "error")

    elif payroll["status"] == "Paid":
        flash("Paid payroll records cannot be changed.", "error")

    elif (
        new_status == "Paid"
        and payroll["status"] != "Finalized"
    ):
        flash("Finalize payroll before marking it as paid.", "error")

    elif (
        payroll["status"] == "Draft"
        and new_status == "Paid"
    ):
        flash("Finalize payroll before marking it as paid.", "error")

    else:
        db.execute(
            "UPDATE payroll SET status = ? WHERE id = ?",
            (new_status, payroll_id)
        )
        db.commit()
        flash("Payroll status updated successfully!", "success")

    return redirect(url_for("manage_payroll"))

@app.route("/employee/salary-history")
@role_required("employee")
def employee_salary_history():
    db = get_db()

    employee = db.execute(
        "SELECT id FROM employees WHERE user_id = ?",
        (session["user_id"],)
    ).fetchone()

    if not employee:
        flash("Your employee profile was not found.", "error")
        return redirect(url_for("dashboard"))

    payroll_records = db.execute(
        """
        SELECT id, month, basic_salary, bonus, tax_deduction,
       leave_deduction, other_deductions, net_salary,
       status, generated_at
FROM payroll
WHERE employee_id = ?
ORDER BY month DESC
        """,
        (employee["id"],)
    ).fetchall()

    return render_template(
        "employee_salary_history.html",
        payroll_records=payroll_records
    )

@app.route("/employee/salary-slip/<int:payroll_id>")
@role_required("employee")
def download_salary_slip(payroll_id):
    db = get_db()

    # Find the logged-in employee's profile.
    employee = db.execute(
        """
        SELECT id, employee_code, full_name, email,
               department, designation
        FROM employees
        WHERE user_id = ?
        """,
        (session["user_id"],)
    ).fetchone()

    if not employee:
        flash("Your employee profile was not found.", "error")
        return redirect(url_for("employee_salary_history"))

    # Retrieve only a payroll record belonging to this employee.
    payroll = db.execute(
        """
        SELECT id, month, basic_salary, bonus, tax_deduction,
               leave_deduction, other_deductions, net_salary,
               status, generated_at
        FROM payroll
        WHERE id = ? AND employee_id = ?
        """,
        (payroll_id, employee["id"])
    ).fetchone()

    if not payroll:
        flash("Salary slip not found.", "error")
        return redirect(url_for("employee_salary_history"))

    # Generate the PDF in memory; no PDF files are saved on the server.
    pdf_buffer = BytesIO()

    document = SimpleDocTemplate(
        pdf_buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="SlipTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#173b68"),
        fontSize=20,
        spaceAfter=8
    ))

    elements = [
        Paragraph("SALARY SLIP", styles["SlipTitle"]),
        Paragraph(
            f"Payroll Month: {payroll['month']}",
            styles["Heading2"]
        ),
        Spacer(1, 8 * mm),
        Paragraph("Employee Details", styles["Heading2"])
    ]

    employee_data = [
        ["Employee Code", employee["employee_code"]],
        ["Employee Name", employee["full_name"]],
        ["Department", employee["department"] or "-"],
        ["Designation", employee["designation"] or "-"],
        ["Email", employee["email"] or "-"],
    ]

    employee_table = Table(
        employee_data,
        colWidths=[50 * mm, 110 * mm]
    )
    employee_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eaf1f8")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#173b68")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d5deea")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    elements.extend([
        employee_table,
        Spacer(1, 8 * mm),
        Paragraph("Salary Breakdown", styles["Heading2"])
    ])

    def money(value):
        return f"Rs. {float(value or 0):,.2f}"

    salary_data = [
        ["Description", "Amount"],
        ["Basic Salary", money(payroll["basic_salary"])],
        ["Performance Bonus", money(payroll["bonus"])],
        ["Tax Deduction", money(payroll["tax_deduction"])],
        ["Leave Deduction", money(payroll["leave_deduction"])],
        ["Other Deductions", money(payroll["other_deductions"])],
        ["Net Salary", money(payroll["net_salary"])],
    ]

    salary_table = Table(
        salary_data,
        colWidths=[100 * mm, 60 * mm],
        repeatRows=1
    )
    salary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173b68")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -2), "Helvetica"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e4f5e9")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d5deea")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))

    elements.extend([
        salary_table,
        Spacer(1, 8 * mm),
        Paragraph(
            f"Payroll Status: {payroll['status']}",
            styles["Normal"]
        ),
        Paragraph(
            f"Generated At: {payroll['generated_at']}",
            styles["Normal"]
        ),
        Spacer(1, 10 * mm),
        Paragraph(
            "This salary slip was generated electronically by the "
            "Smart Payroll Management System.",
            styles["Italic"]
        )
    ])

    document.build(elements)
    pdf_buffer.seek(0)

    response = make_response(pdf_buffer.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = (
        f'attachment; filename="salary_slip_{payroll["month"]}.pdf"'
    )

    return response




@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You have logged out successfully.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
