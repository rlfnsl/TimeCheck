import discord
import asyncio
import json
from datetime import datetime, timedelta
import pytz
import os
import re

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
CHANNEL_ID = 1346156878111182910
DATA_FILE = "voice_data.json"

class VoiceTrackerBot(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.KST = pytz.timezone("Asia/Seoul")
        self.user_join_times = {}  # {user_id: 입장시간}
        self.user_total_time = {str(i): {} for i in range(7)}  # {요일: {유저ID: 누적시간}}
        self.user_daily_time = {str(i): {} for i in range(7)}  # {요일: {유저ID: 하루 이용 시간}}
        self.alarms = {}  # ✅ 알람 저장하는 딕셔너리 추가 ✅
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

    async def on_message(self, message):
        if message.author.bot:  # 봇이 보낸 메시지는 무시
            return
        if message.content == "!중간정산":
            await self.send_intermediate_summary(message.channel)
        elif message.content == "!진행도":
            await self.send_progress_status(message.channel)
        elif re.match(r"^!\d+$", message.content):  # "!숫자" 형식인지 확인
            minutes = int(message.content[1:])  # 숫자 부분만 추출
            await self.set_alarm(message, minutes)
        elif message.content == "!알람삭제":
            await self.cancel_alarm(message)

    async def on_voice_state_update(self, member, before, after):
        now = datetime.now(self.KST)
        weekday = str(now.weekday())
        channel = self.get_channel(CHANNEL_ID)

        if before.channel is None and after.channel is not None:
            self.user_join_times[member.id] = now
        elif before.channel is not None and after.channel is None:
            if member.id in self.user_join_times:
                join_time = self.user_join_times.pop(member.id)
                weekday = str(join_time.weekday())
                duration = now - join_time
                if duration >= timedelta(minutes=20):
                    self.user_total_time[weekday].setdefault(str(member.id), 0)
                    self.user_daily_time[weekday].setdefault(str(member.id), 0)
                    self.user_total_time[weekday][str(member.id)] += duration.seconds
                    self.user_daily_time[weekday][str(member.id)] += duration.seconds
                    self.save_data()
                    if channel:
                        await channel.send(f"🔴 {join_time.strftime('%H:%M:%S')} ~ {now.strftime('%H:%M:%S')} ({member.display_name})")

    async def send_intermediate_summary(self, channel):
        """현재까지의 누적 스터디 시간을 정산하여 출력"""
        summary = "**📊 현재까지의 스터디 이용 시간**\n"
        days = ["월", "화", "수", "목", "금", "토", "일"]
        
        for i, users in self.user_total_time.items():
            summary += f"🗓 {days[int(i)]}요일:\n"
            if not users:
                summary += "  └ 기록 없음\n"
            else:
                for user_id, duration in users.items():
                    hours, remainder = divmod(duration, 3600)
                    minutes, _ = divmod(remainder, 60)
                    summary += f"  └ <@{user_id}>: {hours}시간 {minutes}분\n"
        
        await channel.send(summary)
    
    async def send_progress_status(self, channel):
        """현재 음성 채널에 있는 사람들의 진행도 출력"""
        now = datetime.now(self.KST)
        if not self.user_join_times:
            await channel.send("현재 음성 채널에 있는 사람이 없습니다.")
            return
        
        summary = "**🔄 현재 진행도 현황**\n"
        for user_id, join_time in self.user_join_times.items():
            duration = now - join_time
            hours, remainder = divmod(duration.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            summary += f"🔹 <@{user_id}>: {hours}시간 {minutes}분째 진행 중\n"
        
        await channel.send(summary)

    async def set_alarm(self, message, minutes):
        """입력된 시간(분) 후에 알람을 설정"""
        if message.author.id in self.alarms:
            await message.channel.send(f"⚠️ {message.author.mention}, 이미 설정된 알람이 있습니다! 먼저 삭제하세요. (`!알람삭제`)")
            return
        
        task = asyncio.create_task(self.alarm_task(message, minutes))
        self.alarms[message.author.id] = task  # 알람 저장
        await message.channel.send(f"⏳ {minutes}분 뒤에 알람을 설정했습니다! ({message.author.mention})")

    async def alarm_task(self, message, minutes):
        """알람 대기 및 실행"""
        await asyncio.sleep(minutes * 60)
        await message.channel.send(f"⏰ {minutes}분이 지났습니다! ({message.author.mention})")
        self.alarms.pop(message.author.id, None)  # 알람 완료 후 삭제

    async def cancel_alarm(self, message):
        """사용자가 설정한 알람 취소"""
        if message.author.id in self.alarms:
            self.alarms[message.author.id].cancel()  # 알람 취소
            del self.alarms[message.author.id]  # 딕셔너리에서 제거
            await message.channel.send(f"✅ {message.author.mention}, 알람을 삭제했습니다!")
        else:
            await message.channel.send(f"⚠️ {message.author.mention}, 삭제할 알람이 없습니다!")

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

            summary = "**📊 주간 스터디 이용 요약**\n"
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
            
            summary += f"\n**✅ 성공한 닝겐**: {', '.join(successful_users) if successful_users else '없음'}\n"
            summary += f"**❌ 실패한 닝겐**: {', '.join(failed_users) if failed_users else '없음'}\n"
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
intents.messages = True  # 메시지 관련 인텐트 활성화
intents.message_content = True  # 메시지 내용을 읽을 수 있도록 추가!

client = VoiceTrackerBot(intents=intents)
client.run(TOKEN)
