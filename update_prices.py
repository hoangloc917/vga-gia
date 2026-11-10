"""Lấy giá card màn hình RTX 30 / 40 / 50 từ GearVN và lưu vào data.js.

Chạy:  python update_prices.py
Mỗi lần chạy sẽ ghi thêm giá của ngày hôm nay vào history.json,
rồi tạo lại data.js để index.html đọc.
"""
import datetime
import json
import pathlib
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://gearvn.com"
LIST_URL = BASE + "/collections/vga-card-man-hinh"
MAX_PAGES = 15
HERE = pathlib.Path(__file__).parent
HISTORY_FILE = HERE / "history.json"
DATA_FILE = HERE / "data.js"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9",
}

PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+)\s*đ")
SERIES_RE = re.compile(r"rtx\s*(30|40|50)\d{2}", re.I)
# Cắt phần thông số (xung nhịp, VRAM...) bị dính vào tên
SPEC_RE = re.compile(r"\s+(?:\d{3,}\s*Mhz|\d+,\d{3,}\s*GB|\d{3,};AI)", re.I)


def slug_to_name(href):
    slug = href.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").title()


def parse_page(html):
    """Trả về dict {url: {name, price, original}} của một trang danh sách."""
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    images = {}
    for a in soup.select('a[href*="/products/"]'):
        href = a["href"].split("?")[0]
        if href.startswith("/"):
            href = BASE + href
        for img in a.find_all("img"):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
            if src.startswith("//"):
                src = "https:" + src
            if src.startswith("http"):
                images.setdefault(href, src)
                break
        text = a.get_text(" ", strip=True)
        prices = [int(p.replace(".", "")) for p in PRICE_RE.findall(text)]
        if not prices:
            continue
        price = prices[-1]
        original = prices[0] if len(prices) > 1 and prices[0] > price else None
        parts = re.split(r"(?=Card màn hình)", text)
        name = parts[1].strip() if len(parts) > 1 else slug_to_name(href)
        # Tên thường lặp lại 2 lần, giữ lại phần đầu
        half = name.split(" Card màn hình")[0]
        name = half.strip() or name
        name = PRICE_RE.split(name)[0].strip() or name
        name = SPEC_RE.split(name)[0].strip() or name
        found[href] = {"name": name, "price": price, "original": original, "image": None}
    for href, item in found.items():
        item["image"] = images.get(href)
    return found


def get_series(name, url):
    m = SERIES_RE.search(name) or SERIES_RE.search(url.replace("-", " "))
    return f"RTX {m.group(1)}" if m else None


# Trang danh sách của GearVN đảo thứ tự sản phẩm mỗi lần tải, nên nếu chỉ đọc
# 1 danh sách thì sẽ sót hàng. Ta đọc nhiều danh sách và nhiều lượt rồi gộp lại.
SOURCES = [
    "/collections/vga-card-man-hinh",
    "/collections/vga-rtx-50-series",
    "/collections/vga-rtx-5090-series",
    "/collections/vga-rtx-5080",
    "/collections/vga-rtx-5070-ti-series",
    "/collections/vga-rtx-5070-series",
    "/collections/vga-rtx-5060-ti-series",
    "/collections/vga-rtx-5060-series",
    "/collections/nvidia-geforce-quadro-chinh-hang",
    "/collections/vga-rtx-4090",
    "/collections/vga-rtx-4080",
    "/collections/vga-rtx-4070",
    "/collections/vga-rtx-ampere-3060-12gb",
    "/collections/vga-rtx-ampere-3050",
]
PASSES = 2


def scrape_source(path, products):
    for page in range(1, MAX_PAGES + 1):
        resp = requests.get(BASE + path, params={"page": page}, headers=HEADERS, timeout=30)
        if resp.status_code == 404:
            print(f"  Bỏ qua {path} (không tìm thấy)")
            return
        resp.raise_for_status()
        page_items = parse_page(resp.text)
        if not page_items:
            return  # hết trang
        for url, item in page_items.items():
            old = products.get(url)
            if old is None:
                products[url] = item
            elif not old["image"] and item["image"]:
                old["image"] = item["image"]
        time.sleep(0.5)


def scrape():
    products = {}
    for n in range(PASSES):
        for path in SOURCES:
            before = len(products)
            scrape_source(path, products)
            print(f"Lượt {n + 1} {path}: +{len(products) - before} (tổng {len(products)})")
    return products


def main():
    # Dùng giờ Việt Nam (UTC+7) để chạy trên máy chủ nước ngoài vẫn đúng ngày
    vn = datetime.timezone(datetime.timedelta(hours=7))
    now = datetime.datetime.now(vn)
    today = now.date().isoformat()
    history = {}
    if HISTORY_FILE.exists():
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))

    products = scrape()
    items = []
    for url, p in products.items():
        series = get_series(p["name"], url)
        if not series:
            continue  # bỏ qua GTX, RTX PRO, Radeon...
        rec = history.setdefault(url, {"name": p["name"], "prices": {}})
        rec["name"] = p["name"]
        rec["image"] = p["image"] or rec.get("image")
        rec["prices"][today] = p["price"]
        prices = rec["prices"]
        dates = sorted(prices)
        older = [d for d in dates if d < today]
        prev = prices[older[-1]] if older else None
        # Ngày bắt đầu của mức giá hiện tại
        changed = dates[0]
        for i in range(len(dates) - 1, 0, -1):
            if prices[dates[i]] != prices[dates[i - 1]]:
                changed = dates[i]
                break
        cutoff = (now.date() - datetime.timedelta(days=92)).isoformat()
        items.append(
            {
                "name": p["name"],
                "url": url,
                "image": rec["image"],
                "series": series,
                "price": p["price"],
                "original": p["original"],
                "prev": prev,
                "first": dates[0],
                "changed": changed,
                "hist": [[d, prices[d]] for d in dates if d >= cutoff],
            }
        )

    if not items:
        raise SystemExit(
            "Không đọc được sản phẩm nào. Có thể GearVN đã đổi giao diện, "
            "hãy gửi thông báo này cho AI để sửa lại script."
        )

    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    payload = {
        "updated": now.strftime("%d/%m/%Y %H:%M"),
        "source": "GearVN",
        "items": sorted(items, key=lambda x: x["price"]),
    }
    DATA_FILE.write_text(
        "window.PRICE_DATA = " + json.dumps(payload, ensure_ascii=False) + ";",
        encoding="utf-8",
    )
    print(f"Xong: {len(items)} card RTX 30/40/50. Mở index.html để xem.")


if __name__ == "__main__":
    main()
