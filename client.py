import os

import requests

# Đọc API key từ biến môi trường (KHÔNG hard-code key trong code).
# Cách set:
#   export GEMINI_API_KEY="your-key-here"      (Linux/Mac)
#   $env:GEMINI_API_KEY="your-key-here"         (PowerShell)
# Hoặc dùng file .env + python-dotenv (xem load_dotenv bên dưới).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Model có thể override qua env GEMINI_MODEL nếu muốn đổi nhanh.
# gemini-2.5-flash: cân bằng tốc độ/độ chính xác, phù hợp sinh pandas query.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

try:
    # Optional: nếu có cài python-dotenv thì tự load file .env
    from dotenv import load_dotenv

    load_dotenv()
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", GEMINI_API_KEY)
except ImportError:
    pass


def ask_llm(prompt: str, temperature: float = 0.0) -> str:
    """Gọi Gemini API, trả về text response thô."""

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Chưa cấu hình GEMINI_API_KEY. "
            "Hãy set biến môi trường GEMINI_API_KEY trước khi chạy app."
        )

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 512,
        },
    }

    response = requests.post(
        GEMINI_URL,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        json=payload,
        timeout=60,
    )

    response.raise_for_status()
    data = response.json()

    try:
        candidate = data["candidates"][0]

        # Gemini có thể trả finishReason=SAFETY/RECITATION mà không có content
        if "content" not in candidate:
            reason = candidate.get("finishReason", "UNKNOWN")
            raise RuntimeError(f"Gemini không trả nội dung (finishReason={reason}).")

        parts = candidate["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts).strip()

        if not text:
            raise RuntimeError("Gemini trả về nội dung rỗng.")

        return text

    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Phản hồi từ Gemini không đúng định dạng: {data}") from exc