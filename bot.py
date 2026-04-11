import discord
from discord.ext import commands
import threading
import time
import random
import string
import json
import os
import requests
from discord.ui import View, Button
from datetime import datetime, timedelta, timezone

from client.mess import (
    FacebookMQTTAllInOne, create_facebook_client, send_simple_message,
    share_simple_link, share_simple_contact, send_simple_poll, set_simple_theme,
    rename_facebook_group, block_facebook_user, unblock_facebook_user,
    add_users_to_group, get_facebook_threads, dataGetHome, fbTools, THEMES
)

from client.gmail import parse_accounts, gmail_nhay_send, gmail_treo_send, gmail_treo_anh_send
from client.dis import dis_nhay_send_messages, dis_treo_send_messages, dis_nhay_tag_send_messages
from client.tele import run_tele_treo, run_tele_nhay

try:
    from client.zalo import zalo_send_messages_with_cookie, zalo_get_group_list, zalo_get_friend_list, ThreadType
    ZALO_AVAILABLE = True
except ImportError:
    ZALO_AVAILABLE = False

os.system("clear")
TOKEN = input("Nhập Token Bot: ").strip()
ADMIN_ID = int(input("Nhập ID Admin: ").strip())
PREFIX = input("Nhập Prefix: ").strip()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

active_tasks = {}
stop_flags = {}
member_name_cache = {}

def load_keys():
    try:
        with open("key.json", "r") as f:
            return json.load(f)
    except:
        return {}

def save_keys(keys):
    with open("key.json", "w") as f:
        json.dump(keys, f, indent=4)

def has_valid_key(user_id):
    keys = load_keys()
    if str(user_id) in keys:
        expire_time = datetime.fromisoformat(keys[str(user_id)])
        if expire_time.tzinfo is None:
            expire_time = expire_time.replace(tzinfo=timezone.utc)
        return expire_time > datetime.now(timezone.utc)
    return False

def is_admin(ctx):
    return ctx.author.id == ADMIN_ID

def is_authorized(interaction):
    return has_valid_key(interaction.user.id) or interaction.user.id == ADMIN_ID

def generate_task_id():
    return ''.join(random.choices(string.ascii_uppercase, k=6))

def get_member_name_fast(cookie: str, thread_id: str, user_id: str) -> str:
    cache_key = f"{thread_id}_{user_id}"
    if cache_key in member_name_cache:
        return member_name_cache[cache_key]
    try:
        data_fb = dataGetHome(cookie)
        fb_tool = fbTools(data_fb, thread_id)
        if fb_tool.getAllThreadList():
            members = fb_tool.typeCommand("exportMemberListToJson")
            if isinstance(members, list):
                for member_json in members:
                    try:
                        member_data = json.loads(member_json)
                        for uid, info in member_data.items():
                            if uid == user_id:
                                name = info.get("nameFB", "")
                                if name:
                                    member_name_cache[cache_key] = name
                                    return name
                    except:
                        continue
    except:
        pass
    fallback = f"User_{user_id[-6:]}"
    member_name_cache[cache_key] = fallback
    return fallback

def get_all_member_names_fast(cookie: str, thread_id: str, user_ids: list) -> dict:
    result = {}
    uncached_ids = []
    for uid in user_ids:
        cache_key = f"{thread_id}_{uid}"
        if cache_key in member_name_cache:
            result[uid] = member_name_cache[cache_key]
        else:
            uncached_ids.append(uid)
    if uncached_ids:
        try:
            data_fb = dataGetHome(cookie)
            fb_tool = fbTools(data_fb, thread_id)
            if fb_tool.getAllThreadList():
                members = fb_tool.typeCommand("exportMemberListToJson")
                if isinstance(members, list):
                    id_to_name = {}
                    for member_json in members:
                        try:
                            member_data = json.loads(member_json)
                            for uid, info in member_data.items():
                                name = info.get("nameFB", "")
                                if name:
                                    id_to_name[uid] = name
                        except:
                            continue
                    for uid in uncached_ids:
                        if uid in id_to_name:
                            name = id_to_name[uid]
                            result[uid] = name
                            member_name_cache[f"{thread_id}_{uid}"] = name
                        else:
                            fallback = f"User_{uid[-6:]}"
                            result[uid] = fallback
                            member_name_cache[f"{thread_id}_{uid}"] = fallback
        except:
            for uid in uncached_ids:
                fallback = f"User_{uid[-6:]}"
                result[uid] = fallback
                member_name_cache[f"{thread_id}_{uid}"] = fallback
    return result

class GmailView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180.0)
    
    @discord.ui.button(label="Nhây Gmail", style=discord.ButtonStyle.red, row=0)
    async def nhay_gmail_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        modal = NhayGmailModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Treo Gmail", style=discord.ButtonStyle.green, row=0)
    async def treo_gmail_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        modal = TreoGmailModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Treo Ảnh Gmail", style=discord.ButtonStyle.blurple, row=1)
    async def treo_anh_gmail_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        modal = TreoAnhGmailModal()
        await interaction.response.send_modal(modal)

