"""Model layer: SQLite schema, transactions and named persistence operations."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL, image TEXT NOT NULL,
                    created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY, page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                    title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'todo'
                    CHECK(status IN ('todo','doing','done')), created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS updates (
                    id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    body TEXT NOT NULL, created TEXT NOT NULL);
            ''')
            if 'updated_at' not in {row['name'] for row in db.execute('PRAGMA table_info(pages)')}:
                db.execute('ALTER TABLE pages ADD COLUMN updated_at TEXT')
            if 'pinned' not in {row['name'] for row in db.execute('PRAGMA table_info(pages)')}:
                db.execute('ALTER TABLE pages ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0')
            if 'favorite' not in {row['name'] for row in db.execute('PRAGMA table_info(pages)')}:
                db.execute('ALTER TABLE pages ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0')
            for table in ('pages', 'items'):
                if 'deleted_at' not in {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}:
                    db.execute(f'ALTER TABLE {table} ADD COLUMN deleted_at TEXT')
            db.execute('''CREATE TABLE IF NOT EXISTS page_entries (
                id INTEGER PRIMARY KEY,
                page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                body TEXT NOT NULL, created TEXT NOT NULL)''')
            for column in ('attachment', 'media_type'):
                if column not in {row['name'] for row in db.execute('PRAGMA table_info(page_entries)')}:
                    db.execute(f"ALTER TABLE page_entries ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            db.execute('''CREATE TABLE IF NOT EXISTS page_tags (
                page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                tag TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY(page_id,tag))''')
            db.execute('''
                UPDATE pages SET updated_at = max(
                    created,
                    coalesce((SELECT max(created) FROM items WHERE page_id=pages.id), created),
                    coalesce((SELECT max(u.created) FROM updates u JOIN items i ON i.id=u.item_id
                              WHERE i.page_id=pages.id), created)
                ) WHERE updated_at IS NULL
            ''')


def set_updated_at(db, timestamp, page_id):
    return db.execute('UPDATE pages SET updated_at=? WHERE id=?', (timestamp, page_id))


def clear_tags(db, page_id):
    return db.execute('DELETE FROM page_tags WHERE page_id=?', (page_id,))


def insert_tags(db, parameters):
    return db.executemany('INSERT INTO page_tags(page_id,tag) VALUES (?,?)', parameters)


def trash_page(db, deleted_at, page_id):
    return db.execute('UPDATE pages SET deleted_at=?,pinned=0 WHERE id=?', (deleted_at, page_id))


def restore_record(db, kind, record_id):
    if kind not in ('pages', 'items'):
        raise ValueError('Unsupported record type')
    return db.execute(f'UPDATE {kind} SET deleted_at=NULL WHERE id=?', (record_id,))


def purge_record(db, kind, record_id):
    if kind not in ('pages', 'items'):
        raise ValueError('Unsupported record type')
    return db.execute(f'DELETE FROM {kind} WHERE id=?', (record_id,))


def begin_write(db):
    return db.execute('BEGIN IMMEDIATE')


def set_pin(db, pinned, page_id):
    return db.execute('UPDATE pages SET pinned=? WHERE id=?', (pinned, page_id))


def set_favorite(db, favorite, page_id):
    return db.execute('UPDATE pages SET favorite=? WHERE id=?', (favorite, page_id))


def insert_item(db, page_id, title, created):
    return db.execute('INSERT INTO items(page_id,title,created) VALUES (?,?,?)', (page_id, title, created))


def update_item(db, title, status, item_id):
    return db.execute('UPDATE items SET title=?,status=? WHERE id=?', (title, status, item_id))


def insert_update(db, item_id, body, created):
    return db.execute('INSERT INTO updates(item_id,body,created) VALUES (?,?,?)', (item_id, body, created))


def trash_item(db, deleted_at, item_id):
    return db.execute('UPDATE items SET deleted_at=? WHERE id=?', (deleted_at, item_id))


def find_record(db, table, record_id):
    if table not in ('pages', 'items'):
        raise ValueError('Unsupported record type')
    return db.execute(f'SELECT * FROM {table} WHERE id=?', (record_id,)).fetchone()


def rename_page(db, title, page_id):
    return db.execute('UPDATE pages SET title=? WHERE id=?', (title, page_id))


def search_pages(db, parameters):
    return db.execute('''SELECT p.* FROM pages p WHERE p.deleted_at IS NULL
            AND (?='' OR instr(lower(p.title),lower(?))>0
                OR EXISTS(SELECT 1 FROM items i WHERE i.page_id=p.id AND i.deleted_at IS NULL
                    AND (instr(lower(i.title),lower(?))>0 OR EXISTS(
                        SELECT 1 FROM updates u WHERE u.item_id=i.id AND instr(lower(u.body),lower(?))>0)))
                OR EXISTS(SELECT 1 FROM page_tags t WHERE t.page_id=p.id AND instr(lower(t.tag),lower(?))>0)
                OR EXISTS(SELECT 1 FROM page_entries e WHERE e.page_id=p.id AND instr(lower(e.body),lower(?))>0))
            AND (?='' OR EXISTS(SELECT 1 FROM page_tags t WHERE t.page_id=p.id AND t.tag=? COLLATE NOCASE))
            ORDER BY pinned DESC, coalesce(updated_at,created) DESC, id DESC''', parameters).fetchall()


def list_tag_rows(db):
    return db.execute('SELECT * FROM page_tags ORDER BY tag').fetchall()


def list_active_tags(db):
    return db.execute('SELECT DISTINCT t.tag FROM page_tags t JOIN pages p ON p.id=t.page_id WHERE p.deleted_at IS NULL ORDER BY t.tag')


def insert_page(db, title, image, created):
    return db.execute('INSERT INTO pages(title,image,created) VALUES (?,?,?)', (title, image, created)).lastrowid


def list_page_tags(db, page_id):
    return db.execute('SELECT tag FROM page_tags WHERE page_id=?', (page_id,))


def list_trashed_pages(db):
    return db.execute('SELECT * FROM pages WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC,id DESC').fetchall()


def list_trashed_items(db):
    return db.execute('''SELECT i.*,p.title AS page_title FROM items i JOIN pages p ON p.id=i.page_id
            WHERE i.deleted_at IS NOT NULL AND p.deleted_at IS NULL ORDER BY i.deleted_at DESC,i.id DESC''').fetchall()


def count_active_pins(db):
    return db.execute('SELECT count(*) FROM pages WHERE pinned=1 AND deleted_at IS NULL').fetchone()


def list_items(db, page_id):
    return db.execute('SELECT * FROM items WHERE page_id=? AND deleted_at IS NULL ORDER BY id', (page_id,)).fetchall()


def list_updates(db, item_id):
    return db.execute('SELECT * FROM updates WHERE item_id=? ORDER BY id DESC', (item_id,)).fetchall()


def count_pins(db):
    return db.execute('SELECT count(*) FROM pages WHERE pinned=1').fetchone()


def insert_page_entry(db, page_id, body, created, attachment='', media_type=''):
    return db.execute('INSERT INTO page_entries(page_id,body,created,attachment,media_type) VALUES (?,?,?,?,?)', (page_id, body, created, attachment, media_type))


def list_page_entries(db, page_id):
    return db.execute('SELECT * FROM page_entries WHERE page_id=? ORDER BY id DESC', (page_id,)).fetchall()


def find_page_entry(db, entry_id):
    return db.execute('SELECT * FROM page_entries WHERE id=?', (entry_id,)).fetchone()
