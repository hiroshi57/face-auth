# 顔認証システム セットアップ手順

## 必要環境
- Python 3.10 以上
- PCのWebカメラ
- Windows PowerShell（または macOS/Linux ターミナル）

---

## インストール手順

### ステップ1: 仮想環境を作成する

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### ステップ2: 依存ライブラリをインストールする

```powershell
pip install fastapi uvicorn python-multipart opencv-python numpy
```

### ステップ3: InsightFace をインストールする（推奨・精度が大幅に向上）

```powershell
pip install insightface onnxruntime
```

InsightFace は初回起動時にモデルファイル（buffalo_l、約100MB）を自動ダウンロードします。  
インターネット接続が必要です。

InsightFace のインストールに失敗した場合は、OpenCV 簡易モードで動作します。  
ただし精度は大幅に低下するため、業務用途には InsightFace を強く推奨します。

---

## 起動方法

```powershell
cd face_auth
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

ブラウザで以下を開く:
```
http://localhost:8000
```

---

## テストの実行

```powershell
pip install pytest
python -m pytest tests/ -v
```

---

## 使い方

1. **ユーザー登録**  
   左パネルで名前を入力 → カメラに顔を向ける → 「撮影」→「登録する」

2. **顔認証**  
   右パネルでカメラに顔を向ける → 「認証する」  
   認証成功: 名前とスコアが表示される  
   認証失敗: 「一致するユーザーが見つかりません」と表示される

---

## 注意事項

- **照明**: 顔に均一に光が当たる環境で使用する。逆光は誤認識の原因になる
- **距離**: カメラから30〜60cm程度が最適
- **角度**: 正面を向いて撮影する。横顔では精度が落ちる
- **メガネ**: メガネ着用のまま登録し、認証時も同じ状態で使用する
- **マスク**: マスク着用時は認証精度が大幅に低下する（顔認証の制約）

---

## ファイル構成

```
face_auth/
├── main.py          # FastAPIサーバー
├── encoder.py       # 顔特徴量生成（InsightFace / OpenCV）
├── db.py            # SQLiteユーザー管理
├── matcher.py       # コサイン類似度による照合
├── face_auth.db     # 登録データ（起動後に自動生成）
├── static/
│   └── index.html   # ブラウザUI
└── tests/
    └── test_matcher.py
```

---

## 閾値の調整について

`matcher.py` の `THRESHOLD_INSIGHTFACE = 0.40` を変更することで感度を調整できます。

- 値を上げる（例: 0.50）→ 厳しくなる。他人を弾きやすくなるが、本人も弾かれやすくなる
- 値を下げる（例: 0.35）→ 緩くなる。本人を通しやすくなるが、他人も通りやすくなる

5人以上のユーザーで実測してから調整することを推奨します。
