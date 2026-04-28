"""
顔認証APIサーバー v3
エンドポイント:
  GET    /health            - ヘルスチェック
  POST   /register          - ユーザー登録（APIキー必須）
  POST   /users/{id}/face  - 顔画像追加登録（最大5枚・APIキー必須）
  POST   /verify            - 顔認証（JWT返却 + Webhook発火）
  GET    /users             - 登録ユーザー一覧（APIキー必須）
  GET    /users/{id}/photo  - 顔写真JPEG（APIキー必須）
  DELETE /users/{id}        - ユーザー削除（APIキー必須）
  GET    /config            - 現在の連携設定確認（APIキー必須）
  POST   /config            - Webhook URL・JWT秘密鍵の設定（APIキー必須）
  GET    /auth-logs         - 認証試行ログ一覧（APIキー必須）
  GET    /embed             - iframe埋め込み用ページ
  GET    /widget.js         - JS埋め込みウィジェット
"""

import os
import time
import hmac
import json
import base64
import hashlib
import logging
import logging.handlers
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional, List

import numpy as np
import cv2
from fastapi import FastAPI, Form, HTTPException, Request, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, HTMLResponse
from pydantic import BaseModel

from encoder import FaceEncoder
from db import Database
from matcher import FaceMatcher

# ── 機能9: 環境変数サポート ───────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv 未インストール時はスキップ

ADMIN_API_KEY    = os.environ.get("ADMIN_API_KEY", "")
JWT_SECRET_ENV   = os.environ.get("JWT_SECRET", "change-me-in-production")
JWT_EXPIRES_SEC  = int(os.environ.get("JWT_EXPIRES_SEC", "3600"))

# ── 機能8: 構造化ログ出力 ────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

_log_fmt = logging.Formatter(
    '{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("face_auth")
logger.setLevel(logging.INFO)

_ch = logging.StreamHandler()
_ch.setFormatter(_log_fmt)
logger.addHandler(_ch)

_fh = logging.handlers.RotatingFileHandler(
    str(LOG_DIR / "face_auth.log"), maxBytes=10_000_000, backupCount=5, encoding="utf-8"
)
_fh.setFormatter(_log_fmt)
logger.addHandler(_fh)

# ── 機能10: OpenAPIドキュメント整備 ──────────────────────────────────
app = FastAPI(
    title="顔認証API",
    version="3.0.0",
    description=(
        "InsightFace ベースの顔認証システム。"
        "JWT発行・Webhook通知・複数顔登録・監査ログ対応。\n\n"
        "**認証が必要なエンドポイント**: `X-API-Key` ヘッダーに管理者キーを付与してください。"
        "環境変数 `ADMIN_API_KEY` 未設定時は認証スキップ（開発モード）。"
    ),
    openapi_tags=[
        {"name": "auth",   "description": "顔認証（一般公開）"},
        {"name": "users",  "description": "ユーザー管理（X-API-Key 必須）"},
        {"name": "config", "description": "設定管理（X-API-Key 必須）"},
        {"name": "admin",  "description": "管理者向け（X-API-Key 必須）"},
        {"name": "system", "description": "システム情報・埋め込み"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Auth-Token"],
)

static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

encoder = FaceEncoder()
db      = Database()
matcher = FaceMatcher()

# ── 機能4: 設定の永続化（DB から復元）────────────────────────────────
_config = {
    "webhook_url":     db.get_config("webhook_url",     ""),
    "jwt_secret":      db.get_config("jwt_secret",      JWT_SECRET_ENV),
    "jwt_expires_sec": int(db.get_config("jwt_expires_sec", str(JWT_EXPIRES_SEC))),
}

# ── 機能2: レート制限 ────────────────────────────────────────────────
class _RateLimiter:
    """スライディングウィンドウ方式の IP ベースレート制限"""
    def __init__(self, max_calls: int, window_sec: int):
        self.max_calls  = max_calls
        self.window_sec = window_sec
        self._log: dict = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        dq  = self._log[key]
        while dq and dq[0] < now - self.window_sec:
            dq.popleft()
        if len(dq) >= self.max_calls:
            return False
        dq.append(now)
        return True


_verify_rl   = _RateLimiter(max_calls=5,  window_sec=60)
_register_rl = _RateLimiter(max_calls=10, window_sec=60)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _dep_rate_verify(request: Request):
    if not _verify_rl.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。1分後に再試行してください")


def _dep_rate_register(request: Request):
    if not _register_rl.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます。1分後に再試行してください")


# ── 機能3: APIキー認証 ────────────────────────────────────────────────
def _dep_api_key(x_api_key: str = Header(default="")):
    if not ADMIN_API_KEY:
        return  # 未設定時は開発モード（スキップ）
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="APIキーが無効です。X-API-Key ヘッダーを確認してください",
        )


# ── 機能7: 入力バリデーション ─────────────────────────────────────────
_MAX_NAME_LEN   = 64
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def _validate_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="名前を入力してください")
    if len(name) > _MAX_NAME_LEN:
        raise HTTPException(status_code=422, detail=f"名前は {_MAX_NAME_LEN} 文字以内にしてください")
    return name


def _validate_image_size(image_data: str):
    raw = image_data.split(",")[-1]
    if len(raw) * 3 // 4 > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="画像サイズが大きすぎます（上限 10MB）")


# ── 画像ユーティリティ ─────────────────────────────────────────────────

def decode_image(image_data: str) -> np.ndarray:
    _validate_image_size(image_data)
    if "," in image_data:
        image_data = image_data.split(",")[1]
    arr = np.frombuffer(base64.b64decode(image_data), np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="画像デコード失敗")
    return img


def crop_face(img: np.ndarray) -> np.ndarray:
    try:
        from insightface.app import FaceAnalysis
        _app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _app.prepare(ctx_id=0, det_size=(640, 640))
        faces = _app.get(img)
        if faces:
            f = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1]))
            x1, y1, x2, y2 = [int(v) for v in f.bbox]
            m = 20
            return img[max(0, y1-m):min(img.shape[0], y2+m),
                       max(0, x1-m):min(img.shape[1], x2+m)]
    except Exception:
        pass
    gray  = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    cas   = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cas.detectMultiScale(gray, 1.1, 5, minSize=(80, 80))
    if len(faces):
        x, y, w, h = max(faces, key=lambda r: r[2]*r[3])
        return img[y:y+h, x:x+w]
    return img


