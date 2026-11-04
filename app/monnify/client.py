
import httpx

from app.core.config import settings


class MonnifyClient:
    """
    Monnify API client.

    Handles:
    - Authentication
    - Authenticated GET requests
    - Authenticated POST requests
    - Provider error handling
    - Cloudflare/non-JSON response handling
    """

    def __init__(self):
        self.base_url = (
            settings.MONNIFY_BASE_URL or ""
        ).rstrip("/")

        self.api_key = settings.MONNIFY_API_KEY
        self.secret_key = settings.MONNIFY_SECRET_KEY

        if not self.base_url:
            raise RuntimeError(
                "MONNIFY_BASE_URL is not configured."
            )

        if not self.api_key or not self.secret_key:
            raise RuntimeError(
                "Monnify API credentials are not configured."
            )

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"

        return f"{self.base_url}{path}"

    # ============================================================
    # RESPONSE HANDLING
    # ============================================================

    @staticmethod
    def _parse_response(response: httpx.Response, operation: str) -> dict:
        """
        Parse Monnify JSON response and provide useful errors
        when the provider returns HTML or invalid content.
        """

        try:
            response_data = response.json()

        except ValueError as exc:
            content_type = response.headers.get(
                "content-type", ""
            )

            server = response.headers.get(
                "server", ""
            )

            body_preview = (
                response.text[:300]
                .replace("\n", " ")
                .replace("\r", "")
            )

            raise RuntimeError(
                f"Monnify {operation} returned non-JSON content. "
                f"HTTP {response.status_code}; "
                f"content-type={content_type!r}; "
                f"server={server!r}; "
                f"body_preview={body_preview!r}"
            ) from exc

        if not isinstance(response_data, dict):
            raise RuntimeError(
                f"Monnify {operation} returned an unexpected "
                f"response format. HTTP {response.status_code}."
            )

        if response.is_error:
            message = response_data.get(
                "responseMessage",
                response_data.get(
                    "message",
                    "Monnify request failed.",
                ),
            )

            raise RuntimeError(
                f"Monnify {operation} failed. "
                f"HTTP {response.status_code}: {message}"
            )

        return response_data

    # ============================================================
    # AUTHENTICATION
    # ============================================================

    def authenticate(self) -> str:
        """
        Authenticate with Monnify and return access token.
        """

        try:
            with httpx.Client(
                http2=False,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0),
            ) as client:

                response = client.post(
                    self._url("/api/v1/auth/login"),
                    auth=(
                        self.api_key,
                        self.secret_key,
                    ),
                    headers={
                        "Accept": "application/json",
                    },
                )

        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "Monnify authentication timed out. "
                "Check sandbox availability before retrying."
            ) from exc

        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Unable to connect to Monnify authentication service: {exc}"
            ) from exc

        response_data = self._parse_response(
            response,
            "authentication",
        )

        if not response_data.get("requestSuccessful"):
            message = response_data.get(
                "responseMessage",
                "Monnify authentication failed.",
            )

            raise RuntimeError(
                f"Monnify authentication failed: {message}"
            )

        response_body = response_data.get(
            "responseBody"
        ) or {}

        access_token = response_body.get(
            "accessToken"
        )

        if not access_token:
            raise RuntimeError(
                "Monnify authentication response did not "
                "contain an access token."
            )

        return access_token

    # ============================================================
    # AUTHENTICATED GET
    # ============================================================

    def get(
        self,
        path: str,
        params: dict | None = None,
    ) -> dict:
        """
        Perform authenticated GET request.
        """

        access_token = self.authenticate()

        try:
            with httpx.Client(
                http2=False,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0),
            ) as client:

                response = client.get(
                    self._url(path),
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "Authorization": (
                            f"Bearer {access_token}"
                        ),
                    },
                )

        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Monnify GET request timed out: {path}"
            ) from exc

        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Unable to connect to Monnify service: {exc}"
            ) from exc

        response_data = self._parse_response(
            response,
            "GET request",
        )

        if not response_data.get("requestSuccessful", True):
            message = response_data.get(
                "responseMessage",
                "Monnify GET request failed.",
            )

            raise RuntimeError(
                f"Monnify GET request failed: {message}"
            )

        return response_data

    # ============================================================
    # AUTHENTICATED POST
    # ============================================================

    def post(
        self,
        path: str,
        data: dict | None = None,
    ) -> dict:
        """
        Perform authenticated POST request.

        Used for:
        - Checkout initialization
        - Other Monnify POST endpoints
        """

        access_token = self.authenticate()

        try:
            with httpx.Client(
                http2=False,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0),
            ) as client:

                response = client.post(
                    self._url(path),
                    json=data or {},
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Authorization": (
                            f"Bearer {access_token}"
                        ),
                    },
                )

        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Monnify POST request timed out: {path}. "
                "The provider may have received the request. "
                "Reconcile the existing reference before retrying."
            ) from exc

        except httpx.RequestError as exc:
            raise RuntimeError(
                f"Unable to connect to Monnify service: {exc}"
            ) from exc

        response_data = self._parse_response(
            response,
            "POST request",
        )

        if not response_data.get("requestSuccessful", True):
            message = response_data.get(
                "responseMessage",
                "Monnify POST request failed.",
            )

            raise RuntimeError(
                f"Monnify POST request failed: {message}"
            )

        return response_data
