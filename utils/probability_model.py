"""轻量、可序列化的二分类概率模型。"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize
from scipy.stats import rankdata


class BinaryLogit:
    def __init__(self, feature_names: list[str], l2: float = 1.0):
        self.feature_names = list(feature_names)
        self.l2 = float(l2)
        self.medians = np.zeros(len(feature_names))
        self.means = np.zeros(len(feature_names))
        self.stds = np.ones(len(feature_names))
        self.coef = np.zeros(len(feature_names) + 1)
        self.constant_probability: float | None = None

    def _matrix(self, frame, fit: bool = False) -> np.ndarray:
        # pandas Copy-on-Write 会返回只读视图；后续清洗需要自己的可写数组。
        x = frame[self.feature_names].to_numpy(dtype=float, copy=True)
        x[~np.isfinite(x)] = np.nan
        if fit:
            med = np.nanmedian(x, axis=0)
            med[~np.isfinite(med)] = 0
            self.medians = med
        x = np.where(np.isnan(x), self.medians, x)
        # 成交额等特征可能跨越多个数量级；极端值先截断，避免标准化和优化器溢出。
        x = np.clip(x, -1e12, 1e12)
        if fit:
            self.means = x.mean(axis=0)
            self.stds = x.std(axis=0)
            self.stds[self.stds < 1e-8] = 1
        scaled = (x - self.means) / self.stds
        return np.nan_to_num(np.clip(scaled, -20, 20), nan=0.0, posinf=20.0, neginf=-20.0)

    def fit(self, frame, target: str, sample_weight=None) -> "BinaryLogit":
        y = frame[target].to_numpy(dtype=float)
        x = self._matrix(frame, fit=True)
        if len(np.unique(y)) < 2:
            self.constant_probability = float(np.clip(y.mean() if len(y) else 0.5, 1e-4, 1 - 1e-4))
            return self
        self.constant_probability = None
        xb = np.column_stack([np.ones(len(x)), x])
        weight = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight, dtype=float)

        def objective(beta):
            # 当前 macOS Accelerate/NumPy 组合对有限矩阵的 matmul 会误报浮点异常；
            # 维度很小，逐元素归约结果等价且更稳定。
            linear = np.sum(xb * beta, axis=1)
            z = np.clip(np.nan_to_num(linear, nan=0.0, posinf=30.0, neginf=-30.0), -30, 30)
            p = 1 / (1 + np.exp(-z))
            loss = -(weight * (y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12))).mean()
            return loss + self.l2 * np.square(beta[1:]).sum() / max(len(y), 1)

        result = minimize(
            objective, np.zeros(xb.shape[1]), method="L-BFGS-B",
            bounds=[(-20.0, 20.0)] * xb.shape[1],
        )
        self.coef = (
            result.x if result.success and np.isfinite(result.x).all()
            else np.zeros(xb.shape[1])
        )
        return self

    def predict_proba(self, frame) -> np.ndarray:
        if self.constant_probability is not None:
            return np.full(len(frame), self.constant_probability)
        x = self._matrix(frame)
        linear = self.coef[0] + np.sum(x * self.coef[1:], axis=1)
        z = np.clip(
            np.nan_to_num(linear, nan=0.0, posinf=30.0, neginf=-30.0),
            -30, 30,
        )
        return 1 / (1 + np.exp(-z))

    def to_dict(self) -> dict:
        return {
            "kind": "binary_logit", "feature_names": self.feature_names, "l2": self.l2,
            "medians": self.medians.tolist(), "means": self.means.tolist(),
            "stds": self.stds.tolist(), "coef": self.coef.tolist(),
            "constant_probability": self.constant_probability,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "BinaryLogit":
        model = cls(payload["feature_names"], payload.get("l2", 1.0))
        for name in ("medians", "means", "stds", "coef"):
            values = np.asarray(payload[name], dtype=float)
            setattr(model, name, np.nan_to_num(values, nan=0.0, posinf=20.0, neginf=-20.0))
        model.stds[model.stds < 1e-8] = 1
        model.constant_probability = payload.get("constant_probability")
        return model


def binary_auc(y_true, probability) -> float | None:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probability, dtype=float)
    positives, negatives = int(y.sum()), int((1 - y).sum())
    if not positives or not negatives:
        return None
    ranks = rankdata(p)
    value = (ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives)
    return round(float(value), 4)


def probability_metrics(y_true, probability) -> dict:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(probability, dtype=float)
    if not len(y):
        return {"n": 0, "auc": None, "brier": None, "log_loss": None}
    return {
        "n": len(y),
        "auc": binary_auc(y, p),
        "brier": round(float(np.mean((p - y) ** 2)), 5),
        "log_loss": round(float(-np.mean(y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12))), 5),
    }
