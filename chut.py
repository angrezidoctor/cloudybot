import asyncio
import nest_asyncio
import logging
import json
import io
import boto3
import time
import re 
from botocore.client import Config
from botocore.exceptions import ClientError

# Suppress noisy logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# Telegram & OpenAI Libraries
from openai import AsyncOpenAI, APITimeoutError
from telegram import Update, InputFile
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ParseMode

# Apply asyncio patch
nest_asyncio.apply()

# ==========================================
# 🔑 CONFIGURATION & KEYS
# ==========================================

# --- TELEGRAM BOT TOKEN ---
TELEGRAM_BOT_TOKEN = "8477056079:AAF44cdTAfdcQQ7csPXIKxCg-rRPwoQ7IJk"

# --- OPENROUTER API KEY ---
OPENROUTER_API_KEY = "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"

# --- AI MODELS (Priority Order) ---
AI_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free", # Priority 1
    "kwaipilot/kat-coder-pro:free"             # Priority 2
]

# --- INTERCOLO STORAGE KEYS ---
ENDPOINT = "https://de-fra.i3storage.com"
ACCESS_KEY = "builcygo2mqlgoze"
SECRET_KEY = "8BDnKnwHHoGwieJCs2t51ZOAeUpTilNmNSf2GQjVFJDSITlg"
BUCKET_NAME = "destroyer-bot-official-storage"

# ==========================================
# 🚀 CLIENT INITIALIZATION
# ==========================================

# Initialize S3 Client
s3 = boto3.client(
    's3', 
    endpoint_url=ENDPOINT, 
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY, 
    config=Config(signature_version='s3v4')
)

# Initialize AI Client
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1", 
    api_key=OPENROUTER_API_KEY
)

CUSTOM_NAME = "DESTROYER v4.1"

# ==========================================
# 🧠 UTILITY FUNCTIONS
# ==========================================

def get_user_memory_path(uid):
    return f"DESTROYER_AI/memory/{uid}.json"

async def run_sync(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)

def load_user_history(uid):
    try:
        r = s3.get_object(Bucket=BUCKET_NAME, Key=get_user_memory_path(uid))
        data = json.loads(r['Body'].read().decode('utf-8'))
        return data if isinstance(data, list) else []
    except:
        return []

def save_user_history(uid, history):
    trimmed = history[-20:] 
    try: 
        s3.put_object(
            Bucket=BUCKET_NAME, 
            Key=get_user_memory_path(uid), 
            Body=json.dumps(trimmed), 
            ContentType='application/json'
        )
    except: pass

def get_readable_size(size_in_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_in_bytes < 1024.0: return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} TB"

def generate_presigned_link(key):
    try:
        return s3.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': BUCKET_NAME, 'Key': key},
            ExpiresIn=3600
        )
    except: return None

async def create_destroyer_bucket():
    try:
        await run_sync(s3.head_bucket, Bucket=BUCKET_NAME)
        print(f"✅ Storage Connected: {BUCKET_NAME}")
    except:
        try:
            await run_sync(s3.create_bucket, Bucket=BUCKET_NAME)
            print(f"✅ Bucket Created: {BUCKET_NAME}")
        except Exception as e:
            print(f"❌ Storage Error: {e}")

# ==========================================
# 🤖 INTELLIGENT AI ENGINE
# ==========================================

async def get_ai_response_smart(messages, system_prompt):
    full_messages = [{"role": "system", "content": system_prompt}] + messages
    
    for model in AI_MODELS:
        try:
            print(f"🔄 Thinking with {model}...")
            response = await client.chat.completions.create(
                model=model,
                messages=full_messages,
                max_tokens=4000, 
                temperature=0.7
            )
            reply = response.choices[0].message.content.strip()
            if reply:
                return reply
        except Exception as e:
            print(f"⚠️ {model} Failed: {e}")
            continue 
            
    return "❌ All AI servers are busy. Try again later."

async def send_smart_split(update, text):
    """Splits long messages (>4000 chars)."""
    if not text: return
    MAX_LEN = 4000
    
    if len(text) <= MAX_LEN:
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except:
            await update.message.reply_text(text)
    else:
        parts = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
        for i, part in enumerate(parts):
            try:
                msg_content = part
                if i > 0: msg_content = f"...(continued)\n{msg_content}"
                await update.message.reply_text(msg_content, parse_mode=ParseMode.MARKDOWN)
            except:
                await update.message.reply_text(msg_content)
            await asyncio.sleep(0.5)

# ==========================================
# 🛠️ STORAGE COMMAND HANDLERS
# ==========================================

