"""
Tests for PawPal+ AI Care Advisor (Module 5 Extension)
All tests use MockClient or no client so they run fully offline.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime

from pawpal_system import Owner, Pet, Task, TaskType, Priority, RecurrencePattern
from pawpal_advisor import PawPalAdvisor
from llm_client import MockClient
from reliability.confidence_checker import check_confidence


# ----------------------------
# Fixtures
# ----------------------------
@pytest.fixture
def dog_owner_no_tasks():
    owner = Owner("Alex", "alex@example.com")
    dog = Pet("Rex", "Dog", "Labrador", 4)
    owner.add_pet(dog)
    return owner


@pytest.fixture
def dog_owner_with_walk():
    owner = Owner("Sam", "sam@example.com")
    dog = Pet("Buddy", "Dog", "Golden Retriever", 3)
    walk = Task("Morning Walk", TaskType.WALK, 30, Priority.HIGH,
                scheduled_time=datetime.now().replace(hour=8, minute=0))
    dog.add_task(walk)
    owner.add_pet(dog)
    return owner


@pytest.fixture
def complete_owner():
    owner = Owner("Jordan", "jordan@example.com")
    dog = Pet("Max", "Dog", "Poodle", 2)
    walk1 = Task("Morning Walk", TaskType.WALK, 30, Priority.HIGH,
                 scheduled_time=datetime.now().replace(hour=8, minute=0))
    walk2 = Task("Evening Walk", TaskType.WALK, 30, Priority.MEDIUM,
                 scheduled_time=datetime.now().replace(hour=18, minute=0))
    feed = Task("Breakfast", TaskType.FEEDING, 15, Priority.HIGH,
                scheduled_time=datetime.now().replace(hour=7, minute=0))
    dog.add_task(walk1)
    dog.add_task(walk2)
    dog.add_task(feed)
    owner.add_pet(dog)
    return owner


@pytest.fixture
def cat_missing_food():
    owner = Owner("Riley", "riley@example.com")
    cat = Pet("Luna", "Cat", "Siamese", 1)
    # Cat with enrichment but no feeding
    enrich = Task("Playtime", TaskType.ENRICHMENT, 20, Priority.LOW)
    cat.add_task(enrich)
    owner.add_pet(cat)
    return owner


@pytest.fixture
def dog_with_non_recurring_med():
    owner = Owner("Casey", "casey@example.com")
    dog = Pet("Bolt", "Dog", "Beagle", 5)
    feed = Task("Breakfast", TaskType.FEEDING, 15, Priority.HIGH)
    walk1 = Task("Walk AM", TaskType.WALK, 30, Priority.HIGH)
    walk2 = Task("Walk PM", TaskType.WALK, 30, Priority.MEDIUM)
    med = Task("Heart Meds", TaskType.MEDICATION, 5, Priority.HIGH,
               is_recurring=False)  # Not recurring — should be flagged
    dog.add_task(feed)
    dog.add_task(walk1)
    dog.add_task(walk2)
    dog.add_task(med)
    owner.add_pet(dog)
    return owner


# ----------------------------
# Advisor workflow tests (offline / heuristic)
# ----------------------------
class TestAdvisorOfflineMode:

    def test_run_returns_correct_shape(self, dog_owner_no_tasks):
        advisor = PawPalAdvisor(client=None)
        result = advisor.run(dog_owner_no_tasks)

        assert isinstance(result, dict)
        assert "issues" in result
        assert "suggestions" in result
        assert "confidence" in result
        assert "logs" in result
        assert isinstance(result["issues"], list)
        assert isinstance(result["suggestions"], list)
        assert isinstance(result["confidence"], dict)
        assert len(result["logs"]) > 0

    def test_pet_with_no_tasks_is_high_severity(self, dog_owner_no_tasks):
        advisor = PawPalAdvisor(client=None)
        result = advisor.run(dog_owner_no_tasks)

        high_issues = [i for i in result["issues"] if i["severity"] == "high"]
        assert len(high_issues) >= 1
        assert any(i["pet_name"] == "Rex" for i in high_issues)

    def test_dog_missing_walks_flagged(self, cat_missing_food):
        # The fixture has a cat missing food — check feeding gap is detected
        advisor = PawPalAdvisor(client=None)
        result = advisor.run(cat_missing_food)

        feeding_issues = [i for i in result["issues"] if i["type"] == "Feeding Gap"]
        assert len(feeding_issues) >= 1
        assert feeding_issues[0]["pet_name"] == "Luna"

    def test_dog_with_one_walk_gets_medium_exercise_issue(self, dog_owner_with_walk):
        advisor = PawPalAdvisor(client=None)
        result = advisor.run(dog_owner_with_walk)

        exercise_issues = [i for i in result["issues"] if i["type"] == "Exercise Gap"]
        assert len(exercise_issues) >= 1
        assert exercise_issues[0]["severity"] == "medium"

    def test_complete_schedule_produces_no_issues(self, complete_owner):
        advisor = PawPalAdvisor(client=None)
        result = advisor.run(complete_owner)

        assert result["issues"] == []
        assert result["suggestions"] == []

    def test_non_recurring_medication_is_flagged(self, dog_with_non_recurring_med):
        advisor = PawPalAdvisor(client=None)
        result = advisor.run(dog_with_non_recurring_med)

        med_issues = [i for i in result["issues"] if i["type"] == "Medication Schedule"]
        assert len(med_issues) >= 1
        assert med_issues[0]["pet_name"] == "Bolt"

    def test_suggestions_reference_real_pets(self, dog_owner_no_tasks):
        advisor = PawPalAdvisor(client=None)
        result = advisor.run(dog_owner_no_tasks)

        pet_names = {p.name for p in dog_owner_no_tasks.pets}
        for s in result["suggestions"]:
            assert s["pet_name"] in pet_names, (
                f"Suggestion references unknown pet: {s['pet_name']}"
            )

    def test_agent_trace_contains_all_steps(self, dog_owner_no_tasks):
        advisor = PawPalAdvisor(client=None)
        result = advisor.run(dog_owner_no_tasks)

        steps = {entry["step"] for entry in result["logs"]}
        for expected_step in ("PLAN", "ANALYZE", "SUGGEST", "EVALUATE", "REFLECT"):
            assert expected_step in steps, f"Missing step in trace: {expected_step}"


# ----------------------------
# Mock client fallback tests
# ----------------------------
class TestAdvisorMockClientFallback:

    def test_mock_client_forces_heuristic_fallback(self, dog_owner_no_tasks):
        # MockClient returns non-JSON, so the advisor must fall back to heuristics
        advisor = PawPalAdvisor(client=MockClient())
        result = advisor.run(dog_owner_no_tasks)

        assert len(result["issues"]) > 0
        assert any(
            "Falling back to heuristics" in entry["message"]
            for entry in result["logs"]
        )

    def test_fallback_still_produces_suggestions(self, dog_owner_no_tasks):
        advisor = PawPalAdvisor(client=MockClient())
        result = advisor.run(dog_owner_no_tasks)

        assert len(result["suggestions"]) > 0


# ----------------------------
# Confidence checker tests
# ----------------------------
class TestConfidenceChecker:

    def test_no_suggestions_is_low_confidence(self):
        owner = Owner("A", "a@a.com")
        pet = Pet("Spot", "Dog")
        owner.add_pet(pet)
        conf = check_confidence([], [pet], [])

        assert conf["level"] == "low"
        assert conf["should_display"] is False
        assert conf["score"] == 0

    def test_valid_suggestions_get_high_confidence(self):
        owner = Owner("B", "b@b.com")
        pet = Pet("Spot", "Dog")
        owner.add_pet(pet)
        suggestions = [{"pet_name": "Spot", "priority": "high", "suggestion": "Add a walk."}]
        issues = [{"type": "Exercise Gap", "severity": "high", "pet_name": "Spot", "msg": "No walks."}]
        conf = check_confidence(suggestions, [pet], issues)

        assert conf["level"] in ("medium", "high")
        assert conf["should_display"] is True

    def test_hallucinated_pet_name_lowers_confidence(self):
        owner = Owner("C", "c@c.com")
        pet = Pet("Spot", "Dog")
        owner.add_pet(pet)
        # Suggestion references a pet that doesn't exist
        suggestions = [{"pet_name": "GhostPet", "priority": "high", "suggestion": "Feed it."}]
        conf = check_confidence(suggestions, [pet], [])

        assert conf["score"] <= 70
        assert any("hallucinated" in r.lower() or "not in the system" in r.lower()
                   for r in conf["reasons"])

    def test_guardrail_blocks_display_when_many_unknown_pets(self):
        # Guardrail: if all suggestions reference non-existent pets, block display
        owner = Owner("D", "d@d.com")
        pet = Pet("Spot", "Dog")
        owner.add_pet(pet)
        suggestions = [
            {"pet_name": "Ghost1", "priority": "high", "suggestion": "Walk daily."},
            {"pet_name": "Ghost2", "priority": "medium", "suggestion": "Feed twice."},
        ]
        conf = check_confidence(suggestions, [pet], [])

        assert conf["should_display"] is False
