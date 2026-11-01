
import os
import sqlite3
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_DIR = os.path.join(BASE_DIR, "database")
DATABASE_PATH = os.path.join(DATABASE_DIR, "payroll.db")


def initialize_database():
    os.makedirs(DATABASE_DIR, exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")

    connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'employee')),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            employee_code TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT,
            department TEXT,
            designation TEXT,
            joining_date TEXT,
            basic_salary REAL NOT NULL DEFAULT 0
                CHECK(basic_salary >= 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
                ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            assigned_date TEXT NOT NULL,
            deadline TEXT,
            status TEXT NOT NULL DEFAULT 'Pending'
                CHECK(status IN (
                    'Pending', 'In Progress', 'Completed'
                )),
            completed_at TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees(id)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            attendance_date TEXT NOT NULL,
            check_in TEXT,
            check_out TEXT,
            status TEXT NOT NULL
                CHECK(status IN (
                    'Present', 'Absent', 'Half Day', 'Leave'
                )),
            FOREIGN KEY (employee_id) REFERENCES employees(id)
                ON DELETE CASCADE,
            UNIQUE(employee_id, attendance_date)
        );

        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending'
                CHECK(status IN (
                    'Pending', 'Approved', 'Rejected'
                )),
            admin_comment TEXT,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees(id)
                ON DELETE CASCADE,
            CHECK(end_date >= start_date)
        ); 

        CREATE TABLE IF NOT EXISTS performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            attendance_score REAL NOT NULL DEFAULT 0,
            task_score REAL NOT NULL DEFAULT 0,
            punctuality_score REAL NOT NULL DEFAULT 0,
            total_score REAL NOT NULL DEFAULT 0,
            grade TEXT,
            bonus REAL NOT NULL DEFAULT 0,
            evaluated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees(id)
                ON DELETE CASCADE,
            UNIQUE(employee_id, month)
        );

        CREATE TABLE IF NOT EXISTS payroll (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            basic_salary REAL NOT NULL DEFAULT 0,
            bonus REAL NOT NULL DEFAULT 0,
            tax_deduction REAL NOT NULL DEFAULT 0,
            leave_deduction REAL NOT NULL DEFAULT 0,
            other_deductions REAL NOT NULL DEFAULT 0,
            net_salary REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Draft'
                CHECK(status IN ('Draft', 'Finalized', 'Paid')),
            generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees(id)
                ON DELETE RESTRICT,
            UNIQUE(employee_id, month),
            CHECK(basic_salary >= 0),
            CHECK(bonus >= 0),
            CHECK(tax_deduction >= 0),
            CHECK(leave_deduction >= 0),
            CHECK(other_deductions >= 0),
            CHECK(net_salary >= 0)
        );
    """)

    # Create demonstration accounts only on first initialization.
    # Passwords are stored as hashes, not plain text.
    admin = connection.execute(
        "SELECT id FROM users WHERE username = ?",
        ("admin",)
    ).fetchone()

    if admin is None:
        connection.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, ?)
            """,
            (
                "admin",
                generate_password_hash("Admin@123"),
                "admin"
            )
        )

    employee_user = connection.execute(
        "SELECT id FROM users WHERE username = ?",
        ("employee1",)
    ).fetchone()

    if employee_user is None:
        cursor = connection.execute(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES (?, ?, ?)
            """,
            (
                "employee1",
                generate_password_hash("Employee@123"),
                "employee"
            )
        )
        employee_user_id = cursor.lastrowid
    else:
        employee_user_id = employee_user[0]

    demo_employee = connection.execute(
        "SELECT id FROM employees WHERE employee_code = ?",
        ("EMP001",)
    ).fetchone()

    if demo_employee is None:
        connection.execute(
            """
            INSERT INTO employees
            (user_id, employee_code, full_name, email, department,
             designation, joining_date, basic_salary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_user_id,
                "EMP001",
                "Demo Employee",
                "employee1@example.com",
                "IT",
                "Software Developer",
                "2026-01-01",
                25000
            )
        )

    connection.commit()
    connection.close()

    print("Database initialized successfully.")
    print(f"Database location: {DATABASE_PATH}")


if __name__ == "__main__":
    initialize_database()