async def cmd_list_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_chat_action("typing")
    try:
        response = await run_sync(s3.list_objects_v2, Bucket=BUCKET_NAME, MaxKeys=20)
        if 'Contents' not in response:
            await update.message.reply_text("📂 Bucket is empty.")
            return

        msg = "📂 **Recent Storage Files:**\n\n"
        for obj in response['Contents']:
            msg += f"📄 `{obj['Key']}` ({get_readable_size(obj['Size'])})\n"
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def cmd_delete_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Use: `/delete filename.ext`", parse_mode=ParseMode.MARKDOWN)
        return
    filename = " ".join(context.args)
    try:
        await run_sync(s3.delete_object, Bucket=BUCKET_NAME, Key=filename)
        await update.message.reply_text(f"🗑️ `{filename}` deleted.", parse_mode=ParseMode.MARKDOWN)
    except:
        await update.message.reply_text("❌ Failed to delete.")

async def cmd_get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return
    filename = " ".join(context.args)
    url = generate_presigned_link(filename)
    if url: 
        await update.message.reply_text(f"🔗 **Download Link:**\n{url}", parse_mode=ParseMode.MARKDOWN)
    else: 
        await update.message.reply_text("❌ Could not generate link.")

# ==========================================
# 📨 MESSAGE HANDLERS
# ==========================================

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    await msg.reply_chat_action("upload_document")
    
    f_obj = msg.document or msg.video or msg.audio or (msg.photo[-1] if msg.photo else None)
    if not f_obj: return

    fname = getattr(f_obj, 'file_name', None)
    if not fname:
        ext = "jpg" if msg.photo else "bin"
        fname = f"upload_{update.message.from_user.id}_{int(time.time())}.{ext}"

    status = await msg.reply_text(f"⬇️ Processing `{fname}`...")
    
    try:
        new_file = await f_obj.get_file()
        f_stream = io.BytesIO()
        await new_file.download_to_memory(f_stream)
        f_stream.seek(0)
        
        await context.bot.edit_message_text(f"🚀 Uploading to InterColo...", chat_id=msg.chat_id, message_id=status.message_id)
        
        await run_sync(s3.put_object, Bucket=BUCKET_NAME, Key=fname, Body=f_stream)
        
        link = generate_presigned_link(fname)
        await context.bot.edit_message_text(
            f"✅ **Upload Complete!**\n📄 `{fname}`\n🔗 [Download Link]({link})", 
            chat_id=msg.chat_id, 
            message_id=status.message_id, 
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        await msg.reply_text(f"❌ Upload Error: {e}")

async def handle_text_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.message.from_user.id)
    text = update.message.text.strip()
    
    if not text: return
    
    # 1. Identity & Owner Checks
    text_lower = text.lower()
    
    if any(x in text_lower for x in ["who is owner", "owner name", "creator"]):
        await update.message.reply_text("👑 My Owner is **DESTROYER SIR** (@Everyonesking)", parse_mode=ParseMode.MARKDOWN)
        return

    # Check for Identity/Model questions
    if any(x in text_lower for x in ["what model", "which model", "who are you", "bot name", "your name", "ai name"]):
        await update.message.reply_text(f"🤖 I am **{CUSTOM_NAME}**.", parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_chat_action("typing")

    # 2. Load Memory
    history = await run_sync(load_user_history, uid)
    
    # 3. Build Prompt
    system_prompt = (
        f"You are {CUSTOM_NAME}. "
        "You are an expert programmer and a helpful AI assistant. "
        "If the user asks for code, provide the FULL, WORKING code. Do not shorten it. "
        "Use Python, C++, Java, PHP etc as requested. "
        "Your responses should be complete and helpful."
    )

    # 4. Generate Response
    response_text = await get_ai_response_smart(
        history + [{"role": "user", "content": text}], 
        system_prompt
    )
    
    # 5. Save Memory
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": response_text})
    await run_sync(save_user_history, uid, history)

    # 6. Send Response (Clean, NO Header)
    await send_smart_split(update, response_text)

# ==========================================
# 🔥 MAIN LOOP
# ==========================================

async def main():
    print(f"--- {CUSTOM_NAME} ONLINE (v24) ---")
    
    await create_destroyer_bucket()
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", lambda u,c: u.message.reply_text(
        f"⚡ **{CUSTOM_NAME} ONLINE** ⚡\n\n"
        "💬 **Chat & Code:** Just type.\n"
        "📂 **Storage:** Send me any file.\n"
        "📜 **Commands:** /list, /delete, /link"
    )))
    app.add_handler(CommandHandler("list", cmd_list_files))
    app.add_handler(CommandHandler("delete", cmd_delete_file))
    app.add_handler(CommandHandler("link", cmd_get_link))
    
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO, handle_file_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_ai))

    print("✅ Bot is Polling... (Press Ctrl+C to stop)")
    await app.run_polling()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
    except Exception as e:
        print(f"Critical Error: {e}")
