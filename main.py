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
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--window-size=1280,720'
            ]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US,en"
        )
        page = await context.new_page()

        # Hide WebDriver automation flags
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        await page.goto(LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Phone Input Selectors
        phone_input = page.locator("form input[type='text'], input[type='tel']").first
        await phone_input.click()
        await phone_input.fill("")
        await phone_input.type(payload.phone, delay=150)

        # Click Request OTP
        btn = page.locator("button:has-text('Request OTP'), button:has-text('CONTINUE')").first
        if await btn.is_visible():
            await btn.click()
        else:
            await page.keyboard.press("Enter")

        await asyncio.sleep(4)

        # Check if Flipkart blocked or showed error on screen
        page_content = await page.content()
        if "Please enter valid Mobile number" in page_content or "CAPTCHA" in page_content:
            await browser.close()
            return {"status": "error", "message": "Flipkart ने बॉट डिटेक्शन या अमान्य नंबर के कारण ब्लॉक किया!"}

        session_store["playwright"] = p
        session_store["browser"] = browser
        session_store["context"] = context
        session_store["page"] = page

        return {"status": "otp_required", "message": "OTP रिक्वेस्ट भेजी गई। अगर SMS आए तो दर्ज करें!"}

    except Exception as e:
        if "browser" in session_store:
            await session_store["browser"].close()
            session_store.clear()
        return {"status": "error", "message": f"फ़ोन नंबर सबमिट करने में विफल: {str(e)}"}

@app.post("/api/verify-otp")
async def verify_otp(payload: OtpPayload):
    if "page" not in session_store:
        raise HTTPException(status_code=400, detail="कोई एक्टिव लॉगिन सेशन नहीं मिला!")

    try:
        page = session_store["page"]
        context = session_store["context"]

        # Fill OTP
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

        await asyncio.sleep(4)

        # --- STRICT VERIFICATION (CHECK IF FLIPKART ACCEPTED OTP) ---
        page_text = await page.content()

        # 1. Look for explicit failure text
        if "Incorrect OTP" in page_text or "Please enter valid OTP" in page_text or "Invalid OTP" in page_text:
            return {"status": "error", "message": "गलत OTP! Flipkart ने इसे अमान्य कर दिया।"}

        # 2. Check if login was actually successful (looking for Account elements or cookie auth)
        cookies = await context.cookies()
        auth_cookie_found = any(c['name'] in ['SN', 'at', 'S', 'T'] for c in cookies)

        if not auth_cookie_found and "account" not in page.url.lower():
            return {"status": "error", "message": "लॉगिन असफलता: OTP सत्यापन पास नहीं हुआ!"}

        # Save cookies ONLY if valid auth session confirmed
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f, indent=2)

        await session_store["browser"].close()
        await session_store["playwright"].stop()
        session_store.clear()

        return {"status": "success", "message": "असली लॉगिन सफल हुआ! सेषन कुकीज़ सुरक्षित कर ली गई हैं।"}

    except Exception as e:
        if "browser" in session_store:
            await session_store["browser"].close()
            session_store.clear()
        return {"status": "error", "message": f"सत्यापन में समस्या: {str(e)}"}
