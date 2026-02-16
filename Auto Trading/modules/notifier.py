try:
    import telegram
except ImportError:
    print("Warning: python-telegram-bot not installed. Alerts disabled.")
    telegram = None

import asyncio

class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        if telegram:
             self.bot = telegram.Bot(token=token)
        else:
             self.bot = None
    
    async def send_msg(self, text):
        if not self.bot: 
            print(f"[Telegram Mock] {text}")
            return

        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text, parse_mode='Markdown')
        except Exception as e:
            print(f"Telegram Error: {e}")

    async def notify_entry(self, symbol, side, price, qty, logic_name):
        msg = f"🚀 **[ENTRY] {side.upper()}**\n"
        msg += f"Symbol: `{symbol}`\n"
        msg += f"Price: `{price:,.0f}`\n"
        msg += f"Qty: `{qty}`\n"
        msg += f"Logic: {logic_name}"
        await self.send_msg(msg)

    async def notify_exit(self, symbol, exit_type, entry_price, exit_price, qty):
        pnl_pct = (exit_price - entry_price) / entry_price * 100
        # Determine sign based on side (Assuming Long only for now)
        pnl_krw = (exit_price - entry_price) * qty
        
        emoji = "💰" if pnl_krw > 0 else "🩸"
        
        msg = f"{emoji} **[EXIT] {exit_type}**\n"
        msg += f"Symbol: `{symbol}`\n"
        msg += f"PnL: **{pnl_krw:+,.0f} KRW** ({pnl_pct:+.2f}%)\n"
        msg += f"Price: `{entry_price:,.0f}` -> `{exit_price:,.0f}`"
        await self.send_msg(msg)
