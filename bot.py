import asyncio
import os
import time
from urllib.parse import quote
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import UserNotParticipant
from pyrogram.enums import ChatMemberStatus  # Add this import
from datetime import datetime
import math
import humanize
import aiohttp
from config import *
from logger import setup_logger

logger = setup_logger()

# Create downloads directory if it doesn't exist
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

app = Client("terabox_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

from pyrogram import utils

def get_peer_type_new(peer_id: int) -> str:
    peer_id_str = str(peer_id)
    if not peer_id_str.startswith("-"):
        return "user"
    elif peer_id_str.startswith("-100"):
        return "channel"
    else:
        return "chat"

utils.get_peer_type = get_peer_type_new

TERABOX_DOMAINS = [
    'terabox.com',
    'teraboxapp.com',
    '4funbox.com',
    '4funbox.net',
    'mirrobox.com',
    'nephobox.com',
    'terabox.app',
    'terabyte.cc',
    'terabox.cc',
    '1024tera.com',
    'terabox.fun',
    'terabox.net',
    'teraboxlink.com',
    'www.terabox.com',
    'www.teraboxapp.com',
    'teramox.com'
]

cancel_flag = False
last_progress_update = 0

class CancelledError(Exception):
    pass

def format_size(size):
    if size == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size, 1024)))
    p = math.pow(1024, i)
    s = round(size / p, 2)
    return f"{s} {size_name[i]}"

async def check_force_sub(client, user_id):
    try:
        logger.info(f"Checking subscription for user {user_id}")
        member = await client.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
        logger.info(f"Member status: {member.status}")
        
        # Fix the status check to use ChatMemberStatus enum
        if member.status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER]:
            logger.info(f"User {user_id} is subscribed")
            return True
        
        logger.info(f"User {user_id} is not subscribed (status: {member.status})")
        return False
            
    except UserNotParticipant:
        logger.info(f"User {user_id} is not a participant")
        return False
    except Exception as e:
        logger.error(f"Force sub check error for user {user_id}: {str(e)}", exc_info=True)
        # Return False on error to ensure subscription
        return False

@app.on_message(filters.command("start") | filters.regex(r'https?://[^\s]+'))
async def handle_message(client, message):
    try:
        user_id = message.from_user.id
        is_subbed = await check_force_sub(client, user_id)
        logger.info(f"Subscription check result for user {user_id}: {is_subbed}")
        
        if not is_subbed:
            logger.info(f"Sending force sub message to user {user_id}")
            await message.reply(
                FORCE_SUB_MSG.format(channel=CHANNEL_USERNAME),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔔 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME}"),
                     InlineKeyboardButton("🔄 Check Again", callback_data="checksub")]
                ])
            )
            return

        # Rest of the handler
        if message.text.startswith("/start"):
            await start_cmd(client, message)
        else:
            await handle_terabox_link(client, message)
            
    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
        await message.reply("An error occurred. Please try again later.")

@app.on_callback_query(filters.regex("checksub"))
async def check_sub_callback(client, callback_query):
    user_id = callback_query.from_user.id
    logger.info(f"Check subscription callback for user {user_id}")
    
    if await check_force_sub(client, user_id):
        logger.info(f"User {user_id} subscription verified in callback")
        await callback_query.message.delete()
        await start_cmd(client, callback_query.message)
    else:
        logger.info(f"User {user_id} still not subscribed")
        await callback_query.answer("❌ Please join the channel first!", show_alert=True)

@app.on_callback_query(filters.regex("cancel"))
async def cancel_download(client, callback_query):
    logger.info(f"Download cancelled by user {callback_query.from_user.id}")
    global cancel_flag
    cancel_flag = True
    await callback_query.answer("Cancelling download...")
    # Don't edit message here, let download_file handle it

async def start_cmd(client, message):
    await message.reply(
        START_MSG.format(
            user=message.from_user.mention,
            channel=CHANNEL_USERNAME
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Channel", url=f"https://t.me/{CHANNEL_USERNAME}")]
        ])
    )

async def progress_bar(current, total, message, start):
    global last_progress_update
    if total is None:
        return
        
    now = time.time()
    if now - last_progress_update < 3 and current < total:
        return
    
    last_progress_update = now
    elapsed_time = now - start
    speed = current / elapsed_time if elapsed_time > 0 else 0
    percentage = current * 100 / total
    
    bar_length = 12
    filled_length = int(bar_length * current // total)
    bar = '■' * filled_length + '□' * (bar_length - filled_length)
    
    current_size = format_size(current)
    total_size = format_size(total)
    eta = humanize.naturaltime((total - current) / speed if speed > 0 else 0)
    
    await message.edit(
        text=(
            f"**📥 Downloading File**\n\n"
            f"**{bar}** `{percentage:.1f}%`\n\n"
            f"**Size:** `{current_size}` / `{total_size}`\n"
            f"**Speed:** `{format_size(speed)}/s`\n"
            f"**ETA:** `{eta}`"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ])
    )