def img_to_jpeg(img: np.ndarray, size=(200, 200)) -> bytes:
    _, buf = cv2.imencode(".jpg", cv2.resize(img, size), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()


# ── JWT（依存ライブラリなし・軽量実装）──────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(payload: dict) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body   = _b64url(json.dumps(payload).encode())
    sig    = _b64url(
        hmac.new(
            _config["jwt_secret"].encode(),
            f"{header}.{body}".encode(),
            hashlib.sha256,
        ).digest()
    )
    return f"{header}.{body}.{sig}"


# ── Webhook ──────────────────────────────────────────────────────────

async def fire_webhook(payload: dict):
    url = _config.get("webhook_url", "").strip()
    if not url:
        return
    try:
        import urllib.request
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        logger.info(f"webhook sent url={url}")
    except Exception as e:
        logger.warning(f"webhook failed url={url} error={e}")


# ── 機能10: Pydanticレスポンスモデル ─────────────────────────────────

class RegisterResponse(BaseModel):
    user_id: int
    name: str
    department: str
    message: str

class AddFaceResponse(BaseModel):
    user_id: int
    face_count: int
    message: str

class VerifyResponse(BaseModel):
    user_id: int
    name: str
    department: str
    score: float
    token: str
    message: str

class UserItem(BaseModel):
    user_id: int
    name: str
    department: str
    created_at: Optional[str] = None
    photo_b64: Optional[str] = None

class ConfigResponse(BaseModel):
    webhook_url: str
    jwt_expires_sec: int
    jwt_secret_set: bool

class HealthResponse(BaseModel):
    status: str
    db: str
    encoder_mode: str
    version: str


# ── エンドポイント ────────────────────────────────────────────────────

@app.get("/", tags=["system"])
async def root():
    idx = static_path / "index.html"
    return FileResponse(str(idx)) if idx.exists() else {"status": "ok"}


# 機能1: ヘルスチェック
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="ヘルスチェック",
    description="サーバー・DB・エンコーダーの疎通確認。死活監視・ロードバランサーのヘルスプローブ用。",
)
async def health():
    try:
        db.get_all_users()
        db_status = "ok"
    except Exception as e:
        logger.error(f"health check db_error={e}")
        db_status = "error"
    status = "ok" if db_status == "ok" else "degraded"
    return HealthResponse(
        status=status,
        db=db_status,
        encoder_mode=encoder.mode,
        version="3.0.0",
    )


