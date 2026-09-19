"""Composition root: configure and assemble the application in one place."""
from pathlib import Path
import os
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .controllers import router
from .errors import MemoError
from .models import Store
from .services import MemoService
from .views import render

ROOT = Path(__file__).resolve().parents[1]


async def protect_local_app(request: Request, call_next):
    if request.method == 'POST':
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return HTMLResponse('不允许来自其他网站的操作。', status_code=403)
        token = request.query_params.get('token', '')
        if not secrets.compare_digest(token, request.app.state.token):
            return HTMLResponse('页面已过期，请刷新页面后重试。', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; form-action 'self'; frame-ancestors 'none'"
    return response


async def expected_error(request, exc):
    message = exc.message if isinstance(exc, MemoError) else exc.detail
    return render(request, 'error.html', {'message': message}, status_code=exc.status_code)


def create_app(data_dir=None):
    """Separate instances can use separate data directories (including in tests)."""
    data = Path(data_dir or os.environ.get('MEMO_DATA_DIR', ROOT / 'data')).resolve()
    store = Store(data / 'memo.db')
    store.initialize()
    app = FastAPI(title='memo', docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.service = MemoService(store, data / 'uploads')
    app.state.token = secrets.token_urlsafe(32)
    app.state.templates = Jinja2Templates(directory=ROOT / 'templates')
    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
    app.middleware('http')(protect_local_app)
    app.add_exception_handler(MemoError, expected_error)
    app.add_exception_handler(HTTPException, expected_error)
    app.include_router(router)
    return app
