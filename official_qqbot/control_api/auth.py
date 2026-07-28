from fastapi import Header, HTTPException


def require_bot_token(expected_token: str):
    def guard(x_bot_token: str = Header(default="")) -> None:
        if not expected_token or x_bot_token != expected_token:
            raise HTTPException(status_code=401, detail="invalid bot token")

    return guard


def require_admin_token(expected_token: str):
    def guard(x_admin_token: str = Header(default="")) -> None:
        if not expected_token or x_admin_token != expected_token:
            raise HTTPException(status_code=401, detail="invalid admin token")

    return guard
