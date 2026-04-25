# Bu modül, data/kurallar/ altındaki JSON kural dosyalarını yükleyip
# indeksleyen yardımcı bir depo sunar. Online arama başarısız olduğunda
# veya offline kullanım için fallback olarak çalışır.

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("avukat-mcp.yerel")


class YerelKuralDeposu:
    """
    data/kurallar/ dizinindeki JSON dosyalarını yükler ve anahtar kelimeye
    göre hızlı arama sağlar. Her kural dosyası ayrı bir mevzuat seti temsil eder.
    """

    def __init__(self, kurallar_dizini: Path):
        # Kural JSON'larının bulunduğu dizin
        self.kurallar_dizini = Path(kurallar_dizini)
        self._onbellek: Dict[str, dict] = {}
        self._yukle()

    def _yukle(self) -> None:
        """JSON dosyalarını bellekte indekser. Her açılışta bir kez çalışır."""
        if not self.kurallar_dizini.exists():
            logger.warning(f"Kural dizini yok: {self.kurallar_dizini}")
            return

        for dosya in self.kurallar_dizini.glob("*.json"):
            try:
                with open(dosya, "r", encoding="utf-8") as f:
                    self._onbellek[dosya.stem] = json.load(f)
                logger.debug(f"Yüklendi: {dosya.name}")
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Kural yüklenemedi: {dosya} — {e}")

    def kaynak_listesi(self) -> List[str]:
        """Yüklü tüm kural kaynaklarının adını döndürür."""
        return sorted(self._onbellek.keys())

    def kural_getir(self, kaynak: str, kural_id: str) -> Optional[dict]:
        """Belirli bir kaynaktan tek bir kuralı kimliğiyle getirir."""
        veri = self._onbellek.get(kaynak)
        if not veri:
            return None
        for kural in veri.get("kurallar", []):
            if kural.get("id") == kural_id:
                return kural
        return None

    def ara(
        self,
        sorgu: str,
        kaynak: Optional[str] = None,
        ulke: Optional[str] = None,
    ) -> List[dict]:
        """
        Sorgu metnini tüm kurallarda (başlık, açıklama, anahtar kelime) arar.
        kaynak: sadece belirli bir JSON dosyasında ara (örn: 'kvkk')
        ulke: 'TR', 'EU', 'US', 'GLOBAL' — meta.ulke ile eşleşenleri döndürür
        """
        sorgu_kucuk = sorgu.lower()
        sorgu_parcalari = [p for p in sorgu_kucuk.split() if p]
        sonuclar: List[dict] = []

        for kaynak_adi, veri in self._onbellek.items():
            if kaynak and kaynak_adi != kaynak:
                continue

            meta = veri.get("meta", {})
            if ulke and meta.get("ulke", "").upper() != ulke.upper():
                continue

            for kural in veri.get("kurallar", []):
                # Aranacak alan — başlık + açıklama + tüm anahtar kelimeler
                anahtar_list = kural.get("anahtar_kelimeler", [])
                anahtar_list += kural.get("kontrol_desenleri", [])

                aranacak = " ".join([
                    kural.get("baslik", ""),
                    kural.get("aciklama", ""),
                    " ".join(str(a) for a in anahtar_list),
                ]).lower()

                # Tam cümle veya kelime bazlı eşleşme
                eslesti = sorgu_kucuk in aranacak or any(
                    parca in aranacak for parca in sorgu_parcalari
                )
                if eslesti:
                    sonuclar.append({
                        "kaynak": kaynak_adi,
                        "id": kural.get("id"),
                        "baslik": kural.get("baslik"),
                        "seviye": kural.get("seviye"),
                        "aciklama": kural.get("aciklama"),
                        "mevzuat": kural.get(
                            "mevzuat_maddesi",
                            kural.get("mevzuat_referans", ""),
                        ),
                        "duzeltme": kural.get(
                            "duzeltme",
                            kural.get("duzeltme_onerisi", ""),
                        ),
                        "ulke": meta.get("ulke", ""),
                    })

        return sonuclar

    def istatistik(self) -> dict:
        """Yüklü kural setleri hakkında özet istatistik döndürür."""
        istatistik = {"toplam_kaynak": len(self._onbellek), "kaynaklar": {}}
        for ad, veri in self._onbellek.items():
            istatistik["kaynaklar"][ad] = {
                "kural_sayisi": len(veri.get("kurallar", [])),
                "ulke": veri.get("meta", {}).get("ulke", "?"),
                "mevzuat": veri.get("meta", {}).get("mevzuat", "?"),
            }
        return istatistik