# 機能: ユーザー登録（機能2 レート制限 + 機能3 APIキー + 機能7 バリデーション）
@app.post(
    "/register",
    response_model=RegisterResponse,
    tags=["users"],
    summary="ユーザー登録",
    description="顔画像とともにユーザーを登録する。`X-API-Key` ヘッダーが必要（`ADMIN_API_KEY` 未設定時はスキップ）。",
    dependencies=[Depends(_dep_api_key), Depends(_dep_rate_register)],
)
async def register(name: str = Form(...), image: str = Form(...), department: str = Form("")):
    name       = _validate_name(name)
    department = department.strip()[:64]
    img        = decode_image(image)
    embedding  = encoder.encode(img)
    if embedding is None:
        raise HTTPException(status_code=422, detail="顔を検出できません。正面を向いて再撮影してください")
    photo   = img_to_jpeg(crop_face(img))
    user_id = db.register_user(name, embedding, photo, department)
    logger.info(f"register user_id={user_id} name={name} dept={department}")
    return RegisterResponse(user_id=user_id, name=name, department=department, message="登録完了")


# 機能6: 複数顔登録
@app.post(
    "/users/{user_id}/face",
    response_model=AddFaceResponse,
    tags=["users"],
    summary="顔画像を追加登録（最大5枚）",
    description="既存ユーザーに追加の顔画像を登録する。角度・照明違いを登録すると認証精度が向上する。",
    dependencies=[Depends(_dep_api_key)],
)
async def add_face(user_id: int, image: str = Form(...)):
    extra_count = db.get_face_count(user_id)
    if extra_count >= 5:
        raise HTTPException(status_code=400, detail="追加顔画像は最大5枚まで登録できます")
    img = decode_image(image)
    embedding = encoder.encode(img)
    if embedding is None:
        raise HTTPException(status_code=422, detail="顔を検出できません。正面を向いて再撮影してください")
    if not db.add_face(user_id, embedding):
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    total = extra_count + 2  # 主顔 + 追加分
    logger.info(f"add_face user_id={user_id} total_faces={total}")
    return AddFaceResponse(user_id=user_id, face_count=total, message="顔画像を追加しました")


# 機能: 顔認証（機能2 レート制限 + 機能5 監査ログ + 機能6 複数顔対応）
@app.post(
    "/verify",
    response_model=VerifyResponse,
    tags=["auth"],
    summary="顔認証",
    description="顔画像を送信し、登録ユーザーと照合する。認証成功時に JWT トークンと Webhook を返す。",
    dependencies=[Depends(_dep_rate_verify)],
)
async def verify(request: Request, image: str = Form(...)):
    ip  = _client_ip(request)
    img = decode_image(image)
    embedding = encoder.encode(img)

    if embedding is None:
        db.log_auth(success=False, ip=ip)
        raise HTTPException(status_code=422, detail="顔を検出できません")

    users = db.get_all_users()
    if not users:
        raise HTTPException(status_code=404, detail="登録ユーザーが存在しません")

    # 機能6: 全ユーザーの全顔埋め込みに対してマッチング
    expanded = [
        {"user_id": u["user_id"], "name": u["name"], "embedding": emb}
        for u in users
        for emb in u["embeddings"]
    ]
    result = matcher.find_best_match(embedding, expanded, mode=encoder.mode)

    if result is None:
        db.log_auth(success=False, ip=ip)
        logger.info(f"verify failed ip={ip}")
        raise HTTPException(status_code=401, detail="認証失敗：一致するユーザーが見つかりません")

    # 機能5: 監査ログ記録
    # 部署情報をユーザーリストから補完
    department = ""
    for u in users:
        if u["user_id"] == result["user_id"]:
            department = u.get("department", "")
            break

    db.log_auth(
        success=True, ip=ip,
        user_id=result["user_id"], name=result["name"], score=result["score"],
    )
    logger.info(f"verify success user_id={result['user_id']} score={result['score']:.4f} ip={ip}")

    now = int(time.time())
    token = make_jwt({
        "sub":        str(result["user_id"]),
        "name":       result["name"],
        "department": department,
        "score":      round(result["score"], 4),
        "iat":        now,
        "exp":        now + _config["jwt_expires_sec"],
    })

    await fire_webhook({
        "event":      "auth.success",
        "user_id":    result["user_id"],
        "name":       result["name"],
        "department": department,
        "score":      round(result["score"], 4),
        "timestamp":  now,
    })

    return VerifyResponse(
        user_id=result["user_id"],
        name=result["name"],
        department=department,
        score=round(result["score"], 4),
        token=token,
        message="認証成功",
    )


