# Bu modül değiştirme işleminden önce orijinal görselleri ve post_content
# kopyalarını diske yedekler. Rollback gerektiğinde değişiklikleri geri alabilmek için
# her değişiklik bir manifest dosyasına JSON olarak kaydedilir.

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import httpx

logger = logging.getLogger("avukat-mcp.yedekleme")


@dataclass
class YedekKaydi:
    """Tek bir değişiklik için yedek kaydı — rollback yapılabilmesi için yeterli bilgi."""
    zaman: str                          # ISO tarih
    eski_media_id: int
    eski_url: str
    eski_dosya_yolu: str                # Yedeklenen orijinalin disk yolu
    yeni_media_id: int = 0
    yeni_url: str = ""
    etkilenen_postlar: List[dict] = field(default_factory=list)
    # Her post için: {id, type, eski_md5(content), yeni_md5(content)}


class YedeklemeMotoru:
    """
    Değiştirme öncesi tüm orijinalleri diske yedekleyen ve değişiklikleri
    bir manifest dosyasında kaydeden motor.
    """

    def __init__(self, yedek_kok_dizini: Path, oturum_adi: Optional[str] = None):
        self.yedek_kok = Path(yedek_kok_dizini)
        self.oturum_adi = oturum_adi or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.oturum_dizini = self.yedek_kok / self.oturum_adi
        self.dosyalar_dizini = self.oturum_dizini / "orijinal_dosyalar"
        self.postlar_dizini = self.oturum_dizini / "post_iceriği_snapshot"
        self.manifest_yolu = self.oturum_dizini / "manifest.json"

        for d in [self.dosyalar_dizini, self.postlar_dizini]:
            d.mkdir(parents=True, exist_ok=True)

        self._kayitlar: List[YedekKaydi] = []
        self._manifest_yukle()

    def _manifest_yukle(self) -> None:
        """Varsa mevcut manifest'i yükler (devam edilebilir çalışma için)."""
        if self.manifest_yolu.exists():
            try:
                veri = json.loads(self.manifest_yolu.read_text(encoding="utf-8"))
                self._kayitlar = [YedekKaydi(**k) for k in veri.get("kayitlar", [])]
            except (json.JSONDecodeError, TypeError):
                self._kayitlar = []

    def _manifest_kaydet(self) -> None:
        self.manifest_yolu.write_text(
            json.dumps({
                "oturum": self.oturum_adi,
                "baslangic": self._kayitlar[0].zaman if self._kayitlar else "",
                "guncelleme": datetime.now().isoformat(),
                "toplam": len(self._kayitlar),
                "kayitlar": [asdict(k) for k in self._kayitlar],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def dosyayi_yedekle(self, url: str, media_id: int) -> Optional[Path]:
        """Orijinal görseli URL'den indirir ve oturum dizinine kaydeder."""
        dosya_adi = Path(url.split("?")[0]).name
        hedef = self.dosyalar_dizini / f"{media_id}_{dosya_adi}"

        if hedef.exists():
            return hedef

        try:
            async with httpx.AsyncClient(timeout=60) as ist:
                r = await ist.get(url)
                if r.status_code != 200:
                    logger.warning(f"Yedekleme indirilemedi: {url} (HTTP {r.status_code})")
                    return None
                hedef.write_bytes(r.content)
                return hedef
        except httpx.HTTPError as e:
            logger.error(f"Yedekleme hatası: {e}")
            return None

    def post_icerigi_snapshot(self, post_id: int, post_type: str, icerik: str) -> Path:
        """post_content'in anlık görüntüsünü yedekler."""
        hedef = self.postlar_dizini / f"{post_type}_{post_id}_{datetime.now().strftime('%H%M%S')}.html"
        hedef.write_text(icerik, encoding="utf-8")
        return hedef

    def kayit_ekle(self, kayit: YedekKaydi) -> None:
        """Yeni bir değişiklik kaydı ekler ve manifest'i günceller."""
        self._kayitlar.append(kayit)
        self._manifest_kaydet()

    def son_kaydi_guncelle(self, **alanlar) -> None:
        """En son eklenen kaydın alanlarını günceller (yeni_media_id, yeni_url vs.)."""
        if not self._kayitlar:
            return
        for k, v in alanlar.items():
            setattr(self._kayitlar[-1], k, v)
        self._manifest_kaydet()

    def kayitlari_listele(self) -> List[YedekKaydi]:
        return list(self._kayitlar)

    @staticmethod
    def icerik_md5(icerik: str) -> str:
        """post_content için değişiklik izlemek amacıyla kısa hash."""
        return hashlib.md5(icerik.encode("utf-8")).hexdigest()[:16]
