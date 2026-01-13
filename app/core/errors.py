from fastapi import HTTPException

def http_error(status_code: int, message: str, details: dict | None = None):
    payload = {"message": message}
    if details:
        payload["details"] = details
    raise HTTPException(status_code=status_code, detail=payload)
