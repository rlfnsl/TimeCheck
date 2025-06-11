import discord
import asyncio
import json
import os
import re
from datetime import datetime, timedelta
import pytz
from collections import defaultdict

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
CHANNEL_ID = 1346156878111182910
DATA_FILE = "voice_data.json"
EXCLUDED_USERS_FILE = "excluded_users.json"
JOIN_DATA_FILE = "voice_join_data.json"
GUILD_ID = 1327633759427625012

class VoiceTrackerBot(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)
        self.KST = pytz.timezone("Asia/Seoul")
        self.user_join_times = {}  # {user_id: 입장시간}
        self.user_total_time = {str(i): {} for i in range(7)}  # {요일: {유저ID: 누적시간}}
        self.user_daily_time = {str(i): {} for i in range(7)}  # {요일: {유저ID: 하루 이용 시간}}
        self.alarms = {}  # ✅ 알람 저장하는 딕셔너리 추가 ✅
        self.excluded_users = set()  # 제외된 유저 ID 목록
        self.load_data()
        self.load_excluded_users()
        self.load_user_join_times()

    def load_data(self):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.user_total_time = data.get("user_total_time", {str(i): {} for i in range(7)})
                self.user_daily_time = data.get("user_daily_time", {str(i): {} for i in range(7)})
        except FileNotFoundError:
            self.save_data()
    
    def load_excluded_users(self):
        try:
            with open(EXCLUDED_USERS_FILE, "r", encoding="utf-8") as f:
                self.excluded_users = set(json.load(f))
        except FileNotFoundError:
            self.excluded_users = set()
    
    def save_excluded_users(self):
        with open(EXCLUDED_USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(list(self.excluded_users), f, indent=4)
    
    def save_data(self):
        data = {
            "user_total_time": self.user_total_time,
            "user_daily_time": self.user_daily_time
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    async def load_user_join_times(self):
        try:
            with open(JOIN_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                now = datetime.now(self.KST)
                recovered = {}
                channel = self.get_channel(CHANNEL_ID)

                # 🔍 현재 음성 채널에 있는 유저 목록 파악
                guild = self.get_guild(GUILD_ID)
                if not guild:
                    print("[ERROR] 서버 정보를 불러오지 못했습니다.")
                    return

                # 전체 유저의 음성 상태 확인
                voice_connected_users = {
                    member.id
                    for vc in guild.voice_channels
                    for member in vc.members
                }

                for user_id_str, time_str in data.items():
                    user_id = int(user_id_str)
                    join_time = datetime.fromisoformat(time_str)
                    duration = now - join_time
                    weekday = str(join_time.weekday())

                    if user_id in voice_connected_users:
                        # 🔁 아직 음성 채널에 있으면 그대로 유지
                        recovered[user_id] = join_time
                        print(f"🔗 {user_id} - 여전히 음성 채널에 있음 (유지)")
                        continue

                    if duration >= timedelta(minutes=20):
                        seconds = int(duration.total_seconds())

                        # ✅ 시간 저장
                        self.user_total_time[weekday].setdefault(user_id_str, 0)
                        self.user_daily_time[weekday].setdefault(user_id_str, 0)
                        self.user_total_time[weekday][user_id_str] += seconds
                        self.user_daily_time[weekday][user_id_str] += seconds

                        # ✅ 알림 전송
                        if channel:
                            minutes = seconds // 60
                            await channel.send(f"🔁 <@{user_id}>님은 재부팅 중에도 {minutes}분 동안 공부하셨습니다!")

                        print(f"✅ [자동기록] {user_id} - {minutes}분 인정됨")
                    else:
                        print(f"⏱️ [삭제] {user_id} - 음성에 없고 20분 미만 (제외)")

                self.user_join_times = recovered
                self.save_user_join_times()
                self.save_data()

        except FileNotFoundError:
            self.user_join_times = {}
        except Exception as e:
            print(f"[ERROR] 유저 입장 시간 로드 실패: {e}")
            self.user_join_times = {}




    def save_user_join_times(self):
        try:
            save_dict = {
                str(user_id): time.isoformat()
                for user_id, time in self.user_join_times.items()
            }
            with open(JOIN_DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(save_dict, f, indent=4)
        except Exception as e:
            print(f"[ERROR] 유저 입장 시간 저장 실패: {e}")

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        channel = self.get_channel(CHANNEL_ID)
        if channel:
            await channel.send("✅ 디스코드 봇이 켜졌습니다!")
        
        await self.load_user_join_times() 
        self.loop.create_task(self.send_weekly_summary())

    async def on_message(self, message):
        if message.author.bot:  # 봇이 보낸 메시지는 무시
            return
        if message.content == "!중간정산":
            await self.send_intermediate_summary(message.channel)
        elif message.content == "!진행도":
            await self.send_progress_status(message.channel)
        elif message.content == "!현재상황":
            await self.send_weekly_summary_Test(message.channel)
        elif message.content == "!제외":
            today = datetime.now(self.KST).weekday()
            if today in [0, 1, 2]:  # 월(0), 화(1), 수(2)만 제외 가능
                self.excluded_users.add(str(message.author.id))
                self.save_excluded_users()
                await message.channel.send(f"🚫 {message.author.mention}, 주간 요약에서 제외되었습니다.")
            else:
                await message.channel.send(f"⚠️ {message.author.mention}, 월, 화, 수요일에만 제외할 수 있습니다.")
        elif message.content == "!제외취소":
            self.excluded_users.discard(str(message.author.id))
            self.save_excluded_users()
            await message.channel.send(f"✅ {message.author.mention}, 주간 요약에 다시 포함됩니다.")
        elif re.match(r"^!\d+$", message.content):  # "!숫자" 형식인지 확인
            minutes = int(message.content[1:])  # 숫자 부분만 추출
            await self.set_alarm(message, minutes)
        elif message.content == "!알람삭제":
            await self.cancel_alarm(message)
            # !시간추가 <분>
        elif message.content.startswith("!시간추가"):
            parts = message.content.split()
            if len(parts) != 2:
                return
            try:
                add_minutes = int(parts[1])
                if add_minutes <= 0:
                    return
            except ValueError:
                return

            now = datetime.now(self.KST)
            weekday = str(now.weekday())
            user_id = str(message.author.id)

            self.user_total_time[weekday].setdefault(user_id, 0)
            self.user_daily_time[weekday].setdefault(user_id, 0)
            self.user_total_time[weekday][user_id] += add_minutes * 60
            self.user_daily_time[weekday][user_id] += add_minutes * 60
            self.save_data()

            channel = self.get_channel(CHANNEL_ID)   # ★ 이 부분이 핵심!
            if channel:
                await channel.send(
                    f"⏫ <@{user_id}> ({message.author.display_name})님이 {add_minutes}분을 수동 추가했습니다! ({now.strftime('%Y-%m-%d')})"
                )
            return



    async def on_voice_state_update(self, member, before, after):
        now = datetime.now(self.KST)
        weekday = str(now.weekday())
        channel = self.get_channel(CHANNEL_ID)

        if before.channel is None and after.channel is not None:
            # 입장
            self.user_join_times[member.id] = now
            self.save_user_join_times()  # ✅ 저장
        elif before.channel is not None and after.channel is None:
            # 퇴장
            if member.id in self.user_join_times:
                join_time = self.user_join_times.pop(member.id)
                self.save_user_join_times()  # ✅ 삭제 반영
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

                user_total_time = defaultdict(int)
                user_active_days = defaultdict(int)
                daily_hours = defaultdict(lambda: defaultdict(int))

                summary = await self.generate_weekly_summary()

                channel = self.get_channel(CHANNEL_ID)
                if channel:
                    await channel.send(summary)

                self.user_total_time = {str(i): {} for i in range(7)}
                self.user_daily_time = {str(i): {} for i in range(7)}
                self.excluded_users.clear()
                self.save_data()
                self.save_excluded_users()

                await asyncio.sleep(1)

    async def send_weekly_summary_Test(self, channel):
        """명령어로 호출 시 주간 요약을 보내는 함수"""
        summary = await self.generate_weekly_summary()
        await channel.send(summary)

    async def generate_weekly_summary(self):
        """주간 스터디 이용 요약을 생성하는 함수"""
        guild = self.get_guild(GUILD_ID)  # 서버 객체 가져오기
        if not guild:
            return "⚠️ 서버 정보를 가져올 수 없습니다."

        all_members = {str(member.id): member for member in guild.members if not member.bot} 
        user_total_time = defaultdict(int)
        user_active_days = defaultdict(int)
        daily_hours = defaultdict(lambda: defaultdict(int))

        summary = "**📊 주간 스터디 이용 요약**\n"
        days = ["월", "화", "수", "목", "금", "토", "일"]
        successful_users = set()  # ✅ 중복 방지를 위해 `set()` 사용
        failed_users = set()  # ✅ 중복 방지를 위해 `set()` 사용
        excluded_users_list = {f"<@{user_id}>" for user_id in self.excluded_users}  # `set` 사용

        # 🔹 사용자별 총 시간 및 활성 요일 저장
        for day, records in self.user_total_time.items():
            for user_id, seconds in records.items():
                if user_id in self.excluded_users:
                    continue  # 제외된 유저는 건너뜀
                daily_hours[user_id][day] = seconds
                user_active_days[user_id] += 1

        # 🔹 성공 / 실패 판별
        for user_id, active_days in user_active_days.items():
            valid_total_time = 0
            valid_days = 0

            for day, seconds in daily_hours[user_id].items():
                hours = seconds / 3600
                if active_days == 2 and hours >= 1:  
                    valid_total_time += seconds
                    valid_days += 1
                elif active_days == 1 and hours >=4:
                    valid_total_time += seconds
                    valid_days += 1
                elif active_days >= 3 and hours >= 1:
                    valid_total_time += seconds
                    valid_days += 1

            if valid_days < 1 or valid_total_time < 4 * 3600:
                failed_users.add(f"<@{user_id}>")  # ✅ `set`에 추가하여 중복 방지
            else:
                successful_users.add(f"<@{user_id}>")  # ✅ `set`에 추가하여 중복 방지

        # ✅ 기록이 없는 사람도 실패한 닝겐에 추가
        for user_id in all_members.keys():
            if user_id not in self.user_total_time["0"] and user_id not in self.excluded_users:
                failed_users.add(f"<@{user_id}>")  # ✅ `set`에 추가하여 중복 방지

        # 🔹 요일별 기록 추가
        summary += "\n".join([
            f"🗓 {days[int(day)]}요일:\n" + (
                "\n".join([f"  └ <@{user_id}>: {seconds // 3600}시간 {seconds % 3600 // 60}분"
                        for user_id, seconds in records.items()])
                if records else "  └ 기록 없음"
            )
            for day, records in self.user_total_time.items()
        ])

        failed_users = sorted(set(failed_users) - set(successful_users))  # 성공한 유저는 실패 목록에서 제거
        successful_users = sorted(set(successful_users))

        # 🔹 최종 결과 출력 (set을 다시 리스트로 변환해서 정렬)
        summary += f"\n**✅ 성공한 닝겐**: {', '.join(sorted(successful_users)) if successful_users else '없음'}\n"
        summary += f"**❌ 실패한 닝겐**: {', '.join(sorted(failed_users)) if failed_users else '없음'}\n"
        summary += f"\n🚫 **제외된 닝겐**: {', '.join(sorted(excluded_users_list)) if excluded_users_list else '없음'}"

        return summary



intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.messages = True  # 메시지 관련 인텐트 활성화
intents.message_content = True  # 메시지 내용을 읽을 수 있도록 추가!

client = VoiceTrackerBot(intents=intents)
client.run(TOKEN)