class NhayGmailModal(discord.ui.Modal, title="Nhây Gmail"):
    accounts = discord.ui.TextInput(label="Tài khoản Gmail", style=discord.TextStyle.paragraph, required=True, placeholder="email|pass,email|pass,...")
    to_email = discord.ui.TextInput(label="Email nhận", required=True, placeholder="email@example.com")
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 10", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            accounts = parse_accounts(self.accounts.value)
            to_email = self.to_email.value.strip()
            delay = float(self.delay.value.strip())
            if not accounts:
                await interaction.response.send_message("Không có tài khoản Gmail hợp lệ!", ephemeral=True)
                return
            try:
                with open("nhay.txt", "r", encoding="utf-8") as f:
                    if not [line.strip() for line in f if line.strip()]:
                        await interaction.response.send_message("File nhay.txt trống!", ephemeral=True)
                        return
            except FileNotFoundError:
                await interaction.response.send_message("Không tìm thấy file nhay.txt!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                gmail_nhay_send(accounts, to_email, delay, task_id, stop_flags)
            except Exception as e:
                print(f"[{task_id}] Gmail Nhây Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Nhây Gmail", "to_email": to_email, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Nhây Gmail thành công", color=0xEA4335)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Email nhận", value=f"`{to_email}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TreoGmailModal(discord.ui.Modal, title="Treo Gmail"):
    accounts = discord.ui.TextInput(label="Tài khoản Gmail", style=discord.TextStyle.paragraph, required=True, placeholder="email|pass,email|pass,...")
    to_email = discord.ui.TextInput(label="Email nhận", required=True, placeholder="email@example.com")
    content = discord.ui.TextInput(label="Nội dung", style=discord.TextStyle.paragraph, required=True, placeholder="Nội dung email")
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 10", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            accounts = parse_accounts(self.accounts.value)
            to_email = self.to_email.value.strip()
            content = self.content.value.strip()
            delay = float(self.delay.value.strip())
            if not accounts:
                await interaction.response.send_message("Không có tài khoản Gmail hợp lệ!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                gmail_treo_send(accounts, to_email, content, delay, task_id, stop_flags)
            except Exception as e:
                print(f"[{task_id}] Gmail Treo Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Treo Gmail", "to_email": to_email, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Treo Gmail thành công", color=0xEA4335)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Email nhận", value=f"`{to_email}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TreoAnhGmailModal(discord.ui.Modal, title="Treo Ảnh Gmail"):
    accounts = discord.ui.TextInput(label="Tài khoản Gmail", style=discord.TextStyle.paragraph, required=True, placeholder="email|pass,email|pass,...")
    to_email = discord.ui.TextInput(label="Email nhận", required=True, placeholder="email@example.com")
    image_url = discord.ui.TextInput(label="Link ảnh", required=True, placeholder="https://example.com/image.jpg")
    subject = discord.ui.TextInput(label="Tiêu đề", required=True, placeholder="Tiêu đề email")
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 10", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            accounts = parse_accounts(self.accounts.value)
            to_email = self.to_email.value.strip()
            image_url = self.image_url.value.strip()
            subject = self.subject.value.strip()
            delay = float(self.delay.value.strip())
            if not accounts:
                await interaction.response.send_message("Không có tài khoản Gmail hợp lệ!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                gmail_treo_anh_send(accounts, to_email, image_url, subject, delay, task_id, stop_flags)
            except Exception as e:
                print(f"[{task_id}] Gmail Treo Ảnh Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Treo Ảnh Gmail", "to_email": to_email, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Treo Ảnh Gmail thành công", color=0xEA4335)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Email nhận", value=f"`{to_email}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class DiscordView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180.0)
    
    @discord.ui.button(label="Nhây Discord", style=discord.ButtonStyle.blurple, row=0)
    async def nhay_discord_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        modal = NhayDiscordModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Nhây Tag Discord", style=discord.ButtonStyle.red, row=0)
    async def nhay_tag_discord_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        modal = NhayTagDiscordModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Treo Discord", style=discord.ButtonStyle.green, row=1)
    async def treo_discord_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        modal = TreoDiscordModal()
        await interaction.response.send_modal(modal)

class NhayDiscordModal(discord.ui.Modal, title="Nhây Discord"):
    token = discord.ui.TextInput(label="Discord Token", style=discord.TextStyle.paragraph, required=True, placeholder="Nhập token Discord...")
    channel_id = discord.ui.TextInput(label="Channel ID", required=True, placeholder="Nhập ID kênh, cách nhau bằng dấu phẩy")
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 5", required=True)
    use_typing = discord.ui.TextInput(label="Soạn tin (true/false)", placeholder="true hoặc false", required=False, default="false")

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            token = self.token.value.strip()
            channel_ids = [cid.strip() for cid in self.channel_id.value.split(",") if cid.strip()]
            delay = float(self.delay.value.strip())
            use_typing = self.use_typing.value.strip().lower() == "true"
            try:
                with open("nhay.txt", "r", encoding="utf-8") as f:
                    if not [line.strip() for line in f if line.strip()]:
                        await interaction.response.send_message("File nhay.txt trống!", ephemeral=True)
                        return
            except FileNotFoundError:
                await interaction.response.send_message("Không tìm thấy file nhay.txt!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                dis_nhay_send_messages(token, channel_ids, delay, task_id, stop_flags, use_typing)
            except Exception as e:
                print(f"[{task_id}] Discord Nhây Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Nhây Discord", "channel_ids": channel_ids, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Nhây Discord thành công", color=0x5865F2)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Channel ID", value=f"`{', '.join(channel_ids)}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class NhayTagDiscordModal(discord.ui.Modal, title="Nhây Tag Discord"):
    token = discord.ui.TextInput(label="Discord Token", style=discord.TextStyle.paragraph, required=True, placeholder="Nhập token Discord...")
    channel_id = discord.ui.TextInput(label="Channel ID", required=True, placeholder="Nhập ID kênh, cách nhau bằng dấu phẩy")
    tag_id = discord.ui.TextInput(label="User ID cần tag", required=True, placeholder="Nhập ID người dùng cần tag")
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 5", required=True)
    use_typing = discord.ui.TextInput(label="Soạn tin (true/false)", placeholder="true hoặc false", required=False, default="false")

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            token = self.token.value.strip()
            channel_ids = [cid.strip() for cid in self.channel_id.value.split(",") if cid.strip()]
            tag_id = self.tag_id.value.strip()
            delay = float(self.delay.value.strip())
            use_typing = self.use_typing.value.strip().lower() == "true"
            try:
                with open("nhay.txt", "r", encoding="utf-8") as f:
                    if not [line.strip() for line in f if line.strip()]:
                        await interaction.response.send_message("File nhay.txt trống!", ephemeral=True)
                        return
            except FileNotFoundError:
                await interaction.response.send_message("Không tìm thấy file nhay.txt!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                dis_nhay_tag_send_messages(token, channel_ids, delay, task_id, stop_flags, tag_id, use_typing)
            except Exception as e:
                print(f"[{task_id}] Discord Nhây Tag Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Nhây Tag Discord", "channel_ids": channel_ids, "tag_id": tag_id, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Nhây Tag Discord thành công", color=0x5865F2)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Channel ID", value=f"`{', '.join(channel_ids)}`", inline=False)
        embed.add_field(name="User Tag", value=f"`{tag_id}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TreoDiscordModal(discord.ui.Modal, title="Treo Discord"):
    token = discord.ui.TextInput(label="Discord Token", style=discord.TextStyle.paragraph, required=True, placeholder="Nhập token Discord...")
    channel_id = discord.ui.TextInput(label="Channel ID", required=True, placeholder="Nhập ID kênh, cách nhau bằng dấu phẩy")
    content = discord.ui.TextInput(label="Nội Dung", style=discord.TextStyle.paragraph, required=True, placeholder="Nội dung tin nhắn")
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 5", required=True)
    use_typing = discord.ui.TextInput(label="Soạn tin (true/false)", placeholder="true hoặc false", required=False, default="false")

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            token = self.token.value.strip()
            channel_ids = [cid.strip() for cid in self.channel_id.value.split(",") if cid.strip()]
            content = self.content.value.strip()
            delay = float(self.delay.value.strip())
            use_typing = self.use_typing.value.strip().lower() == "true"
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                dis_treo_send_messages(token, channel_ids, content, delay, task_id, stop_flags, use_typing)
            except Exception as e:
                print(f"[{task_id}] Discord Treo Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Treo Discord", "channel_ids": channel_ids, "content": content, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Treo Discord thành công", color=0x5865F2)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Channel ID", value=f"`{', '.join(channel_ids)}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TelegramView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180.0)
    
    @discord.ui.button(label="Treo Telegram", style=discord.ButtonStyle.blurple, row=0)
    async def treo_tele_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        modal = TreoTeleModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Nhây Telegram", style=discord.ButtonStyle.green, row=0)
    async def nhay_tele_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        modal = NhayTeleModal()
        await interaction.response.send_modal(modal)

class TreoTeleModal(discord.ui.Modal, title="Treo Telegram"):
    api_info = discord.ui.TextInput(label="API ID | API Hash", required=True, placeholder="API_ID|API_HASH")
    phone = discord.ui.TextInput(label="Số điện thoại", required=True, placeholder="+84123456789")
    target_ids = discord.ui.TextInput(label="ID Targets", required=True, placeholder="Nhập ID, cách nhau bằng dấu phẩy")
    content = discord.ui.TextInput(label="Nội Dung", style=discord.TextStyle.paragraph, required=True, placeholder="Nhập nội dung tin nhắn")
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 5", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            api_parts = self.api_info.value.strip().split('|')
            if len(api_parts) != 2:
                await interaction.response.send_message("Sai định dạng API! Vui lòng nhập: API_ID|API_HASH", ephemeral=True)
                return
            api_id = int(api_parts[0].strip())
            api_hash = api_parts[1].strip()
            phone = self.phone.value.strip()
            target_ids = [tid.strip() for tid in self.target_ids.value.split(",") if tid.strip()]
            content = self.content.value.strip()
            delay = float(self.delay.value.strip())
            if not content:
                await interaction.response.send_message("Nội dung không được để trống!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("API ID và Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                run_tele_treo(api_id, api_hash, phone, target_ids, content, delay, task_id, stop_flags)
            except Exception as e:
                print(f"[{task_id}] Telegram Treo Error: {e}")
            finally:
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Treo Telegram", "target_ids": target_ids, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Treo Telegram thành công", color=0x0088cc)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Target IDs", value=f"`{', '.join(target_ids)}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class NhayTeleModal(discord.ui.Modal, title="Nhây Telegram"):
    api_info = discord.ui.TextInput(label="API ID | API Hash", required=True, placeholder="API_ID|API_HASH")
    phone = discord.ui.TextInput(label="Số điện thoại", required=True, placeholder="+84123456789")
    target_ids = discord.ui.TextInput(label="ID Targets", required=True, placeholder="Nhập ID, cách nhau bằng dấu phẩy")
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 5", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            api_parts = self.api_info.value.strip().split('|')
            if len(api_parts) != 2:
                await interaction.response.send_message("Sai định dạng API! Vui lòng nhập: API_ID|API_HASH", ephemeral=True)
                return
            api_id = int(api_parts[0].strip())
            api_hash = api_parts[1].strip()
            phone = self.phone.value.strip()
            target_ids = [tid.strip() for tid in self.target_ids.value.split(",") if tid.strip()]
            delay = float(self.delay.value.strip())
            try:
                with open("nhay.txt", "r", encoding="utf-8") as f:
                    if not [line.strip() for line in f if line.strip()]:
                        await interaction.response.send_message("File nhay.txt trống!", ephemeral=True)
                        return
            except FileNotFoundError:
                await interaction.response.send_message("Không tìm thấy file nhay.txt!", ephemeral=True)
                return
        except ValueError:
            await interaction.response.send_message("API ID và Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                run_tele_nhay(api_id, api_hash, phone, target_ids, delay, task_id, stop_flags)
            except Exception as e:
                print(f"[{task_id}] Telegram Nhây Error: {e}")
            finally:
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Nhây Telegram", "target_ids": target_ids, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Nhây Telegram thành công", color=0x0088cc)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Target IDs", value=f"`{', '.join(target_ids)}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ZaloView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180.0)
    
    @discord.ui.button(label="Nhây Zalo", style=discord.ButtonStyle.blurple, row=0)
    async def nhay_zalo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        if not ZALO_AVAILABLE:
            await interaction.response.send_message("Tính năng Zalo hiện không khả dụng.", ephemeral=True)
            return
        modal = NhayZaloModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Treo Zalo", style=discord.ButtonStyle.green, row=0)
    async def treo_zalo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        if not ZALO_AVAILABLE:
            await interaction.response.send_message("Tính năng Zalo hiện không khả dụng.", ephemeral=True)
            return
        modal = TreoZaloModal()
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Lấy Danh Sách Nhóm Zalo", style=discord.ButtonStyle.red, row=1)
    async def list_group_zalo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        if not ZALO_AVAILABLE:
            await interaction.response.send_message("Tính năng Zalo hiện không khả dụng.", ephemeral=True)
            return
        modal = ListGroupZaloModal()
        await interaction.response.send_modal(modal)

class NhayZaloModal(discord.ui.Modal, title="Nhây Zalo"):
    imei = discord.ui.TextInput(label="IMEI", required=True, placeholder="Nhập IMEI Zalo...")
    cookies = discord.ui.TextInput(label="Cookies", style=discord.TextStyle.paragraph, required=True, placeholder='{"cookie1": "value1", "cookie2": "value2"}')
    thread_ids = discord.ui.TextInput(label="ID Nhóm/Người", required=True, placeholder="Nhập ID, cách nhau bằng dấu phẩy")
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 5", required=True)
    use_typing = discord.ui.TextInput(label="Soạn tin (true/false)", required=False, default="false")

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            imei = self.imei.value.strip()
            cookies = self.cookies.value.strip()
            thread_ids = [tid.strip() for tid in self.thread_ids.value.split(",") if tid.strip()]
            delay = float(self.delay.value.strip())
            use_typing = self.use_typing.value.strip().lower() == "true"
            with open("nhay.txt", "r", encoding="utf-8") as f:
                messages = [line.strip() for line in f if line.strip()]
            if not messages:
                await interaction.response.send_message("File nhay.txt trống!", ephemeral=True)
                return
        except FileNotFoundError:
            await interaction.response.send_message("Không tìm thấy file nhay.txt!", ephemeral=True)
            return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                zalo_send_messages_with_cookie(imei, cookies, thread_ids, messages, delay, task_id, stop_flags, ThreadType.GROUP, use_typing)
            except Exception as e:
                print(f"[{task_id}] Zalo Nhây Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Nhây Zalo", "thread_ids": thread_ids, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Nhây Zalo thành công", color=0x0099ff)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="ID Nhóm", value=f"`{', '.join(thread_ids)}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TreoZaloModal(discord.ui.Modal, title="Treo Zalo"):
    imei = discord.ui.TextInput(label="IMEI", required=True, placeholder="Nhập IMEI Zalo...")
    cookies = discord.ui.TextInput(label="Cookies", style=discord.TextStyle.paragraph, required=True, placeholder='{"cookie1": "value1", "cookie2": "value2"}')
    thread_ids = discord.ui.TextInput(label="ID Nhóm/Người", required=True, placeholder="Nhập ID, cách nhau bằng dấu phẩy")
    content = discord.ui.TextInput(label="Nội Dung", style=discord.TextStyle.paragraph, required=True)
    delay = discord.ui.TextInput(label="Delay (giây)", placeholder="VD: 5", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        try:
            imei = self.imei.value.strip()
            cookies = self.cookies.value.strip()
            thread_ids = [tid.strip() for tid in self.thread_ids.value.split(",") if tid.strip()]
            content = self.content.value.strip()
            delay = float(self.delay.value.strip())
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                zalo_send_messages_with_cookie(imei, cookies, thread_ids, [content], delay, task_id, stop_flags, ThreadType.GROUP, False)
            except Exception as e:
                print(f"[{task_id}] Zalo Treo Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Treo Zalo", "thread_ids": thread_ids, "content": content, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Treo Zalo thành công", color=0x0099ff)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="ID Nhóm", value=f"`{', '.join(thread_ids)}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ListGroupZaloModal(discord.ui.Modal, title="Danh Sách Nhóm Zalo"):
    imei = discord.ui.TextInput(label="IMEI", required=True, placeholder="Nhập IMEI Zalo...")
    cookies = discord.ui.TextInput(label="Cookies", style=discord.TextStyle.paragraph, required=True, placeholder='{"cookie1": "value1"}')

    async def on_submit(self, interaction: discord.Interaction):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền sử dụng bot.", ephemeral=True)
            return
        imei = self.imei.value.strip()
        cookies = self.cookies.value.strip()
        await interaction.response.send_message("🔍 Đang lấy danh sách nhóm Zalo...", ephemeral=True)
        try:
            groups = zalo_get_group_list(imei, cookies)
            if isinstance(groups, dict) and "error" in groups:
                await interaction.followup.send(f"{groups['error']}", ephemeral=True)
                return
            if not groups:
                await interaction.followup.send("Không tìm thấy nhóm nào.", ephemeral=True)
                return
            msg = "📦 **Danh sách nhóm Zalo:**\n"
            for i, group in enumerate(groups, 1):
                msg += f"{i}. {group['name']} — `{group['id']}`\n"
                if len(msg) > 1800:
                    await interaction.followup.send(msg, ephemeral=True)
                    msg = ""
            if msg:
                await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Lỗi: {e}", ephemeral=True)

class TreoThuongModal(discord.ui.Modal, title="Treo Ngôn"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)
    thread_id = discord.ui.TextInput(label="ID Thread", required=True)
    content = discord.ui.TextInput(label="Nội Dung", style=discord.TextStyle.paragraph, required=True)
    delay = discord.ui.TextInput(label="Delay (giây)", required=True)
    use_typing = discord.ui.TextInput(label="Bật Typing (true/false)", required=False, default="false")

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        try:
            cookie = self.cookie.value.strip()
            thread_id = self.thread_id.value.strip()
            content = self.content.value.strip()
            delay = float(self.delay.value.strip())
            use_typing = self.use_typing.value.strip().lower() == "true"
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                client = create_facebook_client(cookie, {"debug": False})
                if client.connect():
                    while not stop_flags.get(task_id, False):
                        if use_typing:
                            typing_time = delay / 2
                            client.send_typing_indicator(thread_id, True)
                            for _ in range(int(typing_time)):
                                if stop_flags.get(task_id, False):
                                    break
                                time.sleep(1)
                            client.send_typing_indicator(thread_id, False)
                        client.send_message(text=content, thread_id=thread_id)
                        for _ in range(int(delay)):
                            if stop_flags.get(task_id, False):
                                break
                            time.sleep(1)
                    client.disconnect()
            except Exception as e:
                print(f"[{task_id}] Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Treo Thường", "thread_id": thread_id, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Treo Ngôn thành công", color=0x3498db)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        embed.add_field(name="Typing", value="Bật" if use_typing else "Tắt", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TreoShareContactModal(discord.ui.Modal, title="Treo Share Contact"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)
    thread_id = discord.ui.TextInput(label="ID Thread", required=True)
    contact_id = discord.ui.TextInput(label="ID Contact", required=True)
    content = discord.ui.TextInput(label="Nội Dung", style=discord.TextStyle.paragraph, required=True)
    delay = discord.ui.TextInput(label="Delay (giây)", required=True)
    use_typing = discord.ui.TextInput(label="Bật Typing (true/false)", required=False, default="false")

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        try:
            cookie = self.cookie.value.strip()
            thread_id = self.thread_id.value.strip()
            contact_id = self.contact_id.value.strip()
            content = self.content.value.strip()
            delay = float(self.delay.value.strip())
            use_typing = self.use_typing.value.strip().lower() == "true"
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                client = create_facebook_client(cookie, {"debug": False})
                if client.connect():
                    while not stop_flags.get(task_id, False):
                        if use_typing:
                            typing_time = delay / 2
                            client.send_typing_indicator(thread_id, True)
                            for _ in range(int(typing_time)):
                                if stop_flags.get(task_id, False):
                                    break
                                time.sleep(1)
                            client.send_typing_indicator(thread_id, False)
                        client.share_contact(contact_id, thread_id, content)
                        for _ in range(int(delay)):
                            if stop_flags.get(task_id, False):
                                break
                            time.sleep(1)
                    client.disconnect()
            except Exception as e:
                print(f"[{task_id}] Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Treo Contact", "thread_id": thread_id, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Treo Share Contact thành công", color=0x3498db)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=False)
        embed.add_field(name="Contact ID", value=f"`{contact_id}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        embed.add_field(name="Typing", value="Bật" if use_typing else "Tắt", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class TreoShareLinkModal(discord.ui.Modal, title="Treo Share Link"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)
    thread_id = discord.ui.TextInput(label="ID Thread", required=True)
    url = discord.ui.TextInput(label="URL", required=True)
    content = discord.ui.TextInput(label="Nội Dung", style=discord.TextStyle.paragraph, required=True)
    delay = discord.ui.TextInput(label="Delay (giây)", required=True)
    use_typing = discord.ui.TextInput(label="Bật Typing (true/false)", required=False, default="false")

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        try:
            cookie = self.cookie.value.strip()
            thread_id = self.thread_id.value.strip()
            url = self.url.value.strip()
            content = self.content.value.strip()
            delay = float(self.delay.value.strip())
            use_typing = self.use_typing.value.strip().lower() == "true"
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                client = create_facebook_client(cookie, {"debug": False})
                if client.connect():
                    while not stop_flags.get(task_id, False):
                        if use_typing:
                            typing_time = delay / 2
                            client.send_typing_indicator(thread_id, True)
                            for _ in range(int(typing_time)):
                                if stop_flags.get(task_id, False):
                                    break
                                time.sleep(1)
                            client.send_typing_indicator(thread_id, False)
                        client.share_link(url, thread_id, content)
                        for _ in range(int(delay)):
                            if stop_flags.get(task_id, False):
                                break
                            time.sleep(1)
                    client.disconnect()
            except Exception as e:
                print(f"[{task_id}] Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Treo Link", "thread_id": thread_id, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Treo Share Link thành công", color=0x3498db)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        embed.add_field(name="Typing", value="Bật" if use_typing else "Tắt", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class NhayThuongModal(discord.ui.Modal, title="Nhây Thường"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)
    thread_id = discord.ui.TextInput(label="ID Thread", required=True)
    delay = discord.ui.TextInput(label="Delay (giây)", required=True)
    use_typing = discord.ui.TextInput(label="Bật Typing (true/false)", required=False, default="false")

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        try:
            cookie = self.cookie.value.strip()
            thread_id = self.thread_id.value.strip()
            delay = float(self.delay.value.strip())
            use_typing = self.use_typing.value.strip().lower() == "true"
            with open("nhay.txt", "r", encoding="utf-8") as f:
                messages = [line.strip() for line in f if line.strip()]
            if not messages:
                await interaction.response.send_message("File nhay.txt trống!", ephemeral=True)
                return
        except FileNotFoundError:
            await interaction.response.send_message("Không tìm thấy nhay.txt!", ephemeral=True)
            return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                client = create_facebook_client(cookie, {"debug": False})
                if client.connect():
                    idx = 0
                    while not stop_flags.get(task_id, False):
                        msg = messages[idx % len(messages)]
                        if use_typing:
                            typing_time = delay / 2
                            client.send_typing_indicator(thread_id, True)
                            for _ in range(int(typing_time)):
                                if stop_flags.get(task_id, False):
                                    break
                                time.sleep(1)
                            client.send_typing_indicator(thread_id, False)
                        client.send_message(text=msg, thread_id=thread_id)
                        idx += 1
                        for _ in range(int(delay)):
                            if stop_flags.get(task_id, False):
                                break
                            time.sleep(1)
                    client.disconnect()
            except Exception as e:
                print(f"[{task_id}] Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Nhây Thường", "thread_id": thread_id, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Nhây Thường thành công", color=0x3498db)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        embed.add_field(name="Typing", value="Bật" if use_typing else "Tắt", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class NhayTagModal(discord.ui.Modal, title="Nhây Tag"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)
    thread_id = discord.ui.TextInput(label="ID Thread", required=True)
    user_ids = discord.ui.TextInput(label="ID Users (cách nhau bằng ,)", required=True, placeholder="61585146600163,61574475271356")
    delay = discord.ui.TextInput(label="Delay (giây)", required=True)
    use_typing = discord.ui.TextInput(label="Bật Typing (true/false)", required=False, default="false")

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        try:
            cookie = self.cookie.value.strip()
            thread_id = self.thread_id.value.strip()
            user_ids = [uid.strip() for uid in self.user_ids.value.split(",") if uid.strip()]
            delay = float(self.delay.value.strip())
            use_typing = self.use_typing.value.strip().lower() == "true"
            with open("nhay.txt", "r", encoding="utf-8") as f:
                messages = [line.strip() for line in f if line.strip()]
            if not messages:
                await interaction.response.send_message("File nhay.txt trống!", ephemeral=True)
                return
        except FileNotFoundError:
            await interaction.response.send_message("Không tìm thấy nhay.txt!", ephemeral=True)
            return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        except Exception as e:
            await interaction.response.send_message(f"Lỗi: {e}", ephemeral=True)
            return
        member_names = get_all_member_names_fast(cookie, thread_id, user_ids)
        names_display = []
        for uid in user_ids:
            name = member_names.get(uid, f"User_{uid[-6:]}")
            names_display.append(f"{name}")
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                client = create_facebook_client(cookie, {"debug": False})
                if client.connect():
                    msg_idx = 0
                    while not stop_flags.get(task_id, False):
                        base_msg = messages[msg_idx % len(messages)]
                        text_with_mentions = base_msg
                        mention_list = []
                        current_pos = len(base_msg)
                        for uid in user_ids:
                            name = member_names.get(uid, f"User_{uid[-6:]}")
                            text_with_mentions += f" @{name}"
                            mention_list.append({
                                "id": uid,
                                "tag": f"@{name}",
                                "offset": current_pos + 1 if current_pos > 0 else current_pos
                            })
                            current_pos += len(f" @{name}")
                        if use_typing:
                            typing_time = delay / 2
                            client.send_typing_indicator(thread_id, True)
                            for _ in range(int(typing_time)):
                                if stop_flags.get(task_id, False):
                                    break
                                time.sleep(1)
                            client.send_typing_indicator(thread_id, False)
                        if mention_list:
                            client.send_message(text=text_with_mentions, thread_id=thread_id, mention=mention_list)
                        else:
                            client.send_message(text=base_msg, thread_id=thread_id)
                        msg_idx += 1
                        for _ in range(int(delay)):
                            if stop_flags.get(task_id, False):
                                break
                            time.sleep(1)
                    client.disconnect()
            except Exception as e:
                print(f"[{task_id}] Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Nhây Tag", "thread_id": thread_id, "delay": delay, "user_ids": user_ids}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Nhây Tag thành công", color=0x3498db)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=False)
        embed.add_field(name="Người bị tag", value=", ".join(names_display), inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        embed.add_field(name="Typing", value="Bật" if use_typing else "Tắt", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class NhayNameBoxModal(discord.ui.Modal, title="Nhây Tên Box"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)
    thread_id = discord.ui.TextInput(label="ID Thread", required=True)
    delay = discord.ui.TextInput(label="Delay (giây)", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        try:
            cookie = self.cookie.value.strip()
            thread_id = self.thread_id.value.strip()
            delay = float(self.delay.value.strip())
            with open("nhay.txt", "r", encoding="utf-8") as f:
                names = [line.strip() for line in f if line.strip()]
            if not names:
                await interaction.response.send_message("File nhay.txt trống!", ephemeral=True)
                return
        except FileNotFoundError:
            await interaction.response.send_message("Không tìm thấy nhay.txt!", ephemeral=True)
            return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                idx = 0
                while not stop_flags.get(task_id, False):
                    new_name = names[idx % len(names)]
                    rename_facebook_group(cookie, thread_id, new_name)
                    idx += 1
                    for _ in range(int(delay)):
                        if stop_flags.get(task_id, False):
                            break
                        time.sleep(1)
            except Exception as e:
                print(f"[{task_id}] Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Nhây Tên Box", "thread_id": thread_id, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Nhây Tên Box thành công", color=0x3498db)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class NhayPollModal(discord.ui.Modal, title="Nhây Poll"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)
    thread_id = discord.ui.TextInput(label="ID Thread", required=True)
    delay = discord.ui.TextInput(label="Delay (giây)", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        try:
            cookie = self.cookie.value.strip()
            thread_id = self.thread_id.value.strip()
            delay = float(self.delay.value.strip())
            with open("poll.txt", "r", encoding="utf-8") as f:
                polls = [line.strip() for line in f if line.strip()]
            if not polls:
                await interaction.response.send_message("File poll.txt trống! Format: câu hỏi|option1|option2|option3", ephemeral=True)
                return
        except FileNotFoundError:
            await interaction.response.send_message("Không tìm thấy poll.txt!", ephemeral=True)
            return
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                client = create_facebook_client(cookie, {"debug": False})
                if client.connect():
                    idx = 0
                    while not stop_flags.get(task_id, False):
                        poll_data = polls[idx % len(polls)]
                        parts = poll_data.split("|")
                        if len(parts) >= 3:
                            question = parts[0]
                            options = parts[1:]
                            client.send_poll(thread_id, question, options)
                        idx += 1
                        for _ in range(int(delay)):
                            if stop_flags.get(task_id, False):
                                break
                            time.sleep(1)
                    client.disconnect()
            except Exception as e:
                print(f"[{task_id}] Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Nhây Poll", "thread_id": thread_id, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Nhây Poll thành công", color=0x3498db)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class SpamThemeModal(discord.ui.Modal, title="Spam Theme"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)
    thread_id = discord.ui.TextInput(label="ID Thread", required=True)
    delay = discord.ui.TextInput(label="Delay (giây)", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        try:
            cookie = self.cookie.value.strip()
            thread_id = self.thread_id.value.strip()
            delay = float(self.delay.value.strip())
        except ValueError:
            await interaction.response.send_message("Delay phải là số!", ephemeral=True)
            return
        task_id = generate_task_id()
        stop_flags[task_id] = False
        def run_task():
            try:
                client = create_facebook_client(cookie, {"debug": False})
                if client.connect():
                    while not stop_flags.get(task_id, False):
                        for theme in THEMES:
                            if stop_flags.get(task_id, False):
                                break
                            client.set_theme(thread_id, theme_id=theme["id"])
                            time.sleep(3)
                    client.disconnect()
            except Exception as e:
                print(f"[{task_id}] Error: {e}")
            finally:
                stop_flags.pop(task_id, None)
                if user_id in active_tasks and task_id in active_tasks[user_id]:
                    del active_tasks[user_id][task_id]
        thread = threading.Thread(target=run_task, daemon=True)
        if user_id not in active_tasks:
            active_tasks[user_id] = {}
        active_tasks[user_id][task_id] = {"thread": thread, "type": "Spam Theme", "thread_id": thread_id, "delay": delay}
        thread.start()
        embed = discord.Embed(title="Đã bắt đầu Spam Theme thành công", color=0x3498db)
        embed.add_field(name="ID TASK", value=f"`{task_id}`", inline=False)
        embed.add_field(name="Thread ID", value=f"`{thread_id}`", inline=False)
        embed.add_field(name="Delay", value=f"`{delay} giây` (3s giữa các theme)", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ListBoxModal(discord.ui.Modal, title="List Box"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        cookie = self.cookie.value.strip()
        await interaction.response.send_message("Đang lấy danh sách...", ephemeral=True)
        try:
            result = get_facebook_threads(cookie)
            if "ERR" in result:
                await interaction.followup.send(f"{result['ERR']}", ephemeral=True)
                return
            threads = result.get("threadIDList", [])
            names = result.get("threadNameList", [])
            if not threads:
                await interaction.followup.send("Không tìm thấy thread nào.", ephemeral=True)
                return
            msg = "**Danh sách Box:**\n"
            for i, (tid, name) in enumerate(zip(threads, names), 1):
                msg += f"{i}. {name} — `{tid}`\n"
                if len(msg) > 1800:
                    await interaction.followup.send(msg, ephemeral=True)
                    msg = ""
            if msg:
                await interaction.followup.send(msg, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Lỗi: {e}", ephemeral=True)

class ListThanhVienModal(discord.ui.Modal, title="List Thành Viên"):
    cookie = discord.ui.TextInput(label="Cookie", style=discord.TextStyle.paragraph, required=True)
    thread_id = discord.ui.TextInput(label="ID Thread", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        cookie = self.cookie.value.strip()
        thread_id = self.thread_id.value.strip()
        await interaction.response.send_message("Đang lấy danh sách thành viên...", ephemeral=True)
        try:
            data_fb = dataGetHome(cookie)
            fb_tool = fbTools(data_fb, thread_id)
            if fb_tool.getAllThreadList():
                members = fb_tool.typeCommand("exportMemberListToJson")
                if isinstance(members, list):
                    msg = "**Danh sách thành viên:**\n"
                    for i, member_json in enumerate(members, 1):
                        try:
                            member_data = json.loads(member_json)
                            for uid, info in member_data.items():
                                name = info.get("nameFB", "Unknown")
                                msg += f"{i}. {name} — `{uid}`\n"
                                member_name_cache[f"{thread_id}_{uid}"] = name
                                if len(msg) > 1800:
                                    await interaction.followup.send(msg, ephemeral=True)
                                    msg = ""
                        except:
                            continue
                    if msg:
                        await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.followup.send(f"{members}", ephemeral=True)
            else:
                await interaction.followup.send("Không thể lấy danh sách thành viên.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Lỗi: {e}", ephemeral=True)

class GetIDMessView(discord.ui.View):
    @discord.ui.button(label="List Box", style=discord.ButtonStyle.blurple, row=0)
    async def listbox_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(ListBoxModal())

    @discord.ui.button(label="List Thành Viên", style=discord.ButtonStyle.green, row=0)
    async def list_member_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(ListThanhVienModal())

class TreoView(discord.ui.View):
    @discord.ui.button(label="Treo Thường", style=discord.ButtonStyle.blurple, row=0)
    async def treo_thuong_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(TreoThuongModal())

    @discord.ui.button(label="Treo Share Contact", style=discord.ButtonStyle.green, row=0)
    async def treo_contact_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(TreoShareContactModal())

    @discord.ui.button(label="Treo Share Link", style=discord.ButtonStyle.blurple, row=1)
    async def treo_link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(TreoShareLinkModal())

class NhayView(discord.ui.View):
    @discord.ui.button(label="Nhây Thường", style=discord.ButtonStyle.blurple, row=0)
    async def nhay_thuong_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(NhayThuongModal())

    @discord.ui.button(label="Nhây Tag", style=discord.ButtonStyle.green, row=0)
    async def nhay_tag_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(NhayTagModal())

    @discord.ui.button(label="Nhây Tên Box", style=discord.ButtonStyle.blurple, row=1)
    async def nhay_namebox_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(NhayNameBoxModal())

    @discord.ui.button(label="Nhây Poll", style=discord.ButtonStyle.green, row=1)
    async def nhay_poll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(NhayPollModal())

    @discord.ui.button(label="Spam Theme", style=discord.ButtonStyle.red, row=2)
    async def spam_theme_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_authorized(interaction):
            await interaction.response.send_message("Bạn không có quyền.", ephemeral=True)
            return
        await interaction.response.send_modal(SpamThemeModal())

@bot.command()
async def gmail(ctx):
    if not (has_valid_key(ctx.author.id) or ctx.author.id == ADMIN_ID):
        await ctx.send("Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    view = GmailView()
    embed = discord.Embed(title="📧 Gmail", description="**Chức Năng Gmail**", color=0xEA4335)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def dis(ctx):
    if not (has_valid_key(ctx.author.id) or ctx.author.id == ADMIN_ID):
        await ctx.send("Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    view = DiscordView()
    embed = discord.Embed(title="Discord", description="**Chức Năng Discord**", color=0x5865F2)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def tele(ctx):
    if not (has_valid_key(ctx.author.id) or ctx.author.id == ADMIN_ID):
        await ctx.send("Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    view = TelegramView()
    embed = discord.Embed(title="📱 Telegram", description="**Chức Năng Telegram**", color=0x0088cc)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def zalo(ctx):
    if not (has_valid_key(ctx.author.id) or ctx.author.id == ADMIN_ID):
        await ctx.send("Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    if not ZALO_AVAILABLE:
        await ctx.send("Tính năng Zalo hiện không khả dụng.")
        return
    view = ZaloView()
    embed = discord.Embed(title="📱 Zalo", description="**Chức Năng Zalo**", color=0x0099ff)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def treo(ctx):
    if not (has_valid_key(ctx.author.id) or ctx.author.id == ADMIN_ID):
        await ctx.send("Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    view = TreoView()
    embed = discord.Embed(title="Treo Ngôn Messenger", color=0x3498db)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def nhay(ctx):
    if not (has_valid_key(ctx.author.id) or ctx.author.id == ADMIN_ID):
        await ctx.send("Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    view = NhayView()
    embed = discord.Embed(title="Nhây Ngôn Messenger", color=0x3498db)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def getidmes(ctx):
    if not (has_valid_key(ctx.author.id) or ctx.author.id == ADMIN_ID):
        await ctx.send("Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    view = GetIDMessView()
    embed = discord.Embed(title="Get ID Messenger", description="Chọn chức năng:", color=0x3498db)
    await ctx.send(embed=embed, view=view)

@bot.command()
async def xemtask(ctx):
    user_id = ctx.author.id
    if not (has_valid_key(user_id) or user_id == ADMIN_ID):
        await ctx.send("Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    if user_id not in active_tasks or not active_tasks[user_id]:
        await ctx.send("Không có task nào đang hoạt động.")
        return
    embed = discord.Embed(title="**Danh Sách Task**", color=0x00ff00)
    for task_id, info in active_tasks[user_id].items():
        noi_dung = f"**Type:** {info.get('type', 'unknown')}\n**Delay:** {info.get('delay', 'N/A')}s"
        if 'thread_id' in info:
            noi_dung += f"\n**Thread ID:** {info['thread_id']}"
        if 'channel_ids' in info:
            noi_dung += f"\n**Channel ID:** {', '.join(info['channel_ids'])}"
        if 'target_ids' in info:
            noi_dung += f"\n**Target IDs:** {', '.join(info['target_ids'])}"
        if 'user_ids' in info:
            noi_dung += f"\n**Users Tag:** {len(info['user_ids'])} người"
        embed.add_field(name=f"{task_id}", value=noi_dung, inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def dungtask(ctx, task_id: str):
    user_id = ctx.author.id
    task_id = task_id.upper()
    if user_id not in active_tasks or task_id not in active_tasks[user_id]:
        await ctx.send(f"Không tìm thấy task với ID: `{task_id}`")
        return
    stop_flags[task_id] = True
    del active_tasks[user_id][task_id]
    if not active_tasks[user_id]:
        del active_tasks[user_id]
    await ctx.send(f"🛑 Đã dừng task thành công: `{task_id}`")

@bot.command()
async def key(ctx, member: discord.Member, days: int):
    if not is_admin(ctx):
        await ctx.send("Bạn không có quyền sử dụng lệnh này.")
        return
    keys = load_keys()
    expire_date = datetime.now(timezone.utc) + timedelta(days=days)
    keys[str(member.id)] = expire_date.isoformat()
    save_keys(keys)
    await ctx.send(f"Đã cấp key cho `{member.name}` trong `{days}` ngày.")

@bot.command()
async def xoakey(ctx, member: discord.Member):
    if not is_admin(ctx):
        await ctx.send("Bạn không có quyền sử dụng lệnh này.")
        return
    keys = load_keys()
    user_id = member.id
    if str(user_id) in keys:
        del keys[str(user_id)]
        save_keys(keys)
        if user_id in active_tasks:
            for task_id in list(active_tasks[user_id].keys()):
                stop_flags[task_id] = True
            del active_tasks[user_id]
        await ctx.send(f"🗑️ Đã xóa key và dừng toàn bộ task của `{member.name}`.")
    else:
        await ctx.send("Người dùng này không có key.")

@bot.command()
async def listkey(ctx):
    if not is_admin(ctx):
        await ctx.send("Bạn không có quyền sử dụng lệnh này.")
        return
    keys = load_keys()
    if not keys:
        await ctx.send("Không có key nào được cấp.")
        return
    embed = discord.Embed(title="DANH SÁCH KEY", color=0x00acee)
    for user_id, expiry in keys.items():
        try:
            member = await bot.fetch_user(int(user_id))
            name = member.name
        except:
            name = "Không tìm thấy"
        try:
            expire_fmt = datetime.fromisoformat(expiry).strftime("%d/%m/%Y %H:%M")
        except:
            expire_fmt = expiry
        embed.add_field(name=f"**{name}**", value=f"ID: `{user_id}`\nHạn: `{expire_fmt}`", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def ping(ctx):
    if not (has_valid_key(ctx.author.id) or ctx.author.id == ADMIN_ID):
        await ctx.send("❌ Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    
    latency = round(bot.latency * 1000)
    uptime = datetime.now(timezone.utc) - start_time
    days = uptime.days
    hours = uptime.seconds // 3600
    minutes = (uptime.seconds % 3600) // 60
    seconds = uptime.seconds % 60
    
    embed = discord.Embed(title="PING!", color=0x00ff00)
    embed.add_field(name="Độ trễ", value=f"`{latency}ms`", inline=True)
    embed.add_field(name="Uptime", value=f"`{days}d {hours}h {minutes}m {seconds}s`", inline=True)
    
    if latency < 100:
        status = "🟢 Tốt"
        color = 0x00ff00
    elif latency < 200:
        status = "🟡 Ổn định"
        color = 0xffaa00
    else:
        status = "🔴 Chậm"
        color = 0xff0000
    
    embed.add_field(name="Trạng thái", value=status, inline=False)
    embed.color = color
    
    await ctx.send(embed=embed)

@bot.command()
async def menu(ctx):
    if not (has_valid_key(ctx.author.id) or ctx.author.id == ADMIN_ID):
        await ctx.send("Bạn chưa được cấp key hoặc key đã hết hạn.")
        return
    embed = discord.Embed(title="🎮 MENU 🎮", color=discord.Colour.from_rgb(0, 255, 255))
    embed.add_field(name="👑 Lệnh Admin", value=f"🔑 `{PREFIX}key` → Cấp key\n🚬 `{PREFIX}xoakey` → Xóa key\n📋 `{PREFIX}listkey` → Xem key", inline=False)
    embed.add_field(name="🤖 App Messenger", value=f"📨 `{PREFIX}treo` → Treo Ngôn\n🎭 `{PREFIX}nhay` → Nhây Ngôn\n📋 `{PREFIX}getidmes` → Get ID Messenger", inline=False)
    embed.add_field(name="💿 App Zalo", value=f"📱 `{PREFIX}zalo` → Zalo Bot", inline=False)
    embed.add_field(name="🎭 App Discord", value=f"💬 `{PREFIX}dis` → Discord Bot", inline=False)
    embed.add_field(name="🪽 App Gmail", value=f"🫧 `{PREFIX}gmail` → Gmail Bot", inline=False)
    embed.add_field(name="✈️ App Telegram", value=f"📱 `{PREFIX}tele` → Telegram Bot", inline=False)
    embed.add_field(name="🛠️ Quản Lý Task", value=f"📂 `{PREFIX}xemtask` → Xem task\n⛔ `{PREFIX}dungtask` → Dừng task", inline=False)
    embed.set_footer(text="🎮 Trọng Nhân 🎮 | Liên hệ: @nhandz486483")
    
    try:
        with open("trail.mp4", "rb") as video:
            video_file = discord.File(video, filename="trail.mp4")
            await ctx.send(embed=embed, file=video_file)
    except:
        await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f'✅ Đã đăng nhập: {bot.user.name}')
    print(f'👑 Admin ID: {ADMIN_ID}')
    print(f'🎯 Prefix: {PREFIX}')
    print('🎮 Bot đã sẵn sàng!')

if __name__ == "__main__":
    bot.run(TOKEN)