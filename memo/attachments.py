"""Local attachment validation and bounded file I/O; independent of HTTP and SQL."""
from io import BytesIO
from pathlib import Path
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError
from .errors import MemoError

MAX_PHOTO_BYTES = 20 * 1024 * 1024
MAX_MEDIA_BYTES = 200 * 1024 * 1024
COPY_CHUNK = 1024 * 1024
MEDIA_TYPES = {'.mp3': 'audio/mpeg', '.mp4': 'video/mp4'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}


def save_photo(uploads, content):
    if content is None:
        return ''
    if len(content) > MAX_PHOTO_BYTES:
        raise MemoError(400, '图片不能超过 20 MB。')
    filename = f'{uuid.uuid4().hex}.jpg'
    path = uploads / filename
    try:
        with Image.open(BytesIO(content)) as source:
            if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise MemoError(400, '请选择 JPG、PNG 或 WebP 图片。')
            if source.width * source.height > 40000000:
                raise MemoError(400, '图片尺寸过大，请先缩小后上传。')
            source.load()
            picture = ImageOps.exif_transpose(source).convert('RGB')
            picture.save(path, quality=95)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        path.unlink(missing_ok=True)
        raise MemoError(400, '无法读取图片，请选择有效的 JPG、PNG 或 WebP 文件。')
    return filename


def save_attachment(uploads, stream, original_name):
    extension = Path(original_name).suffix.lower()
    stream.seek(0)
    if extension in IMAGE_EXTENSIONS:
        return save_photo(uploads, stream.read(MAX_PHOTO_BYTES + 1)), 'image/jpeg'
    if extension not in MEDIA_TYPES:
        raise MemoError(400, '支持 JPG、PNG、WebP 图片，以及 MP3、MP4 文件。')
    # Basic file signature check, not codec validation or transcoding.
    header = stream.read(16)
    mp3_frame = (len(header) >= 4 and header[0] == 255 and header[1] & 0xE0 == 0xE0
                 and header[1] & 6 == 2 and header[2] >> 4 not in (0, 15)
                 and header[2] & 12 != 12)
    mp3_tag = len(header) >= 10 and header[:3] == b'ID3' and header[3] in (2, 3, 4)
    mp4 = len(header) >= 16 and header[4:8] == b'ftyp'
    if not ((extension == '.mp3' and (mp3_frame or mp3_tag)) or (extension == '.mp4' and mp4)):
        raise MemoError(400, '文件内容与格式不符，请选择有效的 MP3 或 MP4 文件。')
    stream.seek(0)
    filename = f'{uuid.uuid4().hex}{extension}'
    path = uploads / filename
    total = 0
    try:
        with path.open('xb') as target:
            while chunk := stream.read(COPY_CHUNK):
                total += len(chunk)
                if total > MAX_MEDIA_BYTES:
                    raise MemoError(400, '音频或视频不能超过 200 MB。')
                target.write(chunk)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return filename, MEDIA_TYPES[extension]
