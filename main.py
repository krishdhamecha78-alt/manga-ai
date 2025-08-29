mport os
import subprocess
import requests
from typing import List
from fastapi import FastAPI, Body
from playwright.async_api import async_playwright
from playwright_stealth import stealth   # ✅ correct import

# ✅ Ensure Chromium is installed at runtime (safe wrapper for Render)
try:
    subprocess.run(["playwright", "install", "chromium"], check=True)
except Exception as e:
    print("⚠️ Playwright install skipped:", e)

BASE_DOWNLOADS = "downloads"
os.makedirs(BASE_DOWNLOADS, exist_ok=True)  # ✅ ensure folder exists

UPLOAD_API = "https://your-site.com/api/upload"  # TODO: CHANGE THIS
HEADERS = {"User-Agent": "Mozilla/5.0"}

# 🔑 Optional proxy (set env var PROXY_SERVER like "http://user:pass@host:port")
PROXY_SERVER = os.getenv("PROXY_SERVER")

app = FastAPI()


# ---------------------- Scraper Helpers ----------------------

async def get_chapter_links(page, series_url: str):
    """Collect chapter links from a series page (with debug logs)."""
    await page.goto(series_url, wait_until="domcontentloaded", timeout=60000)

    links = await page.eval_on_selector_all("a", "els => els.map(el => el.href)")
    print(f"🔗 Found {len(links)} total links on page")

    if links:
        print("🔎 First 10 links:")
        for l in links[:10]:
            print("   ", l)

    chapter_links = [l for l in links if "chapter" in l.lower()]
    print(f"✅ Filtered {len(chapter_links)} chapter links")
    return sorted(set(chapter_links))


async def get_chapter_images(page, chapter_url: str):
    """Collect all image URLs from a chapter page (with debug logs)."""
    await page.goto(chapter_url, wait_until="domcontentloaded", timeout=60000)
    img_urls = await page.eval_on_selector_all("img", "els => els.map(el => el.src)")
    print(f"🖼️  Found {len(img_urls)} images in {chapter_url}")
    return [url for url in img_urls if url.endswith((".webp", ".jpg", ".png"))]


def download_images(img_urls, chapter_folder):
    """Download chapter images to local folder."""
    os.makedirs(chapter_folder, exist_ok=True)
    files = []
    for i, url in enumerate(img_urls, 1):
        ext = os.path.splitext(url)[-1] or ".jpg"
        filename = os.path.join(chapter_folder, f"{i:03d}{ext}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            with open(filename, "wb") as f:
                f.write(r.content)
            files.append(filename)
            print(f"⬇️  Downloaded {filename}")
        except Exception as e:
            print(f"❌ Failed {url}: {e}")
    return files


def upload_chapter(chapter_title: str, files: List[str]):
    """Upload chapter images to external API (with logs)."""
    results = []
    for file in files:
        try:
            with open(file, "rb") as f:
                files_data = {"file": f}
                data = {"chapter": chapter_title}
                r = requests.post(UPLOAD_API, files=files_data, data=data, timeout=30)
                results.append({file: r.status_code})
                print(f"☁️  Uploaded {file} → {r.status_code}")
        except Exception as e:
            results.append({file: f"error: {e}"})
            print(f"⚠️ Upload failed for {file}: {e}")
    return results


# ---------------------- Main Series Processor ----------------------

async def process_series(series_url: str):
    """Scrape, download, and upload the entire manga series."""
    results = []
    async with async_playwright() as p:
        browser_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-zygote"
        ]

        # ✅ Launch with optional proxy
        launch_opts = {"headless": True, "args": browser_args}
        if PROXY_SERVER:
            launch_opts["proxy"] = {"server": PROXY_SERVER}

        browser = await p.chromium.launch(**launch_opts)
        page = await browser.new_page()

        # ✅ Apply stealth to evade Cloudflare / bot detection
        await stealth(page)

        chapters = await get_chapter_links(page, series_url)
        print(f"📖 Found {len(chapters)} chapters total")

        for idx, chapter_url in enumerate(chapters, 1):
            chapter_title = f"Chapter_{idx}"
            chapter_folder = os.path.join(BASE_DOWNLOADS, chapter_title)

            img_urls = await get_chapter_images(page, chapter_url)
            files = download_images(img_urls, chapter_folder)
            upload_results = upload_chapter(chapter_title, files)

            results.append({
                "chapter": chapter_title,
                "chapter_url": chapter_url,
                "pages": len(files),
                "upload_status": upload_results
            })

        await browser.close()
    return results


# ---------------------- API Endpoints ----------------------

@app.get("/")
async def root():
    return {"message": "API is running 🚀"}


@app.post("/process")
async def process_api(series_url: str = Body(..., embed=True)):
    results = await process_series(series_url)
    return {"status": "done", "chapters": results}


@app.get("/status")
async def status():
    return {"status": "running", "downloads_folder": BASE_DOWNLOADS}
