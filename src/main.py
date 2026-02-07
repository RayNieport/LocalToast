from fastapi import FastAPI, Form, Request, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from recipe_scrapers import scrape_me
from PIL import Image, ImageOps, ExifTags
from io import BytesIO
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from collections import Counter
from typing import List
from pydantic import BaseModel
import yaml
import os
import glob
import requests
import time
import shutil
import re
import subprocess
import html
import socket
import uuid

app = FastAPI()

# --- CONFIGURATION ---
CONTENT_DIR = "/app/site/content/recipes"
# Internal URL to check if Nginx has served the new build (Must match Nginx port)
HUGO_INTERNAL_URL = "http://127.0.0.1:8080" 
templates = Jinja2Templates(directory="templates")

# Browser headers to avoid 403 Forbidden on some recipe sites
FAKE_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# --- SECURITY LIMITS ---
# Prevent decompression bombs
Image.MAX_IMAGE_PIXELS = 90_000_000 
BATCH_TIMEOUT = 3600

# --- CACHE ---
TAXONOMY_CACHE = {"tags": Counter()}
PENDING_BATCHES = {}

# --- DATA MODELS ---
class BulkCommitItem(BaseModel):
    id: int
    tags: str

class BulkCommitPayload(BaseModel):
    batch_id: str
    items: List[BulkCommitItem]

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def generate_slug(title):
    """Generates a URL-safe slug from a title."""
    if not title: return ""
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')

def is_safe_url(url):
    """Validates that a URL belongs to a public, non-local domain."""
    if not url or not url.strip(): return False
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ['http', 'https']: return False
        hostname = parsed.hostname
        if not hostname: return False
        # block loopback/local
        if hostname in ['localhost', '127.0.0.1', '::1', '0.0.0.0']: return False
        try:
            ip = socket.gethostbyname(hostname)
        except:
            return False 
        # block private ranges
        ip_parts = [int(x) for x in ip.split('.')]
        if ip_parts[0] == 10: return False
        if ip_parts[0] == 192 and ip_parts[1] == 168: return False
        if ip_parts[0] == 172 and 16 <= ip_parts[1] <= 31: return False
        if ip_parts[0] == 127: return False
        return True
    except:
        return False

def trigger_hugo_rebuild():
    """Touches config.toml to force Hugo (running in watch mode) to rebuild."""
    try:
        config_path = "/app/site/config.toml"
        if os.path.exists(config_path):
            Path(config_path).touch()
    except Exception as e:
        print(f"Warning: Failed to trigger Hugo rebuild: {e}")

def rebuild_taxonomy_cache():
    """Scans all recipe markdown files to rebuild the tag cloud."""
    global TAXONOMY_CACHE
    print("Rebuilding Tag Cache...", flush=True)
    tag_counter = Counter()
    
    files = glob.glob(os.path.join(CONTENT_DIR, "*", "index.md"))
    for f in files:
        try:
            with open(f, 'r') as file:
                # Read only head to avoid loading full content
                head = [next(file) for _ in range(20)]
                content = "".join(head)
                match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
                if match:
                    data = yaml.safe_load(match.group(1))
                    if 'tags' in data:
                        for t in data['tags']: 
                            if t: tag_counter[str(t).strip().lower()] += 1
        except: pass
        
    TAXONOMY_CACHE["tags"] = tag_counter

def update_taxonomy_counters(old_tags=None, new_tags=None):
    """Incrementally updates the in-memory tag cache."""
    global TAXONOMY_CACHE
    if old_tags:
        TAXONOMY_CACHE["tags"].subtract(old_tags)
    if new_tags:
        TAXONOMY_CACHE["tags"].update(new_tags)
    # Remove zero/negative counts
    TAXONOMY_CACHE["tags"] = +TAXONOMY_CACHE["tags"]

def get_cached_tags():
    """Returns tags sorted by popularity."""
    tag_items = [[k, v] for k, v in TAXONOMY_CACHE["tags"].items()]
    return sorted(tag_items, key=lambda x: (-x[1], x[0]))

def cleanup_expired_batches():
    now = time.time()
    expired_ids = [bid for bid, data in PENDING_BATCHES.items() if now - data['timestamp'] > BATCH_TIMEOUT]
    for bid in expired_ids:
        del PENDING_BATCHES[bid]