async def upload_progress_bar(current, total, message, start_time):
    global last_progress_update
    if total is None:
        return
        
    now = time.time()
    if now - last_progress_update < 3 and current < total:
        return
    
    last_progress_update = now
    percentage = current * 100 / total
    bar_length = 12
    filled_length = int(bar_length * current // total)
    bar = '■' * filled_length + '□' * (bar_length - filled_length)
    speed = current / (time.time() - start_time) if time.time() > start_time else 0
    eta = humanize.naturaltime((total - current) / speed if speed > 0 else 0)
    
    await message.edit(
        text=(
            f"**📤 Uploading File**\n\n"
            f"**{bar}** `{percentage:.1f}%`\n\n"
            f"**Uploaded:** `{format_size(current)}` / `{format_size(total)}`\n"
            f"**Speed:** `{format_size(speed)}/s`\n"
            f"**ETA:** `{eta}`"
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
        ])
    )

async def send_file_by_type(client, chat_id, filename, caption, message, progress, is_dump=False):
    file_type = None
    sent_message = None
    
    try:
        if filename.lower().endswith(('.mp4', '.mkv', '.avi', '.webm')):
            await message.edit("📤 Uploading video...")
            sent_message = await client.send_video(
                chat_id=chat_id,
                video=filename,
                caption=caption,
                progress=progress if not is_dump else None,
                progress_args=(message, time.time()) if not is_dump else None
            )
        elif filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            await message.edit("📤 Uploading photo...")
            sent_message = await client.send_photo(
                chat_id=chat_id,
                photo=filename,
                caption=caption
            )
        elif filename.lower().endswith(('.mp3', '.m4a', '.ogg', '.opus')):
            await message.edit("📤 Uploading audio...")
            sent_message = await client.send_audio(
                chat_id=chat_id,
                audio=filename,
                caption=caption,
                progress=progress if not is_dump else None,
                progress_args=(message, time.time()) if not is_dump else None
            )
        else:
            await message.edit("📤 Uploading file...")
            sent_message = await client.send_document(
                chat_id=chat_id,
                document=filename,
                caption=caption,
                progress=progress if not is_dump else None,
                progress_args=(message, time.time()) if not is_dump else None
            )
        return sent_message
    except Exception as e:
        logger.error(f"Failed to send file: {str(e)}")
        raise e

async def handle_terabox_link(client, message: Message):
    logger.info(f"Processing link from user {message.from_user.id}")
    link = message.text.strip()
    api_url = f"{TERABOX_API}/?url={quote(link)}"
    
    status_msg = await message.reply("⏳ Processing your link...")
    temp_file = None
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as response:
                if response.status != 200:
                    await status_msg.edit(f"❌ Failed to process link (Status: {response.status})")
                    return

                # Get file info and sanitize filename
                content_disp = response.headers.get('content-disposition', '')
                if 'filename=' in content_disp:
                    filename = content_disp.split('filename=')[-1].strip('"')
                else:
                    filename = f'terabox_file_{int(time.time())}'
                
                # Sanitize filename to remove invalid characters
                filename = "".join(c for c in filename if c.isalnum() or c in (' ', '-', '_', '.'))
                temp_file = os.path.join(DOWNLOAD_DIR, filename)

                # Download file with progress
                await status_msg.edit("📥 Downloading file...")
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                start_time = time.time()

                with open(temp_file, 'wb') as f:
                    async for chunk in response.content.iter_chunked(8192):
                        if cancel_flag:
                            raise CancelledError("Download cancelled")
                        f.write(chunk)
                        downloaded += len(chunk)
                        await progress_bar(downloaded, total_size, status_msg, start_time)

                # Send to dump channel
                await status_msg.edit("📤 Uploading to channel...")
                dump_msg = await send_file_by_type(
                    client,
                    int(DUMP_CHANNEL),
                    temp_file,
                    f"#terabox\nUser: {message.from_user.id}\nLink: {link}",
                    status_msg,
                    upload_progress_bar,
                    is_dump=True
                )

                # Send copy to user without forward header
                if dump_msg:
                    try:
                        await dump_msg.copy(
                            chat_id=message.chat.id,
                            caption=f"Terabox downloader @{CHANNEL_USERNAME}"
                        )
                        await status_msg.edit("✅ File sent successfully!")
                    except Exception as e:
                        logger.error(f"Failed to forward file: {e}")
                        await status_msg.edit("❌ Failed to send file!")
                else:
                    await status_msg.edit("❌ Failed to upload file!")

    except CancelledError:
        await status_msg.edit("📛 Download cancelled!")
    except Exception as e:
        logger.error(f"Link processing failed: {e}")
        await status_msg.edit(f"❌ Failed to process link: {str(e)}")
    finally:
        # Cleanup
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
                logger.info(f"Cleaned up file: {temp_file}")
            except Exception as e:
                logger.error(f"Failed to cleanup file: {e}")

app.run()
