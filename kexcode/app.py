from dotenv import load_dotenv
load_dotenv()

import os
import csv
import io
from flask import Response

from cs50 import SQL
from flask import Flask, jsonify, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from datetime import datetime, timedelta
from helpers import admin_required, apology, login_required, generate_code, send_verification_email
from openai import OpenAI

from werkzeug.utils import secure_filename
import uuid

app = Flask(__name__)
app.secret_key = "kexcode-super-secret-key-change-later"
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads", "lectures")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload limit

db = SQL("sqlite:///kexcode.db")

# Existing Groq Client


client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
    default_headers={
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "KexCode"
    }
)


@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    if session["role"] == "admin":
        return redirect("/admin/dashboard")
    return redirect("/dashboard")


# ---------- Auth ----------

@app.route("/register", methods=["GET", "POST"])
def register():
    session.clear()
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")
        role = request.form.get("role")

        if not name:
            return apology("must provide name", 400)
        if not email:
            return apology("must provide email", 400)
        if not password:
            return apology("must provide password", 400)
        if password != confirmation:
            return apology("passwords must match", 400)
        if role not in ("admin", "student"):
            return apology("invalid role", 400)

        hash = generate_password_hash(password)
        code = generate_code()
        expires = datetime.now() + timedelta(minutes=10)

        try:
            user_id = db.execute(
                "INSERT INTO users (name, email, hash, role, verification_code, code_expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                name, email, hash, role, code, expires,
            )
        except ValueError:
            return apology("email already registered", 400)

        send_verification_email(email, code)
        session["pending_user_id"] = user_id
        return redirect("/verify")

    return render_template("register.html")

@app.route("/verify", methods=["GET", "POST"])
def verify():
    user_id = session.get("pending_user_id")
    if not user_id:
        return redirect("/register")

    if request.method == "POST":
        code = request.form.get("code")
        user = db.execute("SELECT * FROM users WHERE id = ?", user_id)[0]

        if datetime.now() > datetime.fromisoformat(user["code_expires_at"]):
            return apology("code expired, please request a new one", 400)

        if code != user["verification_code"]:
            return apology("incorrect code", 400)

        db.execute("UPDATE users SET verified = 1 WHERE id = ?", user_id)
        session.pop("pending_user_id", None)
        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["name"] = user["name"]
        return redirect("/")

    return render_template("verify.html")


@app.route("/verify/resend")
def resend_code():
    user_id = session.get("pending_user_id")
    if not user_id:
        return redirect("/register")

    code = generate_code()
    expires = datetime.now() + timedelta(minutes=10)
    user = db.execute("SELECT * FROM users WHERE id = ?", user_id)[0]

    db.execute(
        "UPDATE users SET verification_code = ?, code_expires_at = ? WHERE id = ?",
        code, expires, user_id,
    )
    send_verification_email(user["email"], code)
    return redirect("/verify")

@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            return apology("must provide email and password", 403)

        rows = db.execute("SELECT * FROM users WHERE email = ?", email)

        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], password):
            return apology("invalid email and/or password", 403)

        session["user_id"] = rows[0]["id"]
        session["role"] = rows[0]["role"]
        session["name"] = rows[0]["name"]

        # NEW: block login until verified
        if not rows[0]["verified"]:
            session["pending_user_id"] = rows[0]["id"]
            session.pop("user_id", None)
            return redirect("/verify")

        return redirect("/")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ---------- Admin routes ----------

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    # 1. Fetch instructor's classes with student counts
    classes = db.execute("""
        SELECT c.*,
               (SELECT COUNT(*) FROM enrollments e WHERE e.class_id = c.id) AS student_count
        FROM classes c
        WHERE c.admin_id = ?
        ORDER BY c.name ASC
    """, session["user_id"])

    # 2. Total assignments created by this instructor
    assignments_count = db.execute("""
        SELECT COUNT(*) AS count
        FROM assignments a
        JOIN classes c ON a.class_id = c.id
        WHERE c.admin_id = ?
    """, session["user_id"])[0]["count"]

    # 3. Pending submissions that need grading
    pending_grading_count = db.execute("""
        SELECT COUNT(*) AS count
        FROM submissions s
        JOIN assignments a ON s.assignment_id = a.id
        JOIN classes c ON a.class_id = c.id
        WHERE c.admin_id = ? AND s.grade IS NULL
    """, session["user_id"])[0]["count"]

    return render_template(
        "admin_dashboard.html",
        classes=classes,
        total_classes=len(classes),
        total_assignments=assignments_count,
        pending_grading=pending_grading_count
    )



@app.route("/admin/classes", methods=["GET", "POST"])
@admin_required
def admin_classes():
    admin_id = session["user_id"]

    # Handle creating a new class
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return apology("must provide class name", 400)

        db.execute(
            "INSERT INTO classes (name, admin_id) VALUES (?, ?)",
            name, admin_id
        )
        return redirect("/admin/classes")

    # Fetch classes with live stats (student count and assignment count)
    classes = db.execute("""
        SELECT
            c.*,
            (SELECT COUNT(*) FROM enrollments e WHERE e.class_id = c.id) AS student_count,
            (SELECT COUNT(*) FROM assignments a WHERE a.class_id = c.id) AS assignment_count
        FROM classes c
        WHERE c.admin_id = ?
        ORDER BY c.name ASC
    """, admin_id)

    return render_template("admin_classes.html", classes=classes)


@app.route("/admin/classes/<int:class_id>")
@admin_required
def admin_class_roster(class_id):
    admin_id = session["user_id"]

    # Verify class belongs to this instructor
    class_rows = db.execute(
        "SELECT * FROM classes WHERE id = ? AND admin_id = ?",
        class_id, admin_id
    )
    if not class_rows:
        return apology("class not found or access denied", 404)

    target_class = class_rows[0]

    # Fetch enrolled students with their assignment submission stats
    roster = db.execute("""
        SELECT
            u.id AS student_id,
            u.name AS student_name,
            u.email AS student_email,
            (
                SELECT COUNT(DISTINCT s.assignment_id)
                FROM submissions s
                JOIN assignments a ON s.assignment_id = a.id
                WHERE s.student_id = u.id AND a.class_id = ?
            ) AS completed_count,
            (
                SELECT ROUND(AVG(CAST(s.grade AS FLOAT)), 1)
                FROM submissions s
                JOIN assignments a ON s.assignment_id = a.id
                WHERE s.student_id = u.id AND a.class_id = ? AND s.grade IS NOT NULL
            ) AS avg_grade
        FROM enrollments e
        JOIN users u ON e.student_id = u.id
        WHERE e.class_id = ?
        ORDER BY u.name ASC
    """, class_id, class_id, class_id)

    # Total assignments in this class for completion reference
    total_assignments_rows = db.execute(
        "SELECT COUNT(*) AS count FROM assignments WHERE class_id = ?",
        class_id
    )
    total_assignments = total_assignments_rows[0]["count"] if total_assignments_rows else 0

    return render_template(
        "admin_class_roster.html",
        target_class=target_class,
        roster=roster,
        total_assignments=total_assignments
    )


