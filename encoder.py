"""
顔特徴量エンコーダー
InsightFaceを使って顔画像から512次元のベクトルを生成する
InsightFaceが使えない環境ではOpenCVのLBPHで簡易版にフォールバック
"""

import numpy as np
import cv2
from typing import Optional


class FaceEncoder:
    def __init__(self):
        self._model = None
        self._mode = None
        self._load_model()

    def _load_model(self):
        """InsightFaceを優先ロード、失敗時はOpenCV簡易モードへ"""
        try:
            import insightface
            from insightface.app import FaceAnalysis
            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=0, det_size=(640, 640))
            self._model = app
            self._mode = "insightface"
            print("[FaceEncoder] InsightFace モードで起動")
        except Exception as e:
            print(f"[FaceEncoder] InsightFace 利用不可 ({e})")
            self._load_opencv_fallback()

    def _load_opencv_fallback(self):
        """OpenCV + LBPH の簡易モード"""
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._model = cv2.CascadeClassifier(cascade_path)
        self._mode = "opencv"
        print("[FaceEncoder] OpenCV（簡易）モードで起動 — 精度は限定的です")

    def encode(self, img: np.ndarray) -> Optional[np.ndarray]:
        """
        画像から顔の特徴量ベクトルを返す
        顔が検出できない場合は None を返す
        """
        if self._mode == "insightface":
            return self._encode_insightface(img)
        return self._encode_opencv(img)

    def _encode_insightface(self, img: np.ndarray) -> Optional[np.ndarray]:
        faces = self._model.get(img)
        if not faces:
            return None
        # 最も大きい顔（画面中央に近い顔）を使う
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        embedding = face.embedding
        # L2正規化
        norm = np.linalg.norm(embedding)
        if norm == 0:
            return None
        return embedding / norm

    def _encode_opencv(self, img: np.ndarray) -> Optional[np.ndarray]:
        """
        OpenCV簡易版：顔領域をリサイズしてLBPHヒストグラムを特徴量とする
        InsightFaceと比べて精度は大幅に低い
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = self._model.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        if len(faces) == 0:
            return None
        # 最大の顔を使う
        x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
        face_roi = gray[y:y+h, x:x+w]
        face_resized = cv2.resize(face_roi, (64, 64))

        lbp = self._compute_lbph(face_resized)
        norm = np.linalg.norm(lbp)
        if norm == 0:
            return None
        return lbp / norm

    def _compute_lbph(self, gray: np.ndarray, radius: int = 1, neighbors: int = 8) -> np.ndarray:
        """LBP（局所二値パターン）ヒストグラムを計算"""
        h, w = gray.shape
        lbp = np.zeros_like(gray, dtype=np.uint8)
        for i in range(radius, h - radius):
            for j in range(radius, w - radius):
                center = gray[i, j]
                code = 0
                for k in range(neighbors):
                    angle = 2 * np.pi * k / neighbors
                    ni = int(round(i + radius * np.sin(angle)))
                    nj = int(round(j + radius * np.cos(angle)))
                    code |= (1 << k) if gray[ni, nj] >= center else 0
                lbp[i, j] = code
        hist, _ = np.histogram(lbp.ravel(), bins=256, range=(0, 256))
        return hist.astype(np.float32)

    @property
    def mode(self) -> str:
        return self._mode
