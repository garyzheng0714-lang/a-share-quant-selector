"""轻量、可序列化的二分类概率模型。"""

from __future__ import annotations


import numpy as np
from scipy.optimize import minimize
from scipy.stats import rankdata


class ModelFitError(RuntimeError):
    """优化器没有产出可发布模型。"""


class BinaryLogit:
    def __init__(self, feature_names: list[str], l2: float = 1.0):
        self.feature_names = list(feature_names)
        self.l2 = float(l2)
        self.medians = np.zeros(len(feature_names))
        self.means = np.zeros(len(feature_names))
        self.stds = np.ones(len(feature_names))
        self.coef = np.zeros(len(feature_names) + 1)
        self.constant_probability: float | None = None
        self.training_diagnostics: dict = {
            "converged": False,
            "releaseable": False,
            "optimizer_status": "not_fitted",
        }

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
        return np.nan_to_num(
            np.clip(scaled, -20, 20), nan=0.0, posinf=20.0, neginf=-20.0
        )

    def fit(self, frame, target: str, sample_weight=None) -> "BinaryLogit":
        y = frame[target].to_numpy(dtype=float)
        x = self._matrix(frame, fit=True)
        finite_y = y[np.isfinite(y)]
        if len(finite_y) != len(y) or not len(y):
            raise ModelFitError("目标标签为空或包含非有限值")
        classes, counts = np.unique(y, return_counts=True)
        class_balance = {
            str(int(label)): int(count) for label, count in zip(classes, counts)
        }
        missing_rate = (
            float(
                frame[self.feature_names]
                .replace([np.inf, -np.inf], np.nan)
                .isna()
                .mean()
                .mean()
            )
            if self.feature_names
            else 0.0
        )
        if len(classes) < 2:
            self.constant_probability = float(
                np.clip(y.mean() if len(y) else 0.5, 1e-4, 1 - 1e-4)
            )
            self.training_diagnostics = {
                "converged": False,
                "releaseable": False,
                "optimizer_status": "single_class",
                "iterations": 0,
                "gradient_norm": None,
                "n_samples": int(len(y)),
                "class_balance": class_balance,
                "missing_rate": round(missing_rate, 6),
                "coefficient_l2_norm": 0.0,
            }
            return self
        self.constant_probability = None
        xb = np.column_stack([np.ones(len(x)), x])
        weight = (
            np.ones(len(y))
            if sample_weight is None
            else np.asarray(sample_weight, dtype=float)
        )

        def objective(beta):
            # 当前 macOS Accelerate/NumPy 组合对有限矩阵的 matmul 会误报浮点异常；
            # 维度很小，逐元素归约结果等价且更稳定。
            linear = np.sum(xb * beta, axis=1)
            z = np.clip(
                np.nan_to_num(linear, nan=0.0, posinf=30.0, neginf=-30.0), -30, 30
            )
            p = 1 / (1 + np.exp(-z))
            loss = -(
                weight * (y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12))
            ).mean()
            return loss + self.l2 * np.square(beta[1:]).sum() / max(len(y), 1)

        result = minimize(
            objective,
            np.zeros(xb.shape[1]),
            method="L-BFGS-B",
            bounds=[(-20.0, 20.0)] * xb.shape[1],
        )
        finite_coefficients = bool(np.isfinite(result.x).all())
        jac = getattr(result, "jac", None)
        gradient_norm = (
            float(np.linalg.norm(jac))
            if jac is not None and np.isfinite(jac).all()
            else None
        )
        self.training_diagnostics = {
            "converged": bool(result.success and finite_coefficients),
            "releaseable": bool(result.success and finite_coefficients),
            "optimizer_status": str(getattr(result, "message", "unknown")),
            "optimizer_status_code": int(getattr(result, "status", -1)),
            "iterations": int(getattr(result, "nit", 0)),
            "gradient_norm": gradient_norm,
            "objective": (
                float(result.fun)
                if np.isfinite(getattr(result, "fun", np.nan))
                else None
            ),
            "n_samples": int(len(y)),
            "class_balance": class_balance,
            "missing_rate": round(missing_rate, 6),
            "coefficient_l2_norm": (
                float(np.linalg.norm(result.x[1:])) if finite_coefficients else None
            ),
        }
        if not self.training_diagnostics["converged"]:
            raise ModelFitError(
                "逻辑回归优化失败: "
                f"status={self.training_diagnostics['optimizer_status_code']}, "
                f"message={self.training_diagnostics['optimizer_status']}"
            )
        self.coef = np.asarray(result.x, dtype=float)
        return self

    def predict_proba(self, frame) -> np.ndarray:
        if self.constant_probability is not None:
            return np.full(len(frame), self.constant_probability)
        x = self._matrix(frame)
        linear = self.coef[0] + np.sum(x * self.coef[1:], axis=1)
        z = np.clip(
            np.nan_to_num(linear, nan=0.0, posinf=30.0, neginf=-30.0),
            -30,
            30,
        )
        return 1 / (1 + np.exp(-z))

    def to_dict(self) -> dict:
        return {
            "kind": "binary_logit",
            "feature_names": self.feature_names,
            "l2": self.l2,
            "medians": self.medians.tolist(),
            "means": self.means.tolist(),
            "stds": self.stds.tolist(),
            "coef": self.coef.tolist(),
            "constant_probability": self.constant_probability,
            "training_diagnostics": self.training_diagnostics,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "BinaryLogit":
        model = cls(payload["feature_names"], payload.get("l2", 1.0))
        for name in ("medians", "means", "stds", "coef"):
            values = np.asarray(payload[name], dtype=float)
            setattr(
                model, name, np.nan_to_num(values, nan=0.0, posinf=20.0, neginf=-20.0)
            )
        model.stds[model.stds < 1e-8] = 1
        model.constant_probability = payload.get("constant_probability")
        model.training_diagnostics = payload.get("training_diagnostics") or {
            "converged": False,
            "releaseable": False,
            "optimizer_status": "legacy_artifact_without_diagnostics",
        }
        return model


def binary_auc(y_true, probability) -> float | None:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(probability, dtype=float)
    positives, negatives = int(y.sum()), int((1 - y).sum())
    if not positives or not negatives:
        return None
    ranks = rankdata(p)
    value = (ranks[y == 1].sum() - positives * (positives + 1) / 2) / (
        positives * negatives
    )
    return round(float(value), 4)


def probability_metrics(y_true, probability) -> dict:
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(probability, dtype=float)
    if not len(y):
        return {
            "n": 0,
            "auc": None,
            "brier": None,
            "log_loss": None,
            "expected_calibration_error": None,
            "calibration_curve": [],
        }
    p = np.clip(np.nan_to_num(p, nan=0.5, posinf=1.0, neginf=0.0), 0, 1)
    calibration_curve = []
    calibration_error = 0.0
    edges = np.linspace(0.0, 1.0, 11)
    bin_indexes = np.minimum(np.digitize(p, edges[1:-1], right=False), 9)
    for index in range(10):
        mask = bin_indexes == index
        if not mask.any():
            continue
        predicted = float(p[mask].mean())
        observed = float(y[mask].mean())
        count = int(mask.sum())
        calibration_error += abs(predicted - observed) * count / len(y)
        calibration_curve.append(
            {
                "lower": round(float(edges[index]), 2),
                "upper": round(float(edges[index + 1]), 2),
                "count": count,
                "mean_probability": round(predicted, 6),
                "observed_rate": round(observed, 6),
            }
        )
    return {
        "n": len(y),
        "auc": binary_auc(y, p),
        "brier": round(float(np.mean((p - y) ** 2)), 5),
        "log_loss": round(
            float(-np.mean(y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12))), 5
        ),
        "expected_calibration_error": round(calibration_error, 6),
        "calibration_curve": calibration_curve,
    }


