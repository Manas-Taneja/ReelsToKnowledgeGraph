-- Reels To Knowledge Base

CREATE TABLE IF NOT EXISTS posts (
  shortcode   TEXT PRIMARY KEY,          -- e.g. Dbm7X5IAuEe
  url         TEXT NOT NULL,
  kind        TEXT NOT NULL,             -- reel | post  (from the URL shape)
  saved_at    TEXT,                      -- ISO8601, from the Meta export timestamp
  media_kind  TEXT,                      -- video | images  (resolved at acquire time)
  caption     TEXT,
  collection  TEXT,                      -- your own Instagram collection, if filed
  author      TEXT,                      -- creator's @username
  author_link TEXT,                      -- creator's link-in-bio
  hashtags    TEXT NOT NULL DEFAULT '[]',-- JSON array, from the export
  transcript  TEXT,
  ocr_text    TEXT,             -- verbatim text read off the frames
  media_dir   TEXT,
  status      TEXT NOT NULL DEFAULT 'new',
             -- new -> prepared -> extracted ; or failed / skipped
  error       TEXT,
  imported_at TEXT NOT NULL DEFAULT (datetime('now')),
  prepared_at TEXT
);

CREATE INDEX IF NOT EXISTS posts_status ON posts(status);

CREATE TABLE IF NOT EXISTS extractions (
  shortcode    TEXT PRIMARY KEY REFERENCES posts(shortcode) ON DELETE CASCADE,
  summary      TEXT NOT NULL,
  detail       TEXT,                     -- 2-4 sentences: what it actually does / how
  tools        TEXT NOT NULL DEFAULT '[]',   -- JSON array of tool/product names
  links        TEXT NOT NULL DEFAULT '[]',   -- JSON array of URLs seen on-screen or spoken
  prompt       TEXT,                     -- the prompt/checklist VERBATIM, if the post is one
  tags         TEXT NOT NULL DEFAULT '[]',   -- JSON array
  actionable   TEXT,                     -- the concrete next step, if any
  confidence   TEXT,                      -- high | medium | low
  extracted_by TEXT,
  extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Full-text search across everything worth searching.
CREATE VIRTUAL TABLE IF NOT EXISTS search_idx USING fts5(
  shortcode UNINDEXED,
  summary, detail, tools, links, prompt, tags, caption, transcript, ocr_text,
  collection, author, hashtags,
  tokenize = 'porter unicode61'
);
