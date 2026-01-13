import discord
import asyncio
import json
import os
import re
from datetime import datetime, timedelta
import pytz
from collections import defaultdict

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
CHANNEL_ID = 1346156878111182910
DATA_FILE = "voice_data.json"
EXCLUDED_USERS_FILE = "excluded_users.json"
JOIN_DATA_FILE = "voice_join_data.json"
GUILD_ID = 1327633759427625012


class VoiceTrackerBot(discord.Client):
    def __init__(self, intents):
        super().__init__(intents=intents)

        self.KST = pytz.timezone("Asia/Seoul")

        self.user_join_times = {}
        self.user_total_time = {str(i): {} for i in range(7)}
        self.user_daily_time = {str(i): {} for i in range(7)}
        self.alarms = {}
        self.excluded_users = set()

        self.load_data()
        self.load_excluded_users()
        self.load_user_join_times_file()

    def load_data(self):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.user_total_time = data.get("user_total_time", {str(i): {} for i in range(7)})
                self.user_daily_time = data.get("user_daily_time", {str(i): {} for i in range(7)})
        except FileNotFoundError:
            self.save_data()
        except Exception as e:
            print(f"[ERROR] 데이터 로드 실패: {e}")

    def save_data(self):
        data = {
            "user_total_time": self.user_total_time,
            "user_daily_time": self.user_daily_time,
        }
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] 데이터 저장 실패: {e}")

    def load_excluded_users(self):
        try:
            with open(EXCLUDED_USERS_FILE, "r", encoding="utf-8") as f:
                self.excluded_users = set(json.load(f))
        except FileNotFoundError:
            self.excluded_users = set()
        except Exception as e:
            print(f"[ERROR] 제외 유저 로드 실패: {e}")
            self.excluded_users = set()

    def save_excluded_users(self):
        try:
            with open(EXCLUDED_USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(self.excluded_users), f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] 제외 유저 저장 실패: {e}")

    def load_user_join_times_file(self):
        try:
            with open(JOIN_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            recovered = {}
            for user_id_str, time_str in data.items():
                try:
                    recovered[int(user_id_str)] = datetime.fromisoformat(time_str)
                except Exception:
                    continue
            self.user_join_times = recovered
        except FileNotFoundError:
            self.user_join_times = {}
        except Exception as e:
            print(f"[ERROR] 유저 입장 시간 파일 로드 실패: {e}")
            self.user_join_times = {}

    def save_user_join_times(self):
        try:
            save_dict = {str(user_id): time.isoformat() for user_id, time in self.user_join_times.items()}
            with open(JOIN_DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(save_dict, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] 유저 입장 시간 저장 실패: {e}")

    def is_admin(self, member: discord.Member) -> bool:
        perms = member.guild_permissions
        return perms.administrator or perms.manage_guild

    def reset_all_records(self):
        self.user_total_time = {str(i): {} for i in range(7)}
        self.user_daily_time = {str(i): {} for i in range(7)}
        self.excluded_users.clear()
        self.save_data()
        self.save_excluded_users()

    def reset_user_records(self, user_id: int):
        uid = str(user_id)
        for i in range(7):
            day = str(i)
            if uid in self.user_total_time.get(day, {}):
                del self.user_total_time[day][uid]
            if uid in self.user_daily_time.get(day, {}):
                del self.user_daily_time[day][uid]
        if uid in self.excluded_users:
            self.excluded_users.discard(uid)
            self.save_excluded_users()
        self.save_data()

    def find_member_by_name(self, guild: discord.Guild, name: str):
        key = name.strip().lower()
        if not key:
            return None, "이름이 비어있음"

        exact = []
        partial = []

        for m in guild.members:
            if m.bot:
                continue
            dn = (m.display_name or "").lower()
            un = (m.name or "").lower()

            if key == dn or key == un:
                exact.append(m)
            elif key in dn or key in un:
                partial.append(m)

        if len(exact) == 1:
            return exact[0], None
        if len(exact) > 1:
            return None, "동일한 이름이 여러명"

        if len(partial) == 1:
            return partial[0], None
        if len(partial) > 1:
            return None, "비슷한 이름이 여러명"

        return None, "대상 없음"

    async def recover_join_times_on_boot(self):
        guild = self.get_guild(GUILD_ID)
        if not guild:
            print("[ERROR] 서버 정보를 불러오지 못했습니다.")
            return

        channel = self.get_channel(CHANNEL_ID)
        now = datetime.now(self.KST)

        voice_connected_users = {
            member.id
            for vc in guild.voice_channels
            for member in vc.members
        }

        recovered = {}

        for user_id, join_time in list(self.user_join_times.items()):
            if user_id in voice_connected_users:
                recovered[user_id] = join_time
                continue

            duration = now - join_time
            if duration >= timedelta(minutes=20):
                seconds = int(duration.total_seconds())
                weekday = str(join_time.weekday())
                uid = str(user_id)

                self.user_total_time[weekday].setdefault(uid, 0)
                self.user_daily_time[weekday].setdefault(uid, 0)
                self.user_total_time[weekday][uid] += seconds
                self.user_daily_time[weekday][uid] += seconds

                if channel:
                    minutes = seconds // 60
                    await channel.send(f"🔁 <@{user_id}>님은 재부팅 중에도 {minutes}분 동안 공부하셨습니다!")
            else:
                pass

        self.user_join_times = recovered
        self.save_user_join_times()
        self.save_data()

    async def flush_active_voice_sessions_until(self, cutoff: datetime):
        guild = self.get_guild(GUILD_ID)
        if not guild:
            return

        voice_connected_users = {
            member.id
            for vc in guild.voice_channels
            for member in vc.members
        }

        for user_id, join_time in list(self.user_join_times.items()):
            if user_id not in voice_connected_users:
                continue

            if join_time >= cutoff:
                self.user_join_times[user_id] = cutoff
                continue

            total_seconds = int((cutoff - join_time).total_seconds())
            if total_seconds < 20 * 60:
                self.user_join_times[user_id] = cutoff
                continue

            current = join_time
            while current < cutoff:
                next_midnight = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                segment_end = cutoff if cutoff < next_midnight else next_midnight

                seg_seconds = int((segment_end - current).total_seconds())
                if seg_seconds > 0:
                    day_key = str(current.weekday())
                    uid = str(user_id)

                    self.user_total_time[day_key].setdefault(uid, 0)
                    self.user_daily_time[day_key].setdefault(uid, 0)
                    self.user_total_time[day_key][uid] += seg_seconds
                    self.user_daily_time[day_key][uid] += seg_seconds

                current = segment_end

            self.user_join_times[user_id] = cutoff

        self.save_user_join_times()
        self.save_data()

    async def on_ready(self):
        print(f"Logged in as {self.user}")

        channel = self.get_channel(CHANNEL_ID)
        if channel:
            await channel.send("✅ 디스코드 봇이 켜졌습니다!")

        await self.recover_join_times_on_boot()
        self.loop.create_task(self.send_weekly_summary())

    async def on_message(self, message):
        if message.author.bot:
            return

        if message.content == "!중간정산":
            await self.send_intermediate_summary(message.channel)
            return

        if message.content == "!진행도":
            await self.send_progress_status(message.channel)
            return

        if message.content == "!현재상황":
            await self.send_weekly_summary_Test(message.channel)
            return

        if message.content == "!제외":
            today = datetime.now(self.KST).weekday()
            if today in [0, 1, 2]:
                self.excluded_users.add(str(message.author.id))
                self.save_excluded_users()
                await message.channel.send(f"🚫 {message.author.mention}, 주간 요약에서 제외되었습니다.")
            else:
                await message.channel.send(f"⚠️ {message.author.mention}, 월, 화, 수요일에만 제외할 수 있습니다.")
            return

        if message.content == "!제외취소":
            self.excluded_users.discard(str(message.author.id))
            self.save_excluded_users()
            await message.channel.send(f"✅ {message.author.mention}, 주간 요약에 다시 포함됩니다.")
            return

        if message.content.startswith("!초기화"):
            guild = self.get_guild(GUILD_ID)
            if not guild:
                await message.channel.send("⚠️ 서버 정보를 가져올 수 없습니다.")
                return

            if not self.is_admin(message.author):
                await message.channel.send("⚠️ 이 명령은 관리자만 사용할 수 있습니다.")
                return

            parts = message.content.split(maxsplit=1)

            if len(parts) == 1:
                self.reset_all_records()
                await message.channel.send("✅ 모든 기록을 초기화했습니다.")
                return

            target = parts[1].strip()

            if message.mentions:
                m = message.mentions[0]
                self.reset_user_records(m.id)
                await message.channel.send(f"✅ {m.mention} 기록을 초기화했습니다.")
                return

            member, err = self.find_member_by_name(guild, target)
            if member is None:
                await message.channel.send(f"⚠️ 대상 찾기 실패: {err}")
                return

            self.reset_user_records(member.id)
            await message.channel.send(f"✅ {member.mention} 기록을 초기화했습니다.")
            return

        if re.match(r"^!\d+$", message.content):
            minutes = int(message.content[1:])
            await self.set_alarm(message, minutes)
            return

        if message.content == "!알람삭제":
            await self.cancel_alarm(message)
            return

        if message.content.startswith("!시간추가"):
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

            channel = self.get_channel(CHANNEL_ID)
            if channel:
                await channel.send(
                    f"⏫ <@{user_id}> ({message.author.display_name})님이 {add_minutes}분을 수동 추가했습니다! ({now.strftime('%Y-%m-%d')})"
                )
            return

    async def on_voice_state_update(self, member, before, after):
        now = datetime.now(self.KST)
        channel = self.get_channel(CHANNEL_ID)

        if before.channel is None and after.channel is not None:
            self.user_join_times[member.id] = now
            self.save_user_join_times()
            return

        if before.channel is not None and after.channel is None:
            if member.id not in self.user_join_times:
                return

            join_time = self.user_join_times.pop(member.id)
            self.save_user_join_times()

            duration = now - join_time
            if duration < timedelta(minutes=20):
                return

            total_seconds = int(duration.total_seconds())

            current = join_time
            cutoff = now
            while current < cutoff:
                next_midnight = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                segment_end = cutoff if cutoff < next_midnight else next_midnight

                seg_seconds = int((segment_end - current).total_seconds())
                if seg_seconds > 0:
                    day_key = str(current.weekday())
                    uid = str(member.id)

                    self.user_total_time[day_key].setdefault(uid, 0)
                    self.user_daily_time[day_key].setdefault(uid, 0)
                    self.user_total_time[day_key][uid] += seg_seconds
                    self.user_daily_time[day_key][uid] += seg_seconds

                current = segment_end

            self.save_data()

            if channel:
                await channel.send(f"🔴 {join_time.strftime('%H:%M:%S')} ~ {now.strftime('%H:%M:%S')} ({member.display_name})")
            return

    async def send_intermediate_summary(self, channel):
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
        now = datetime.now(self.KST)
        if not self.user_join_times:
            await channel.send("현재 음성 채널에 있는 사람이 없습니다.")
            return

        summary = "**🔄 현재 진행도 현황**\n"
        for user_id, join_time in self.user_join_times.items():
            duration = now - join_time
            hours, remainder = divmod(int(duration.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            summary += f"🔹 <@{user_id}>: {hours}시간 {minutes}분째 진행 중\n"

        await channel.send(summary)

    async def set_alarm(self, message, minutes):
        if message.author.id in self.alarms:
            await message.channel.send(f"⚠️ {message.author.mention}, 이미 설정된 알람이 있습니다! 먼저 삭제하세요. (`!알람삭제`)")
            return

        task = asyncio.create_task(self.alarm_task(message, minutes))
        self.alarms[message.author.id] = task
        await message.channel.send(f"⏳ {minutes}분 뒤에 알람을 설정했습니다! ({message.author.mention})")

    async def alarm_task(self, message, minutes):
        await asyncio.sleep(minutes * 60)
        await message.channel.send(f"⏰ {minutes}분이 지났습니다! ({message.author.mention})")
        self.alarms.pop(message.author.id, None)

    async def cancel_alarm(self, message):
        if message.author.id in self.alarms:
            self.alarms[message.author.id].cancel()
            del self.alarms[message.author.id]
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

            await self.flush_active_voice_sessions_until(target_time)

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
        now = datetime.now(self.KST)
        cutoff = now.replace(second=0, microsecond=0)
        await self.flush_active_voice_sessions_until(cutoff)

        summary = await self.generate_weekly_summary()
        await channel.send(summary)

    async def generate_weekly_summary(self):
        guild = self.get_guild(GUILD_ID)
        if not guild:
            return "⚠️ 서버 정보를 가져올 수 없습니다."

        all_members = {str(member.id): member for member in guild.members if not member.bot}

        user_active_days = defaultdict(int)
        daily_hours = defaultdict(lambda: defaultdict(int))

        summary = "**📊 주간 스터디 이용 요약**\n"
        days = ["월", "화", "수", "목", "금", "토", "일"]

        successful_users = set()
        failed_users = set()
        excluded_users_list = {f"<@{user_id}>" for user_id in self.excluded_users}

        for day, records in self.user_total_time.items():
            for user_id, seconds in records.items():
                if user_id in self.excluded_users:
                    continue
                daily_hours[user_id][day] = seconds
                user_active_days[user_id] += 1

        for user_id, active_days in user_active_days.items():
            valid_total_time = 0
            valid_days = 0

            for day, seconds in daily_hours[user_id].items():
                hours = seconds / 3600
                if active_days == 2 and hours >= 1:
                    valid_total_time += seconds
                    valid_days += 1
                elif active_days == 1 and hours >= 4:
                    valid_total_time += seconds
                    valid_days += 1
                elif active_days >= 3 and hours >= 1:
                    valid_total_time += seconds
                    valid_days += 1

            if valid_days < 1 or valid_total_time < 4 * 3600:
                failed_users.add(f"<@{user_id}>")
            else:
                successful_users.add(f"<@{user_id}>")

        for user_id in all_members.keys():
            if user_id in self.excluded_users:
                continue
            if user_id not in user_active_days:
                failed_users.add(f"<@{user_id}>")

        summary += "\n".join(
            [
                f"🗓 {days[int(day)]}요일:\n"
                + (
                    "\n".join(
                        [
                            f"  └ <@{user_id}>: {seconds // 3600}시간 {seconds % 3600 // 60}분"
                            for user_id, seconds in records.items()
                        ]
                    )
                    if records
                    else "  └ 기록 없음"
                )
                for day, records in self.user_total_time.items()
            ]
        )

        failed_users = sorted(set(failed_users) - set(successful_users))
        successful_users = sorted(set(successful_users))

        summary += f"\n**✅ 성공한 닝겐**: {', '.join(successful_users) if successful_users else '없음'}\n"
        summary += f"**❌ 실패한 닝겐**: {', '.join(failed_users) if failed_users else '없음'}\n"
        summary += f"\n🚫 **제외된 닝겐**: {', '.join(sorted(excluded_users_list)) if excluded_users_list else '없음'}"

        return summary


intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.messages = True
intents.message_content = True

client = VoiceTrackerBot(intents=intents)
client.run(TOKEN)
