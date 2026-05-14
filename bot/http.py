import requests


class HttpClient:
    def __init__(self, retries: int = 1):
        self.session = requests.Session()
        self.retries = retries

    def get_json(self, url: str, *, params: dict | None = None, timeout: float = 3.0):
        last_exc: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except Exception as exc:
                last_exc = exc
        raise last_exc  # type: ignore[misc]