@app.route("/admin/classes/<int:class_id>/enroll", methods=["POST"])
@admin_required
def enroll_student(class_id):
    admin_id = session["user_id"]

    # Confirm instructor owns this class
    owned = db.execute(
        "SELECT id FROM classes WHERE id = ? AND admin_id = ?",
        class_id, admin_id
    )
    if not owned:
        return apology("access denied", 403)

    email = request.form.get("email", "").strip().lower()
    if not email:
        return apology("must provide student email", 400)

    student = db.execute(
        "SELECT * FROM users WHERE LOWER(email) = ? AND role = 'student'",
        email
    )
    if not student:
        return apology("No registered student found with that email", 404)

    # Check if already enrolled
    existing = db.execute(
        "SELECT * FROM enrollments WHERE class_id = ? AND student_id = ?",
        class_id, student[0]["id"]
    )
    if existing:
        return apology("Student is already enrolled in this class", 400)

    db.execute(
        "INSERT INTO enrollments (class_id, student_id) VALUES (?, ?)",
        class_id, student[0]["id"]
    )

    return redirect(f"/admin/classes/{class_id}")


@app.route("/admin/classes/<int:class_id>/unenroll/<int:student_id>", methods=["POST"])
@admin_required
def unenroll_student(class_id, student_id):
    admin_id = session["user_id"]

    # Confirm instructor owns this class
    owned = db.execute(
        "SELECT id FROM classes WHERE id = ? AND admin_id = ?",
        class_id, admin_id
    )
    if not owned:
        return apology("access denied", 403)

    db.execute(
        "DELETE FROM enrollments WHERE class_id = ? AND student_id = ?",
        class_id, student_id
    )

    return redirect(f"/admin/classes/{class_id}")


@app.route("/admin/classes/<int:class_id>/delete", methods=["POST"])
@admin_required
def delete_class(class_id):
    admin_id = session["user_id"]

    owned = db.execute(
        "SELECT id FROM classes WHERE id = ? AND admin_id = ?",
        class_id, admin_id
    )
    if not owned:
        return apology("class not found or access denied", 403)

    # Clean up related records: drafts, submissions, assignments, enrollments, then the class
    db.execute("""
        DELETE FROM drafts WHERE assignment_id IN (
            SELECT id FROM assignments WHERE class_id = ?
        )
    """, class_id)

    db.execute("""
        DELETE FROM submissions WHERE assignment_id IN (
            SELECT id FROM assignments WHERE class_id = ?
        )
    """, class_id)

    db.execute("DELETE FROM assignments WHERE class_id = ?", class_id)
    db.execute("DELETE FROM enrollments WHERE class_id = ?", class_id)
    db.execute("DELETE FROM classes WHERE id = ?", class_id)

    return redirect("/admin/classes")



