import discord
from discord.ext import commands
import os
import asyncio
from datetime import datetime, timedelta
import pytz  # 한국 시간 적용

TOKEN = os.environ['TOKEN']  # 환경변수에서 토큰 가져오기
CHANNEL_ID = 1346156878111182910

class MyClient(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.user_join_times = {}  # {user_id: 입장시간}
        self.user_total_time = {i: {} for i in range(7)}  # {요일: {유저ID: 누적시간}}
        self.user_daily_time = {i: {} for i in range(7)}  # {요일: {유저ID: 하루 이용 시간}}
        self.KST = pytz.timezone("Asia/Seoul")

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        channel = self.get_channel(CHANNEL_ID)
        self.loop.create_task(self.send_weekly_summary())

    async def on_voice_state_update(self, member, before, after):
        now = datetime.now(self.KST)
        weekday = now.weekday()  # 0(월) ~ 6(일)
        channel = self.get_channel(CHANNEL_ID)

        # 사용자가 음성 채널에 들어올 때
        if before.channel is None and after.channel is not None:
            self.user_join_times[member.id] = now

        # 사용자가 음성 채널에서 나갈 때
        elif before.channel is not None and after.channel is None:
            if member.id in self.user_join_times:
                join_time = self.user_join_times.pop(member.id)
                duration = now - join_time

                # 10분 이상 머물렀을 경우 메시지 전송 + 요일별 누적 시간 증가
                if duration >= timedelta(minutes=20):
                    if member.id not in self.user_total_time[weekday]:
                        self.user_total_time[weekday][member.id] = timedelta()
                    if member.id not in self.user_daily_time[weekday]:
                        self.user_daily_time[weekday][member.id] = timedelta()
                    
                    self.user_total_time[weekday][member.id] += duration  # 유저별 누적 시간 저장
                    self.user_daily_time[weekday][member.id] += duration  # 하루 이용 시간 기록

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
                days_until_tuesday = (7 - now.weekday()) % 7 
                target_time += timedelta(days=days_until_tuesday)

            wait_time = (target_time - now).total_seconds()
            await asyncio.sleep(wait_time)  # 월요일 00:00:00까지 대기

            # 📊 주간 요약 메시지 생성 및 전송
            summary = "**📊 주간 음성 채널 이용 요약**\n"
            days = ["월", "화", "수", "목", "금", "토", "일"]
            
            successful_users = []  # 성공한 유저 리스트
            failed_users = []  # 실패한 유저 리스트

            for i, users in self.user_total_time.items():
                summary += f"🗓 {days[i]}요일:\n"
                if not users:
                    summary += "  └ 기록 없음\n"
                else:
                    guild = self.get_guild(1327633759427625012)  # 원하는 서버의 ID로 설정
                    for user_id, duration in users.items():
                        member = guild.get_member(user_id) if guild else None
                        if member:
                            name = member.display_name
                        else:
                            name = "알 수 없음"  # 유저가 나갔거나 서버에 없을 경우

                        # 하루 최소 시간 조건 체크
                        if user_id in self.user_daily_time[i]:
                            daily_time = self.user_daily_time[i][user_id]
                            hours, remainder = divmod(daily_time.seconds, 3600)
                            minutes, _ = divmod(remainder, 60)

                            # 하루 최소 시간 조건을 만족하는 경우에만 누적시간에 포함
                            if daily_time >= timedelta(hours=1):  # 하루 최소 1시간 이상
                                if user_id not in self.user_total_time[i]:
                                    self.user_total_time[i][user_id] = timedelta()
                                self.user_total_time[i][user_id] += daily_time

                        # 하루 시간을 출력 (최소 1시간을 넘는 경우만 누적된 시간에 포함)
                        hours, remainder = divmod(duration.seconds, 3600)
                        minutes, _ = divmod(remainder, 60)
                        summary += f"  └ {name}: {hours}시간 {minutes}분\n"

                    # 각 유저의 누적 시간 체크 및 성공/실패 처리
                    for user_id, total_duration in users.items():
                        total_time = self.user_total_time[i].get(user_id, timedelta())  # 유저별 누적 시간
                        total_hours, remainder = divmod(total_time.seconds, 3600)
                        total_minutes, _ = divmod(remainder, 60)

                        # 주간 사용일 수에 따른 조건 처리
                        used_days = len([1 for j in range(7) if user_id in self.user_total_time[j]])

                        if used_days == 1:
                            # 1일만 사용한 사람은 무조건 실패
                            failed_users.append(name)
                            continue

                        if used_days == 2:
                            # 2일 사용한 사람은 하루 최소 2시간 이상 + 총 4시간 이상이어야 성공
                            if total_time < timedelta(hours=4):  # 총 4시간 이상
                                failed_users.append(name)
                                continue
                            # 하루 최소 2시간 조건 체크
                            daily_condition_met = True
                            for j in range(7):
                                if user_id in self.user_daily_time[j]:
                                    daily_time = self.user_daily_time[j][user_id]
                                    if daily_time < timedelta(hours=2):  # 하루 최소 2시간 이상
                                        daily_condition_met = False
                                        break
                            if not daily_condition_met:
                                failed_users.append(name)
                                continue
                            successful_users.append(name)
                            continue

                        if total_time >= timedelta(hours=4):
                            successful_users.append(name)
                        else:
                            failed_users.append(name)

            # 성공/실패한 유저 출력
            summary += f"\n**성공한 유저**: {', '.join(successful_users)}\n"
            summary += f"**실패한 유저**: {', '.join(failed_users)}\n"

            # 채널에 메시지 전송
            channel = self.get_channel(CHANNEL_ID)
            if channel:
                await channel.send(summary)

            # 🧹 데이터 초기화 (새로운 주 시작)
            self.user_total_time = {i: {} for i in range(7)}
            self.user_daily_time = {i: {} for i in range(7)}  # 하루 이용 시간 초기화
            break  # 주간 요약 한 번만 보내기

# 인텐트 설정
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
intents.guilds = True
intents.members = True

client = MyClient(intents=intents)
client.run(TOKEN)