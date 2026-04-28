# NEXT_TASKS.md — 次回セッション再開用タスク一覧

> 最終更新: 2026-04-24
> プロジェクト: face-auth

---

## 状態サマリー

現在のプロジェクト `face-auth` は基本機能が完成済み。

| 機能 | 状態 |
|------|------|
| FastAPI サーバー v3・InsightFace（buffalo_l）動作確認済み | ✅ |
| ヘルスチェック・レート制限・APIキー認証・設定永続化 | ✅ |
| 監査ログ・複数顔登録（最大5枚）・構造化ログ | ✅ |
| 部署フィールド（register / verify / 一覧 / JWT / Webhook） | ✅ |
| ユーザー一覧の名前・部署検索フィルター | ✅ |
| XSS対策（innerHTML → DOM操作・escapeHtml 関数） | ✅ |

---

## 次回着手候補タスク

現時点で明示的な残タスクはありません。

次回セッション開始時に以下を確認してください：
1. ユーザーから新規要件・バグ報告があれば着手
2. `main.py` / `db.py` のコードレビューが必要であれば実施
3. テスト拡充（`test_matcher.py` を参考に結合テスト追加）

---

## 起動コマンド

```bash
uvicorn main:app --port 8000
```

- UI: `http://localhost:8000/`
- API仕様: `http://localhost:8000/docs`
