"""Service layer: validation and memo workflows, without HTTP or template code."""
from datetime import datetime
from io import BytesIO
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

from . import models
from .errors import MemoError

STATUSES = {'todo': '待办', 'doing': '进行中', 'done': '已完成'}
MAX_PHOTO_BYTES = 20 * 1024 * 1024


class MemoService:
    def __init__(self, store, uploads):
        self.store = store
        self.uploads = uploads
        uploads.mkdir(parents=True, exist_ok=True)

    def now(self):
        return datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')

    def touch_page(self, db, page_id):
        timestamp = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S.%f')
        models.set_updated_at(db, timestamp, page_id)

    def clean(self, value, limit=200):
        value = value.strip()
        if not value or len(value) > limit:
            raise MemoError(400, f'内容不能为空，且不能超过 {limit} 个字。')
        return value

    def require(self, db, table, record_id, include_deleted=False):
        row = models.find_record(db, table, record_id)
        if row is None:
            raise MemoError(404, '这条记录不存在，可能已经被删除。')
        if not include_deleted and table in ('pages', 'items'):
            if row['deleted_at']:
                raise MemoError(404, '这条记录在回收站中，请先恢复。')
            if table == 'items':
                self.require(db, 'pages', row['page_id'])
        return row

    def parse_tags(self, value):
        tags = []
        for part in value.replace('，', ',').split(','):
            tag = part.strip()
            if tag and tag.casefold() not in {t.casefold() for t in tags}:
                if len(tag) > 30:
                    raise MemoError(400, '每个标签最多 30 个字。')
                tags.append(tag)
        if len(tags) > 10:
            raise MemoError(400, '每页最多添加 10 个标签。')
        return tags

    def set_tags(self, db, page_id, tags):
        models.clear_tags(db, page_id)
        models.insert_tags(db, [(page_id, tag) for tag in tags])

    def home(self, page=None, q='', tag='', view='recent'):
        q, tag = (q.strip(), tag.strip())
        if view not in ('recent', 'all', 'favorites'):
            view = 'recent'
        with self.store.connection() as db:
            pages = models.search_pages(db, (q, q, q, q, q, q, tag, tag))
            favorite_count = sum(bool(p['favorite']) for p in pages)
            total_count = len(pages)
            if view == 'favorites':
                pages = [p for p in pages if p['favorite']]
            selected = self.require(db, 'pages', page) if page else pages[0] if pages else None
            tag_rows = models.list_tag_rows(db)
            page_tags = {}
            for row in tag_rows:
                page_tags.setdefault(row['page_id'], []).append(row['tag'])
            all_tags = [row[0] for row in models.list_active_tags(db)]
            pinned_count = models.count_active_pins(db)[0]
            items = []
            timeline = []
            if selected:
                timeline = [dict(e, source='') for e in models.list_page_entries(db, selected['id'])]
                for row in models.list_items(db, selected['id']):
                    item = dict(row)
                    item['updates'] = models.list_updates(db, row['id'])
                    items.append(item)
                    timeline.extend(dict(u, source=row['title']) for u in item['updates'])
            timeline.sort(key=lambda e: (e['created'], e['id']), reverse=True)
            pinned_pages = [p for p in pages if p['pinned']]
            recent_pages = [p for p in pages if not p['pinned']]
            if view == 'recent' and not q and not tag:
                recent_pages = recent_pages[:5]
            pages = pinned_pages + recent_pages
        return {
            'pages': pages,
            'selected': selected,
            'items': items,
            'statuses': STATUSES,
            'done': sum((item['status'] == 'done' for item in items)),
            'pinned_count': pinned_count,
            'favorite_count': favorite_count,
            'total_count': total_count,
            'pinned_pages': pinned_pages,
            'recent_pages': recent_pages,
            'timeline': timeline,
            'view': view,
            'q': q,
            'tag': tag,
            'all_tags': all_tags,
            'page_tags': page_tags,
        }

    def create_page(self, title, photo=None, tags=''):
        title = self.clean(title)
        tags = self.parse_tags(tags)
        filename = ''
        if photo is not None:
            content = photo
            if len(content) > MAX_PHOTO_BYTES:
                raise MemoError(400, '照片不能超过 20 MB。')
            try:
                with Image.open(BytesIO(content)) as source:
                    if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                        raise MemoError(400, '请选择 JPG、PNG 或 WebP 照片。')
                    if source.width * source.height > 40000000:
                        raise MemoError(400, '照片尺寸过大，请先缩小后上传。')
                    source.load()
                    picture = ImageOps.exif_transpose(source).convert('RGB')
                    filename = f'{uuid.uuid4().hex}.jpg'
                    picture.save(self.uploads / filename, quality=95)
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
                raise MemoError(400, '无法读取这张照片，请选择有效的 JPG、PNG 或 WebP 文件。')
        try:
            with self.store.connection() as db:
                page_id = models.insert_page(db, title, filename, self.now())
                self.touch_page(db, page_id)
                self.set_tags(db, page_id, tags)
        except Exception:
            if filename:
                (self.uploads / filename).unlink(missing_ok=True)
            raise
        return page_id

    def photo(self, page_id):
        with self.store.connection() as db:
            page = self.require(db, 'pages', page_id)
        if not page['image']:
            raise MemoError(404, '这页笔记没有照片。')
        return self.uploads / page['image']

    def delete_page(self, page_id):
        with self.store.connection() as db:
            self.require(db, 'pages', page_id)
            models.trash_page(db, self.now(), page_id)
        return None

    def edit_page(self, page_id, title, tags=''):
        title, tags = (self.clean(title), self.parse_tags(tags))
        with self.store.connection() as db:
            page = self.require(db, 'pages', page_id)
            old_tags = {row[0] for row in models.list_page_tags(db, page_id)}
            if page['title'] != title or old_tags != set(tags):
                models.rename_page(db, title, page_id)
                self.set_tags(db, page_id, tags)
                self.touch_page(db, page_id)
        return page_id

    def trash(self):
        with self.store.connection() as db:
            pages = models.list_trashed_pages(db)
            items = models.list_trashed_items(db)
        return {'pages': pages, 'items': items}

    def restore_record(self, kind, record_id):
        if kind not in ('pages', 'items'):
            raise MemoError(404, '记录类型不存在。')
        with self.store.connection() as db:
            row = self.require(db, kind, record_id, include_deleted=True)
            if not row['deleted_at']:
                raise MemoError(400, '这条记录不在回收站中。')
            page_id = record_id if kind == 'pages' else row['page_id']
            if kind == 'items':
                self.require(db, 'pages', page_id)
            models.restore_record(db, kind, record_id)
            self.touch_page(db, page_id)
        return page_id

    def purge_record(self, kind, record_id):
        if kind not in ('pages', 'items'):
            raise MemoError(404, '记录类型不存在。')
        with self.store.connection() as db:
            row = self.require(db, kind, record_id, include_deleted=True)
            if not row['deleted_at']:
                raise MemoError(400, '请先将记录移入回收站。')
            models.purge_record(db, kind, record_id)
        if kind == 'pages' and row['image']:
            (self.uploads / row['image']).unlink(missing_ok=True)
        return None

    def pin_page(self, page_id, pinned):
        if pinned not in (0, 1):
            raise MemoError(400, '请选择有效的置顶状态。')
        with self.store.connection() as db:
            models.begin_write(db)
            page = self.require(db, 'pages', page_id)
            if pinned and (not page['pinned']) and (models.count_pins(db)[0] >= 5):
                raise MemoError(400, '最多置顶 5 个 memo，请先取消一个置顶。')
            models.set_pin(db, pinned, page_id)
        return page_id

    def favorite_page(self, page_id, favorite):
        if favorite not in (0, 1):
            raise MemoError(400, '请选择有效的收藏状态。')
        with self.store.connection() as db:
            self.require(db, 'pages', page_id)
            models.set_favorite(db, favorite, page_id)
        return page_id

    def add_item(self, page_id, title):
        title = self.clean(title)
        with self.store.connection() as db:
            self.require(db, 'pages', page_id)
            models.insert_item(db, page_id, title, self.now())
            self.touch_page(db, page_id)
        return page_id

    def edit_item(self, item_id, title, status):
        title = self.clean(title)
        if status not in STATUSES:
            raise MemoError(400, '请选择有效的状态。')
        with self.store.connection() as db:
            item = self.require(db, 'items', item_id)
            models.update_item(db, title, status, item_id)
            if item['title'] != title or item['status'] != status:
                self.touch_page(db, item['page_id'])
            if item['status'] != status:
                models.insert_update(db, item_id, f"状态：{STATUSES[item['status']]} → {STATUSES[status]}", self.now())
        return item['page_id']

    def add_update(self, item_id, body):
        body = self.clean(body, 5000)
        with self.store.connection() as db:
            item = self.require(db, 'items', item_id)
            models.insert_update(db, item_id, body, self.now())
            self.touch_page(db, item['page_id'])
        return item['page_id']

    def delete_item(self, item_id):
        with self.store.connection() as db:
            item = self.require(db, 'items', item_id)
            models.trash_item(db, self.now(), item_id)
            self.touch_page(db, item['page_id'])
        return item['page_id']


    def add_page_entry(self, page_id, body):
        body = self.clean(body, 5000)
        with self.store.connection() as db:
            self.require(db, 'pages', page_id)
            timestamp = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S.%f')
            models.insert_page_entry(db, page_id, body, timestamp)
            self.touch_page(db, page_id)
        return page_id