def clean_ingredient(text):
    """Standardizes ingredient units and formatting."""
    # Add space between number and letter (1cup -> 1 cup)
    text = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', text)
    
    # Unit normalization logic
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def download_image_with_fallback(image_url, source_url=None):
    """Attempts download via Requests, falls back to subprocess Curl."""
    if not image_url or not image_url.strip(): return None
    
    # Method 1: Python Requests
    try:
        session = requests.Session()
        session.headers.update(FAKE_BROWSER_HEADERS)
        if source_url: session.headers.update({'Referer': source_url})
        response = session.get(image_url, timeout=10)
        if response.status_code == 200:
            return Image.open(BytesIO(response.content)).convert('RGB')
    except: pass
    
    # Method 2: System Curl (often handles TSL/Headers better)
    try:
        cmd = ["curl", "-L", "-A", FAKE_BROWSER_HEADERS["User-Agent"], "--max-time", "15", image_url]
        if source_url: cmd.extend(["-e", source_url])
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and len(result.stdout) > 0:
            return Image.open(BytesIO(result.stdout)).convert('RGB')
    except Exception as e: 
        print(f"Curl failed: {e}")
    
    return None

def scrape_recipe_data(url):
    """Scrapes data using recipe_scrapers library."""
    scraper = scrape_me(url)
    clean_ing = [clean_ingredient(i) for i in scraper.ingredients()]
    
    # Combine Host, Cuisine, and Category into Tags
    raw_tags = [scraper.host()]
    try:
        c = scraper.cuisine()
        if c: raw_tags.extend([x.strip() for x in c.split(',')] if "," in c else [c])
    except: pass
    
    cat_raw = scraper.category()
    if cat_raw:
        raw_tags.extend([c.strip().lower() for c in cat_raw.split(',') if c.strip()])

    final_tags = list(dict.fromkeys([t.replace('-', ' ').strip().lower() for t in raw_tags if t]))
        
    return {
        "title": scraper.title(), 
        "image_url": scraper.image(), 
        "source_url": url,
        "tags": final_tags, 
        "ingredients": clean_ing,
        "instructions": scraper.instructions()
    }

def process_and_save_recipe(data, original_slug=None):
    """Saves recipe to disk, processing images and frontmatter."""
    try:
        title = data['title']
        slug = generate_slug(title)
        recipe_path = os.path.join(CONTENT_DIR, slug)
        
        # Duplicate protection
        if os.path.exists(recipe_path):
            if not original_slug or original_slug != slug:
                return False, f"Recipe '{title}' already exists.", None

        os.makedirs(recipe_path, exist_ok=True)
        
        # Image Processing
        original_img = None
        if data.get('image_bytes'):
            try:
                img_stream = BytesIO(data['image_bytes'])
                original_img = Image.open(img_stream)
                original_img.verify()
                img_stream.seek(0)
                original_img = Image.open(img_stream)
                original_img = ImageOps.exif_transpose(original_img) # Fix rotation
                original_img = original_img.convert('RGB')
            except Exception: original_img = None

        if not original_img:
            original_img = download_image_with_fallback(data.get('image_url'), data.get('source_url'))

        # Fallback to default if no image found/uploaded
        img_filename_jpg = "cover.jpg" if original_img else (data.get('existing_image') or "")
        if not img_filename_jpg and not original_img:
            try: 
                original_img = Image.open("/app/default.jpg").convert('RGB')
                img_filename_jpg = "cover.jpg"
            except: pass

        # Save Image Variants (WebP + JPG)
        if original_img:
            sizes = [("", 800, 600, 80, 80), ("_small", 400, 300, 50, 50)]
            for suffix, w, h, q_jpg, q_webp in sizes:
                resample = Image.Resampling.BICUBIC if suffix == "_small" else Image.Resampling.LANCZOS
                resized = ImageOps.fit(original_img, (w, h), method=resample, centering=(0.5, 0.5))
                resized.save(os.path.join(recipe_path, f"cover{suffix}.jpg"), "JPEG", quality=q_jpg, optimize=True)
                resized.save(os.path.join(recipe_path, f"cover{suffix}.webp"), "WEBP", quality=q_webp, method=6)
        
        # Save Markdown
        tags_list = data.get('tags', [])
        if isinstance(tags_list, str):
            tags_list = [t.strip().lower() for t in tags_list.split(',') if t.strip()]

        frontmatter = {
            "title": title, 
            "date": datetime.now().strftime("%Y-%m-%d"),
            "tags": tags_list, 
            "image": img_filename_jpg, 
            "source_url": data.get('source_url')
        }

        md_content = f"""---\n{yaml.dump(frontmatter)}\n---\n## Ingredients\n{chr(10).join([f'- {i}' for i in data['ingredients']])}\n\n## Instructions\n{data['instructions']}\n"""
        
        with open(os.path.join(recipe_path, "index.md"), "w") as f: f.write(md_content)
        return True, slug, {"tags": tags_list}
        
    except Exception as e: return False, str(e), None

