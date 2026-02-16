import requests
import os
from dotenv import load_dotenv

# Load .env explicitly
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    """
    Send a message to the configured Telegram Chat.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials missing in .env")
        return False
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            return True
        else:
            print(f"Telegram Error: {response.text}")
            return False
            
    except Exception as e:
        print(f"Telegram Failed: {e}")
        return False

if __name__ == "__main__":
    # Test
    send_telegram_message("*Test Alert* form Bithumb Quant Dashboard 🐯")
