class GovernanceError(Exception):
    status = 400
    code = "invalid_request"

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        if code:
            self.code = code
        if status is not None:
            self.status = status


class Forbidden(GovernanceError):
    status = 403
    code = "forbidden"


class NotFound(GovernanceError):
    status = 404
    code = "not_found"


class Conflict(GovernanceError):
    status = 409
    code = "conflict"
