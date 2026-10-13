class PsmError(Exception):
    def __init__(self, message: str, code: str = "PSM"):
        super().__init__(message)
        self.message = message
        self.code = code

    def __str__(self) -> str:
        return self.message
