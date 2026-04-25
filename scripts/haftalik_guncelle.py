r"""
Haftalık mevzuat güncelleme CLI script'i.
Windows Task Scheduler veya Linux cron ile haftada bir çalıştırılmak üzere tasarlanmıştır.

Kullanım:
    python scripts/haftalik_guncelle.py                    # Tüm kaynakları günceller
    python scripts/haftalik_guncelle.py --kaynak kvkk      # Sadece KVKK
    python scripts/haftalik_guncelle.py --onbellek-temizle # Önce eski önbelleği siler

Task Scheduler örnek komut:
    schtasks /create /tn "Avukat-MCP-Haftalik" /sc WEEKLY /d SUN /st 03:00 ^
      /tr "D:\0\000MCP-Servers\avukat-mcp\.venv\Scripts\python.exe D:\0\000MCP-Servers\avukat-mcp\scripts\haftalik_guncelle.py"
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# UTF-8 konsolu zorla
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Avukat MCP src dizinini path'e ekle
PROJE_KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJE_KOK / "src"))

from mevzuat import DiskOnbellegi, MevzuatScraper, KuralGuncelleyici  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [haftalik-guncelle] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("haftalik-guncelle")


async def ana(args: argparse.Namespace) -> int:
    kurallar_dir = PROJE_KOK / "data" / "kurallar"
    cache_dir = PROJE_KOK / "data" / "cache"
    rapor_dir = PROJE_KOK / "data" / "raporlar"
    rapor_dir.mkdir(parents=True, exist_ok=True)

    onbellek = DiskOnbellegi(cache_dir / "mevzuat_onbellek.sqlite")

    if args.onbellek_temizle:
        silindi = onbellek.temizle(eski_mi=True)
        logger.info(f"Süresi dolmuş {silindi} önbellek kaydı silindi")

    scraper = MevzuatScraper(onbellek=onbellek)
    guncelleyici = KuralGuncelleyici(kurallar_dir, onbellek, scraper)

    try:
        if args.kaynak:
            sonuclar = [await guncelleyici.kaynak_guncelle(args.kaynak)]
        else:
            sonuclar = await guncelleyici.tumunu_guncelle()
    finally:
        await scraper.kapat()

    # Özet raporu disk'e yaz
    zaman_damgasi = datetime.now().strftime("%Y%m%d_%H%M")
    rapor = {
        "tarih": datetime.now().isoformat(),
        "taranan": len(sonuclar),
        "degisiklik_tespit_edilen": sum(1 for s in sonuclar if s.durum == "basarili" and s.onceki_hash),
        "sonuclar": [
            {
                "kaynak_id": s.kaynak_id,
                "durum": s.durum,
                "onceki_hash": s.onceki_hash,
                "yeni_hash": s.yeni_hash,
                "metin_uzunlugu": s.metin_uzunlugu,
                "hata": s.hata,
            }
            for s in sonuclar
        ],
    }

    rapor_dosya = rapor_dir / f"guncelleme_{zaman_damgasi}.json"
    rapor_dosya.write_text(json.dumps(rapor, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(rapor, ensure_ascii=False, indent=2))
    logger.info(f"Rapor: {rapor_dosya}")

    return 0 if all(s.durum in ("basarili", "degisiklik_yok", "atlandi") for s in sonuclar) else 1


def main() -> None:
    ayrici = argparse.ArgumentParser(description="Avukat MCP haftalık mevzuat güncelleme")
    ayrici.add_argument("--kaynak", help="Sadece belirtilen kural setini güncelle")
    ayrici.add_argument("--onbellek-temizle", action="store_true", help="Eski önbelleği güncellemeden önce sil")
    args = ayrici.parse_args()
    sys.exit(asyncio.run(ana(args)))


if __name__ == "__main__":
    main()
