from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright
import json
import os
import asyncio

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOGIN_URL = "https://www.flipkart.com/account/login"
COOKIE_FILE = "saved_cookies.json"

session_store = {}

class PhonePayload(BaseModel):
    phone: str

class OtpPayload(BaseModel):
    otp: str

@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html file not found!</h1>"

@app.post("/api/send-phone")
async def send_phone(payload: PhonePayload):
    try:
        if "browser" in session_store:
            await session_store["browser"].close()
            session_store.clear()

        p = await async_playwright().start()
        # Headless mode me Bot bypass karne ke liye args
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()

        # Stealth Script to hide Playwright
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        await page.goto(LOGIN_URL, timeout=60000, wait_until="networkidle")

        # Select Phone Input Box
        phone_input = page.locator("form input[type='text']").first
        await phone_input.click()
        
        # Human Typing Speed (bot protection bypass)
        await phone_input.type(payload.phone, delay=120)

        # Click Request OTP button
        btn = page.locator("button:has-text('Request OTP'), button:has-text('CONTINUE')").first
        if await btn.is_visible():
            await btn.click()
        else:
            await page.keyboard.press("Enter")

        # Wait for actual SMS trigger response
        await asyncio.sleep(3)

        session_store["playwright"] = p
        session_store["browser"] = browser
        session_store["context"] = context
        session_store["page"] = page

        return {"status": "otp_required", "message": "Flipkart से OTP भेज दिया गया है। फोन चेक करें!"}

    except Exception as e:
        if "browser" in session_store:
            await session_store["browser"].close()
            session_store.clear()
        return {"status": "error", "message": f"OTP भेजने में विफलता: {str(e)}"}

@app.post("/api/verify-otp")
async def verify_otp(payload: OtpPayload):
    if "page" not in session_store:
        raise HTTPException(status_code=400, detail="कोई एक्टिव लॉगिन सेशन नहीं मिला!")

    try:
        page = session_store["page"]
        context = session_store["context"]

        # Type OTP digit by digit
        otp_inputs = page.locator("input[maxlength='1']")
        count = await otp_inputs.count()

        if count >= 6:
            for i in range(min(6, len(payload.otp))):
                await otp_inputs.nth(i).fill(payload.otp[i])
        else:
            main_otp = page.locator("input[type='text']").last
            await main_otp.fill(payload.otp)

        # Submit OTP
        verify_btn = page.locator("button:has-text('VERIFY'), button:has-text('Login'), button[type='submit']").first
        await verify_btn.click()

        await page.wait_for_timeout(4000)

        # Save session cookies
        cookies = await context.cookies()
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f, indent=2)

        await session_store["browser"].close()
        await session_store["playwright"].stop()
        session_store.clear()

        return {"status": "success", "message": "लॉगिन सफल! कुकीज़ सेव हो गई हैं।"}

    except Exception as e:
        if "browser" in session_store:
            await session_store["browser"].close()
            session_store.clear()
        return {"status": "error", "message": f"सत्यापन में समस्या: {str(e)}"}
