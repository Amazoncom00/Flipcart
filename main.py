from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright
import json
import os

app = FastAPI()

# CORS Middleware (WebApp और External Requests अलाऊ करने के लिए)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

COOKIE_FILE = "saved_cookies.json"

class CookiePayload(BaseModel):
    cookies: list[dict]

class CheckoutPayload(BaseModel):
    product_url: str


# EndPoint 1: Full-Page HTML WebApp लोड करना
@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html फाइल नहीं मिली!</h1>"


# EndPoint 2: WebApp से भेजी गई Session Cookies सेव करना
@app.post("/api/cookies")
async def save_cookies(payload: CookiePayload):
    try:
        with open(COOKIE_FILE, "w") as f:
            json.dump(payload.cookies, f, indent=2)
        return {"status": "success", "message": "लॉगिन सेषन कुकीज़ Render पर सफलतापूर्वक सेव हो गई हैं!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# EndPoint 3: Telegram Bot से लिंक रिसीव करके Headless Playwright चलाना
@app.post("/api/start-checkout")
async def start_checkout(payload: CheckoutPayload):
    if not os.path.exists(COOKIE_FILE):
        return {
            "status": "error", 
            "message": "कुकीज़ नहीं मिलीं! कृपया पहले WebApp के जरिए ई-कॉमर्स साइट पर लॉगिन करके कुकीज़ सिंक करें।"
        }

    # सेव की हुई कुकीज़ लोड करें
    with open(COOKIE_FILE, "r") as f:
        saved_cookies = json.load(f)

    async with async_playwright() as p:
        # Headless Browser चालू करना
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        # Session Cookies इंजेक्ट करना (Logged-in state बनाए रखने के लिए)
        await context.add_cookies(saved_cookies)
        page = await context.new_page()

        try:
            # 1. सीधे प्रोडक्ट लिंक पर जाना
            await page.goto(payload.product_url, timeout=60000, wait_until="domcontentloaded")

            # 2. 'Buy Now' बटन क्लिक करना (साइट के हिसाब से Selectors एडजस्ट करें)
            buy_button = page.locator("button#buy-now, .buy-now, #buyNow")
            await buy_button.first.click()

            # 3. एड्रेस सिलेक्शन और आगे बढ़ना
            await page.wait_for_selector(".address-card, #address-select", timeout=15000)
            await page.locator(".address-card, #address-select").first.click()
            
            continue_button = page.locator("button#continue, .deliver-here-btn")
            await continue_button.first.click()

            # 4. पेमेंट गेटवे पेज का URL आने तक रुकना
            await page.wait_for_url("**/payment**", timeout=20000)
            payment_url = page.url

            await browser.close()
            # बोट को नया पेमेंट लिंक वापस भेजना
            return {"status": "success", "payment_url": payment_url}

        except Exception as e:
            await browser.close()
            return {"status": "error", "message": f"ऑटोमेशन में गड़बड़ी: {str(e)}"}
