"""
テスト: encoder.py と matcher.py の単体テスト
実行: python -m pytest tests/ -v
"""

import numpy as np
import pytest
from matcher import FaceMatcher


class TestFaceMatcher:
    def setup_method(self):
        self.matcher = FaceMatcher()

    def _make_vec(self, values):
        v = np.array(values, dtype=np.float32)
        return v / np.linalg.norm(v)

    def test_同一ベクトルは類似度1(self):
        v = self._make_vec([1, 2, 3, 4])
        score = self.matcher.cosine_similarity(v, v)
        assert abs(score - 1.0) < 1e-5

    def test_直交ベクトルは類似度0(self):
        a = self._make_vec([1, 0, 0])
        b = self._make_vec([0, 1, 0])
        score = self.matcher.cosine_similarity(a, b)
        assert abs(score) < 1e-5

    def test_正しいユーザーが返る(self):
        user_vec = self._make_vec([1, 2, 3, 4])
        # ほぼ同じベクトルをクエリとして使う
        query = self._make_vec([1.01, 1.99, 3.01, 3.99])
        users = [
            {"user_id": 1, "name": "Alice", "embedding": user_vec},
            {"user_id": 2, "name": "Bob",   "embedding": self._make_vec([10, 0, 0, 0])},
        ]
        result = self.matcher.find_best_match(query, users, mode="insightface")
        assert result is not None
        assert result["name"] == "Alice"
        assert result["score"] >= 0.40

    def test_閾値未満は認証失敗(self):
        query = self._make_vec([1, 0, 0, 0])
        users = [
            {"user_id": 1, "name": "Alice", "embedding": self._make_vec([0, 1, 0, 0])},
        ]
        # 直交なのでコサイン類似度 ≒ 0 → 閾値未満
        result = self.matcher.find_best_match(query, users, mode="insightface")
        assert result is None

    def test_ユーザーなしはNone(self):
        query = self._make_vec([1, 2, 3])
        result = self.matcher.find_best_match(query, [], mode="insightface")
        assert result is None

    def test_ゼロベクトルは類似度0(self):
        zero = np.zeros(4, dtype=np.float32)
        v = self._make_vec([1, 2, 3, 4])
        score = self.matcher.cosine_similarity(zero, v)
        assert score == 0.0
