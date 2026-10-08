class WorkflowError(Exception):
    status_code = 400
    def __init__(self, message, **extra):
        super().__init__(message); self.message = message; self.extra = extra

class NotAllowed(WorkflowError): status_code = 403
class InvalidTransition(WorkflowError): status_code = 409
class Conflict(WorkflowError): status_code = 409
class ValidationFailed(WorkflowError): status_code = 422
class DuplicateFound(WorkflowError): status_code = 409
class NotFound(WorkflowError): status_code = 404
