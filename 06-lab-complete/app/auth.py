"""
API Key authentication.

Client gửi header X-API-Key trùng biến môi trường AGENT_API_KEY; thiếu hoặc sai → 401.
"""
import hmac

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings

# auto_error=False: tự trả 401 thay vì mã mặc định của FastAPI khi thiếu header.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Dependency cho FastAPI — dùng trong /ask: Depends(verify_api_key)."""
    expected = settings.agent_api_key
    # compare_digest so sánh thời gian hằng định; dùng bytes để key có ký tự
    # ngoài ASCII không làm app ném TypeError (500).
    if not expected or not api_key or not hmac.compare_digest(api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key
