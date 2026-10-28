"""Domain exceptions shared by queue and persistence layers."""


class LeaseOwnershipLost(Exception):
    """The worker no longer owns a valid lease for the claimed job."""


class RecordingHasActiveJobsError(RuntimeError):
    """A recording cannot be removed while local work still references it."""


class ChatGPTError(RuntimeError):
    """Base exception for ChatGPT integration errors."""


class ChatGPTAuthError(ChatGPTError):
    """Authentication or OAuth token error with ChatGPT."""


class ChatGPTTokenRevokedError(ChatGPTAuthError):
    """OAuth token has been revoked or invalidated by the user or OpenAI."""


class ChatGPTModelUnavailableError(ChatGPTError):
    """Requested model (e.g. gpt-6-luna) is not available in the user account catalog."""


class ChatGPTLimitError(ChatGPTError):
    """Plan limit, quota, or rate limit exceeded on ChatGPT."""


class ChatGPTServiceUnavailableError(ChatGPTError):
    """ChatGPT service is temporarily unavailable or unreachable."""


class ChatGPTInferenceError(ChatGPTError):
    """Inference failed or returned incomplete generation from ChatGPT."""


class AntigravityError(RuntimeError):
    """Base exception for Antigravity integration errors."""


class AntigravityUnavailableError(AntigravityError):
    """Antigravity CLI (agy) is not installed or available on this system."""


class AntigravityInferenceError(AntigravityError):
    """Inference failed or returned an error from the Antigravity CLI."""
