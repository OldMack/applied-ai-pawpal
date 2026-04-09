import os


class MockClient:
    """
    Offline stand-in for an LLM client.
    Returns predictable non-JSON output to force the advisor's fallback logic.
    """

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if "analyzer" in system_prompt.lower() or "care gap" in user_prompt.lower():
            # Not valid JSON — forces fallback to heuristic analyzer
            return "I reviewed the schedule but am not returning JSON right now."
        return "I have some ideas but cannot format them as JSON at the moment."


class GeminiClient:
    """
    Minimal Gemini API wrapper for PawPal+ AI Advisor.

    Requirements:
      - google-generativeai installed
      - GEMINI_API_KEY set in environment (loaded via python-dotenv)
    """

    def __init__(self, model_name: str = "gemini-2.5-flash", temperature: float = 0.2):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "Missing GEMINI_API_KEY. Create a .env file and set GEMINI_API_KEY=..."
            )

        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        self.temperature = float(temperature)

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self.model.generate_content(
                [
                    {"role": "user", "parts": [f"{system_prompt}\n\n{user_prompt}"]},
                ],
                generation_config={"temperature": self.temperature},
            )
            return response.text or ""
        except Exception:
            # Return empty string — advisor will detect failure and fall back
            return ""
