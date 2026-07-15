CREATE TABLE IF NOT EXISTS proxies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  scheme TEXT NOT NULL DEFAULT 'socks5',
  host TEXT NOT NULL,
  port INTEGER NOT NULL,
  auth_ref TEXT,
  health TEXT NOT NULL DEFAULT 'unknown',
  last_check_at TEXT
);

CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  site_key TEXT NOT NULL,
  username TEXT,
  secret_ref TEXT,
  profile_path TEXT NOT NULL,
  proxy_id INTEGER REFERENCES proxies(id),
  status TEXT NOT NULL DEFAULT 'active',
  last_ok_at TEXT,
  last_error TEXT,
  meta_json TEXT NOT NULL DEFAULT '{}',
  fail_streak INTEGER NOT NULL DEFAULT 0,
  cooling_until TEXT
);

CREATE TABLE IF NOT EXISTS site_policies (
  site_key TEXT PRIMARY KEY,
  url_allow_prefix TEXT NOT NULL DEFAULT '[]',
  min_interval_sec INTEGER NOT NULL DEFAULT 0,
  max_concurrency INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  script TEXT NOT NULL,
  schedule TEXT NOT NULL DEFAULT 'interval:300',
  enabled INTEGER NOT NULL DEFAULT 1,
  max_retries INTEGER NOT NULL DEFAULT 2,
  timeout_sec INTEGER NOT NULL DEFAULT 120,
  params_json TEXT NOT NULL DEFAULT '{}',
  last_started_at TEXT
);

CREATE TABLE IF NOT EXISTS task_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  error TEXT,
  log_path TEXT
);
