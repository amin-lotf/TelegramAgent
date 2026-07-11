class TelegramAuthUnavailableError(Exception):
    pass


class TelegramAuthBadResponseError(Exception):
    pass


class TelegramUserUnauthorizedError(Exception):
    pass


class ContentProcessingUnavailableError(Exception):
    pass


class ContentProcessingBadResponseError(Exception):
    pass

class JobCreationError(RuntimeError):
    """Raised when a content-processing job cannot be persisted."""
    pass


class WhisperXBackendUnavailableError(Exception):
    pass


class WhisperXBackendBusyError(RuntimeError):
    def __init__(
        self,
        message: str = "WhisperX backend is busy",
    ) -> None:
        super().__init__(message)