def load_existing_recipe(slug):
    """Parses a markdown file and returns recipe data."""
    try:
        path = os.path.join(CONTENT_DIR, slug, "index.md")
        with open(path, 'r') as f: content = f.read()
        parts = content.split('---', 2)
        if len(parts) < 3: return None
        fm = yaml.safe_load(parts[1])
        body = parts[2]
        
        # Regex to extract sections
        ing_match = re.search(r'## Ingredients\n(.*?)\n## Instructions', body, re.DOTALL)
        ingredients = [line.lstrip('- ').strip() for line in ing_match.group(1).strip().split('\n')] if ing_match else []
        
        inst_match = re.search(r'## Instructions\n(.*)', body, re.DOTALL)
        instructions = inst_match.group(1).strip() if inst_match else ""
        
        return {
            "title": fm.get('title', ''), 
            "slug": slug, 
            "existing_image": fm.get('image', ''), 
            "source_url": fm.get('source_url', ''),
            "tags": ", ".join(fm.get('tags', [])),
            "raw_tags_list": fm.get('tags', []),
            "ingredients": "\n".join(ingredients), 
            "instructions": instructions
        }
    except Exception: return None

# ==============================================================================
# API ENDPOINTS
# ==============================================================================

@app.on_event("startup")
def startup_event():
    rebuild_taxonomy_cache()

@app.get("/")
def health_check():
    return {"status": "Ingester is running"}

@app.post("/check-title")
def check_title_availability(title: str = Form(...), original_slug: str = Form(None)):
    slug = generate_slug(title)
    if not slug: return {"exists": False}
    if original_slug and slug == original_slug: return {"exists": False}
    return {"exists": os.path.exists(os.path.join(CONTENT_DIR, slug))}

@app.post("/edit")
def edit_recipe(request: Request, slug: str = Form(None)):
    context = {"request": request, "known_tags": get_cached_tags(), "error": None}
    if slug:
        data = load_existing_recipe(slug)
        if data: context.update(data)
        else: context["error"] = f"Could not load recipe: {slug}"
    return templates.TemplateResponse("editor.html", context)

@app.post("/stage")
def stage_recipe(request: Request, url: str = Form(None)):
    if not url or not is_safe_url(url): 
        return templates.TemplateResponse("editor.html", {
            "request": request, "known_tags": get_cached_tags(), "error": "Invalid URL"
        })

    context = {"request": request, "known_tags": get_cached_tags(), "source_url": url, "error": None}
    try:
        scraped = scrape_recipe_data(url)
        # Convert lists to strings for the textarea inputs
        scraped['tags'] = ", ".join(scraped['tags'])
        scraped['ingredients'] = "\n".join(scraped['ingredients'])
        context.update(scraped)
    except Exception as e: context["error"] = str(e)
    return templates.TemplateResponse("editor.html", context)

