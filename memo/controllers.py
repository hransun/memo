"""Controller layer: HTTP inputs, service calls, redirects and page rendering."""
from fastapi import APIRouter, Request, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .attachments import MAX_PHOTO_BYTES
from .views import render

router = APIRouter()


def service(request):
    return request.app.state.service


def redirect(page_id=None):
    return RedirectResponse(f'/?page={page_id}&saved=1' if page_id else '/?saved=1', status_code=303)


@router.get('/')
def home(request: Request, page: int | None = None, q: str = Query('', max_length=200), tag: str = Query('', max_length=30), view: str = Query('recent', max_length=20)):
    return render(request, 'index.html', service(request).home(page, q, tag, view))


async def read_photo(photo):
    content = None
    if photo is not None:
        try:
            if photo.filename:
                content = await photo.read(MAX_PHOTO_BYTES + 1)
        finally:
            await photo.close()
    return content


@router.post('/pages')
async def create_page(request: Request, title: str = Form(...), photo: UploadFile | None = File(None), tags: str = Form('')):
    content = await read_photo(photo)
    page_id = await run_in_threadpool(service(request).create_page, title, content, tags)
    return redirect(page_id)


@router.get('/pages/{page_id}/photo')
def photo(request: Request, page_id: int):
    return FileResponse(service(request).photo(page_id), media_type='image/jpeg')


@router.get('/trash')
def trash(request: Request):
    return render(request, 'trash.html', service(request).trash())


@router.post('/pages/{page_id}/delete')
def delete_page(request: Request, page_id: int):
    service(request).delete_page(page_id)
    return redirect()


@router.post('/pages/{page_id}/edit')
def edit_page(request: Request, page_id: int, title: str = Form(...), tags: str = Form("")):
    service(request).edit_page(page_id, title, tags)
    return redirect(page_id)


@router.post('/pages/{page_id}/pin')
def pin_page(request: Request, page_id: int, pinned: int = Form(...)):
    service(request).pin_page(page_id, pinned)
    return redirect(page_id)


@router.post('/pages/{page_id}/favorite')
def favorite_page(request: Request, page_id: int, favorite: int = Form(...)):
    service(request).favorite_page(page_id, favorite)
    return redirect(page_id)


@router.post('/pages/{page_id}/items')
def add_item(request: Request, page_id: int, title: str = Form(...)):
    service(request).add_item(page_id, title)
    return redirect(page_id)


@router.post('/items/{item_id}/edit')
def edit_item(request: Request, item_id: int, title: str = Form(...), status: str = Form(...)):
    result = service(request).edit_item(item_id, title, status)
    return redirect(result)


@router.post('/items/{item_id}/updates')
def add_update(request: Request, item_id: int, body: str = Form(...)):
    result = service(request).add_update(item_id, body)
    return redirect(result)


@router.post('/items/{item_id}/delete')
def delete_item(request: Request, item_id: int):
    result = service(request).delete_item(item_id)
    return redirect(result)


@router.post('/trash/{kind}/{record_id}/restore')
def restore_record(request: Request, kind: str, record_id: int):
    result = service(request).restore_record(kind, record_id)
    return redirect(result)


@router.post('/trash/{kind}/{record_id}/purge')
def purge_record(request: Request, kind: str, record_id: int):
    service(request).purge_record(kind, record_id)
    return RedirectResponse('/trash?saved=1', status_code=303)


@router.post('/pages/{page_id}/entries')
async def add_page_entry(request: Request, page_id: int, body: str = Form(''), attachment: UploadFile | None = File(None)):
    try:
        # UploadFile spools large uploads to disk. Do not read the whole media into RAM.
        stream = attachment.file if attachment and attachment.filename else None
        name = attachment.filename if stream else ''
        await run_in_threadpool(service(request).add_page_entry, page_id, body, stream, name)
    finally:
        if attachment is not None:
            await attachment.close()
    return redirect(page_id)


@router.api_route('/entries/{entry_id}/attachment', methods=['GET', 'HEAD'])
def entry_attachment(request: Request, entry_id: int):
    path, media_type = service(request).entry_attachment(entry_id)
    # Starlette serves bounded chunks and handles Range / If-Range / 206 / 416.
    return FileResponse(path, media_type=media_type)
