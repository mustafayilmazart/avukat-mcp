# Bu modül Pillow (PIL) kullanarak görsel boyutlandırma ve kırpma işlemlerini yapar.
# Değiştirilecek görsel, orijinalinin boyutuna ve oranına tam uyması gerekir ki
# site layout'u bozulmasın.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    PIL_VAR = True
except ImportError:
    PIL_VAR = False

logger = logging.getLogger("avukat-mcp.gorsel_islem")


def gorsel_boyutla(
    kaynak_yol: Path,
    hedef_yol: Path,
    hedef_genislik: int,
    hedef_yukseklik: int,
    kalite: int = 90,
) -> bool:
    """
    Görseli hedef boyuta getirir: 'cover' stratejisi (oran koruyarak kırparak doldurur).
    Çıktı formatı hedef dosya uzantısından çıkarılır (.webp, .jpg, .png).
    """
    if not PIL_VAR:
        logger.error("Pillow yüklü değil — görsel işleme yapılamaz")
        return False

    try:
        img = Image.open(kaynak_yol)

        # Şeffaflık kontrolü — JPEG'e çevirirken RGBA → RGB
        if img.mode in ("RGBA", "LA", "P") and hedef_yol.suffix.lower() in (".jpg", ".jpeg"):
            arka = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            arka.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = arka

        # 'cover' kırpma — hedef oranı koruyarak doldur
        kaynak_oran = img.width / img.height
        hedef_oran = hedef_genislik / hedef_yukseklik

        if kaynak_oran > hedef_oran:
            # Kaynak daha geniş — sağdan/soldan kırp
            yeni_genislik = int(img.height * hedef_oran)
            x = (img.width - yeni_genislik) // 2
            img = img.crop((x, 0, x + yeni_genislik, img.height))
        elif kaynak_oran < hedef_oran:
            # Kaynak daha uzun — üst/alt kırp
            yeni_yukseklik = int(img.width / hedef_oran)
            y = (img.height - yeni_yukseklik) // 2
            img = img.crop((0, y, img.width, y + yeni_yukseklik))

        # Hedef boyuta resize
        img = img.resize((hedef_genislik, hedef_yukseklik), Image.Resampling.LANCZOS)

        hedef_yol.parent.mkdir(parents=True, exist_ok=True)

        # Format tespiti
        ext = hedef_yol.suffix.lower()
        if ext == ".webp":
            img.save(hedef_yol, "WEBP", quality=kalite, method=6)
        elif ext in (".jpg", ".jpeg"):
            img.save(hedef_yol, "JPEG", quality=kalite, optimize=True, progressive=True)
        elif ext == ".png":
            img.save(hedef_yol, "PNG", optimize=True)
        else:
            img.save(hedef_yol)

        return True
    except Exception as e:
        logger.error(f"Görsel işleme hatası: {e}")
        return False


# Dosya adı / alt metninden uygun Unsplash arama kelimesi tahmin et
KATEGORI_SOZLUGU = {
    # team/coaching
    ("kocluk", "koç", "coach", "mentor"): "coaching session business",
    ("egitim", "education", "workshop", "training"): "professional workshop training",
    ("takim", "team", "teamwork"): "business team meeting",
    ("toplanti", "meeting"): "business meeting conference",
    # office / work
    ("ofis", "office", "is", "work"): "modern office workspace",
    ("lider", "leader", "yonetici", "management"): "leadership business professional",
    ("girisim", "entrepreneur", "startup"): "startup entrepreneur modern",
    # specific sectors
    ("banka", "bank", "finans", "finance"): "corporate finance banking modern",
    ("saglik", "health", "medical"): "healthcare professional modern",
    ("teknoloji", "technology", "tech"): "technology innovation modern",
    # abstract concepts
    ("strateji", "strategy", "plan"): "strategy planning board",
    ("basari", "success", "gol", "goal"): "success achievement business",
    ("iletisim", "communication"): "communication team discussion",
    # stock neutral
    ("people", "insan"): "professional diverse team",
    ("data", "veri", "analitik", "analytics"): "data analytics dashboard modern",
    # default generic
    ("agile", "scrum", "kanban"): "agile workshop collaborative",
    ("innovation", "inovasyon"): "innovation creative modern",
}


def gorsel_kategori_tahmin(
    dosya_adi: str,
    alt_text: str = "",
    caption: str = "",
    baglam: str = "",
) -> str:
    """
    Dosya adı + alt text + caption + sayfa bağlamına bakarak uygun Unsplash
    arama kelimesini tahmin eder. Konsept kaymasını minimize etmek için
    mümkün olduğunca spesifik kalır.
    """
    tum_metin = f"{dosya_adi} {alt_text} {caption} {baglam}".lower()

    for anahtarlar, sorgu in KATEGORI_SOZLUGU.items():
        if any(a in tum_metin for a in anahtarlar):
            return sorgu

    # Default — iş/profesyonel temalı
    return "professional business modern"
