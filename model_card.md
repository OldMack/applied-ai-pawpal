# PawPal+ AI Care Advisor — Model Card

---

## 1) What is this system?

**Name:** PawPal+ AI Care Advisor
**Base project:** PawPal+ (Module 2 Show — Smart Pet Care Management System)

**Purpose:** Analyze a pet owner's care schedule, detect gaps or missing routines, generate targeted improvement suggestions, and evaluate confidence before presenting them. The system acts as a cautious AI teammate that explains its reasoning and defers to humans when it is unsure.

**Intended users:** Pet owners managing multi-pet care schedules who want a second opinion on whether their routine is complete, and students learning how to integrate agentic workflows into real applications.

---

## 2) How does it work?

The system follows a five-step agentic loop implemented in `PawPalAdvisor`:

1. **PLAN** — Logs intent and counts pets/tasks to frame the analysis scope.
2. **ANALYZE** — Detects care issues. In Heuristic mode, applies rule-based checks (missing walks for dogs, missing feeding tasks, non-recurring medication). In Gemini mode, sends a structured prompt and parses the JSON response; falls back to heuristics if the model returns malformed output.
3. **SUGGEST** — Generates improvement recommendations. Same dual-mode approach: LLM for richer context-aware suggestions, heuristics for offline or fallback use.
4. **EVALUATE** — Passes suggestions through `check_confidence` in `reliability/confidence_checker.py`. Scores 0–100 based on: hallucinated pet names, empty suggestion text, over-generation, and high-severity issue count.
5. **REFLECT** — If confidence is high or medium, suggestions display automatically. If low, a warning is shown and human review is recommended.

**Heuristics** handle all offline work and every LLM failure mode.
**Gemini** is used only when `GEMINI_API_KEY` is set, and every LLM call is wrapped in a try/except with a graceful fallback.

---

## 3) Inputs and outputs

**Inputs tested:**

- A dog with no tasks at all (edge case: empty schedule)
- A dog with one walk but no feeding
- A cat with enrichment but no feeding
- A dog with non-recurring medication + two walks + feeding (mostly complete)
- A dog with a complete schedule: two walks + feeding (no issues)

**Outputs observed:**

| Input | Issues Detected | Suggestions | Confidence |
|---|---|---|---|
| Dog, no tasks | Care Gap (High) | Create basic routine | HIGH (100) |
| Dog, 1 walk, no food | Exercise Gap (Med) + Feeding Gap (High) | Add second walk + add feeding | HIGH (85) |
| Cat, no feeding | Feeding Gap (High) | Add breakfast + dinner | HIGH (100) |
| Dog, non-recurring meds | Medication Schedule (Med) | Enable daily recurrence | HIGH (100) |
| Dog, complete schedule | None | None | N/A |

---

## 4) Reliability and safety rules

**Rule 1 — Hallucinated pet name penalty (confidence_checker.py)**
Checks whether suggestion `pet_name` values match actual pets in the system. Penalizes by `70 × (hallucinated_fraction)` so that fully hallucinated suggestion sets block automatic display entirely.
- *Why it matters:* LLMs can generate plausible-sounding pet names that don't exist. Acting on suggestions for a non-existent pet would be meaningless or confusing.
- *False positive:* A legitimate pet with an unusual name (e.g., a nickname vs. the name stored in the system) could be penalized as "unknown."
- *False negative:* A suggestion that references a real pet but recommends the wrong type of task entirely would not be caught by this rule.

**Rule 2 — LLM issue validation in `_validate_issues` (pawpal_advisor.py)**
Drops any issue from the LLM response that has an empty `msg`, missing `pet_name`, or a severity outside `{low, medium, high}`. If all issues are dropped and the response was not an empty array, falls back to heuristics.
- *Why it matters:* An issue without a message or with an unrecognized severity cannot be risk-scored correctly and provides no actionable information.
- *False positive:* A legitimate LLM issue with an unusual but informative severity string (e.g., "critical") would be discarded even if valid.
- *False negative:* An issue with a technically valid severity and non-empty message but nonsensical content would pass this filter.

---

## 5) Observed failure modes

**Failure 1 — Heuristic analyzer misses cat and bird care gaps**
Input: A cat with only a Walk task (unusual, but valid). The heuristic analyzer does not check for walking-related issues in cats the way it does for dogs. It only checks for feeding gaps and non-recurring medications. The walk task would receive no flag at all.

Gemini mode correctly identified this as unusual for a cat and flagged it as a low-priority enrichment/behavioral note. The heuristic layer cannot match this.

**Failure 2 — Over-generation risk with many issues**
Input: An owner with 4 pets, each having multiple problems (no tasks, no food, no walks, non-recurring meds). Gemini generated 8 suggestions — two per pet — which triggered the over-generation penalty in the confidence checker (more suggestions than issues × 2). The confidence dropped to medium, and a caution warning was shown. This was the intended behavior, but it meant valid suggestions were flagged alongside potentially redundant ones. A per-issue deduplication step in the suggest phase would help.

---

## 6) Heuristic vs Gemini comparison

| Dimension | Heuristic Mode | Gemini Mode |
|---|---|---|
| Detection coverage | Dogs: walks, feeding, medication recurrence. Other species: feeding, medication only. | All species; catches enrichment gaps, unusual task combinations, age-related care notes |
| Suggestion quality | Templated, always consistent | Context-aware, more natural language, but variable |
| Reliability | 100% deterministic | Requires JSON validation + fallback |
| API usage | Zero | 2 requests per advisor run (analyze + suggest) |

Heuristic mode consistently caught the most common and high-severity issues (missing feeding, missing walks for dogs). Gemini mode added value for edge cases and non-dog species, but its output required heavier validation to be trustworthy.

---

## 7) Human-in-the-loop decision

**Scenario:** An owner has a senior dog (age 12+) with a medication task. The AI suggests adding two 30-minute walks based on the "dog needs exercise" heuristic — but a senior dog with a medication flag may have mobility issues or a vet-restricted activity level.

**Trigger:** If a pet has a MEDICATION task AND the advisor is about to suggest high-intensity exercise, confidence should be set to "low" automatically and the suggestion should include a disclaimer: *"Consult your veterinarian before adjusting exercise for a pet on medication."*

**Where to implement:** In `confidence_checker.py` — add a cross-check between detected issues (medication present) and suggestion content (exercise mentioned). This keeps the guardrail decoupled from the advisor itself.

**Message to show:** *"⚠️ This pet has active medication. Please review exercise suggestions with your veterinarian before making changes."*

---

## 8) Improvement idea

**Per-species heuristic profiles**

Currently, heuristic rules treat all non-dog species the same (only feeding and medication checks). Adding a small species profile dict like:

```python
SPECIES_CHECKS = {
    "dog": {"required_types": [WALK, FEEDING], "min_walks": 2},
    "cat": {"required_types": [FEEDING, ENRICHMENT]},
    "bird": {"required_types": [FEEDING, ENRICHMENT]},
}
```

...would let the heuristic analyzer apply species-appropriate checks without any additional API calls. This is low-complexity (a dict lookup replaces a series of `if species == "dog"` conditionals), fully testable offline, and would eliminate the main coverage gap between heuristic and Gemini modes for common pet species.
