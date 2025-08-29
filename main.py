import os
import asyncio
import requests
from fastapi import FastAPI, Body
from playwright.async_api import async_playwright
import subprocess

# Ensure Chromium is installed
subprocess.run(["playwright", "install", "chromium"], check=True)

BASE_DOWNLOADS = "downloads"
UPLOAD_API = "https://your-site.com/api/upload"  # CHANGE THIS
HEADERS = {"User-Agent": "Mozilla/5.0"}

app = FastAPI()


async def get_chapter_links(page, series_url: str):
    await page.goto(series_url, wait_until="networkidle")
    links = await page.eval_on_selector_all(
        "a[href*='chapter']",
        "els => els.map(el => el.href)"
    )
    return sorted(set(links))


async def get_chapter_images(page, chapter_url: str):
    await page.goto(chapter_url, wait_until="networkidle")
    img_urls = await page.eval_on_selector_all(
        "img",
        "els => els.map(el => el.src)"
    )
    return [url for url in img_urls if url.endswith((".webp", ".jpg", ".png"))]


def download_images(img_urls, chapter_folder):
    os.makedirs(chapter_folder, exist_ok=True)
    files = []
    for i, url in enumerate(img_urls, 1):
        ext = os.path.splitext(url)[-1]
        filename = os.path.join(chapter_folder, f"{i:03d}{ext}")
        print(f"Downloading: {url}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            with open(filename, "wb") as f:
                f.write(r.content)
            files.append(filename)
        except Exception as e:
            print(f"❌ Failed {url}: {e}")
    return files


def upload_chapter(chapter_title: str, files: list[str]):
    print(f"Uploading {chapter_title}...")
    results = []
    for file in files:
        try:
            with open(file, "rb") as f:
                files_data = {"file": f}
                data = {"chapter": chapter_title}
                r = requests.post(UPLOAD_API, files=files_data, data=data)
                results.append({file: r.status_code})
        except Exception as e:
            results.append({file: f"error: {e}"})
    return results


async def process_series(series_url: str):
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        chapters = await get_chapter_links(page, series_url)
        print(f"📖 Found {len(chapters)} chapters")

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


@app.post("/process")
async def process_api(series_url: str = Body(..., embed=True)):
    results = await process_series(series_url)
    return {"status": "done", "chapters": results}

