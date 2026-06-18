"""
Statistical Anomaly Detection Module
=====================================

Applies a battery of statistical and machine-learning tests to MGNREGA
financial and attendance data to flag potential fraud or data fabrication.

Tests include:
    - Benford's Law first-digit analysis
    - Round-number bias detection
    - Isolation Forest multi-dimensional anomaly scoring
    - Z-score outlier flagging
    - Attendance clone detection (correlated muster rolls)
    - Time-series seasonal decomposition
    - Amount bunching near audit thresholds
    - Gini coefficient for expenditure inequality
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger
from scipy import stats as sp_stats
from sklearn.ensemble import IsolationForest
from statsmodels.tsa.seasonal import seasonal_decompose


class StatisticalAnomalyDetector:
    """Suite of statistical tests for MGNREGA fraud intelligence.

    The detector is stateless -- each method accepts data and returns
    results.  Call :meth:`run_full_statistical_audit` for a consolidated
    report across all tests.
    """

    # ------------------------------------------------------------------
    # Benford's Law
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_first_digits(data: List[float]) -> List[int]:
        """Return the leading non-zero digit for each value in *data*.

        Values <= 0 or NaN are silently dropped.
        """
        digits: List[int] = []
        for v in data:
            try:
                v_abs = abs(float(v))
            except (TypeError, ValueError):
                continue
            if v_abs == 0 or math.isnan(v_abs):
                continue
            # Strip to leading digit
            s = f"{v_abs:.10f}".lstrip("0").lstrip(".")
            if s:
                d = int(s[0])
                if 1 <= d <= 9:
                    digits.append(d)
        return digits

    def benfords_law_test(
        self,
        data: List[float],
        significance: float = 0.05,
    ) -> Dict[str, Any]:
        """Test whether the first-digit distribution conforms to Benford's Law.

        Benford's Law predicts that in naturally occurring datasets the
        leading digit *d* appears with probability ``log10(1 + 1/d)``.
        Significant deviation is a strong indicator of fabricated data.

        Parameters
        ----------
        data : list[float]
            Monetary amounts or measurements to test.
        significance : float
            P-value threshold for the chi-squared test.

        Returns
        -------
        dict
            ``chi2_statistic``  : float
            ``p_value``         : float
            ``is_anomalous``    : bool  (p < significance)
            ``expected_dist``   : dict  digit -> expected proportion
            ``observed_dist``   : dict  digit -> observed proportion
            ``per_digit_deviation`` : dict  digit -> (observed - expected)
            ``n_values``        : int
        """
        digits = self._extract_first_digits(data)
        n = len(digits)
        if n < 30:
            logger.warning(
                "Benford test: only {n} usable values (need >= 30 for reliable result).",
                n=n,
            )

        # Expected Benford distribution
        expected_prop = {d: math.log10(1 + 1 / d) for d in range(1, 10)}

        # Observed distribution
        counter = Counter(digits)
        observed_prop = {d: counter.get(d, 0) / max(n, 1) for d in range(1, 10)}

        # Chi-squared goodness-of-fit
        observed_counts = np.array([counter.get(d, 0) for d in range(1, 10)])
        expected_counts = np.array([expected_prop[d] * n for d in range(1, 10)])

        if n > 0:
            chi2, p_value = sp_stats.chisquare(observed_counts, expected_counts)
        else:
            chi2, p_value = 0.0, 1.0

        per_digit_dev = {
            d: round(observed_prop[d] - expected_prop[d], 4)
            for d in range(1, 10)
        }

        result = {
            "chi2_statistic": round(float(chi2), 4),
            "p_value": round(float(p_value), 6),
            "is_anomalous": float(p_value) < significance,
            "expected_dist": {d: round(v, 4) for d, v in expected_prop.items()},
            "observed_dist": {d: round(v, 4) for d, v in observed_prop.items()},
            "per_digit_deviation": per_digit_dev,
            "n_values": n,
        }
        logger.info(
            "Benford's test  |  chi2={c:.2f}  p={p:.4f}  anomalous={a}  n={n}",
            c=result["chi2_statistic"],
            p=result["p_value"],
            a=result["is_anomalous"],
            n=n,
        )
        return result

    # ------------------------------------------------------------------
    # Round-number bias
    # ------------------------------------------------------------------
    def detect_round_number_bias(
        self,
        amounts: List[float],
        round_suffixes: Optional[List[int]] = None,
        expected_rate: float = 0.10,
    ) -> Dict[str, Any]:
        """Flag if an abnormally high proportion of amounts are round numbers.

        Fabricated expenditure data frequently clusters on multiples of
        500 or 1000 because humans default to round figures.

        Parameters
        ----------
        amounts : list[float]
            Monetary values.
        round_suffixes : list[int] | None
            Endings to check.  Defaults to ``[0, 500, 1000, 5000, 10000]``.
        expected_rate : float
            Expected baseline proportion of round amounts in genuine data.

        Returns
        -------
        dict
            ``round_count``, ``total``, ``round_pct``, ``is_anomalous``,
            ``suffix_distribution``.
        """
        if round_suffixes is None:
            round_suffixes = [0, 500, 1000, 5000, 10000]

        suffix_counts: Dict[int, int] = {s: 0 for s in round_suffixes}
        total = len(amounts)
        round_count = 0

        for amt in amounts:
            try:
                val = int(round(float(amt)))
            except (TypeError, ValueError):
                continue
            for suffix in sorted(round_suffixes, reverse=True):
                if suffix == 0:
                    # Ends in 000
                    if val % 1000 == 0 and val != 0:
                        suffix_counts[0] += 1
                        round_count += 1
                        break
                elif val % suffix == 0:
                    suffix_counts[suffix] += 1
                    round_count += 1
                    break

        round_pct = round_count / max(total, 1)

        # Binomial test -- is the observed rate significantly higher?
        if total > 0:
            binom_p = float(
                sp_stats.binom_test(round_count, total, expected_rate, alternative="greater")
                if hasattr(sp_stats, "binom_test")
                else sp_stats.binomtest(round_count, total, expected_rate, alternative="greater").pvalue
            )
        else:
            binom_p = 1.0

        result = {
            "round_count": round_count,
            "total": total,
            "round_pct": round(round_pct, 4),
            "is_anomalous": binom_p < 0.05,
            "binom_p_value": round(binom_p, 6),
            "suffix_distribution": suffix_counts,
        }
        logger.info(
            "Round-number bias  |  {rc}/{t} ({pct:.1%})  anomalous={a}",
            rc=round_count,
            t=total,
            pct=round_pct,
            a=result["is_anomalous"],
        )
        return result

    # ------------------------------------------------------------------
    # Isolation Forest
    # ------------------------------------------------------------------
    def isolation_forest_anomaly(
        self,
        features_df: pd.DataFrame,
        contamination: float = 0.1,
        random_state: int = 42,
    ) -> pd.DataFrame:
        """Multi-dimensional anomaly detection using Isolation Forest.

        Each row represents a MGNREGA work / panchayat / worker and the
        columns are numeric features (e.g. total expenditure, days worked,
        material ratio, etc.).

        Parameters
        ----------
        features_df : pd.DataFrame
            Numeric feature matrix (NaN values are imputed with column median).
        contamination : float
            Expected proportion of anomalies.
        random_state : int
            Reproducibility seed.

        Returns
        -------
        pd.DataFrame
            Original data with two extra columns:
            ``anomaly_score`` (lower = more anomalous) and
            ``is_anomaly`` (bool).
        """
        df = features_df.copy()
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if not numeric_cols:
            raise ValueError("features_df must contain at least one numeric column.")

        # Impute NaNs with column median
        for col in numeric_cols:
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)

        model = IsolationForest(
            contamination=contamination,
            random_state=random_state,
            n_estimators=200,
            n_jobs=-1,
        )
        scores = model.decision_function(df[numeric_cols].values)
        labels = model.predict(df[numeric_cols].values)

        df["anomaly_score"] = scores
        df["is_anomaly"] = labels == -1

        n_anomalies = int(df["is_anomaly"].sum())
        logger.info(
            "Isolation Forest  |  features={f}  rows={r}  anomalies={a}",
            f=len(numeric_cols),
            r=len(df),
            a=n_anomalies,
        )
        return df

    # ------------------------------------------------------------------
    # Z-score
    # ------------------------------------------------------------------
    @staticmethod
    def zscore_anomaly(
        values: pd.Series,
        threshold: float = 3.0,
    ) -> pd.Series:
        """Flag statistical outliers based on Z-score.

        Parameters
        ----------
        values : pd.Series   Numeric series.
        threshold : float     Absolute Z-score cutoff.

        Returns
        -------
        pd.Series   Boolean mask (True = outlier).
        """
        mean = values.mean()
        std = values.std()
        if std == 0 or pd.isna(std):
            return pd.Series(False, index=values.index)
        zscores = (values - mean) / std
        outliers = zscores.abs() > threshold
        logger.info(
            "Z-score anomaly  |  threshold={t}  outliers={o}/{n}",
            t=threshold,
            o=int(outliers.sum()),
            n=len(values),
        )
        return outliers

    # ------------------------------------------------------------------
    # Attendance clone detection
    # ------------------------------------------------------------------
    def detect_attendance_correlation(
        self,
        attendance_matrix: np.ndarray,
        correlation_threshold: float = 0.90,
    ) -> List[Dict[str, Any]]:
        """Find groups of workers with near-identical attendance patterns.

        Workers whose attendance is >90% correlated are flagged as potential
        ghost/cloned entries (a common fraud where the same person is
        enrolled multiple times under different names).

        Parameters
        ----------
        attendance_matrix : np.ndarray
            Shape ``(n_workers, n_days)``.  Each cell is ``1`` (present)
            or ``0`` (absent).
        correlation_threshold : float
            Pearson correlation cutoff.

        Returns
        -------
        list[dict]
            Each dict: ``{"workers": (i, j), "correlation": float}``.
        """
        n_workers = attendance_matrix.shape[0]
        if n_workers < 2:
            return []

        # Pairwise Pearson correlation
        # Use numpy to avoid full pandas overhead for large matrices
        mat = attendance_matrix.astype(np.float64)
        # Standardise rows
        means = mat.mean(axis=1, keepdims=True)
        stds = mat.std(axis=1, keepdims=True)
        stds[stds == 0] = 1.0  # prevent division by zero
        normed = (mat - means) / stds
        corr_matrix = (normed @ normed.T) / mat.shape[1]

        pairs: List[Dict[str, Any]] = []
        for i in range(n_workers):
            for j in range(i + 1, n_workers):
                r = float(corr_matrix[i, j])
                if r >= correlation_threshold:
                    pairs.append({
                        "workers": (int(i), int(j)),
                        "correlation": round(r, 4),
                    })

        logger.info(
            "Attendance correlation  |  workers={w}  clone_pairs={p}",
            w=n_workers,
            p=len(pairs),
        )
        return pairs

    # ------------------------------------------------------------------
    # Seasonal decomposition
    # ------------------------------------------------------------------
    def seasonal_decomposition(
        self,
        time_series: pd.Series,
        period: Optional[int] = None,
        model: str = "additive",
    ) -> Dict[str, Any]:
        """Decompose a spending/enrollment time series to find anomalous spikes.

        Uses STL-style decomposition into trend, seasonal, and residual
        components.  Residual spikes beyond 2 standard deviations of the
        residual are flagged as anomalous.

        Parameters
        ----------
        time_series : pd.Series
            Time-indexed numeric series (e.g. monthly expenditure).
        period : int | None
            Seasonal period.  Auto-detected if None (defaults to 12 for
            monthly data).
        model : str
            ``"additive"`` or ``"multiplicative"``.

        Returns
        -------
        dict
            ``trend``, ``seasonal``, ``residual`` as pd.Series;
            ``anomalous_periods`` as list of index labels.
        """
        ts = time_series.dropna()
        if len(ts) < 4:
            logger.warning("Time series too short for decomposition ({n} points).", n=len(ts))
            return {
                "trend": pd.Series(dtype=float),
                "seasonal": pd.Series(dtype=float),
                "residual": pd.Series(dtype=float),
                "anomalous_periods": [],
            }

        if period is None:
            period = min(12, len(ts) // 2)
            period = max(2, period)

        decomposition = seasonal_decompose(ts, model=model, period=period)
        residual = decomposition.resid.dropna()

        # Flag residual spikes
        r_mean = residual.mean()
        r_std = residual.std()
        if r_std > 0:
            anomalous_mask = (residual - r_mean).abs() > 2 * r_std
            anomalous_periods = residual.index[anomalous_mask].tolist()
        else:
            anomalous_periods = []

        logger.info(
            "Seasonal decomposition  |  period={p}  anomalous_spikes={a}",
            p=period,
            a=len(anomalous_periods),
        )
        return {
            "trend": decomposition.trend,
            "seasonal": decomposition.seasonal,
            "residual": decomposition.resid,
            "anomalous_periods": anomalous_periods,
        }

    # ------------------------------------------------------------------
    # Amount bunching
    # ------------------------------------------------------------------
    def detect_bunching(
        self,
        amounts: List[float],
        threshold_amount: float,
        window_pct: float = 0.05,
    ) -> Dict[str, Any]:
        """Detect clustering of amounts just below an audit threshold.

        In India, works above certain value thresholds trigger additional
        scrutiny (e.g., technical sanctions above Rs 5 lakh).  Fraudsters
        split works to stay just below these limits.

        Parameters
        ----------
        amounts : list[float]
            Expenditure values.
        threshold_amount : float
            The audit threshold (e.g. 500000 for Rs 5 lakh).
        window_pct : float
            Fraction below the threshold defining the "bunching" window.
            Default 5% means we check the band from
            ``threshold * (1 - 0.05)`` to ``threshold``.

        Returns
        -------
        dict
            ``bunching_count``, ``expected_count``, ``ratio``,
            ``is_anomalous``, ``window_lower``, ``window_upper``.
        """
        lower = threshold_amount * (1 - window_pct)
        upper = threshold_amount

        total = len(amounts)
        bunching_count = sum(1 for a in amounts if lower <= float(a) < upper)

        # Under a uniform distribution in [0, threshold * 1.5], the expected
        # proportion falling in the window is window_pct * (threshold / (threshold*1.5))
        # We use a simpler expected baseline: window_pct of all values below threshold
        below_threshold = sum(1 for a in amounts if float(a) < upper)
        expected_count = below_threshold * window_pct if below_threshold > 0 else 0
        ratio = bunching_count / max(expected_count, 1)

        # Poisson test -- is the observed count significantly above expected?
        if expected_count > 0 and bunching_count > 0:
            poisson_p = float(1 - sp_stats.poisson.cdf(bunching_count - 1, expected_count))
        else:
            poisson_p = 1.0

        result = {
            "bunching_count": bunching_count,
            "expected_count": round(expected_count, 2),
            "ratio": round(ratio, 2),
            "is_anomalous": poisson_p < 0.05,
            "poisson_p_value": round(poisson_p, 6),
            "window_lower": round(lower, 2),
            "window_upper": round(upper, 2),
            "total_amounts": total,
        }
        logger.info(
            "Bunching detection  |  window=[{lo:.0f}, {hi:.0f})  "
            "count={bc}  expected={ec:.1f}  ratio={r:.2f}  anomalous={a}",
            lo=lower,
            hi=upper,
            bc=bunching_count,
            ec=expected_count,
            r=ratio,
            a=result["is_anomalous"],
        )
        return result

    # ------------------------------------------------------------------
    # Gini coefficient
    # ------------------------------------------------------------------
    @staticmethod
    def compute_gini_coefficient(expenditures: List[float]) -> float:
        """Compute the Gini coefficient for expenditure inequality.

        A Gini close to 1.0 means expenditure is highly concentrated in
        a few panchayats/blocks; close to 0.0 means equitable distribution.
        Extreme inequality can indicate favouritism or fund diversion.

        Parameters
        ----------
        expenditures : list[float]
            Non-negative values (one per panchayat / block).

        Returns
        -------
        float   Gini coefficient in [0, 1].
        """
        arr = np.array([float(x) for x in expenditures if float(x) >= 0], dtype=np.float64)
        if len(arr) == 0:
            return 0.0
        arr = np.sort(arr)
        n = len(arr)
        total = arr.sum()
        if total == 0:
            return 0.0
        index = np.arange(1, n + 1)
        gini = float((2 * (index * arr).sum()) / (n * total) - (n + 1) / n)
        gini = max(0.0, min(1.0, gini))
        logger.info("Gini coefficient  |  {g:.4f}  (n={n})", g=gini, n=n)
        return round(gini, 4)

    # ------------------------------------------------------------------
    # Full audit pipeline
    # ------------------------------------------------------------------
    def run_full_statistical_audit(
        self,
        district_data: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Run all statistical tests on a district dataset and return a
        comprehensive anomaly report.

        Expected columns in *district_data*:
            - ``amount``         : float  (expenditure per work)
            - ``total_workers``  : int
            - ``total_days``     : int
            - ``material_ratio`` : float  (material cost / total cost)
            - ``wage_per_day``   : float
            - ``panchayat_id``   : str

        Optional columns:
            - ``attendance_matrix`` : stored separately
            - ``monthly_expenditure`` : pd.Series for time-series tests

        Parameters
        ----------
        district_data : pd.DataFrame

        Returns
        -------
        dict   Keys: ``benfords``, ``round_number``, ``isolation_forest``,
               ``zscore_outliers``, ``bunching``, ``gini``, ``risk_score``.
        """
        report: Dict[str, Any] = {}

        # --- Benford's Law ---
        if "amount" in district_data.columns:
            amounts = district_data["amount"].dropna().tolist()
            report["benfords"] = self.benfords_law_test(amounts)
            report["round_number"] = self.detect_round_number_bias(amounts)
            report["bunching_5lakh"] = self.detect_bunching(
                amounts, threshold_amount=500_000,
            )
            report["bunching_10lakh"] = self.detect_bunching(
                amounts, threshold_amount=1_000_000,
            )
        else:
            logger.warning("Column 'amount' not found -- skipping monetary tests.")
            report["benfords"] = None
            report["round_number"] = None
            report["bunching_5lakh"] = None
            report["bunching_10lakh"] = None

        # --- Isolation Forest on numeric features ---
        numeric_cols = district_data.select_dtypes(include=[np.number]).columns.tolist()
        if len(numeric_cols) >= 2:
            report["isolation_forest_summary"] = {
                "n_anomalies": int(
                    self.isolation_forest_anomaly(
                        district_data[numeric_cols]
                    )["is_anomaly"].sum()
                ),
                "total_records": len(district_data),
            }
        else:
            report["isolation_forest_summary"] = None

        # --- Z-score on key fields ---
        zscore_results: Dict[str, int] = {}
        for col in ("amount", "total_workers", "total_days", "wage_per_day"):
            if col in district_data.columns:
                outliers = self.zscore_anomaly(district_data[col].dropna())
                zscore_results[col] = int(outliers.sum())
        report["zscore_outliers"] = zscore_results

        # --- Gini coefficient ---
        if "amount" in district_data.columns and "panchayat_id" in district_data.columns:
            panchayat_totals = (
                district_data.groupby("panchayat_id")["amount"].sum().tolist()
            )
            report["gini"] = self.compute_gini_coefficient(panchayat_totals)
        else:
            report["gini"] = None

        # --- Composite risk score (0-100) ---
        risk = 0.0
        weights_used = 0
        if report.get("benfords") and report["benfords"].get("is_anomalous"):
            risk += 25
            weights_used += 1
        if report.get("round_number") and report["round_number"].get("is_anomalous"):
            risk += 20
            weights_used += 1
        if report.get("bunching_5lakh") and report["bunching_5lakh"].get("is_anomalous"):
            risk += 20
            weights_used += 1
        if report.get("gini") is not None and report["gini"] > 0.6:
            risk += 15
            weights_used += 1
        if report.get("isolation_forest_summary"):
            anom_rate = (
                report["isolation_forest_summary"]["n_anomalies"]
                / max(report["isolation_forest_summary"]["total_records"], 1)
            )
            if anom_rate > 0.15:
                risk += 20
                weights_used += 1

        report["risk_score"] = round(min(risk, 100), 1)
        report["risk_level"] = (
            "CRITICAL" if risk >= 70 else
            "HIGH" if risk >= 50 else
            "MEDIUM" if risk >= 30 else
            "LOW"
        )

        logger.info(
            "Full statistical audit complete  |  risk_score={rs}  level={rl}",
            rs=report["risk_score"],
            rl=report["risk_level"],
        )
        return report