def population_stability_index(
    reference,
    current,
    feature_names: list[str],
    *,
    bins: int = 10,
) -> dict:
    """用训练集分位点比较校准窗特征分布，同时纳入缺失桶。"""
    epsilon = 1e-6
    features = {}
    for name in feature_names:
        reference_values = np.asarray(reference[name], dtype=float)
        current_values = np.asarray(current[name], dtype=float)
        reference_finite = reference_values[np.isfinite(reference_values)]
        current_finite = current_values[np.isfinite(current_values)]
        if reference_finite.size:
            quantiles = np.quantile(
                reference_finite, np.linspace(0, 1, max(int(bins), 2) + 1)
            )
            inner = np.unique(quantiles[1:-1])
        else:
            inner = np.array([], dtype=float)
        boundaries = np.concatenate(([-np.inf], inner, [np.inf]))
        reference_counts = np.histogram(reference_finite, bins=boundaries)[0].astype(
            float
        )
        current_counts = np.histogram(current_finite, bins=boundaries)[0].astype(float)
        reference_counts = np.append(
            reference_counts, len(reference_values) - len(reference_finite)
        )
        current_counts = np.append(
            current_counts, len(current_values) - len(current_finite)
        )
        reference_ratio = (reference_counts + epsilon) / (
            reference_counts.sum() + epsilon * len(reference_counts)
        )
        current_ratio = (current_counts + epsilon) / (
            current_counts.sum() + epsilon * len(current_counts)
        )
        psi = float(
            np.sum(
                (current_ratio - reference_ratio)
                * np.log(current_ratio / reference_ratio)
            )
        )
        features[name] = {
            "psi": round(psi, 6),
            "status": "stable"
            if psi < 0.10
            else "monitor"
            if psi < 0.25
            else "drifted",
            "reference_missing_rate": round(
                1 - len(reference_finite) / max(len(reference_values), 1), 6
            ),
            "current_missing_rate": round(
                1 - len(current_finite) / max(len(current_values), 1), 6
            ),
        }
    max_psi = max((float(item["psi"]) for item in features.values()), default=0.0)
    return {
        "method": "training_quantile_psi_with_missing_bucket_v1",
        "features": features,
        "max_psi": round(float(max_psi), 6),
        "releaseable": max_psi < 0.25,
    }
