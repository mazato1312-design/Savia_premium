import discord
from discord.ext import commands, tasks
import aiohttp
import json
import asyncioimport os
import discord
from discord.ext import commands
import asyncio
import re
import requests
import json
import time
import random
from datetime import datetime
import urllib3
import sqlite3
from myserver import server_on

# ตั้งค่าบอท
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# --- CONFIGURATION ---
API_URL = "https://your-website.com/api" # ลิงก์ API เว็บไซต์ของคุณ
API_KEY = "SECRET_KEY_HERE" # คีย์ความปลอดภัยเพื่อยืนยันว่าเป็นบอทจริงๆ
ADMIN_CHANNEL_ID = 123456789012345678 # ห้องสำหรับแจ้งเตือนแอดมิน
LOG_CHANNEL_ID = 123456789012345678 # ห้องสำหรับแจ้งเตือนการซื้อ/เติมเงิน

# --- API HELPER FUNCTION ---
async def call_api(endpoint, data=None, method="GET"):
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        try:
            if method == "POST":
                async with session.post(f"{API_URL}/{endpoint}", json=data, headers=headers) as resp:
                    return await resp.json()
            else:
                async with session.get(f"{API_URL}/{endpoint}", headers=headers) as resp:
                    return await resp.json()
        except Exception as e:
            print(f"API Error: {e}")
            return None

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    check_stock_loop.start() # เริ่มระบบเช็คสต็อก (ถ้าต้องการแจ้งเตือนสต็อกต่ำ)

# --- คำสั่งเช็คสินค้า (Stock) ---
@bot.command()
async def stock(ctx):
    # ดึงข้อมูลจาก API เว็บ
    data = await call_api("get_products") 
    
    if data and data.get("status") == "success":
        embed = discord.Embed(title="📦 รายการสินค้าพรีเมี่ยม", color=0x00ff00)
        for item in data['products']:
            status_text = f"✅ มีของ ({item['stock']} ชิ้น)" if item['stock'] > 0 else "❌ ของหมด"
            embed.add_field(name=f"{item['name']} - {item['price']} บาท", value=status_text, inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send("⚠️ ไม่สามารถดึงข้อมูลสินค้าได้ในขณะนี้")

# --- คำสั่งซื้อสินค้า (Buy) ---
@bot.command()
async def buy(ctx, product_id: str):
    user_id = str(ctx.author.id)
    
    # ส่งคำสั่งซื้อไปที่ API
    payload = {"user_discord_id": user_id, "product_id": product_id}
    response = await call_api("buy_item", data=payload, method="POST")
    
    if response:
        if response.get("status") == "success":
            # แจ้งเตือนหน้าห้อง
            await ctx.send(f"✅ {ctx.author.mention} ซื้อสินค้าสำเร็จ! เช็ค DM ได้เลยครับ")
            
            # ส่งสินค้าเข้า DM
            try:
                dm_embed = discord.Embed(title="🎉 สินค้าของคุณ", description=response['account_data'], color=0xGOLD)
                await ctx.author.send(embed=dm_embed)
            except discord.Forbidden:
                await ctx.send("❌ บอทส่ง DM ไม่ได้ โปรดเปิดรับข้อความจากคนแปลกหน้า")

            # แจ้งเตือนในห้อง Log
            log_channel = bot.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                await log_channel.send(f"💰 มีการสั่งซื้อ: {response['product_name']} โดย {ctx.author.name}")
        
        elif response.get("status") == "insufficient_balance":
            await ctx.send("❌ ยอดเงินไม่พอครับ กรุณาเติมเงินก่อน")
        elif response.get("status") == "out_of_stock":
            await ctx.send("❌ สินค้าหมดครับ")
        else:
            await ctx.send(f"⚠️ เกิดข้อผิดพลาด: {response.get('message')}")
    else:
        await ctx.send("⚠️ เชื่อมต่อเซิร์ฟเวอร์ไม่ได้")

# --- ระบบเติมเงิน (Topup) ---
# ส่วนนี้ปกติ User จะส่งลิ้งค์ซองมา แล้วเราส่งไปเช็คที่ API
@bot.command()
async def topup(ctx, gift_link: str):
    await ctx.message.delete() # ลบข้อความเพื่อความปลอดภัยของลิ้งค์
    
    payload = {"user_discord_id": str(ctx.author.id), "link": gift_link}
    msg = await ctx.send("⏳ กำลังตรวจสอบยอดเงิน...")
    
    # ส่งลิ้งค์ไปให้ API เว็บตรวจสอบ (Backend ต้องไปยิง Truemoney API อีกที)
    response = await call_api("topup_truemoney", data=payload, method="POST")
    
    if response and response.get("status") == "success":
        amount = response['amount']
        await msg.edit(content=f"✅ เติมเงินสำเร็จ! จำนวน {amount} บาท")
        
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"💸 {ctx.author.name} เติมเงิน {amount} บาท")
    else:
        error_msg = response.get('message') if response else "เชื่อมต่อล้มเหลว"
        await msg.edit(content=f"❌ เติมเงินไม่สำเร็จ: {error_msg}")

# --- Loop เช็คแจ้งเตือน (Optional) ---
# ใช้ในกรณีที่ API ฝั่งเว็บมีการอัพเดทสต็อกเอง แล้วอยากให้บอทประกาศ
@tasks.loop(minutes=5)
async def check_stock_loop():
    # โค้ดสำหรับเช็ค API ว่ามีอะไรเปลี่ยนแปลงไหม แล้วแจ้งเตือน
    pass
if __name__ == "__main__":
    # เริ่มต้นระบบ
    print("กำลังเริ่มต้นระบบเติมเงินอัตโนมัติ...")

    server_on()

bot.run(os.getenv('TOKEN'))
