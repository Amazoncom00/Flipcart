from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright
import json
import os

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration Variables
LOGIN_URL = "https://www.flipkart.com/account/login"
HOME_URL = "https://www.flipkart.com"
COOKIE_FILE = "saved_cookies.json"

# In-memory store for holding Playwright session during OTP verification
session_store = {}

class PhonePayload(BaseModel):
    phone: str

class OtpPayload(BaseModel):
    otp: str

class CheckoutPayload(BaseModel):
    product_url: str


@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html file not found!</h1>"


@app.post("/api/send-phone")
async def send_phone(payload: PhonePayload):
    try:
        # Close any lingering session
        if "browser" in session_store:
            await session_store["browser"].close()
            session_store.clear()

        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Navigate to login page
        await page.goto(LOGIN_URL, timeout=60000, wait_until="domcontentloaded")

        # Fill Phone Number (Handles multiple common Flipkart selector formats)
        phone_input = page.locator("input[type='text'], input[type='tel'], input._17N0O5").first
        await phone_input.fill(payload.phone)

        # Click Request OTP / Continue Button
        otp_btn = page.locator("button:has-text('Request OTP'), button:has-text('CONTINUE'), button._2KpZ6l").first
        await otp_btn.click()

        # Wait for OTP input field to appear
        await page.wait_for_selector("input[type='text'], input[maxlength='6'], input._16790_", timeout=15000)

        # Store active session in memory
        session_store["playwright"] = p
        session_store["browser"] = browser
        session_store["context"] = context
        session_store["page"] = page

        return {"status": "otp_required", "message": "OTP भेजा गया है। कृपया दर्ज करें।"}

    except Exception as e:
        if "browser" in session_store:
            await session_store["browser"].close()
            session_store.clear()
        return {"status": "error", "message": f"फ़ोन नंबर सबमिट करने में विफल: {str(e)}"}


@app.post("/api/verify-otp")
async def verify_otp(payload: OtpPayload):
    if "page" not in session_store:
        raise HTTPException(status_code=400, detail="कोई सक्रिय लॉगिन सेशन नहीं मिला!")

    try:
        page = session_store["page"]
        context = session_store["context"]

        # Enter OTP into the input field
        otp_input = page.locator("input[type='text'], input[maxlength='6'], input._16790_").first
        await otp_input.fill(payload.otp)

        # Click Verify / Login Button
        verify_btn = page.locator("button:has-text('VERIFY'), button:has-text('Login'), button[type='submit']").first
        await verify_btn.click()

        # Wait for redirection or logged-in state indicator
        await page.wait_for_timeout(5000)

        # Save context cookies to disk
        cookies = await context.cookies()
        with open(COOKIE_FILE, "w") as f:
            json.dump(cookies, f, indent=2)

        # Cleanup Playwright session
        await session_store["browser"].close()
        await session_store["playwright"].stop()
        session_store.clear()

        return {"status": "success", "message": "लॉगिन सफल हुआ! सेषन कुकीज़ सफलतापूर्वक सेव हो गई हैं।"}

    except Exception as e:
        if "browser" in session_store:
            await session_store["browser"].close()
            session_store.clear()
        return {"status": "error", "message": f"OTP सत्यापन विफल: {str(e)}"}


@app.post("/api/start-checkout")
async def start_checkout(payload: CheckoutPayload):
    if not os.path.exists(COOKIE_FILE):
        return {
            "status": "error",
            "message": "कुकीज़ नहीं मिलीं! कृपया पहले ऐप के जरिए लॉगिन पूरा करें।"
        }

    with open(COOKIE_FILE, "r") as f:
        saved_cookies = json.load(f)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.add_cookies(saved_cookies)
        page = await context.new_page()

        try:
            # Open target product URL
            await page.goto(payload.product_url, timeout=60000, wait_until="domcontentloaded")

            # Click 'Buy Now' button
            buy_now_btn = page.locator("button:has-text('Buy Now'), button:has-text('BUY NOW'), button._2KpZ6l").first
            await buy_now_btn.click()

            # Select Delivery Address / Continue
            await page.wait_for_selector("button:has-text('Deliver Here'), button:has-text('CONTINUE')", timeout=20000)
            deliver_btn = page.locator("button:has-text('Deliver Here'), button:has-text('CONTINUE')").first
            await deliver_btn.click()

            # Wait for Payment Gateway URL redirection
            await page.wait_for_url("**/checkout/**", timeout=25000)
            payment_url = page.url

            await browser.close()
            return {"status": "success", "payment_url": payment_url}

        except Exception as e:
            await browser.close()
            return {"status": "error", "message": f"ऑटोमेशन प्रक्रिया में गड़बड़ी: {str(e)}"}
