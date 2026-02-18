from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import imaplib
import requests
import email
from email.header import decode_header

app = FastAPI()

# Cấu hình Model nhận dữ liệu từ Client
class AuthInfo(BaseModel):
    Email: str
    ClientId: str
    RefreshToken: str
    AccessToken: str = None
    ExpiresAt: float = None

def get_new_access_token(client_id: str, refresh_token: str):
    """Đổi Refresh Token lấy Access Token mới nhất từ Microsoft"""
    url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    payload = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
    }
    response = requests.post(url, data=payload)
    if response.status_code == 200:
        return response.json().get("access_token")
    return None

def decode_mime_text(text):
    """Giải mã tiêu đề email tiếng Việt hoặc ký tự đặc biệt"""
    if not text: return ""
    decoded = decode_header(text)
    result = ""
    for part, encoding in decoded:
        if isinstance(part, bytes):
            result += part.decode(encoding or "utf-8", errors="ignore")
        else:
            result += part
    return result

@app.get("/health")
async def health_check():
    """Health check endpoint để tránh Render sleep"""
    return {"status": "ok", "message": "API is running"}

@app.post("/get-mailbox")
async def get_mailbox(info: AuthInfo):
    # 1. Luôn lấy Access Token mới để đảm bảo không bị hết hạn (401)
    token = get_new_access_token(info.ClientId, info.RefreshToken)
    if not token:
        raise HTTPException(status_code=400, detail="Could not refresh Access Token")

    try:
        # 2. Kết nối IMAP
        mail = imaplib.IMAP4_SSL("outlook.office365.com", 993)
        
        # Xác thực XOAUTH2
        auth_string = f"user={info.Email}\x01auth=Bearer {token}\x01\x01"
        mail.authenticate('XOAUTH2', lambda x: auth_string.encode('utf-8'))
        
        # 3. Chọn INBOX và lấy danh sách email
        mail.select("INBOX")
        status, data = mail.search(None, 'ALL')
        mail_ids = data[0].split()
        
        emails_list = []
        
        # Lấy 10 email mới nhất
        for m_id in reversed(mail_ids[-10:]):
            # Chỉ lấy Header để tốc độ nhanh hơn
            status, msg_data = mail.fetch(m_id, '(BODY[HEADER.FIELDS (SUBJECT FROM DATE)])')
            raw_email = msg_data[0][1].decode('utf-8', errors='ignore')
            msg = email.message_from_string(raw_email)
            
            emails_list.append({
                "id": m_id.decode(),
                "subject": decode_mime_text(msg.get("Subject")),
                "from": decode_mime_text(msg.get("From")),
                "date": msg.get("Date")
            })
            
        mail.logout()
        return {
            "status": "success",
            "account": info.Email,
            "total_emails": len(mail_ids),
            "emails": emails_list
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)