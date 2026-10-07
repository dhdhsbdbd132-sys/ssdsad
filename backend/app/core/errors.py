from fastapi import HTTPException


class AppError(HTTPException):
    def __init__(self, status: int, message: str):
        super().__init__(
            status, message, headers={"WWW-Authenticate": "Bearer"} if status == 401 else None
        )
