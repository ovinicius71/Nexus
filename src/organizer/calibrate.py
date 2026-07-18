"""Calibrate the connection-suggestion threshold from the user's own feedback.

Every suggested connection stores its cosine similarity and whether the user
accepted or rejected it (``connections`` table). Treating accepted links as
positives and rejected ones as negatives, we pick the similarity threshold that
best separates them (maximum F1). This replaces the static ``SIMILARITY_THRESHOLD``
from ``.env`` with a value learned from how the user actually links notes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .db.repository import EntryRepository

logger = logging.getLogger(__name__)

# Key under which the learned threshold is persisted (app_settings table).
THRESHOLD_KEY = "similarity_threshold"


@dataclass
class CalibrationResult:
    """Outcome of a calibration run."""

    enough: bool
    n_pos: int
    n_neg: int
    threshold: float | None = None
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    message: str = ""


def _f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0


def calibrate(samples: list[tuple[float, bool]], min_samples: int = 10) -> CalibrationResult:
    """Find the F1-optimal threshold over labeled ``(similarity, accepted)`` samples.

    Needs at least ``min_samples`` decided samples with both classes present;
    otherwise returns a result flagged ``enough=False``.
    """
    positives = [s for s, accepted in samples if accepted]
    negatives = [s for s, accepted in samples if not accepted]
    n_pos, n_neg = len(positives), len(negatives)

    if len(samples) < min_samples or not positives or not negatives:
        return CalibrationResult(
            enough=False,
            n_pos=n_pos,
            n_neg=n_neg,
            message=(
                f"Preciso de mais feedback: {len(samples)} conexões decididas "
                f"({n_pos} aceitas / {n_neg} rejeitadas). "
                f"Mínimo {min_samples}, com pelo menos uma de cada."
            ),
        )

    # Sweep each observed similarity as a candidate threshold (predict link if
    # sim >= t). Tie-break on the higher threshold (more conservative linking).
    best: tuple[float, float] | None = None  # (f1, threshold)
    best_metrics = (0.0, 0.0, 0.0)  # precision, recall, f1
    for t in sorted({s for s, _ in samples}):
        tp = sum(1 for s in positives if s >= t)
        fp = sum(1 for s in negatives if s >= t)
        fn = sum(1 for s in positives if s < t)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = _f1(precision, recall)
        if best is None or (f1, t) > best:
            best = (f1, t)
            best_metrics = (precision, recall, f1)

    threshold = best[1]
    precision, recall, f1 = best_metrics
    return CalibrationResult(
        enough=True,
        n_pos=n_pos,
        n_neg=n_neg,
        threshold=threshold,
        precision=precision,
        recall=recall,
        f1=f1,
        message="Limiar calibrado a partir do seu feedback.",
    )


def run_calibration(
    session: Session, min_samples: int = 10, persist: bool = True
) -> CalibrationResult:
    """Gather feedback, calibrate and (if enough data) persist the new threshold."""
    repo = EntryRepository(session)
    result = calibrate(repo.list_connection_feedback(), min_samples=min_samples)
    if result.enough and persist and result.threshold is not None:
        repo.set_setting(THRESHOLD_KEY, f"{result.threshold:.3f}")
        logger.info("Similarity threshold calibrated to %.3f", result.threshold)
    return result


def main() -> None:
    from .config import get_settings
    from .db.engine import make_engine, make_session_factory
    from .logging_setup import setup_logging

    settings = get_settings()
    setup_logging(settings.log_level)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        result = run_calibration(session, min_samples=settings.calibration_min_samples)
    if result.enough:
        print(
            f"Limiar calibrado: {result.threshold:.3f} "
            f"(F1={result.f1:.2f}, precisão={result.precision:.2f}, recall={result.recall:.2f}; "
            f"{result.n_pos} aceitas / {result.n_neg} rejeitadas)"
        )
    else:
        print(result.message)


if __name__ == "__main__":
    main()
