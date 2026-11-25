PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, sub TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL, bio TEXT NOT NULL DEFAULT '', approved INTEGER NOT NULL DEFAULT 1 CHECK(approved IN (0,1))
);
CREATE TABLE IF NOT EXISTS locations (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS posts (
 id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id), caption TEXT NOT NULL DEFAULT '',
 location_id INTEGER REFERENCES locations(id), audience TEXT NOT NULL DEFAULT 'all' CHECK(audience IN ('all','followers','groups','selected')),
 state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','published','deleted')),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), revision INTEGER NOT NULL DEFAULT 0, mix_key TEXT
);
CREATE TABLE IF NOT EXISTS media (
 id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id), source_id INTEGER REFERENCES media(id),
 kind TEXT NOT NULL CHECK(kind IN ('image','audio')), object_key TEXT NOT NULL UNIQUE,
 bytes INTEGER NOT NULL, filename TEXT NOT NULL, metadata TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}',
 active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)), position INTEGER, seconds REAL NOT NULL DEFAULT 5,
 CHECK(source_id IS NOT NULL OR active=0)
);
CREATE UNIQUE INDEX IF NOT EXISTS active_source ON media(source_id) WHERE active=1;
CREATE INDEX IF NOT EXISTS post_media ON media(post_id,active,position);
CREATE INDEX IF NOT EXISTS feed_order ON posts(state,created_at DESC,id DESC);
CREATE INDEX IF NOT EXISTS author_posts ON posts(owner_id,created_at DESC,id DESC);
CREATE TABLE IF NOT EXISTS follows (
 follower_id INTEGER REFERENCES users(id), followed_id INTEGER REFERENCES users(id),
 PRIMARY KEY(follower_id,followed_id), CHECK(follower_id<>followed_id)
);
CREATE INDEX IF NOT EXISTS reverse_follow ON follows(followed_id,follower_id);
CREATE TABLE IF NOT EXISTS likes (user_id INTEGER REFERENCES users(id), post_id INTEGER REFERENCES posts(id), PRIMARY KEY(user_id,post_id));
CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS group_members (group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE, user_id INTEGER REFERENCES users(id), PRIMARY KEY(group_id,user_id));
CREATE INDEX IF NOT EXISTS user_groups ON group_members(user_id,group_id);
CREATE TABLE IF NOT EXISTS post_groups (post_id INTEGER REFERENCES posts(id), group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE, PRIMARY KEY(post_id,group_id));
CREATE TABLE IF NOT EXISTS post_viewers (post_id INTEGER REFERENCES posts(id), user_id INTEGER REFERENCES users(id), PRIMARY KEY(post_id,user_id));
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id), input_id INTEGER REFERENCES media(id),
 kind TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('Receiving','Processing','Ready','Failed')),
 reserved_bytes INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 1,
 error TEXT, settings TEXT NOT NULL DEFAULT '{}', output_key TEXT,
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS cleanup (object_key TEXT PRIMARY KEY, post_id INTEGER REFERENCES posts(id), attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT);
