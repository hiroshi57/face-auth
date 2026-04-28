"""
顔照合モジュール
コサイン類似度で登録済みユーザーと比較し、最も近いユーザーを返す
閾値は InsightFace モード: 0.40、OpenCV 簡易モード: 0.80
"""

import numpy as np
from typing import List, Dict, Optional

# InsightFace（L2正規化済み）なら内積がそのままコサイン類似度
# 閾値は実測でチューニングが必要。0.40は一般的な出発点
THRESHOLD_INSIGHTFACE = 0.40
THRESHOLD_OPENCV = 0.80  # OpenCV簡易版は閾値を緩めに設定


class FaceMatcher:
    def __init__(self, threshold: Optional[float] = None):
        self._threshold = threshold  # None の場合はモード別デフォルトを使う

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def find_best_match(
        self,
        query: np.ndarray,
        users: List[Dict],
        mode: str = "insightface",
    ) -> Optional[Dict]:
        """
        登録ユーザー全員との類似度を計算し、最高スコアが閾値を超えたら返す
        """
        threshold = self._threshold or (
            THRESHOLD_INSIGHTFACE if mode == "insightface" else THRESHOLD_OPENCV
        )

        best_score = -1.0
        best_user = None

        for user in users:
            score = self.cosine_similarity(query, user["embedding"])
            if score > best_score:
                best_score = score
                best_user = user

        if best_score >= threshold and best_user is not None:
            return {
                "user_id": best_user["user_id"],
                "name": best_user["name"],
                "score": best_score,
            }
        return None