@app.route("/admin/assignments", methods=["GET", "POST"])
@admin_required
def admin_assignments():
    classes = db.execute("SELECT * FROM classes WHERE admin_id = ?", session["user_id"])

    if request.method == "POST":
        class_id = request.form.get("class_id")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        starter_code = request.form.get("starter_code", "").strip()
        due_date = request.form.get("due_date")
        language = request.form.get("language", "python")

        if not class_id or not title:
            return apology("must provide class and title", 400)

        db.execute(
            """
            INSERT INTO assignments (class_id, title, description, starter_code, due_date, language)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            class_id, title, description, starter_code, due_date, language,
        )
        return redirect("/admin/assignments")

    # Fetch assignments with live student counts, submission counts, and graded counts
    assignments = db.execute(
        """
        SELECT
            assignments.*,
            classes.name AS class_name,
            (
                SELECT COUNT(*)
                FROM enrollments
                WHERE enrollments.class_id = assignments.class_id
            ) AS enrolled_count,
            (
                SELECT COUNT(DISTINCT student_id)
                FROM submissions
                WHERE submissions.assignment_id = assignments.id
            ) AS submitted_count,
            (
                SELECT COUNT(DISTINCT student_id)
                FROM submissions
                WHERE submissions.assignment_id = assignments.id
                AND submissions.grade IS NOT NULL
            ) AS graded_count
        FROM assignments
        JOIN classes ON assignments.class_id = classes.id
        WHERE classes.admin_id = ?
        ORDER BY
            CASE WHEN assignments.due_date IS NULL THEN 1 ELSE 0 END,
            assignments.due_date ASC,
            assignments.id DESC
        """,
        session["user_id"],
    )

    return render_template("admin_assignments.html", classes=classes, assignments=assignments)


@app.route("/admin/assignments/<int:assignment_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_assignment(assignment_id):
    # Verify assignment belongs to this admin's classes
    assignment_rows = db.execute(
        """
        SELECT assignments.*, classes.name AS class_name
        FROM assignments
        JOIN classes ON assignments.class_id = classes.id
        WHERE assignments.id = ? AND classes.admin_id = ?
        """,
        assignment_id,
        session["user_id"],
    )

    if not assignment_rows:
        return apology("assignment not found", 404)

    assignment = assignment_rows[0]
    classes = db.execute("SELECT * FROM classes WHERE admin_id = ?", session["user_id"])

    if request.method == "POST":
        class_id = request.form.get("class_id")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        starter_code = request.form.get("starter_code", "").strip()
        due_date = request.form.get("due_date")
        language = request.form.get("language", "python")

        if not class_id or not title:
            return apology("must provide class and title", 400)

        db.execute(
            """
            UPDATE assignments
            SET class_id = ?, title = ?, description = ?, starter_code = ?, due_date = ?, language = ?
            WHERE id = ?
            """,
            class_id, title, description, starter_code, due_date, language, assignment_id,
        )
        return redirect("/admin/assignments")

    return render_template("admin_assignment_edit.html", assignment=assignment, classes=classes)


@app.route("/admin/assignments/<int:assignment_id>/delete", methods=["POST"])
@admin_required
def admin_delete_assignment(assignment_id):
    # Verify ownership
    owned = db.execute(
        """
        SELECT assignments.id
        FROM assignments
        JOIN classes ON assignments.class_id = classes.id
        WHERE assignments.id = ? AND classes.admin_id = ?
        """,
        assignment_id,
        session["user_id"],
    )

    if not owned:
        return apology("assignment not found or access denied", 403)

    # Delete related submissions, drafts, then the assignment
    db.execute("DELETE FROM drafts WHERE assignment_id = ?", assignment_id)
    db.execute("DELETE FROM submissions WHERE assignment_id = ?", assignment_id)
    db.execute("DELETE FROM assignments WHERE id = ?", assignment_id)

    return redirect("/admin/assignments")


@app.route("/admin/grading/<int:assignment_id>", methods=["GET", "POST"])
@admin_required
def admin_grading(assignment_id):
    # Verify assignment belongs to this admin's classes
    assignment_rows = db.execute(
        """
        SELECT assignments.*, classes.name AS class_name
        FROM assignments
        JOIN classes ON assignments.class_id = classes.id
        WHERE assignments.id = ? AND classes.admin_id = ?
        """,
        assignment_id,
        session["user_id"],
    )

    if not assignment_rows:
        return apology("assignment not found or access denied", 404)

    assignment = assignment_rows[0]

    if request.method == "POST":
        submission_id = request.form.get("submission_id")
        grade = request.form.get("grade", "").strip()
        feedback = request.form.get("feedback", "").strip()

        if not submission_id:
            return apology("missing submission id", 400)

        # Confirm submission belongs to this assignment
        db.execute(
            """
            UPDATE submissions
            SET grade = ?, feedback = ?
            WHERE id = ? AND assignment_id = ?
            """,
            grade if grade else None,
            feedback if feedback else None,
            submission_id,
            assignment_id,
        )
        return redirect(f"/admin/grading/{assignment_id}")

    # Fetch all submissions for this assignment with student info
    submissions = db.execute(
        """
        SELECT
            submissions.*,
            users.name AS student_name,
            users.email AS student_email
        FROM submissions
        JOIN users ON submissions.student_id = users.id
        WHERE submissions.assignment_id = ?
        ORDER BY submissions.submitted_at DESC
        """,
        assignment_id,
    )

    # Calculate submission timing (on-time vs. late)
    due_date = None
    if assignment.get("due_date"):
        try:
            due_date = datetime.fromisoformat(assignment["due_date"].replace("Z", "+00:00"))
        except ValueError:
            due_date = None

    for sub in submissions:
        sub_time = None
        if sub.get("submitted_at"):
            try:
                sub_time = datetime.fromisoformat(sub["submitted_at"].replace("Z", "+00:00"))
                sub["submitted_display"] = sub_time.strftime("%b %d, %Y · %I:%M %p")
            except ValueError:
                sub["submitted_display"] = sub["submitted_at"]

        if due_date and sub_time and sub_time > due_date:
            sub["timing_status"] = "late"
            sub["timing_label"] = "Late"
        else:
            sub["timing_status"] = "on-time"
            sub["timing_label"] = "On time"

    return render_template(
        "admin_grading.html",
        assignment=assignment,
        submissions=submissions,
    )


@app.route("/admin/notes", methods=["GET", "POST"])
@admin_required
def admin_notes():
    admin_id = session["user_id"]
    classes = db.execute("SELECT id, name FROM classes WHERE admin_id = ? ORDER BY name ASC", admin_id)

    if request.method == "POST":
        class_id = request.form.get("class_id")
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        pdf_file = request.files.get("pdf_file")

        if not class_id or not title or not content:
            return apology("Class, title, and content are required", 400)

        # Verify class belongs to this admin
        owned = db.execute("SELECT id FROM classes WHERE id = ? AND admin_id = ?", class_id, admin_id)
        if not owned:
            return apology("Class not found or unauthorized", 403)

        saved_filename = None
        if pdf_file and pdf_file.filename:
            if not pdf_file.filename.lower().endswith(".pdf"):
                return apology("Only PDF files are allowed", 400)

            # Ensure upload directory exists
            upload_dir = os.path.join(app.root_path, "static", "uploads", "lectures")
            os.makedirs(upload_dir, exist_ok=True)

            safe_name = secure_filename(pdf_file.filename)
            saved_filename = f"{uuid.uuid4().hex[:8]}_{safe_name}"
            pdf_path = os.path.join(upload_dir, saved_filename)
            pdf_file.save(pdf_path)

        db.execute(
            "INSERT INTO notes (class_id, title, content, pdf_filename) VALUES (?, ?, ?, ?)",
            class_id,
            title,
            content,
            saved_filename
        )
        return redirect("/admin/notes")

    # GET: fetch notes published by this instructor
    notes = db.execute(
        """
        SELECT notes.*, classes.name AS class_name
        FROM notes
        JOIN classes ON notes.class_id = classes.id
        WHERE classes.admin_id = ?
        ORDER BY notes.id DESC
        """,
        admin_id
    )

    return render_template("admin_notes.html", classes=classes, notes=notes)

@app.route("/admin/notes/<int:note_id>/delete", methods=["POST"])
@admin_required
def admin_delete_note(note_id):
    admin_id = session["user_id"]

    # Verify ownership
    owned = db.execute("""
        SELECT notes.id
        FROM notes
        JOIN classes ON notes.class_id = classes.id
        WHERE notes.id = ? AND classes.admin_id = ?
    """, note_id, admin_id)

    if not owned:
        return apology("note not found or access denied", 403)

    db.execute("DELETE FROM notes WHERE id = ?", note_id)
    return redirect("/admin/notes")


# ---------- Student routes ----------

@app.route("/dashboard")
@login_required
def dashboard():
    # Students only
    if session.get("role") != "student":
        return redirect("/admin/dashboard")

    student_id = session["user_id"]
    now = datetime.now()

    assignments = db.execute(
        """
        SELECT
            assignments.*,
            classes.name AS class_name,

            (
                SELECT submissions.id
                FROM submissions
                WHERE submissions.assignment_id = assignments.id
                AND submissions.student_id = ?
                ORDER BY submissions.submitted_at DESC
                LIMIT 1
            ) AS submission_id,

            (
                SELECT submissions.submitted_at
                FROM submissions
                WHERE submissions.assignment_id = assignments.id
                AND submissions.student_id = ?
                ORDER BY submissions.submitted_at DESC
                LIMIT 1
            ) AS submitted_at,

            (
                SELECT submissions.grade
                FROM submissions
                WHERE submissions.assignment_id = assignments.id
                AND submissions.student_id = ?
                ORDER BY submissions.submitted_at DESC
                LIMIT 1
            ) AS grade

        FROM assignments
        JOIN classes ON assignments.class_id = classes.id
        JOIN enrollments ON enrollments.class_id = classes.id
        WHERE enrollments.student_id = ?
        ORDER BY assignments.due_date ASC
        """,
        student_id,
        student_id,
        student_id,
        student_id,
    )

    classes = {}

    for assignment in assignments:
        assignment["submitted"] = assignment["submission_id"] is not None
        assignment["graded"] = assignment["grade"] is not None

        assignment["status"] = "not-started"
        assignment["status_label"] = "Not started"
        assignment["due_label"] = "No deadline"
        assignment["due_display"] = "No deadline"
        assignment["is_due_soon"] = False
        assignment["is_overdue"] = False

        due_date_value = assignment.get("due_date")

        if due_date_value:
            try:
                due_date = datetime.fromisoformat(str(due_date_value))
                assignment["due_display"] = due_date.strftime("%b %d, %Y")

                days_left = (due_date.date() - now.date()).days

                if days_left < 0:
                    assignment["due_label"] = (
                        f"{abs(days_left)} day"
                        f"{'s' if abs(days_left) != 1 else ''} ago"
                    )
                elif days_left == 0:
                    assignment["due_label"] = "Due today"
                elif days_left == 1:
                    assignment["due_label"] = "Due tomorrow"
                else:
                    assignment["due_label"] = f"Due in {days_left} days"

                # Status priority:
                # graded → submitted → overdue → due soon → not started
                if assignment["graded"]:
                    assignment["status"] = "graded"
                    assignment["status_label"] = "Graded"

                elif assignment["submitted"]:
                    assignment["status"] = "submitted"
                    assignment["status_label"] = "Submitted"

                elif days_left < 0:
                    assignment["status"] = "overdue"
                    assignment["status_label"] = "Overdue"
                    assignment["is_overdue"] = True

                elif 0 <= days_left <= 7:
                    assignment["status"] = "due-soon"
                    assignment["status_label"] = "Due soon"
                    assignment["is_due_soon"] = True

            except (TypeError, ValueError):
                assignment["due_display"] = str(due_date_value)

        # Assignments without a due date can still be submitted or graded.
        elif assignment["graded"]:
            assignment["status"] = "graded"
            assignment["status_label"] = "Graded"

        elif assignment["submitted"]:
            assignment["status"] = "submitted"
            assignment["status_label"] = "Submitted"

        # Build class-progress information.
        class_id = assignment["class_id"]

        if class_id not in classes:
            classes[class_id] = {
                "id": class_id,
                "name": assignment["class_name"],
                "total": 0,
                "submitted": 0,
                "graded": 0,
            }

        classes[class_id]["total"] += 1

        if assignment["submitted"]:
            classes[class_id]["submitted"] += 1

        if assignment["graded"]:
            classes[class_id]["graded"] += 1

    class_progress = list(classes.values())

    for class_item in class_progress:
        if class_item["total"] > 0:
            class_item["progress"] = round(
                (class_item["submitted"] / class_item["total"]) * 100
            )
        else:
            class_item["progress"] = 0

    recent_activity = db.execute(
        """
        SELECT
            submissions.submitted_at,
            submissions.grade,
            assignments.id AS assignment_id,
            assignments.title,
            classes.name AS class_name
        FROM submissions
        JOIN assignments ON submissions.assignment_id = assignments.id
        JOIN classes ON assignments.class_id = classes.id
        WHERE submissions.student_id = ?
        ORDER BY submissions.submitted_at DESC
        LIMIT 5
        """,
        student_id,
    )

    total_assignments = len(assignments)
    submitted_count = sum(
        1 for assignment in assignments if assignment["submitted"]
    )
    graded_count = sum(
        1 for assignment in assignments if assignment["graded"]
    )
    overdue_count = sum(
        1 for assignment in assignments if assignment["is_overdue"]
    )

    progress_percent = 0
    if total_assignments > 0:
        progress_percent = round(
            (submitted_count / total_assignments) * 100
        )

    badges = []

    if submitted_count >= 1:
        badges.append({
            "title": "First Submission",
            "description": "You submitted your first assignment."
        })

    if submitted_count >= 5:
        badges.append({
            "title": "On a Roll",
            "description": "You have submitted five assignments."
        })

    if graded_count >= 1:
        badges.append({
            "title": "Feedback Explorer",
            "description": "You have received your first grade."
        })

    if overdue_count == 0 and submitted_count >= 3:
        badges.append({
            "title": "Deadline Keeper",
            "description": "You have no overdue work right now."
        })

    return render_template(
        "student_dashboard.html",
        assignments=assignments,
        class_progress=class_progress,
        recent_activity=recent_activity,
        badges=badges,
        total_assignments=total_assignments,
        submitted_count=submitted_count,
        graded_count=graded_count,
        overdue_count=overdue_count,
        progress_percent=progress_percent,
    )


@app.route("/activity")
@login_required
def activity():
    student_id = session["user_id"]

    assignments = db.execute(
        """
        SELECT
            assignments.*,
            classes.name AS class_name,

            (
                SELECT submissions.id
                FROM submissions
                WHERE submissions.assignment_id = assignments.id
                AND submissions.student_id = ?
                ORDER BY submissions.submitted_at DESC
                LIMIT 1
            ) AS submission_id,

            (
                SELECT submissions.grade
                FROM submissions
                WHERE submissions.assignment_id = assignments.id
                AND submissions.student_id = ?
                ORDER BY submissions.submitted_at DESC
                LIMIT 1
            ) AS grade

        FROM assignments
        JOIN classes ON assignments.class_id = classes.id
        JOIN enrollments ON enrollments.class_id = classes.id
        WHERE enrollments.student_id = ?
        ORDER BY assignments.due_date ASC
        """,
        student_id,
        student_id,
        student_id,
    )

    classes = {}

    for assignment in assignments:
        assignment["submitted"] = assignment["submission_id"] is not None
        assignment["graded"] = assignment["grade"] is not None

        class_id = assignment["class_id"]

        if class_id not in classes:
            classes[class_id] = {
                "id": class_id,
                "name": assignment["class_name"],
                "total": 0,
                "submitted": 0,
                "graded": 0,
            }

        classes[class_id]["total"] += 1

        if assignment["submitted"]:
            classes[class_id]["submitted"] += 1

        if assignment["graded"]:
            classes[class_id]["graded"] += 1

    class_progress = list(classes.values())

    for class_item in class_progress:
        if class_item["total"] > 0:
            class_item["progress"] = round(
                (class_item["submitted"] / class_item["total"]) * 100
            )
        else:
            class_item["progress"] = 0

    recent_activity = db.execute(
        """
        SELECT
            submissions.submitted_at,
            submissions.grade,
            assignments.id AS assignment_id,
            assignments.title,
            classes.name AS class_name
        FROM submissions
        JOIN assignments ON submissions.assignment_id = assignments.id
        JOIN classes ON assignments.class_id = classes.id
        WHERE submissions.student_id = ?
        ORDER BY submissions.submitted_at DESC
        LIMIT 10
        """,
        student_id,
    )

    submitted_count = sum(
        1 for assignment in assignments if assignment["submitted"]
    )

    graded_count = sum(
        1 for assignment in assignments if assignment["graded"]
    )

    badges = []

    if submitted_count >= 1:
        badges.append({
            "title": "First Submission",
            "description": "You submitted your first assignment."
        })

    if submitted_count >= 5:
        badges.append({
            "title": "On a Roll",
            "description": "You have submitted five assignments."
        })

    if graded_count >= 1:
        badges.append({
            "title": "Feedback Explorer",
            "description": "You have received your first grade."
        })

    if submitted_count >= 3:
        badges.append({
            "title": "Active Learner",
            "description": "You have completed three assignments."
        })

    return render_template(
        "activity.html",
        class_progress=class_progress,
        recent_activity=recent_activity,
        badges=badges,
    )


@app.route("/assignment/<int:assignment_id>", methods=["GET", "POST"])
@login_required
def assignment_detail(assignment_id):
    # Only students can open and submit assignments.
    if session.get("role") != "student":
        return redirect("/admin/dashboard")

    student_id = session["user_id"]

    # Only allow access to assignments in classes the student joined.
    assignment_rows = db.execute(
        """
        SELECT assignments.*, classes.name AS class_name
        FROM assignments
        JOIN classes ON assignments.class_id = classes.id
        JOIN enrollments ON enrollments.class_id = classes.id
        WHERE assignments.id = ?
        AND enrollments.student_id = ?
        """,
        assignment_id,
        student_id,
    )

    if not assignment_rows:
        return apology(
            "assignment not found or you are not enrolled in this class",
            404,
        )

    assignment = assignment_rows[0]

    # Final submission
    if request.method == "POST":
        code = request.form.get("code", "").strip()

        if not code:
            return apology("must write some code before submitting", 400)

        db.execute(
            """
            INSERT INTO submissions (assignment_id, student_id, code)
            VALUES (?, ?, ?)
            """,
            assignment_id,
            student_id,
            code,
        )

        # The final submitted code is now stored in submissions,
        # so the temporary draft is no longer needed.
        db.execute(
            """
            DELETE FROM drafts
            WHERE assignment_id = ?
            AND student_id = ?
            """,
            assignment_id,
            student_id,
        )

        return redirect(f"/assignment/{assignment_id}")

    # Get the student's most recent final submission.
    submission_rows = db.execute(
        """
        SELECT *
        FROM submissions
        WHERE assignment_id = ?
        AND student_id = ?
        ORDER BY submitted_at DESC
        LIMIT 1
        """,
        assignment_id,
        student_id,
    )

    submission = submission_rows[0] if submission_rows else None

    # Get the student's private saved draft, if one exists.
    draft_rows = db.execute(
        """
        SELECT *
        FROM drafts
        WHERE assignment_id = ?
        AND student_id = ?
        """,
        assignment_id,
        student_id,
    )

    draft = draft_rows[0] if draft_rows else None

    return render_template(
        "assignment_detail.html",
        assignment=assignment,
        submission=submission,
        draft=draft,
    )


@app.route("/assignments")
@login_required
def student_assignments():
    if session.get("role") != "student":
        return redirect("/admin/dashboard")

    student_id = session["user_id"]

    assignments = db.execute(
        """
        SELECT
            assignments.*,
            classes.name AS class_name,

            drafts.id AS draft_id,
            drafts.updated_at AS draft_updated_at,

            submissions.id AS submission_id,
            submissions.submitted_at,
            submissions.grade,
            submissions.feedback

        FROM assignments
        JOIN classes ON assignments.class_id = classes.id
        JOIN enrollments ON enrollments.class_id = classes.id

        LEFT JOIN drafts
            ON drafts.assignment_id = assignments.id
            AND drafts.student_id = ?

        LEFT JOIN submissions
            ON submissions.id = (
                SELECT id
                FROM submissions
                WHERE submissions.assignment_id = assignments.id
                AND submissions.student_id = ?
                ORDER BY submitted_at DESC
                LIMIT 1
            )

        WHERE enrollments.student_id = ?
        ORDER BY
            CASE WHEN assignments.due_date IS NULL THEN 1 ELSE 0 END,
            assignments.due_date ASC,
            assignments.id DESC
        """,
        student_id,
        student_id,
        student_id,
    )

    now = datetime.now()

    for assignment in assignments:
        assignment["status"] = "todo"
        assignment["status_label"] = "To do"

        due_date = None

        if assignment["due_date"]:
            try:
                due_date = datetime.fromisoformat(
                    assignment["due_date"].replace("Z", "+00:00")
                )
            except ValueError:
                due_date = None

        # A submission has priority over a draft.
        if assignment["submission_id"]:
            if assignment["grade"] is not None:
                assignment["status"] = "graded"
                assignment["status_label"] = "Graded"
            else:
                assignment["status"] = "submitted"
                assignment["status_label"] = "Submitted"

        elif due_date and due_date < now:
            assignment["status"] = "overdue"
            assignment["status_label"] = "Overdue"

        elif assignment["draft_id"]:
            assignment["status"] = "draft"
            assignment["status_label"] = "Draft saved"

        if due_date:
            assignment["due_display"] = due_date.strftime("%b %d, %Y · %I:%M %p")
        else:
            assignment["due_display"] = "No deadline"

    return render_template(
        "assignments.html",
        assignments=assignments,
    )


@app.route("/assignment/<int:assignment_id>/draft", methods=["POST"])
@login_required
def save_assignment_draft(assignment_id):
    if session.get("role") != "student":
        return jsonify({"error": "Students only"}), 403

    student_id = session["user_id"]
    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing draft data"}), 400

    code = data.get("code", "")
    language = data.get("language", "python")

    if language not in ("python", "javascript", "html", "css"):
        return jsonify({"error": "Unsupported language"}), 400

    # Confirm this assignment belongs to one of the student's classes.
    enrolled_assignment = db.execute(
        """
        SELECT assignments.id
        FROM assignments
        JOIN enrollments ON enrollments.class_id = assignments.class_id
        WHERE assignments.id = ?
        AND enrollments.student_id = ?
        """,
        assignment_id,
        student_id,
    )

    if not enrolled_assignment:
        return jsonify({"error": "Assignment not found"}), 404

    existing_draft = db.execute(
        """
        SELECT id
        FROM drafts
        WHERE assignment_id = ?
        AND student_id = ?
        """,
        assignment_id,
        student_id,
    )

    if existing_draft:
        db.execute(
            """
            UPDATE drafts
            SET code = ?, language = ?, updated_at = CURRENT_TIMESTAMP
            WHERE assignment_id = ? AND student_id = ?
            """,
            code,
            language,
            assignment_id,
            student_id,
        )
    else:
        db.execute(
            """
            INSERT INTO drafts (assignment_id, student_id, code, language)
            VALUES (?, ?, ?, ?)
            """,
            assignment_id,
            student_id,
            code,
            language,
        )

    return jsonify({"message": "Draft saved"})


@app.route("/my-notes", methods=["GET", "POST"])
@login_required
def personal_notes():
    if session.get("role") != "student":
        return redirect("/admin/dashboard")

    student_id = session["user_id"]

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()

        if not title:
            return apology("must provide a note title", 400)

        if not content:
            return apology("must provide note content", 400)

        db.execute(
            """
            INSERT INTO personal_notes (student_id, title, content)
            VALUES (?, ?, ?)
            """,
            student_id,
            title,
            content,
        )

        return redirect("/my-notes")

    notes = db.execute(
        """
        SELECT *
        FROM personal_notes
        WHERE student_id = ?
        ORDER BY updated_at DESC, id DESC
        """,
        student_id,
    )

    return render_template("personal_notes.html", notes=notes)


@app.route("/my-notes/<int:note_id>", methods=["GET", "POST"])
@login_required
def edit_personal_note(note_id):
    if session.get("role") != "student":
        return redirect("/admin/dashboard")

    student_id = session["user_id"]

    note_rows = db.execute(
        """
        SELECT *
        FROM personal_notes
        WHERE id = ? AND student_id = ?
        """,
        note_id,
        student_id,
    )

    if not note_rows:
        return apology("note not found", 404)

    note = note_rows[0]

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()

        if not title or not content:
            return apology("title and content are required", 400)

        db.execute(
            """
            UPDATE personal_notes
            SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND student_id = ?
            """,
            title,
            content,
            note_id,
            student_id,
        )

        return redirect("/my-notes")

    return render_template("edit_personal_note.html", note=note)


@app.route("/my-notes/<int:note_id>/delete", methods=["POST"])
@login_required
def delete_personal_note(note_id):
    if session.get("role") != "student":
        return redirect("/admin/dashboard")

    db.execute(
        """
        DELETE FROM personal_notes
        WHERE id = ? AND student_id = ?
        """,
        note_id,
        session["user_id"],
    )

    return redirect("/my-notes")

@app.route("/notes")
@login_required
def notes():
    notes = db.execute(
        """
        SELECT notes.*, classes.name AS class_name
        FROM notes
        JOIN classes ON notes.class_id = classes.id
        JOIN enrollments ON enrollments.class_id = classes.id
        WHERE enrollments.student_id = ?
        ORDER BY notes.created_at DESC
        """,
        session["user_id"],
    )
    return render_template("notes.html", notes=notes)


@app.route("/note/<int:note_id>")
@login_required
def note_detail(note_id):
    # Retrieve the note with its class name, confirming enrollment if student
    if session["role"] == "admin":
        rows = db.execute(
            """
            SELECT notes.*, classes.name AS class_name
            FROM notes
            JOIN classes ON notes.class_id = classes.id
            WHERE notes.id = ? AND classes.admin_id = ?
            """,
            note_id,
            session["user_id"],
        )
    else:
        rows = db.execute(
            """
            SELECT notes.*, classes.name AS class_name
            FROM notes
            JOIN classes ON notes.class_id = classes.id
            JOIN enrollments ON enrollments.class_id = classes.id
            WHERE notes.id = ? AND enrollments.student_id = ?
            """,
            note_id,
            session["user_id"],
        )

    if not rows:
        return apology("Lecture note not found or access denied", 404)

    return render_template("note_detail.html", note=rows[0])


@app.route("/kex")
@login_required
def kex_editor():
    return render_template("kex.html")

# ---------- Kira (AI assistant) ----------
@app.route("/kira/ask", methods=["POST"])
@login_required
def kira_ask():
    data = request.get_json()
    if not data or "question" not in data:
        return jsonify({"error": "Missing question"}), 400

    question = data.get("question", "").strip()
    if not question:
        return jsonify({"error": "Empty question"}), 400

    # Check if API key exists
    if not os.environ.get("OPENROUTER_API_KEY"):
        return jsonify({"error": "OPENROUTER_API_KEY is missing in .env"}), 500

    try:
        completion = client.chat.completions.create(
            model="openrouter/free",          # ← safest option
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Kira, a friendly coding tutor for students. "
                        "Help them understand concepts and debug code. "
                        "Do NOT give the full solution. Guide them step by step."
                    )
                },
                {"role": "user", "content": question}
            ],
            temperature=0.7,
            max_tokens=600,
        )

        answer = completion.choices[0].message.content
        return jsonify({"answer": answer})

    except Exception as e:
        print("Kira error:", str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/assignment/<int:assignment_id>/submissions")
@login_required
def assignment_submissions(assignment_id):
    # Students only
    if session.get("role") != "student":
        return redirect("/admin/dashboard")

    student_id = session["user_id"]

    # Confirm the student is enrolled in the assignment's class.
    assignment_rows = db.execute(
        """
        SELECT assignments.*, classes.name AS class_name
        FROM assignments
        JOIN classes ON assignments.class_id = classes.id
        JOIN enrollments ON enrollments.class_id = classes.id
        WHERE assignments.id = ?
        AND enrollments.student_id = ?
        """,
        assignment_id,
        student_id,
    )

    if not assignment_rows:
        return apology("assignment not found or you are not enrolled in this class", 404)

    assignment = assignment_rows[0]

    # Get every submission, newest first.
    submissions = db.execute(
        """
        SELECT *
        FROM submissions
        WHERE assignment_id = ?
        AND student_id = ?
        ORDER BY submitted_at DESC, id DESC
        """,
        assignment_id,
        student_id,
    )

    due_date = None

    if assignment["due_date"]:
        try:
            due_date = datetime.fromisoformat(
                str(assignment["due_date"]).replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            due_date = None

    # Add display information to every submission.
    for submission in submissions:
        submitted_at = None

        if submission["submitted_at"]:
            try:
                submitted_at = datetime.fromisoformat(
                    str(submission["submitted_at"]).replace("Z", "+00:00")
                )
            except (TypeError, ValueError):
                submitted_at = None

        submission["submitted_display"] = (
            submitted_at.strftime("%b %d, %Y · %I:%M %p")
            if submitted_at
            else "Unknown date"
        )

        submission["is_late"] = bool(
            due_date and submitted_at and submitted_at > due_date
        )

    assignment["due_display"] = (
        due_date.strftime("%b %d, %Y · %I:%M %p")
        if due_date
        else "No deadline"
    )

    return render_template(
        "submission_history.html",
        assignment=assignment,
        submissions=submissions,
    )


# ---------- Leaderboard & Streaks ----------

def calculate_student_streaks(student_ids):
    """
    Calculates consecutive assignment submission streaks for given student IDs.
    Returns a dict mapping student_id -> streak count.
    """
    if not student_ids:
        return {}

    streaks = {sid: 0 for sid in student_ids}

    for sid in student_ids:
        # Get submissions sorted by date
        subs = db.execute(
            """
            SELECT DISTINCT assignment_id, submitted_at
            FROM submissions
            WHERE student_id = ?
            ORDER BY submitted_at ASC
            """,
            sid,
        )
        # Count total distinct assignments completed as streak metric
        streaks[sid] = len(subs)

    return streaks


@app.route("/leaderboard")
@login_required
def student_leaderboard():
    if session.get("role") != "student":
        return redirect("/admin/leaderboard")

    student_id = session["user_id"]
    class_filter = request.args.get("class_id", type=int)

    # Get student's enrolled classes for filter dropdown
    enrolled_classes = db.execute(
        """
        SELECT classes.id, classes.name
        FROM classes
        JOIN enrollments ON enrollments.class_id = classes.id
        WHERE enrollments.student_id = ?
        ORDER BY classes.name ASC
        """,
        student_id,
    )

    # Query leaderboard across enrolled classes
    query = """
        SELECT
            users.id AS student_id,
            users.name AS student_name,
            COUNT(DISTINCT submissions.assignment_id) AS completed_count,
            COUNT(DISTINCT assignments.id) AS total_assignments,
            ROUND(AVG(CAST(submissions.grade AS FLOAT)), 1) AS avg_grade
        FROM users
        JOIN enrollments ON enrollments.student_id = users.id
        JOIN assignments ON assignments.class_id = enrollments.class_id
        LEFT JOIN submissions
            ON submissions.assignment_id = assignments.id
            AND submissions.student_id = users.id
        WHERE users.role = 'student'
          AND enrollments.class_id IN (
              SELECT class_id FROM enrollments WHERE student_id = ?
          )
    """
    params = [student_id]

    if class_filter:
        query += " AND enrollments.class_id = ?"
        params.append(class_filter)

    query += """
        GROUP BY users.id, users.name
        ORDER BY completed_count DESC, avg_grade DESC, users.name ASC
    """

    leaderboard_data = db.execute(query, *params)
    streaks = calculate_student_streaks([row["student_id"] for row in leaderboard_data])

    user_rank = None
    streak_champion = None
    top_performer = None

    for index, student in enumerate(leaderboard_data):
        rank = index + 1
        student["rank"] = rank
        student["streak"] = streaks.get(student["student_id"], 0)

        if student["student_id"] == student_id:
            user_rank = rank

        if not streak_champion or student["streak"] > streak_champion.get("streak", 0):
            streak_champion = student

        if not top_performer or (student["avg_grade"] or 0) > (top_performer.get("avg_grade") or 0):
            top_performer = student

    current_student = next((s for s in leaderboard_data if s["student_id"] == student_id), None)

    return render_template(
        "leaderboard.html",
        leaderboard=leaderboard_data,
        classes=enrolled_classes,
        selected_class=class_filter,
        user_rank=user_rank,
        current_student=current_student,
        streak_champion=streak_champion,
        top_performer=top_performer,
    )


@app.route("/admin/leaderboard")
@admin_required
def admin_leaderboard():
    admin_id = session["user_id"]
    class_filter = request.args.get("class_id", type=int)

    admin_classes = db.execute(
        "SELECT id, name FROM classes WHERE admin_id = ? ORDER BY name ASC",
        admin_id,
    )

    query = """
        SELECT
            users.id AS student_id,
            users.name AS student_name,
            users.email AS student_email,
            classes.name AS class_name,
            COUNT(DISTINCT submissions.assignment_id) AS completed_count,
            ROUND(AVG(CAST(submissions.grade AS FLOAT)), 1) AS avg_grade
        FROM users
        JOIN enrollments ON enrollments.student_id = users.id
        JOIN classes ON classes.id = enrollments.class_id
        LEFT JOIN assignments ON assignments.class_id = classes.id
        LEFT JOIN submissions
            ON submissions.assignment_id = assignments.id
            AND submissions.student_id = users.id
        WHERE classes.admin_id = ? AND users.role = 'student'
    """
    params = [admin_id]

    if class_filter:
        query += " AND classes.id = ?"
        params.append(class_filter)

    query += """
        GROUP BY users.id, users.name, users.email, classes.name
        ORDER BY completed_count DESC, avg_grade DESC
    """

    leaderboard_data = db.execute(query, *params)
    streaks = calculate_student_streaks([row["student_id"] for row in leaderboard_data])

    for index, student in enumerate(leaderboard_data):
        student["rank"] = index + 1
        student["streak"] = streaks.get(student["student_id"], 0)

    return render_template(
        "admin_leaderboard.html",
        leaderboard=leaderboard_data,
        classes=admin_classes,
        selected_class=class_filter,
    )

@app.route("/admin/insights")
@login_required
@admin_required
def admin_insights():
    admin_id = session["user_id"]

    # 1. Get classes created by this instructor (admin_id)
    classes = db.execute(
        "SELECT id, name FROM classes WHERE admin_id = ? ORDER BY name ASC",
        admin_id
    )

    selected_class_id = request.args.get("class_id", type=int)
    if not selected_class_id and classes:
        selected_class_id = classes[0]["id"]

    selected_class = None
    assignments_insights = []
    recent_activity = []

    if selected_class_id:
        class_rows = db.execute(
            "SELECT * FROM classes WHERE id = ? AND admin_id = ?",
            selected_class_id, admin_id
        )
        if class_rows:
            selected_class = class_rows[0]

            # 2. Get enrolled students (enrollments.student_id)
            enrolled_students = db.execute("""
                SELECT u.id, u.name, u.email
                FROM users u
                JOIN enrollments e ON u.id = e.student_id
                WHERE e.class_id = ?
                ORDER BY u.name ASC
            """, selected_class_id)
            total_students = len(enrolled_students)

            # 3. Get assignments for this class
            assignments = db.execute("""
                SELECT id, title, due_date
                FROM assignments
                WHERE class_id = ?
                ORDER BY due_date DESC, id DESC
            """, selected_class_id)

            for a in assignments:
                due_date_str = str(a.get("due_date") or "").strip()

                # Get latest submission per student for this assignment
                subs = db.execute("""
                    SELECT s.student_id, s.submitted_at, s.grade, u.name AS student_name
                    FROM submissions s
                    JOIN users u ON s.student_id = u.id
                    WHERE s.assignment_id = ?
                    AND s.id IN (
                        SELECT MAX(id) FROM submissions WHERE assignment_id = ? GROUP BY student_id
                    )
                """, a["id"], a["id"])

                submitted_ids = {s["student_id"] for s in subs}
                missing_students = [st for st in enrolled_students if st["id"] not in submitted_ids]

                total_subs = len(subs)
                late_count = 0
                for s in subs:
                    sub_time = str(s.get("submitted_at") or "")
                    if due_date_str and sub_time and sub_time > due_date_str:
                        late_count += 1

                graded_count = sum(1 for s in subs if s.get("grade") is not None and str(s.get("grade")).strip() != "")

                # Average grade
                numeric_grades = []
                for s in subs:
                    val = s.get("grade")
                    if val is not None and str(val).strip() != "":
                        try:
                            numeric_grades.append(float(val))
                        except (ValueError, TypeError):
                            pass
                avg_grade = round(sum(numeric_grades) / len(numeric_grades), 1) if numeric_grades else None
                completion_rate = round((total_subs / total_students) * 100) if total_students > 0 else 0

                assignments_insights.append({
                    "id": a["id"],
                    "title": a["title"],
                    "due_date": a["due_date"],
                    "total_students": total_students,
                    "submitted_count": total_subs,
                    "missing_students": missing_students,
                    "completion_rate": completion_rate,
                    "graded_count": graded_count,
                    "late_count": late_count,
                    "avg_grade": avg_grade
                })

            # 4. Recent submission activity stream
            raw_activity = db.execute("""
                SELECT s.id, s.submitted_at, s.grade, u.name AS student_name, a.title AS assignment_title, a.due_date
                FROM submissions s
                JOIN users u ON s.student_id = u.id
                JOIN assignments a ON s.assignment_id = a.id
                WHERE a.class_id = ?
                ORDER BY s.submitted_at DESC
                LIMIT 8
            """, selected_class_id)

            for act in raw_activity:
                sub_time = str(act.get("submitted_at") or "")
                due_time = str(act.get("due_date") or "")
                is_late = bool(due_time and sub_time and sub_time > due_time)
                recent_activity.append({
                    "student_name": act["student_name"],
                    "assignment_title": act["assignment_title"],
                    "submitted_at": act["submitted_at"],
                    "grade": act["grade"],
                    "is_late": is_late
                })

    return render_template(
        "admin_insights.html",
        classes=classes,
        selected_class=selected_class,
        assignments=assignments_insights,
        recent_activity=recent_activity
    )


@app.route("/admin/classes/<int:class_id>/export-csv")
@login_required
@admin_required
def export_class_csv(class_id):
    admin_id = session["user_id"]

    # 1. Verify class ownership
    class_rows = db.execute(
        "SELECT * FROM classes WHERE id = ? AND admin_id = ?",
        class_id, admin_id
    )
    if not class_rows:
        return apology("Class not found or unauthorized", 404)

    class_info = class_rows[0]
    class_name = class_info["name"]

    # 2. Fetch enrolled students
    students = db.execute("""
        SELECT u.id, u.name, u.email
        FROM users u
        JOIN enrollments e ON u.id = e.student_id
        WHERE e.class_id = ?
        ORDER BY u.name ASC
    """, class_id)

    # 3. Fetch assignments for this class
    assignments = db.execute("""
        SELECT id, title, due_date
        FROM assignments
        WHERE class_id = ?
        ORDER BY due_date ASC, id ASC
    """, class_id)

    # 4. Generate CSV in-memory
    output = io.StringIO()
    writer = csv.writer(output)

    # Header Row
    writer.writerow([
        "Class",
        "Student Name",
        "Student Email",
        "Assignment Title",
        "Due Date",
        "Status",
        "Submitted At",
        "Late",
        "Grade",
        "Feedback"
    ])

    for student in students:
        for a in assignments:
            # Get latest submission from this student for this assignment
            sub = db.execute("""
                SELECT submitted_at, grade, feedback
                FROM submissions
                WHERE assignment_id = ? AND student_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, a["id"], student["id"])

            due_date_str = str(a.get("due_date") or "").strip()

            if sub:
                sub_data = sub[0]
                sub_time = str(sub_data.get("submitted_at") or "")
                is_late = bool(due_date_str and sub_time and sub_time > due_date_str)

                has_grade = sub_data.get("grade") is not None and str(sub_data.get("grade")).strip() != ""
                status = "Graded" if has_grade else "Submitted"

                writer.writerow([
                    class_name,
                    student["name"],
                    student["email"],
                    a["title"],
                    due_date_str or "No deadline",
                    status,
                    sub_time,
                    "Yes" if is_late else "No",
                    sub_data.get("grade") if has_grade else "",
                    sub_data.get("feedback") or ""
                ])
            else:
                writer.writerow([
                    class_name,
                    student["name"],
                    student["email"],
                    a["title"],
                    due_date_str or "No deadline",
                    "Missing",
                    "",
                    "",
                    "",
                    ""
                ])

    # Clean filename (e.g. Python_data_export.csv)
    safe_name = "".join(c for c in class_name if c.isalnum() or c in ("-", "_")).rstrip()
    filename = f"{safe_name}_gradebook.csv"

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Content-type": "text/csv; charset=utf-8"
        }
    )