@app.post("/save")
async def save_recipe(
    request: Request,
    title: str = Form(...), 
    image_url: str = Form(None), 
    file: UploadFile = File(None),
    existing_image: str = Form(None), 
    source_url: str = Form(None), 
    tags: str = Form(""), 
    ingredients: str = Form(""), 
    instructions: str = Form(""),
    original_slug: str = Form(None)
):
    # Validation
    if not ingredients.strip() or not instructions.strip():
        return JSONResponse(status_code=400, content={"success": False, "message": "Missing content."})

    # Data Construction
    data = {
        "title": title, 
        "image_url": image_url if is_safe_url(image_url) else None, 
        "image_bytes": await file.read() if file and file.filename else None, 
        "existing_image": existing_image,
        "source_url": source_url if is_safe_url(source_url) else None, 
        "tags": [html.escape(t.strip()) for t in tags.split(',') if t.strip()],
        "ingredients": [html.escape(l.strip()) for l in ingredients.split('\n') if l.strip()],
        "instructions": html.escape(instructions)
    }

    # Save
    success, result_slug, saved_meta = process_and_save_recipe(data, original_slug)
    
    if success:
        # Cleanup old folder if renamed
        if original_slug and result_slug != original_slug:
            shutil.rmtree(os.path.join(CONTENT_DIR, original_slug), ignore_errors=True)
        
        # Update Cache & Trigger Rebuild
        old_data = load_existing_recipe(original_slug) if original_slug else None
        update_taxonomy_counters(old_tags=old_data['raw_tags_list'] if old_data else [], new_tags=saved_meta['tags'])
        trigger_hugo_rebuild()
        
        # Wait for Nginx/Hugo availability
        check_url = f"{HUGO_INTERNAL_URL}/recipes/{result_slug}/"
        for _ in range(20): # Wait up to 10 seconds
            try:
                if requests.get(check_url, timeout=0.5).status_code == 200: break
            except: pass
            time.sleep(0.5)
            
        return JSONResponse(content={"success": True, "redirect_url": f"/recipes/{result_slug}/"})
    else:
        return JSONResponse(status_code=400, content={"success": False, "message": result_slug})

@app.post("/bulk")
def bulk_import(request: Request, urls: str = Form(None)):
    cleanup_expired_batches()
    if not urls: return RedirectResponse(url="/add", status_code=303)
    
    batch_id = str(uuid.uuid4())
    staged_items = []
    
    for idx, url in enumerate(urls.split('\n')):
        url = url.strip()
        if not url: continue
        
        if not is_safe_url(url):
            staged_items.append({"id": idx, "success": False, "url": url, "message": "Unsafe URL"})
            continue

        try:
            data = scrape_recipe_data(url)
            slug = generate_slug(data['title'])
            staged_items.append({
                "id": idx, "success": True, "title": data['title'], "url": url,
                "proposed_slug": slug, "is_duplicate": os.path.exists(os.path.join(CONTENT_DIR, slug)),
                "tags": ", ".join(data['tags']),
                "data": data
            })
        except Exception as e:
            staged_items.append({"id": idx, "success": False, "url": url, "message": str(e)})
            
    PENDING_BATCHES[batch_id] = {"timestamp": time.time(), "items": staged_items}    
    return templates.TemplateResponse("bulk_results.html", {
        "request": request, "results": staged_items, "batch_id": batch_id, "known_tags": get_cached_tags()
    })

@app.post("/bulk-commit")
def bulk_commit(payload: BulkCommitPayload):
    if payload.batch_id not in PENDING_BATCHES:
        return JSONResponse(status_code=404, content={"success": False, "message": "Batch expired."})
        
    updates_map = {item.id: item.tags for item in payload.items}
    
    for item in PENDING_BATCHES[payload.batch_id]["items"]:
        if not item.get("success") or item.get("is_duplicate"): continue
        
        recipe_data = item['data']
        if item['id'] in updates_map:
             recipe_data['tags'] = updates_map[item['id']] # Update tags with user edits

        success, _, saved_meta = process_and_save_recipe(recipe_data)
        if success: update_taxonomy_counters(new_tags=saved_meta['tags'])

    del PENDING_BATCHES[payload.batch_id]
    trigger_hugo_rebuild()
    time.sleep(2.0)
    return {"success": True}

@app.post("/test-image")
def test_image_availability(url: str = Form(...), source_url: str = Form(None)):
    if not is_safe_url(url): return {"success": False}
    return {"success": bool(download_image_with_fallback(url, source_url))}

@app.post("/delete")
def delete_recipe(slug: str = Form(...)):
    if not slug or "/" in slug: return HTMLResponse("Invalid slug", status_code=400)
    try:
        path = os.path.join(CONTENT_DIR, slug)
        if os.path.exists(path):
            old_data = load_existing_recipe(slug)
            shutil.rmtree(path)
            if old_data: update_taxonomy_counters(old_tags=old_data['raw_tags_list'])
            trigger_hugo_rebuild()
            time.sleep(1.5)
            return RedirectResponse(url="/", status_code=303)
        return HTMLResponse("Recipe not found", status_code=404)
    except Exception as e: return HTMLResponse(str(e), status_code=500)