@app.get(
    "/users",
    response_model=List[UserItem],
    tags=["users"],
    summary="登録ユーザー一覧",
    dependencies=[Depends(_dep_api_key)],
)
async def list_users():
    result = []
    for u in db.get_all_users():
        photo_b64 = (
            "data:image/jpeg;base64," + base64.b64encode(u["photo"]).decode()
            if u["photo"] else None
        )
        result.append(UserItem(
            user_id=u["user_id"],
            name=u["name"],
            department=u.get("department", ""),
            created_at=u["created_at"],
            photo_b64=photo_b64,
        ))
    return result


@app.get(
    "/users/{user_id}/photo",
    tags=["users"],
    summary="顔写真取得",
    dependencies=[Depends(_dep_api_key)],
)
async def get_photo(user_id: int):
    u = db.get_user(user_id)
    if not u or not u["photo"]:
        raise HTTPException(status_code=404, detail="写真が見つかりません")
    return Response(content=u["photo"], media_type="image/jpeg")


@app.delete(
    "/users/{user_id}",
    tags=["users"],
    summary="ユーザー削除",
    dependencies=[Depends(_dep_api_key)],
)
async def delete_user(user_id: int):
    if not db.delete_user(user_id):
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")
    logger.info(f"delete user_id={user_id}")
    return {"message": f"ユーザー {user_id} を削除しました"}


@app.get(
    "/config",
    response_model=ConfigResponse,
    tags=["config"],
    summary="設定確認",
    dependencies=[Depends(_dep_api_key)],
)
async def get_config():
    return ConfigResponse(
        webhook_url=_config["webhook_url"],
        jwt_expires_sec=_config["jwt_expires_sec"],
        jwt_secret_set=_config["jwt_secret"] != "change-me-in-production",
    )


# 機能4: 設定の永続化
@app.post(
    "/config",
    tags=["config"],
    summary="設定変更（DB に永続保存）",
    dependencies=[Depends(_dep_api_key)],
)
async def set_config(
    webhook_url:    str = Form(""),
    jwt_secret:     str = Form(""),
    jwt_expires_sec: int = Form(3600),
):
    if webhook_url:
        _config["webhook_url"] = webhook_url
        db.set_config("webhook_url", webhook_url)
    if jwt_secret:
        _config["jwt_secret"] = jwt_secret
        db.set_config("jwt_secret", jwt_secret)
    if jwt_expires_sec:
        _config["jwt_expires_sec"] = jwt_expires_sec
        db.set_config("jwt_expires_sec", str(jwt_expires_sec))
    logger.info("config updated")
    return {"message": "設定を更新しました", "config": await get_config()}


# 機能5: 監査ログ参照
@app.get(
    "/auth-logs",
    tags=["admin"],
    summary="認証試行ログ一覧",
    description="全認証試行（成功・失敗含む）のログを返す。`limit` 最大 1000 件。",
    dependencies=[Depends(_dep_api_key)],
)
async def get_auth_logs(limit: int = 100, offset: int = 0):
    return db.get_auth_logs(limit=min(limit, 1000), offset=offset)


# ── 埋め込み用エンドポイント ───────────────────────────────────────────

@app.get("/embed", response_class=HTMLResponse, tags=["system"])
async def embed_page():
    """iframe埋め込み専用。認証成功時にpostMessageで親フレームに通知"""
    return HTMLResponse(EMBED_HTML)


@app.get("/widget.js", tags=["system"])
async def widget_js():
    """
    外部ページに1行で埋め込めるJSウィジェット
    使い方:
      <div id="face-auth-widget"></div>
      <script src="http://localhost:8000/widget.js"
              data-target="face-auth-widget"
              data-on-success="myCallback"></script>
    """
    return Response(content=WIDGET_JS, media_type="application/javascript")


# ── 埋め込みHTML（iframeモード）──────────────────────────────────────

