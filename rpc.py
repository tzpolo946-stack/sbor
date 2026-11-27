import time
from pypresence import Presence

CLIENT_ID = "1575547551275552829"


class DiscordRPC:
    def __init__(self):
        self.rpc = None
        self.start_time = int(time.time())
        try:
            self.rpc = Presence(CLIENT_ID)
            self.rpc.connect()
            self.set_in_launcher()
        except Exception:
            self.rpc = None

    def set_in_launcher(self):
        if not self.rpc:
            return
        try:
            self.rpc.update(
                state="В меню лаунчера",
                details="PurpleVisuals • Fabric 26.2",
                large_image="logo",
                large_text="PurpleLauncher",
                start=self.start_time,
                buttons=[
                    {"label": "Сообщество Discord", "url": "https://discord.gg/3w4CYvuct"},
                    {"label": "Telegram канал", "url": "https://t.me"},
                ],
            )
        except Exception:
            pass

    def set_in_game(self, version_name, username):
        if not self.rpc:
            return
        try:
            self.rpc.update(
                state=f"Ник: {username}",
                details=f"Версия: {version_name}",
                large_image="logo",
                large_text="PurpleVisuals Client",
                start=int(time.time()),
                buttons=[
                    {"label": "Сообщество Discord", "url": "https://discord.gg/3w4CYvuct"},
                    {"label": "Telegram канал", "url": "https://t.me/purplelauncher"},
                ],
            )
        except Exception:
            pass
