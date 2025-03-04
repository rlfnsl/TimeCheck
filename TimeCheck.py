import discord
import asyncio
import json
from datetime import datetime, timedelta
import pytz

TOKEN = ''  # 환경변수에서 토큰 가져오기
CHANNEL_ID = 1346156878111182910
DATA_FILE = "voice_data.json"

class VoiceTrackerBot(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.KST = pytz.timezone("Asia/Seoul")
        self.user_join_times = {}  # {user_id: 입장시간}
        self.user_total_time = {str(i): {} for i in range(7)}  # {요일: {유저ID: 누적시간}}
        self.user_daily_time = {str(i): {} for i in range(7)}  # {요일: {유저ID: 하루 이용 시간}}
        self.load_data()

    def load_data(self):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.user_total_time = data.get("user_total_time", {str(i): {} for i in range(7)})
                self.user_daily_time = data.get("user_daily_time", {str(i): {} for i in range(7)})
        except FileNotFoundError:
            self.save_data()

    def save_data(self):
        data = {
            "user_total_time": self.user_total_time,
            "user_daily_time": self.user_daily_time
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        self.loop.create_task(self.send_weekly_summary())

    async def on_voice_state_update(self, member, before, after):
        now = datetime.now(self.KST)
        weekday = str(now.weekday())
        channel = self.get_channel(CHANNEL_ID)

        if before.channel is None and after.channel is not None:
            self.user_join_times[member.id] = now
        elif before.channel is not None and after.channel is None:
            if member.id in self.user_join_times:
                join_time = self.user_join_times.pop(member.id)
                duration = now - join_time
                if duration >= timedelta(minutes=20):
                    self.user_total_time[weekday].setdefault(str(member.id), 0)
                    self.user_daily_time[weekday].setdefault(str(member.id), 0)
                    self.user_total_time[weekday][str(member.id)] += duration.seconds
                    self.user_daily_time[weekday][str(member.id)] += duration.seconds
                    self.save_data()
                    if channel:
                        await channel.send(f"🔴 {join_time.strftime('%H:%M:%S')} ~ {now.strftime('%H:%M:%S')} ({member.display_name})")

    async def send_weekly_summary(self):
        await self.wait_until_ready()
        while not self.is_closed():
            now = datetime.now(self.KST)
            target_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if now.weekday() == 0 and now >= target_time:
                target_time += timedelta(days=7)
            else:
                target_time += timedelta(days=(7 - now.weekday()) % 7)
            await asyncio.sleep((target_time - now).total_seconds())

            summary = "**📊 주간 음성 채널 이용 요약**\n"
            days = ["월", "화", "수", "목", "금", "토", "일"]
            successful_users, failed_users = [], []

            for i, users in self.user_total_time.items():
                summary += f"🗓 {days[int(i)]}요일:\n"
                if not users:
                    summary += "  └ 기록 없음\n"
                else:
                    for user_id, duration in users.items():
                        hours, remainder = divmod(duration, 3600)
                        minutes, _ = divmod(remainder, 60)
                        summary += f"  └ <@{user_id}>: {hours}시간 {minutes}분\n"
                    
                    for user_id, total_time in users.items():
                        used_days = sum(1 for j in range(7) if str(user_id) in self.user_total_time[str(j)])
                        if used_days == 1:
                            failed_users.append(f"<@{user_id}>")
                            continue
                        if used_days == 2 and total_time < 4 * 3600:
                            failed_users.append(f"<@{user_id}>")
                            continue
                        if total_time >= 4 * 3600:
                            successful_users.append(f"<@{user_id}>")
                        else:
                            failed_users.append(f"<@{user_id}>")
            
            summary += f"\n**✅ 성공한 유저**: {', '.join(successful_users) if successful_users else '없음'}\n"
            summary += f"**❌ 실패한 유저**: {', '.join(failed_users) if failed_users else '없음'}\n"
            channel = self.get_channel(CHANNEL_ID)
            if channel:
                await channel.send(summary)
            self.user_total_time = {str(i): {} for i in range(7)}
            self.user_daily_time = {str(i): {} for i in range(7)}
            self.save_data()

intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True

client = VoiceTrackerBot(intents=intents)
client.run(TOKEN)
