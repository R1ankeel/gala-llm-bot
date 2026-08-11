import json
import socket
import time
import urllib.error
import urllib.request


class LLMError(Exception):
    """Ошибка обращения к LLM-бэкенду."""


class LLMRetryableError(LLMError):
    """Сетевая ошибка или 5xx/429 — есть смысл повторить запрос."""


class LLMClient:
    """Транспорт к Ollama-совместимому бэкенду. Никакой персонажной логики.

    Использует нативный Ollama-эндпоинт POST {base_url}/api/chat
    (не OpenAI-совместимый /v1/chat/completions — не все сборки его отдают).
    Если бэкенд сменится — правится только этот класс.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        max_retries: int = 3,
        timeout: float = 120.0,
        think: bool | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self.think = think
        self._endpoint = f"{self.base_url}/api/chat"

    def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Генерирует текст ответа.

        system_prompt — core-блок персонажа (всегда идёт первым и целиком).
        messages — история чата без system-сообщения.
        temperature/max_tokens — если None, бэкенд использует свои дефолты.

        При сетевых ошибках и 5xx/429 делает до max_retries попыток,
        затем бросает LLMError. Никогда не возвращает None.
        """
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": False,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["options"] = {"num_predict": max_tokens}
        if self.think is not None:
            payload["think"] = self.think

        last_error: LLMError | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                parsed = self._post(payload)
                return self._extract_content(parsed)
            except LLMRetryableError as err:
                last_error = err
                if attempt < self.max_retries:
                    time.sleep(1.0 * attempt)
            except LLMError as err:
                raise err

        raise LLMError(
            f"Бэкенд не ответил после {self.max_retries} попыток. "
            f"Последняя ошибка: {last_error}"
        )

    def _post(self, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as err:
            if err.code >= 500 or err.code == 429:
                raise LLMRetryableError(
                    f"HTTP {err.code} ({err.reason}) от {self._endpoint}"
                ) from err
            raise LLMError(
                f"HTTP {err.code} ({err.reason}) от {self._endpoint}. "
                "Проверь URL и что бэкенд поднят."
            ) from err
        except (urllib.error.URLError, socket.timeout, TimeoutError) as err:
            reason = getattr(err, "reason", err)
            raise LLMRetryableError(
                f"Не удалось достучаться до LLM-бэкенда {self._endpoint}: {reason}. "
                "Убедись, что Ollama запущена и OLLAMA_BASE_URL верный."
            ) from err

        try:
            return json.loads(body)
        except json.JSONDecodeError as err:
            raise LLMError(f"Бэкенд вернул не JSON: {body[:200]!r}") from err

    def _extract_content(self, parsed: dict) -> str:
        try:
            content = parsed["message"]["content"]
        except (KeyError, IndexError, TypeError) as err:
            raise LLMError(f"Неожиданный формат ответа бэкенда: {parsed!r}") from err
        if content is None:
            raise LLMError(f"Пустой ответ от бэкенда {self.model}: {parsed!r}")
        return content