EMBED_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #0b0c10; color: #e6e6f0;
         display: flex; flex-direction: column; align-items: center;
         justify-content: center; min-height: 100vh; padding: 20px; }
  .cam-wrap { position: relative; border-radius: 12px; overflow: hidden;
              background: #06070c; width: 300px; aspect-ratio: 4/3;
              border: 1px solid #22232f; margin-bottom: 16px; }
  video { width: 100%; height: 100%; object-fit: cover; display: block; }
  .oval { position: absolute; top:50%; left:50%; transform:translate(-50%,-50%);
          width:120px; height:150px; border:2px solid rgba(108,99,255,.5);
          border-radius:50%; pointer-events:none; }
  button { width: 300px; padding: 14px; border: none; border-radius: 8px;
           background: linear-gradient(135deg,#6c63ff,#3df0be);
           color: #0b0c10; font-weight: 700; font-size: 15px; cursor: pointer; }
  #msg { margin-top: 14px; font-size: 13px; color: #52536e; min-height: 20px; text-align: center; }
  .ok { color: #3df0be !important; } .ng { color: #f06060 !important; }
</style>
</head>
<body>
  <div class="cam-wrap">
    <video id="v" autoplay playsinline></video>
    <div class="oval"></div>
  </div>
  <button onclick="verify()">🔐 認証する</button>
  <div id="msg">カメラに顔を向けてボタンを押してください</div>
<script>
navigator.mediaDevices.getUserMedia({video:{width:640,height:480}})
  .then(s => document.getElementById('v').srcObject = s);

async function verify() {
  const v = document.getElementById('v');
  const c = document.createElement('canvas');
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext('2d').drawImage(v, 0, 0);
  const img = c.toDataURL('image/jpeg', 0.92);
  const msg = document.getElementById('msg');
  msg.textContent = '照合中...'; msg.className = '';
  try {
    const fd = new FormData(); fd.append('image', img);
    const res = await fetch('/verify', {method:'POST', body: fd});
    const d = await res.json();
    if (!res.ok) { msg.textContent = '❌ ' + d.detail; msg.className='ng'; return; }
    msg.textContent = '✓ ' + d.name; msg.className = 'ok';
    window.parent.postMessage({type:'face-auth-success', payload: d}, '*');
  } catch(e) { msg.textContent = '❌ ' + e.message; msg.className='ng'; }
}
</script>
</body>
</html>"""


# ── JS埋め込みウィジェット ────────────────────────────────────────────

WIDGET_JS = r"""
(function() {
  var script = document.currentScript;
  var targetId = script.getAttribute('data-target') || 'face-auth-widget';
  var callbackName = script.getAttribute('data-on-success');
  var apiBase = script.src.replace('/widget.js', '');

  var el = document.getElementById(targetId);
  if (!el) { console.error('[FaceAuth] target element not found:', targetId); return; }

  var style = document.createElement('style');
  style.textContent = `
    .fa-wrap { font-family:system-ui,sans-serif; background:#0b0c10; border-radius:14px;
               padding:20px; display:flex; flex-direction:column; align-items:center; gap:14px; }
    .fa-cam  { position:relative; border-radius:10px; overflow:hidden; background:#06070c;
               width:100%; max-width:320px; aspect-ratio:4/3; border:1px solid #22232f; }
    .fa-cam video { width:100%;height:100%;object-fit:cover;display:block; }
    .fa-oval { position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
               width:120px;height:150px;border:2px solid rgba(108,99,255,.5);
               border-radius:50%;pointer-events:none; }
    .fa-btn  { width:100%;max-width:320px;padding:13px;border:none;border-radius:8px;
               background:linear-gradient(135deg,#6c63ff,#3df0be);color:#0b0c10;
               font-weight:700;font-size:14px;cursor:pointer; }
    .fa-msg  { font-size:12px;color:#52536e;min-height:18px; }
    .fa-ok   { color:#3df0be!important; } .fa-ng { color:#f06060!important; }
  `;
  document.head.appendChild(style);

  el.innerHTML = `
    <div class="fa-wrap">
      <div class="fa-cam"><video id="_faV" autoplay playsinline></video><div class="fa-oval"></div></div>
      <button class="fa-btn" id="_faBtn">🔐 顔認証</button>
      <div class="fa-msg" id="_faMsg">カメラに顔を向けてボタンを押してください</div>
    </div>`;

  navigator.mediaDevices.getUserMedia({video:{width:640,height:480}})
    .then(function(s){ document.getElementById('_faV').srcObject = s; });

  document.getElementById('_faBtn').addEventListener('click', async function() {
    var v = document.getElementById('_faV');
    var c = document.createElement('canvas');
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext('2d').drawImage(v, 0, 0);
    var msg = document.getElementById('_faMsg');
    msg.textContent = '照合中...'; msg.className = 'fa-msg';
    try {
      var fd = new FormData(); fd.append('image', c.toDataURL('image/jpeg', 0.92));
      var res = await fetch(apiBase + '/verify', {method:'POST', body: fd});
      var d = await res.json();
      if (!res.ok) { msg.textContent = '❌ ' + d.detail; msg.className='fa-msg fa-ng'; return; }
      msg.textContent = '✓ ' + d.name; msg.className = 'fa-msg fa-ok';
      if (callbackName && typeof window[callbackName] === 'function') {
        window[callbackName](d);
      }
      el.dispatchEvent(new CustomEvent('face-auth-success', {detail: d, bubbles: true}));
    } catch(e) { msg.textContent = '❌ ' + e.message; msg.className='fa-msg fa-ng'; }
  });
})();
"""
