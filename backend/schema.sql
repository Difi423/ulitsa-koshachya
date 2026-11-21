PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS pets (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    age_months INTEGER NOT NULL CHECK (age_months >= 0 AND age_months <= 360),
    sex TEXT NOT NULL CHECK (sex IN ('male', 'female')),
    temperament TEXT NOT NULL,
    trait TEXT NOT NULL,
    color TEXT NOT NULL,
    short TEXT NOT NULL,
    story TEXT NOT NULL,
    home TEXT NOT NULL,
    care TEXT NOT NULL,
    image TEXT NOT NULL,
    alt TEXT NOT NULL,
    featured INTEGER NOT NULL DEFAULT 0 CHECK (featured IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'available'
        CHECK (status IN ('available', 'reserved', 'adopted', 'archived')),
    adoption_story TEXT NOT NULL DEFAULT '',
    adopted_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT,
    pet_id INTEGER NOT NULL REFERENCES pets(id) ON DELETE RESTRICT,
    visitor_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    visit_time TEXT NOT NULL CHECK (visit_time IN ('12-14', '14-16', '16-18')),
    comment TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'confirmed', 'completed', 'cancelled')),
    admin_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS applications_user ON applications(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS applications_no_duplicate
    ON applications(phone, pet_id, visit_date, visit_time)
    WHERE user_id IS NULL AND status IN ('new', 'confirmed');

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    topic TEXT NOT NULL CHECK (topic IN ('adoption', 'volunteer', 'help', 'question')),
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'read', 'closed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS pet_photos (
    id INTEGER PRIMARY KEY,
    pet_id INTEGER NOT NULL REFERENCES pets(id) ON DELETE RESTRICT,
    image TEXT NOT NULL,
    alt TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    UNIQUE(pet_id, image)
);
CREATE INDEX IF NOT EXISTS pet_photos_order ON pet_photos(pet_id,position,id);

CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE RESTRICT,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('created','updated','imported')),
    old_status TEXT,
    new_status TEXT NOT NULL,
    old_visit_date TEXT NOT NULL DEFAULT '',
    new_visit_date TEXT NOT NULL DEFAULT '',
    old_visit_time TEXT NOT NULL DEFAULT '',
    new_visit_time TEXT NOT NULL DEFAULT '',
    old_note TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS application_events_order ON application_events(application_id,id);
