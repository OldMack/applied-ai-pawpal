"""
PawPal+ AI Care Advisor
Module 5 Extension — Agentic workflow for intelligent pet care recommendations.

Workflow:
  1) PLAN    — Decide what to analyze based on the owner's pets and tasks
  2) ANALYZE — Detect care gaps (heuristics or LLM)
  3) SUGGEST — Generate improvement recommendations (heuristics or LLM)
  4) EVALUATE — Score confidence of suggestions
  5) REFLECT — Decide whether to present suggestions or defer to human
"""

import json
import re
from typing import Any, Dict, List, Optional

from pawpal_system import Owner, Pet, Task, TaskType, RecurrencePattern
from reliability.confidence_checker import check_confidence


class PawPalAdvisor:
    """Agentic AI care advisor for PawPal+."""

    def __init__(self, client: Optional[Any] = None):
        # client must implement: complete(system_prompt, user_prompt) -> str
        self.client = client
        self.logs: List[Dict[str, str]] = []

    # ----------------------------
    # Public API
    # ----------------------------
    def run(self, owner: Owner) -> Dict[str, Any]:
        self.logs = []
        pet_count = len(owner.pets)
        self._log("PLAN", f"Analyzing care schedule for {owner.name} ({pet_count} pet(s)).")

        summary = self._build_schedule_summary(owner)

        issues = self.analyze(owner, summary)
        self._log("ANALYZE", f"Found {len(issues)} care issue(s).")

        suggestions = self.suggest(summary, issues)
        if not suggestions:
            self._log("SUGGEST", "No suggestions produced — schedule may already be complete.")
        else:
            self._log("SUGGEST", f"Generated {len(suggestions)} suggestion(s).")

        confidence = check_confidence(suggestions, owner.pets, issues)
        self._log(
            "EVALUATE",
            f"Confidence: {confidence['level'].upper()} (score={confidence['score']}).",
        )

        if confidence["should_display"]:
            self._log("REFLECT", "Suggestions are confident enough to display automatically.")
        else:
            self._log("REFLECT", "Low confidence — suggestions flagged for human review before display.")

        return {
            "issues": issues,
            "suggestions": suggestions,
            "confidence": confidence,
            "logs": self.logs,
        }

    # ----------------------------
    # Workflow steps
    # ----------------------------
    def analyze(self, owner: Owner, summary: str) -> List[Dict[str, str]]:
        if not self._can_call_llm():
            self._log("ANALYZE", "Using heuristic analyzer (offline mode).")
            return self._heuristic_analyze(owner)

        self._log("ANALYZE", "Using LLM analyzer.")
        system_prompt = self._read_prompt("prompts/analyzer_system.txt") or (
            "You are PawPal Advisor, an expert pet care assistant. "
            "Return ONLY valid JSON. No markdown, no backticks."
        )
        user_prompt = (
            self._read_prompt("prompts/analyzer_user.txt", schedule_summary=summary)
            or (
                "Analyze this pet care schedule and identify care gaps.\n"
                "Return a JSON array with keys: type, severity, pet_name, msg.\n"
                "Severity must be exactly: low, medium, or high.\n\n"
                f"SCHEDULE:\n{summary}"
            )
        )

        try:
            raw = self.client.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception as e:
            self._log("ANALYZE", f"API error: {e}. Falling back to heuristics.")
            return self._heuristic_analyze(owner)

        issues = self._parse_json_array(raw, required_keys={"type", "severity", "pet_name", "msg"})

        if issues is None:
            self._log("ANALYZE", "LLM output was not parseable JSON. Falling back to heuristics.")
            return self._heuristic_analyze(owner)

        issues = self._validate_issues(issues)

        if not issues and raw.strip() not in ("[]", ""):
            self._log("ANALYZE", "LLM returned no valid issues after validation. Falling back to heuristics.")
            return self._heuristic_analyze(owner)

        return issues

    def suggest(self, summary: str, issues: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if not issues:
            self._log("SUGGEST", "No issues to address.")
            return []

        if not self._can_call_llm():
            self._log("SUGGEST", "Using heuristic advisor (offline mode).")
            return self._heuristic_suggest(issues)

        self._log("SUGGEST", "Using LLM advisor.")
        system_prompt = self._read_prompt("prompts/advisor_system.txt") or (
            "You are PawPal Advisor, a careful and practical pet care advisor. "
            "Return ONLY valid JSON. No markdown, no backticks."
        )
        user_prompt = (
            self._read_prompt(
                "prompts/advisor_user.txt",
                issues_json=json.dumps(issues),
                schedule_summary=summary,
            )
            or (
                "Based on these care issues, generate specific improvement suggestions.\n"
                "Return a JSON array with keys: pet_name, priority, suggestion.\n"
                "Priority must be exactly: low, medium, or high.\n\n"
                f"ISSUES (JSON):\n{json.dumps(issues)}\n\nSCHEDULE:\n{summary}"
            )
        )

        try:
            raw = self.client.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception as e:
            self._log("SUGGEST", f"API error: {e}. Falling back to heuristic advisor.")
            return self._heuristic_suggest(issues)

        suggestions = self._parse_json_array(raw, required_keys={"pet_name", "priority", "suggestion"})

        if suggestions is None:
            self._log("SUGGEST", "LLM output not parseable. Falling back to heuristic advisor.")
            return self._heuristic_suggest(issues)

        suggestions = self._validate_suggestions(suggestions)

        if not suggestions and raw.strip() not in ("[]", ""):
            self._log("SUGGEST", "No valid suggestions after validation. Falling back to heuristic advisor.")
            return self._heuristic_suggest(issues)

        return suggestions

    # ----------------------------
    # Heuristic analyzer
    # ----------------------------
    def _heuristic_analyze(self, owner: Owner) -> List[Dict[str, str]]:
        issues: List[Dict[str, str]] = []

        for pet in owner.pets:
            tasks = pet.get_all_tasks()
            task_types = {t.task_type for t in tasks}

            if not tasks:
                issues.append({
                    "type": "Care Gap",
                    "severity": "high",
                    "pet_name": pet.name,
                    "msg": f"{pet.name} has no tasks scheduled at all.",
                })
                continue

            if pet.species.lower() == "dog":
                walk_count = sum(1 for t in tasks if t.task_type == TaskType.WALK)
                if walk_count == 0:
                    issues.append({
                        "type": "Exercise Gap",
                        "severity": "high",
                        "pet_name": pet.name,
                        "msg": f"{pet.name} (Dog) has no walk tasks. Dogs need daily exercise.",
                    })
                elif walk_count < 2:
                    issues.append({
                        "type": "Exercise Gap",
                        "severity": "medium",
                        "pet_name": pet.name,
                        "msg": (
                            f"{pet.name} (Dog) has only {walk_count} walk per day. "
                            "Dogs typically benefit from at least 2 walks daily."
                        ),
                    })

            if TaskType.FEEDING not in task_types:
                issues.append({
                    "type": "Feeding Gap",
                    "severity": "high",
                    "pet_name": pet.name,
                    "msg": f"{pet.name} has no feeding tasks scheduled.",
                })

            for task in tasks:
                if task.task_type == TaskType.MEDICATION and not task.is_recurring:
                    issues.append({
                        "type": "Medication Schedule",
                        "severity": "medium",
                        "pet_name": pet.name,
                        "msg": (
                            f"{pet.name}'s medication '{task.title}' is not set as recurring. "
                            "Medications should be administered consistently."
                        ),
                    })

        return issues

    # ----------------------------
    # Heuristic advisor
    # ----------------------------
    def _heuristic_suggest(self, issues: List[Dict[str, str]]) -> List[Dict[str, str]]:
        suggestions: List[Dict[str, str]] = []

        for issue in issues:
            pet_name = issue.get("pet_name", "your pet")
            issue_type = issue.get("type", "")
            msg = issue.get("msg", "").lower()

            if issue_type == "Care Gap":
                suggestions.append({
                    "pet_name": pet_name,
                    "priority": "high",
                    "suggestion": (
                        f"Create a basic routine for {pet_name}: "
                        "add a HIGH priority Feeding task at 7:00 AM and 5:00 PM, "
                        "and a MEDIUM priority Enrichment task each afternoon."
                    ),
                })
            elif issue_type == "Exercise Gap" and "no walk" in msg:
                suggestions.append({
                    "pet_name": pet_name,
                    "priority": "high",
                    "suggestion": (
                        f"Add two daily Walk tasks for {pet_name}: "
                        "a 30-minute HIGH priority walk at 8:00 AM and a 30-minute walk at 6:00 PM."
                    ),
                })
            elif issue_type == "Exercise Gap":
                suggestions.append({
                    "pet_name": pet_name,
                    "priority": "medium",
                    "suggestion": (
                        f"Add a second Walk task for {pet_name} — "
                        "an evening walk at 6:00 PM helps maintain consistent daily exercise."
                    ),
                })
            elif issue_type == "Feeding Gap":
                suggestions.append({
                    "pet_name": pet_name,
                    "priority": "high",
                    "suggestion": (
                        f"Add HIGH priority Feeding tasks for {pet_name}: "
                        "breakfast at 7:00 AM (15 min) and dinner at 5:00 PM (15 min)."
                    ),
                })
            elif issue_type == "Medication Schedule":
                suggestions.append({
                    "pet_name": pet_name,
                    "priority": "medium",
                    "suggestion": (
                        f"Enable Daily recurrence on {pet_name}'s medication task "
                        "to ensure it appears in every day's schedule automatically."
                    ),
                })

        # Deduplicate
        seen: set = set()
        unique: List[Dict[str, str]] = []
        for s in suggestions:
            key = (s["pet_name"], s["suggestion"][:40])
            if key not in seen:
                seen.add(key)
                unique.append(s)

        return unique

    # ----------------------------
    # Parsing + validation
    # ----------------------------
    def _parse_json_array(
        self, text: str, required_keys: set
    ) -> Optional[List[Dict[str, str]]]:
        text = text.strip()

        # Try direct parse
        parsed = self._try_json_loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]

        # Try extracting first JSON array
        array_str = self._extract_first_json_array(text)
        if array_str:
            parsed2 = self._try_json_loads(array_str)
            if isinstance(parsed2, list):
                return [item for item in parsed2 if isinstance(item, dict)]

        return None

    def _validate_issues(self, arr: List[Dict]) -> List[Dict[str, str]]:
        valid_severities = {"low", "medium", "high"}
        result = []
        for item in arr:
            msg = str(item.get("msg", "")).strip()
            severity = str(item.get("severity", "")).strip().lower()
            pet_name = str(item.get("pet_name", "")).strip()
            if not msg or severity not in valid_severities or not pet_name:
                continue
            result.append({
                "type": str(item.get("type", "Issue")),
                "severity": severity,
                "pet_name": pet_name,
                "msg": msg,
            })
        return result

    def _validate_suggestions(self, arr: List[Dict]) -> List[Dict[str, str]]:
        valid_priorities = {"low", "medium", "high"}
        result = []
        for item in arr:
            suggestion = str(item.get("suggestion", "")).strip()
            priority = str(item.get("priority", "")).strip().lower()
            pet_name = str(item.get("pet_name", "")).strip()
            if not suggestion or priority not in valid_priorities or not pet_name:
                continue
            result.append({
                "pet_name": pet_name,
                "priority": priority,
                "suggestion": suggestion,
            })
        return result

    def _try_json_loads(self, s: str) -> Any:
        try:
            return json.loads(s)
        except Exception:
            return None

    def _extract_first_json_array(self, s: str) -> Optional[str]:
        start = s.find("[")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "[":
                depth += 1
            elif s[i] == "]":
                depth -= 1
                if depth == 0:
                    return s[start: i + 1]
        return None

    # ----------------------------
    # Utilities
    # ----------------------------
    def _build_schedule_summary(self, owner: Owner) -> str:
        lines = [f"Owner: {owner.name}", f"Pets: {len(owner.pets)}"]
        for pet in owner.pets:
            lines.append(f"\nPet: {pet.name} ({pet.species}, age {pet.age})")
            tasks = pet.get_all_tasks()
            if not tasks:
                lines.append("  No tasks scheduled.")
            else:
                for task in tasks:
                    time_str = (
                        task.scheduled_time.strftime("%H:%M")
                        if task.scheduled_time
                        else "no time set"
                    )
                    recurring = " [recurring daily]" if task.is_recurring else ""
                    lines.append(
                        f"  - {task.title}: {task.task_type.value}, "
                        f"{task.priority.name} priority, "
                        f"{task.duration_minutes} min, {time_str}{recurring}"
                    )
        return "\n".join(lines)

    def _read_prompt(self, path: str, **kwargs) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                template = f.read()
            if kwargs:
                for key, value in kwargs.items():
                    template = template.replace("{" + key + "}", str(value))
            return template
        except FileNotFoundError:
            return None

    def _can_call_llm(self) -> bool:
        return self.client is not None and hasattr(self.client, "complete")

    def _log(self, step: str, message: str) -> None:
        self.logs.append({"step": step, "message": message})
