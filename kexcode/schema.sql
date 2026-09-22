CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'student')),
    verified INTEGER NOT NULL DEFAULT 0,
    verification_code TEXT,
    code_expires_at DATETIME
);

CREATE TABLE classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    admin_id INTEGER NOT NULL,
    FOREIGN KEY(admin_id) REFERENCES users(id)
);

CREATE TABLE enrollments (
    class_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    PRIMARY KEY (class_id, student_id),
    FOREIGN KEY(class_id) REFERENCES classes(id),
    FOREIGN KEY(student_id) REFERENCES users(id)
);

CREATE TABLE assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    starter_code TEXT,
    due_date DATETIME,
    FOREIGN KEY(class_id) REFERENCES classes(id)
);

CREATE TABLE submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    grade INTEGER,
    feedback TEXT,
    FOREIGN KEY(assignment_id) REFERENCES assignments(id),
    FOREIGN KEY(student_id) REFERENCES users(id)
);

CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(class_id) REFERENCES classes(id)
);

CREATE TABLE drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    code TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'python',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(assignment_id, student_id),

    FOREIGN KEY(assignment_id) REFERENCES assignments(id),
    FOREIGN KEY(student_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS personal_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (student_id) REFERENCES users(id)
);
