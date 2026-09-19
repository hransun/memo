from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path
import os
import secrets
import sqlite3
import uuid

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError, ImageOps

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('MEMO_DATA_DIR', ROOT / 'data')).resolve()
UPLOADS = DATA / 'uploads'
UPLOADS.mkdir(parents=True, exist_ok=True)
DB = DATA / 'memo.db'
TOKEN = secrets.token_urlsafe(32)
app = FastAPI(title='memo', docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
templates = Jinja2Templates(directory=ROOT / 'templates')
STATUSES = {'todo': '待办', 'doing': '进行中', 'done': '已完成'}


@contextmanager
def database():
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        with connection:
            yield connection
    finally:
        connection.close()


with database() as db:
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


def now():
    return datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')


def touch_page(db, page_id):
    timestamp = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S.%f')
    db.execute('UPDATE pages SET updated_at=? WHERE id=?', (timestamp, page_id))


def clean(value, limit=200):
    value = value.strip()
    if not value or len(value) > limit:
        raise HTTPException(400, f'内容不能为空，且不能超过 {limit} 个字。')
    return value


def require(db, table, record_id, include_deleted=False):
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (record_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '这条记录不存在，可能已经被删除。')
    if not include_deleted and table in ('pages', 'items'):
        if row['deleted_at']:
            raise HTTPException(404, '这条记录在回收站中，请先恢复。')
        if table == 'items':
            require(db, 'pages', row['page_id'])
    return row


def parse_tags(value):
    tags = []
    for part in value.replace('，', ',').split(','):
        tag = part.strip()
        if tag and tag.casefold() not in {t.casefold() for t in tags}:
            if len(tag) > 30:
                raise HTTPException(400, '每个标签最多 30 个字。')
            tags.append(tag)
    if len(tags) > 10:
        raise HTTPException(400, '每页最多添加 10 个标签。')
    return tags


def set_tags(db, page_id, tags):
    db.execute('DELETE FROM page_tags WHERE page_id=?', (page_id,))
    db.executemany('INSERT INTO page_tags(page_id,tag) VALUES (?,?)', [(page_id, tag) for tag in tags])


def redirect(page_id=None):
    return RedirectResponse(f'/?page={page_id}&saved=1' if page_id else '/?saved=1', status_code=303)


@app.middleware('http')
async def protect_local_app(request: Request, call_next):
    if request.method == 'POST':
        # Reject cross-site form submissions without relying on browser cookies.
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return HTMLResponse('不允许来自其他网站的操作。', status_code=403)
        token = request.query_params.get('token', '')
        if not secrets.compare_digest(token, TOKEN):
            return HTMLResponse('页面已过期，请刷新页面后重试。', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'"
    return response


@app.exception_handler(HTTPException)
async def expected_error(request, exc):
    return templates.TemplateResponse(request=request, name='error.html', context={'message': exc.detail}, status_code=exc.status_code)


@app.get('/')
def home(request: Request, page: int | None = None, q: str = Query('', max_length=200), tag: str = Query('', max_length=30)):
    q, tag = q.strip(), tag.strip()
    with database() as db:
        pages = db.execute('''SELECT p.* FROM pages p WHERE p.deleted_at IS NULL
            AND (?='' OR instr(lower(p.title),lower(?))>0
                OR EXISTS(SELECT 1 FROM items i WHERE i.page_id=p.id AND i.deleted_at IS NULL
                    AND (instr(lower(i.title),lower(?))>0 OR EXISTS(
                        SELECT 1 FROM updates u WHERE u.item_id=i.id AND instr(lower(u.body),lower(?))>0)))
                OR EXISTS(SELECT 1 FROM page_tags t WHERE t.page_id=p.id AND instr(lower(t.tag),lower(?))>0))
            AND (?='' OR EXISTS(SELECT 1 FROM page_tags t WHERE t.page_id=p.id AND t.tag=? COLLATE NOCASE))
            ORDER BY pinned DESC, coalesce(updated_at,created) DESC, id DESC''', (q,q,q,q,q,tag,tag)).fetchall()
        selected = require(db, 'pages', page) if page else (pages[0] if pages else None)
        tag_rows = db.execute('SELECT * FROM page_tags ORDER BY tag').fetchall()
        page_tags = {}
        for row in tag_rows:
            page_tags.setdefault(row['page_id'], []).append(row['tag'])
        all_tags = [row[0] for row in db.execute('SELECT DISTINCT t.tag FROM page_tags t JOIN pages p ON p.id=t.page_id WHERE p.deleted_at IS NULL ORDER BY t.tag')]
        pinned_count = db.execute('SELECT count(*) FROM pages WHERE pinned=1 AND deleted_at IS NULL').fetchone()[0]
        items = []
        if selected:
            for row in db.execute('SELECT * FROM items WHERE page_id=? AND deleted_at IS NULL ORDER BY id', (selected['id'],)).fetchall():
                item = dict(row)
                item['updates'] = db.execute('SELECT * FROM updates WHERE item_id=? ORDER BY id DESC', (row['id'],)).fetchall()
                items.append(item)
    return templates.TemplateResponse(request=request, name='index.html', context={
        'pages': pages, 'selected': selected, 'items': items, 'statuses': STATUSES,
        'done': sum(item['status'] == 'done' for item in items), 'token': TOKEN,
        'pinned_count': pinned_count,
        'favorite_count': sum(bool(p['favorite']) for p in pages),
        'q': q, 'tag': tag, 'all_tags': all_tags, 'page_tags': page_tags,
    })


@app.post('/pages')
async def create_page(title: str = Form(...), photo: UploadFile | None = File(None), tags: str = Form('')):
    title = clean(title)
    tags = parse_tags(tags)
    filename = ''  # Empty string preserves compatibility with existing databases.
    if photo is not None and photo.filename:
        content = await photo.read(20 * 1024 * 1024 + 1)
        await photo.close()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(400, '照片不能超过 20 MB。')
        try:
            with Image.open(BytesIO(content)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise HTTPException(400, '请选择 JPG、PNG 或 WebP 照片。')
                if source.width * source.height > 40_000_000:
                    raise HTTPException(400, '照片尺寸过大，请先缩小后上传。')
                source.load()
                picture = ImageOps.exif_transpose(source).convert('RGB')
                filename = f'{uuid.uuid4().hex}.jpg'
                picture.save(UPLOADS / filename, quality=95)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise HTTPException(400, '无法读取这张照片，请选择有效的 JPG、PNG 或 WebP 文件。')
    try:
        with database() as db:
            page_id = db.execute('INSERT INTO pages(title,image,created) VALUES (?,?,?)', (title, filename, now())).lastrowid
            touch_page(db, page_id)
            set_tags(db, page_id, tags)
    except Exception:
        if filename:
            (UPLOADS / filename).unlink(missing_ok=True)
        raise
    return redirect(page_id)


@app.get('/pages/{page_id}/photo')
def photo(page_id: int):
    with database() as db:
        page = require(db, 'pages', page_id)
    if not page['image']:
        raise HTTPException(404, '这页笔记没有照片。')
    return FileResponse(UPLOADS / page['image'], media_type='image/jpeg')


@app.post('/pages/{page_id}/delete')
def delete_page(page_id: int):
    with database() as db:
        require(db, 'pages', page_id)
        db.execute('UPDATE pages SET deleted_at=?,pinned=0 WHERE id=?', (now(), page_id))
    return redirect()


@app.post('/pages/{page_id}/edit')
def edit_page(page_id: int, title: str = Form(...), tags: str = Form('')):
    title, tags = clean(title), parse_tags(tags)
    with database() as db:
        page = require(db, 'pages', page_id)
        old_tags = {row[0] for row in db.execute('SELECT tag FROM page_tags WHERE page_id=?', (page_id,))}
        if page['title'] != title or old_tags != set(tags):
            db.execute('UPDATE pages SET title=? WHERE id=?', (title, page_id))
            set_tags(db, page_id, tags)
            touch_page(db, page_id)
    return redirect(page_id)


@app.get('/trash')
def trash(request: Request):
    with database() as db:
        pages = db.execute('SELECT * FROM pages WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC,id DESC').fetchall()
        items = db.execute('''SELECT i.*,p.title AS page_title FROM items i JOIN pages p ON p.id=i.page_id
            WHERE i.deleted_at IS NOT NULL AND p.deleted_at IS NULL ORDER BY i.deleted_at DESC,i.id DESC''').fetchall()
    return templates.TemplateResponse(request=request, name='trash.html', context={'pages': pages, 'items': items, 'token': TOKEN})


@app.post('/trash/{kind}/{record_id}/restore')
def restore_record(kind: str, record_id: int):
    if kind not in ('pages', 'items'):
        raise HTTPException(404, '记录类型不存在。')
    with database() as db:
        row = require(db, kind, record_id, include_deleted=True)
        if not row['deleted_at']:
            raise HTTPException(400, '这条记录不在回收站中。')
        page_id = record_id if kind == 'pages' else row['page_id']
        if kind == 'items':
            require(db, 'pages', page_id)
        db.execute(f'UPDATE {kind} SET deleted_at=NULL WHERE id=?', (record_id,))
        touch_page(db, page_id)
    return redirect(page_id)


@app.post('/trash/{kind}/{record_id}/purge')
def purge_record(kind: str, record_id: int):
    if kind not in ('pages', 'items'):
        raise HTTPException(404, '记录类型不存在。')
    with database() as db:
        row = require(db, kind, record_id, include_deleted=True)
        if not row['deleted_at']:
            raise HTTPException(400, '请先将记录移入回收站。')
        db.execute(f'DELETE FROM {kind} WHERE id=?', (record_id,))
    if kind == 'pages' and row['image']:
        (UPLOADS / row['image']).unlink(missing_ok=True)
    return RedirectResponse('/trash?saved=1', status_code=303)


@app.post('/pages/{page_id}/pin')
def pin_page(page_id: int, pinned: int = Form(...)):
    if pinned not in (0, 1):
        raise HTTPException(400, '请选择有效的置顶状态。')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        page = require(db, 'pages', page_id)
        if pinned and not page['pinned'] and db.execute('SELECT count(*) FROM pages WHERE pinned=1').fetchone()[0] >= 5:
            raise HTTPException(400, '最多置顶 5 个 memo，请先取消一个置顶。')
        db.execute('UPDATE pages SET pinned=? WHERE id=?', (pinned, page_id))
    return redirect(page_id)


@app.post('/pages/{page_id}/favorite')
def favorite_page(page_id: int, favorite: int = Form(...)):
    if favorite not in (0, 1):
        raise HTTPException(400, '请选择有效的收藏状态。')
    with database() as db:
        require(db, 'pages', page_id)
        db.execute('UPDATE pages SET favorite=? WHERE id=?', (favorite, page_id))
    return redirect(page_id)


@app.post('/pages/{page_id}/items')
def add_item(page_id: int, title: str = Form(...)):
    title = clean(title)
    with database() as db:
        require(db, 'pages', page_id)
        db.execute('INSERT INTO items(page_id,title,created) VALUES (?,?,?)', (page_id, title, now()))
        touch_page(db, page_id)
    return redirect(page_id)


@app.post('/items/{item_id}/edit')
def edit_item(item_id: int, title: str = Form(...), status: str = Form(...)):
    title = clean(title)
    if status not in STATUSES:
        raise HTTPException(400, '请选择有效的状态。')
    with database() as db:
        item = require(db, 'items', item_id)
        db.execute('UPDATE items SET title=?,status=? WHERE id=?', (title, status, item_id))
        if item['title'] != title or item['status'] != status:
            touch_page(db, item['page_id'])
        if item['status'] != status:
            db.execute('INSERT INTO updates(item_id,body,created) VALUES (?,?,?)', (item_id, f'状态：{STATUSES[item["status"]]} → {STATUSES[status]}', now()))
    return redirect(item['page_id'])


@app.post('/items/{item_id}/updates')
def add_update(item_id: int, body: str = Form(...)):
    body = clean(body, 5000)
    with database() as db:
        item = require(db, 'items', item_id)
        db.execute('INSERT INTO updates(item_id,body,created) VALUES (?,?,?)', (item_id, body, now()))
        touch_page(db, item['page_id'])
    return redirect(item['page_id'])


@app.post('/items/{item_id}/delete')
def delete_item(item_id: int):
    with database() as db:
        item = require(db, 'items', item_id)
        db.execute('UPDATE items SET deleted_at=? WHERE id=?', (now(), item_id))
        touch_page(db, item['page_id'])
    return redirect(item['page_id'])
