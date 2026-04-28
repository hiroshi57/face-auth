"""
RAG+CAG Engine
- CAG: Claude API Prompt Caching でナレッジを常時キャッシュ
- RAG: キーワードマッチで関連セクションを絞り込み
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Windows での UTF-8 出力を強制
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import anthropic

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048
TOP_K = 3  # RAG で絞り込む上位セクション数


class RAGCAGEngine:
    def __init__(self, project: str):
        self.client = anthropic.Anthropic()
        self.project = project
        self.knowledge_dir = KNOWLEDGE_DIR / project
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)

    # ── ナレッジ読み込み ──────────────────────────────────────────

    def _load_docs(self) -> list[dict]:
        docs = []
        for md_file in sorted(self.knowledge_dir.glob("*.md")):
            docs.append({"name": md_file.stem, "content": md_file.read_text(encoding="utf-8")})
        return docs

    # ── RAG: キーワードで関連セクションを絞り込む ────────────────

    def _retrieve(self, query: str, docs: list[dict]) -> list[dict]:
        keywords = set(re.sub(r"[^\w\s]", "", query).lower().split())
        scored = []
        for doc in docs:
            text = doc["content"].lower()
            score = sum(1 for kw in keywords if kw in text)
            scored.append((score, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [doc for _, doc in scored[:TOP_K] if _ > 0] or docs[:TOP_K]

    # ── CAG: Prompt Caching でナレッジをキャッシュ ───────────────

    def _build_system(self, docs: list[dict]) -> list[dict]:
        if not docs:
            return [{"type": "text", "text": "あなたは案件サポートアシスタントです。"}]

        blocks = []
        for i, doc in enumerate(docs):
            block: dict = {
                "type": "text",
                "text": f"## {doc['name']}\n\n{doc['content']}",
            }
            # 最後のブロックにキャッシュコントロールを付与（全体をキャッシュ）
            if i == len(docs) - 1:
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        return blocks

    # ── クエリ実行 ────────────────────────────────────────────────

    def query(self, question: str) -> str:
        all_docs = self._load_docs()
        retrieved = self._retrieve(question, all_docs)
        system = self._build_system(all_docs)  # CAG: 全件キャッシュ

        # RAG: 絞り込み結果を user メッセージに付加
        rag_context = ""
        if retrieved and retrieved != all_docs:
            rag_context = "\n\n### 参照ドキュメント（関連度上位）\n"
            for doc in retrieved:
                rag_context += f"\n**{doc['name']}**\n{doc['content'][:800]}\n"

        messages = [{"role": "user", "content": question + rag_context}]

        response = self.client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=messages,
        )
        return response.content[0].text

    # ── ナレッジ保存 ──────────────────────────────────────────────

    def save_knowledge(self, title: str, content: str) -> Path:
        safe_title = re.sub(r"[^\w\-]", "_", title)
        path = self.knowledge_dir / f"{safe_title}.md"
        path.write_text(f"# {title}\n\n{content}", encoding="utf-8")
        return path

    def list_knowledge(self) -> list[str]:
        return [f.name for f in sorted(self.knowledge_dir.glob("*.md"))]

    # ── インタラクティブモード ─────────────────────────────────────

    def run_interactive(self):
        docs = self._load_docs()
        total_chars = sum(len(d["content"]) for d in docs)
        print(f"\n🚀 RAG+CAG エンジン起動")
        print(f"{'─' * 30}")
        print(f"案件    : {self.project}")
        print(f"ナレッジ: {len(docs)} 件 ({total_chars:,} 文字)")
        print(f"モデル  : {MODEL}")
        print(f"キャッシュ: 有効（Prompt Caching）")
        print(f"\n質問を入力してください（終了: exit）\n")

        while True:
            try:
                user_input = input("あなた> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n終了します。")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "終了"):
                print("終了します。")
                break

            # ナレッジ操作コマンド
            if "ナレッジ一覧" in user_input:
                files = self.list_knowledge()
                print(f"📚 ナレッジ一覧 ({len(files)} 件):")
                for f in files:
                    print(f"  - {f}")
                continue

            if "覚えておいて" in user_input or "ナレッジを追加" in user_input:
                title = input("タイトル> ").strip()
                print("内容を入力してください（空行2回で終了）:")
                lines, blank = [], 0
                while blank < 2:
                    line = input()
                    if line == "":
                        blank += 1
                    else:
                        blank = 0
                    lines.append(line)
                content = "\n".join(lines).strip()
                path = self.save_knowledge(title, content)
                print(f"✅ 保存しました: {path.name}\n")
                continue

            # 通常クエリ
            print("考え中...", end="\r")
            answer = self.query(user_input)
            print(f"AI> {answer}\n")


def main():
    parser = argparse.ArgumentParser(description="RAG+CAG Engine")
    parser.add_argument("--project", required=True, help="案件名（ディレクトリ名）")
    parser.add_argument("--mode", default="interactive", choices=["interactive", "query"])
    parser.add_argument("--query", help="クエリ文字列（--mode query 時）")
    args = parser.parse_args()

    engine = RAGCAGEngine(args.project)

    if args.mode == "query":
        if not args.query:
            parser.error("--query が必要です")
        print(engine.query(args.query))
    else:
        engine.run_interactive()


if __name__ == "__main__":
    main()
