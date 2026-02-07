# Contributing to LocalToast

Thank you for your interest in contributing! 🍞

LocalToast is not just another recipe manager; it is an exercise in **digital longevity**. Our primary goal is to ensure the application runs flawlessly on hardware that manufacturers have deemed "obsolete," specifically targeting the **iPad 2 (iOS 9)** and early Android tablets.

To achieve this, we enforce strict constraints on frontend code. Please review them carefully.

## ⚠️ The "Golden Rules" of Legacy Support

If your PR breaks the iPad 2, it will be rejected.

### 1. JavaScript: Strict ES5 Only
We support browsers that lack modern features (e.g., Safari 9). Do not use Babel or transpilations; we write raw, compatible code.

* ❌ **NO** `const` or `let`. Use `var` exclusively.
* ❌ **NO** Arrow functions `() => {}`. Use `function() {}`.
* ❌ **NO** Template literals (backticks). Use string concatenation (`'String ' + variable`).
* ❌ **NO** `fetch()` API. Use `XMLHttpRequest` for all AJAX calls.
* ❌ **NO** Async/Await. Use callbacks.

### 2. CSS: Flexbox Limitations
While iOS 9 supports Flexbox, it has partial implementation quirks.

* ❌ **NO** `gap` property. This is not supported in older flex implementations. Use `margin` on children instead.
* ✅ **DO** Use `-webkit-transform: translateZ(0)` on scrollable cards/elements. This triggers hardware acceleration on older mobile GPUs to prevent UI stutter.

### 3. Performance & Images
* **Images:** Must be heavily compressed. We serve WebP with JPG fallbacks.
* **Lighthouse:** We target a 100 Performance score. Avoid heavy libraries (no jQuery, no React, no Vue).

## 🛠️ Local Development

### Prerequisites
* Docker & Docker Compose

### Setup
1.  Clone the repo.
2.  Run `docker-compose up -d`.
3.  Access the site at `http://localhost:8001`.

### Scraper Updates
If you are working on the ingestion logic and need to pull the latest scrapers without rebuilding the image:
1.  Set `UPDATE_SCRAPERS=true` in `docker-compose.yml`.
2.  Restart the container.