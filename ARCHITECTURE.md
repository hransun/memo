# memo 代码阅读指南

这是一个本地、单用户的 FastAPI 应用。继续使用 Jinja2 和 SQLite，不引入 Django、ORM 或微服务。

## 四层各做什么

| 层 | 文件 | 职责 |
|---|---|---|
| View | `memo/views.py`、`templates/`、`static/` | 渲染中文页面、样式、主题和浏览器交互 |
| Controller | `memo/controllers.py` | 接收表单、调用业务功能、返回页面或重定向 |
| Service | `memo/services.py` | 校验、最多 5 个置顶、回收站恢复、图片处理及事务内的操作顺序 |
| Model | `memo/models.py` | SQLite 表结构、兼容升级、连接与具体 SQL 查询 |

`app.py` 是启动入口。`memo/application.py` 的 `create_app()` 把这些层装配起来，并配置静态文件、错误页面和请求保护。`memo/errors.py` 定义可由界面展示的业务错误。

调用顺序：

```text
浏览器表单
  → Controller：读入字段
  → Service：验证规则、组织操作
  → Model：执行 SQL
  → Controller：重定向到页面
  → View：显示更新后的结果
```

## 从“收藏”开始读代码

1. 在 `templates/index.html` 找到收藏表单，提交到 `/pages/{id}/favorite`。
2. 在 `memo/controllers.py` 看 `favorite_page()`：接收 ID 和收藏状态。
3. 在 `memo/services.py` 看 `favorite_page()`：验证状态及笔记是否存在。
4. 在 `memo/models.py` 看 `set_favorite()`：只负责写入 favorite 字段。
5. 重定向后，`home()` 重新读取并展示结果。

再看置顶：与收藏相似，但 Service 多了“最多 5 个”的判断，并以写事务避免并发超限。

## 修改什么就去哪里

- 配色、留白：`static/style.css`、`static/themes.css`。
- 黑红主题切换：`static/theme.js`，偏好只存在浏览器。
- 文案、按钮和布局：`templates/`。
- 表单接口：`memo/controllers.py`。
- 业务规则：`memo/services.py`。
- 数据字段或查询：`memo/models.py`，升级必须兼容已有数据库。

保持这些边界：Controller 不写 SQL，Service 不返回 HTTP Response，Model 不依赖 FastAPI，模板不读取数据库。

## 测试和数据

`tests/test_app.py` 覆盖真实表单请求、数据保存、搜索、回收站和恢复。`tests/test_layers.py` 验证实例隔离及不用 Web 服务器直接调用业务。

测试使用临时数据目录。日常数据仍在 `data/memo.db` 和 `data/uploads/`。分层不改变数据格式。启动方式仍为双击 `start.bat`。

## Git 版本与隐私

源码、模板、样式、依赖锁定文件及测试进入 Git。数据库、照片、OCR 结果、备份、虚拟环境、环境密钥文件，以及包含个人事项的本地导入脚本不进入 Git。

在本地查看版本：`git log --oneline`。比较版本：`git diff <旧提交> <新提交>`。代码回退不会恢复数据库；数据恢复使用独立备份。

## 笔记附件

`memo/attachments.py` 是 Service 层的文件处理模块：校验大小和基本文件格式、处理图片、分块保存音视频，不依赖 HTTP 或数据库。它不负责判断视频编码，也不做转码。

`page_entries` 新增 `attachment`、`media_type` 字段，启动时兼容升级，旧记录默认没有附件。Controller 把 UploadFile 的临时文件交给 Service，避免整段音视频读入内存。附件读取路由先检查笔记未进入回收站，再通过 FileResponse 提供 GET / HEAD、Range 分段响应；浏览器原生播放器使用 preload="none"。
