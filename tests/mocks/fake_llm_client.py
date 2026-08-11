class FakeLLMClient:
    """Контролируемый fake для LLM: отвечает по подстроке в system+user тексте."""

    def __init__(self, responses_by_substring=None, default="[]", error=None):
        self.responses_by_substring = responses_by_substring or {}
        self.default = default
        self.error = error
        self.calls = []

    def generate(self, system_prompt, messages, temperature=None, max_tokens=None):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if self.error is not None:
            raise self.error
        haystack = system_prompt + "\n" + "\n".join(
            m.get("content", "") if isinstance(m, dict) else str(m) for m in messages
        )
        for key, response in self.responses_by_substring.items():
            if key in haystack:
                return response
        return self.default
