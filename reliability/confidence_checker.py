"""
PawPal+ Confidence Checker
Reliability layer that scores AI-generated care suggestions before they are displayed.

Returns a confidence report used by the advisor's EVALUATE + REFLECT steps
to decide whether to show suggestions automatically or flag them for human review.
"""

from typing import Dict, List, Any


def check_confidence(
    suggestions: List[Dict[str, str]],
    pets: List[Any],
    issues: List[Dict[str, str]],
) -> Dict[str, object]:
    """
    Score the reliability of AI-generated suggestions.

    Returns a dict with:
      - score: int 0–100
      - level: "low" | "medium" | "high"
      - reasons: list of strings explaining the score
      - should_display: bool — True if suggestions are safe to show automatically
    """

    if not suggestions:
        return {
            "score": 0,
            "level": "low",
            "reasons": ["No suggestions were generated."],
            "should_display": False,
        }

    reasons: List[str] = []
    score = 100

    pet_names = {p.name for p in pets}

    # ----------------------------
    # Suggestion quality checks
    # ----------------------------
    unknown_pets = [
        s["pet_name"]
        for s in suggestions
        if s.get("pet_name") and s["pet_name"] not in pet_names
    ]
    if unknown_pets:
        # Scale penalty by the fraction of hallucinated suggestions.
        # If all suggestions reference non-existent pets, score drops below 40 (blocks display).
        hallucinated_fraction = len(unknown_pets) / len(suggestions)
        penalty = int(70 * hallucinated_fraction)
        score -= penalty
        reasons.append(
            f"Suggestions reference pet(s) not in the system: {unknown_pets}. "
            "These may be hallucinated names."
        )

    empty_suggestions = [s for s in suggestions if not s.get("suggestion", "").strip()]
    if empty_suggestions:
        score -= 20 * len(empty_suggestions)
        reasons.append(
            f"{len(empty_suggestions)} suggestion(s) have empty text and cannot be acted on."
        )

    # ----------------------------
    # Proportionality check
    # ----------------------------
    if issues and len(suggestions) > len(issues) * 2:
        score -= 15
        reasons.append(
            "More suggestions than issues — the advisor may be over-generating. "
            "Review suggestions carefully."
        )

    # ----------------------------
    # Severity-based caution
    # ----------------------------
    high_issues = sum(1 for i in issues if str(i.get("severity", "")).lower() == "high")
    if high_issues >= 3:
        score -= 15
        reasons.append(
            f"{high_issues} high-severity issues detected. "
            "Complex care situations should be reviewed by the owner before acting."
        )

    # ----------------------------
    # Guardrail: missing pet_name always blocks display
    # ----------------------------
    missing_pet_name = [s for s in suggestions if not s.get("pet_name", "").strip()]
    if missing_pet_name:
        score -= 25
        reasons.append(
            f"{len(missing_pet_name)} suggestion(s) are missing a pet name "
            "and cannot be attributed correctly."
        )

    # ----------------------------
    # Clamp + level
    # ----------------------------
    score = max(0, min(100, score))

    if score >= 70:
        level = "high"
    elif score >= 40:
        level = "medium"
    else:
        level = "low"

    should_display = level in ("high", "medium")

    if not reasons:
        reasons.append("Suggestions appear well-formed and targeted.")

    return {
        "score": score,
        "level": level,
        "reasons": reasons,
        "should_display": should_display,
    }
