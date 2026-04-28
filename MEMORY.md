# MEMORY.md — AIメモ帳

> このファイルはClaude Codeが学んだことを蓄積するメモ帳です。
> セッションをまたいで参照されます。

---

## セッション管理

| キー | 値 |
|------|-----|
| `update_checker_last_run` | 2026-04-28 (セッション開始時) |

---

## アップデート記録（2026-04-28確認分）

### Claude Code
- **バージョン**: v2.1.119（変更内容の日付記載なし）

### API（platform.claude.com）
- **2026-04-24**: Rate Limits API リリース — 管理者が組織のレート制限をプログラムでクエリ可能
- **2026-04-23**: Managed Agents Memory パブリックベータ — `managed-agents-2026-04-01` ヘッダーで会話横断メモリが利用可能
- **2026-04-20**: Claude Haiku 3（`claude-3-haiku-20240307`）削除 → リクエストはエラー
- **2026-04-16**: Claude Opus 4.7 リリース。**Opus 4.6との破壊的変更あり**（マイグレーションガイド参照必須）
- **2026-04-14**: Sonnet 4 / Opus 4 廃止発表 → 2026-06-15 に削除予定
- **2026-04-09**: advisor tool パブリックベータ公開

### Claude Apps
- **2026-04-17**: Claude Design リリース（デザイン・プロトタイプ・スライド生成）— 前回確認時が最新
- **2026-04-09**: Claude Cowork 一般提供（macOS/Windows、Analytics API統合）
- Opus 4 / 4.1 はモデルセレクターから削除済み

---

## プロジェクト固有メモ

### AI-info-dashboard（C:\Users\hiroshi_takizawa\AI-info-dashboard）

**2026-04-23 実施済み**

| 機能 | 状態 | 詳細 |
|------|------|------|
| 🔧 ハーネス設計ページ | ✅ 完了 | サイドバーに追加、3本柱カード・L1〜L5レイヤー図・マルチエージェント階層図・AIエンジニアリング変遷 |
| 🏢 企業詳細モーダル | ✅ 完了 | 業界マップのトップ企業クリックでモーダル表示。5タブ（概要/財務/セグメント/ニュース/人物）。主要7社のデータ内蔵、その他はAI取得ボタン |
| 📊 競合比較表 | ✅ 削除済み | ニュース系サブタブ・page-matrixすべて除去 |
| 📁 フォルダ整理 | ✅ 完了 | PNG7枚→docs/assets/、templates/→reports/ |

**内蔵データ企業（CO_DATA）**
- トヨタ自動車、ソニーグループ、富士通、NTTデータ、三菱UFJフィナンシャルG、イオングループ、武田薬品工業

**次フェーズ候補（未着手）**
- GA4 / Search Console 実API接続
- プロンプト・キーワード選択UI

**企業詳細モーダルのタブ構成（6タブ）**
概要 / 財務 / セグメント / ニュース / 人物 / 言及数

言及数タブ: 収集済み記事をスキャンし「総言及数・ソース別内訳・直近7日トレンド・該当記事一覧」を表示。CO_DATA未登録企業でも表示可。

### seo-managed-agents（C:\Users\hiroshi_takizawa\seo-managed-agents）

- フォルダ整理済み（2026-04-23）
- AI-info-dashboard は別プロジェクト（上記参照）

### face-auth（C:\Users\hiroshi_takizawa\face-auth）

**2026-04-23 実施済み**

| 機能 | 状態 |
|------|------|
| FastAPI サーバー v3・InsightFace（buffalo_l）動作確認済み | ✅ |
| ヘルスチェック・レート制限・APIキー認証・設定永続化 | ✅ |
| 監査ログ・複数顔登録（最大5枚）・構造化ログ | ✅ |
| 部署フィールド（register / verify / 一覧 / JWT / Webhook） | ✅ |
| ユーザー一覧の名前・部署検索フィルター | ✅ |
| XSS対策（innerHTML → DOM操作・escapeHtml 関数） | ✅ |

**起動コマンド**: `uvicorn main:app --port 8000`
**UI**: `http://localhost:8000/`　**API仕様**: `http://localhost:8000/docs`

---

## 学習パターン

（未記録）
