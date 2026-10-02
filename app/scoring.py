"""Rule-based feedback for a written practice answer.

Deliberately simple and explainable: the point of the repo is the product
flow and its tests, not the scorer.
"""
from __future__ import annotations

import re

MIN_WORDS = 25


def score_answer(answer: str, keywords: list[str]) -> tuple[int, list[str]]:
    words = re.findall(r"[a-zA-ZäöüÄÖÜß']+", answer.lower())
    tips = []
    score = 40

    hits = [k for k in keywords if k in words]
    score += 8 * len(hits)
    if len(hits) < 2:
        tips.append("Address the customer's concern more directly.")

    if "?" in answer:
        score += 10
    else:
        tips.append("Ask at least one open question.")

    if len(words) < MIN_WORDS:
        score -= 15
        tips.append(f"Give a fuller answer (at least {MIN_WORDS} words).")
    elif len(words) > 180:
        score -= 5
        tips.append("Keep it shorter; the customer will stop listening.")

    return max(0, min(100, score)), tips
