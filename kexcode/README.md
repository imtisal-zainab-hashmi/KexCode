# KexCode
#### Video Demo: https://youtu.be/bBFjT2tkyYY
#### Description:

**KexCode** is an educational code workspace and classroom management platform designed specifically for school coding clubs and introductory computer science courses. It solves the challenge of running student code environments safely and reliably without relying on expensive server infrastructure or vulnerable remote code execution backends.

The platform provides two isolated portals: a **Student Portal** equipped with an in-browser code editor, automated syntax validation, draft auto-saving, problem checking, personal scratchpads, and gamified progress tracking; and an **Instructor/Admin Portal** with classroom roster management, assignment creation, submission grading, analytics, one-click CSV gradebook export, and lecture distribution with PDF attachments.

---

## Key Features

### Student Portal
- **Zero-Config Monaco Workspace:** Uses the core engine behind VS Code in the browser, supporting Python, JavaScript, HTML, and CSS.
- **Client-Side Syntax & Safety Checks:** Code is evaluated directly within the student's browser using sandboxed iframes and AST/syntax parsing, preventing server resource exhaustion and security vulnerabilities.
- **Drafts & Autosave Engine:** Periodically preserves student work every 30 seconds, on manual save, and automatically syncs via `navigator.sendBeacon` if a student accidentally closes the browser tab.
- **Submission History:** Allows students to view previous submission attempts, inspection timestamps, grades, and teacher feedback.
- **Kira AI Assistant:** A floating contextual tutor powered by LLM endpoints to guide students through syntax errors and programming concepts without giving away complete solutions.
- **Personal Notes & Club Leaderboard:** Private student scratchpads for lecture takeaways and a streak/activity tracker to encourage consistency.
- **Lecture Catalog & PDF Downloads:** Clean lecture reader with print-optimized styles and downloadable PDF attachments.

### Instructor / Admin Portal
- **Class & Roster Management:** Create classes, issue unique student enrollment codes, view student rosters, and manage student enrollment states.
- **Assignment Builder:** Create programming assignments with starter code templates, language limits, custom deadlines, and markdown problem descriptions.
- **Grading & Submissions Hub:** View submitted code with syntax highlighting, on-time vs. late indicators, score inputs, and markdown feedback.
- **Classroom Insights:** View class-wide assignment completion percentages, pinpoint struggling students, and identify common problem assignments.
- **CSV Gradebook Export:** One-click zero-dependency CSV export for official school reporting and record-keeping.
- **Lecture Publisher with PDF Uploads:** Write lecture notes and upload companion PDF guides (with secure file naming, type validation, and 16MB limits).
- **Branded Verification Emails:** Automated verification emails sent via SMTP with a custom dark-and-cream HTML template.

---

## File Structure & Overview

- `app.py`: The central Flask application controller. Contains session management, role-based access control decorators (`@login_required`, `@admin_required`), routing logic for all student and admin views, database queries, draft management endpoints, and file upload handlers.
- `helpers.py`: Utility functions including password verification, secure random code generation, apology handlers, and the dual-format (HTML + plain text) SMTP email verification routine.
- `schema.sql`: Database schema definition containing tables for `users`, `classes`, `enrollments`, `assignments`, `drafts`, `submissions`, `personal_notes`, and `notes` (lectures with PDF attachments).
- `kexcode.db`: The SQLite database storing application state, student records, assignments, and grades.
- `requirements.txt`: Python package requirements (`Flask`, `Flask-Session`, `cs50`, `requests`, `python-dotenv`, `werkzeug`, `openai`).
- `.env`: Environment variables configuration file storing secret keys, email credentials, and AI API keys.
- `static/css/styles.css`: Complete custom stylesheet providing a cohesive, dark-and-cream monochrome aesthetic across desktop and mobile screens, modal drawers, and print layouts.
- `static/js/editor.js`: Browser script managing the Monaco Editor initialization, language switching, client-side syntax validation, problems panel rendering, and autosave syncing.
- `static/uploads/lectures/`: Secure local file storage directory for instructor-uploaded lecture PDFs.
- `templates/layout.html`: Base Jinja2 layout providing responsive navigation, collapsible sidebar, the floating Kira assistant modal, and flash messaging.
- `templates/`:
  - `login.html` & `register.html`: Centered authentication and registration forms.
  - `dashboard.html`: Student home view summarizing active classes, deadlines, and recent activity.
  - `assignment_detail.html`: The Monaco-powered assignment solving workspace with autosave and problems tabs.
  - `assignment_submissions.html`: Student submission history and instructor feedback timeline.
  - `assignments.html`: Categorized assignment directory (To Do, Draft Saved, Submitted, Graded).
  - `admin_dashboard.html`: Instructor dashboard overview.
  - `admin_classes.html`: Class creator, invite code manager, and roster viewer.
  - `admin_grading.html`: Submission grading interface with collapsible code inspection.
  - `admin_insights.html`: Classroom completion metrics and CSV export buttons.
  - `admin_notes.html` & `note_detail.html`: Lecture publisher and student lecture reader with PDF download support.
  - `my_notes.html`: Private student scratchpad notes manager.
  - `leaderboard.html`: Gamified club activity and streak rankings.

---

## Design Decisions

1. **Client-Side Validation Over Server-Side Execution:** Running untrusted student Python/C code on a shared server poses security risks (fork bombs, infinite loops, unauthorized file access) and requires isolated container infrastructure (Docker, gVisor) that free hosting providers cannot support. KexCode uses client-side syntax parsers and sandboxed iframes for web projects, making the entire platform free to host without risking server stability.
2. **SQLite via CS50 SQL:** SQLite was chosen for zero-configuration, ACID compliance, and portability. Combined with the CS50 SQL wrapper, queries remain concise, fast, and easy to inspect.
3. **Draft Separation from Submissions:** Unfinished student work is kept in a distinct `drafts` table with an automatic 30-second autosave interval and `sendBeacon` synchronization. When a student submits their assignment, the draft is cleared and an immutable record is inserted into `submissions`, maintaining full revision history without overwriting work.
4. **Monaco Editor via CDN:** Rather than embedding basic `textarea` elements or heavier dependencies, Monaco was integrated directly from CDN. This gives students the exact code editing experience of Visual Studio Code (syntax highlighting, bracket matching, indentation rules, error squiggles) with zero client setup.

---

## How to Run the Project

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/kexcode.git
   cd kexcode

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   # On macOS/Linux:
   source venv/bin/activate
   # On Windows (Command Prompt):
   venv\Scripts\activate.bat
   # On Windows (PowerShell):
   venv\Scripts\Activate.ps1

3. Install required dependencies:
```bash
pip install -r requirements.txt

4. Configure environment variables:
```bash
Create a .env file in the root directory:
SECRET_KEY=kexcode-production-secret-key-change-this
OPENROUTER_API_KEY=your_openrouter_or_openai_api_key
EMAIL_ADDRESS=yourclub@gmail.com
EMAIL_PASSWORD=your_16_character_app_password
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=465

5. Initialize the database:
```bash
sqlite3 kexcode.db < schema.sql

6. Start the Flask development server:
```bash
flask run --debug

Open your browser and navigate to http://127.0.0.1:5000
