# Bu modül, çeşitli online mevzuat kaynaklarından (mevzuat.gov.tr, EUR-Lex,
# kvkk.gov.tr) asenkron HTTP istekleriyle içerik çeker ve basit HTML
# parsing yaparak özetlenmiş sonuçlar döndürür. Ağ hatalarına karşı
# dayanıklı olacak şekilde timeout ve fallback mantığı içerir.

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("avukat-mcp.mevzuat")


# Mevzuat sorgu sonucu — tek bir kanun, madde veya karar referansı
@dataclass
class MevzuatSonucu:
    kaynak: str                              # Veri kaynağı (mevzuat.gov.tr, eur-lex vb.)
    baslik: str                              # Kanun/madde başlığı
    ozet: str                                # Kısa açıklama
    link: str = ""                           # Orijinal kaynak bağlantısı
    madde_no: str = ""                       # İlgili madde numarası
    tam_metin: str = ""                      # Tam metin (istenirse doldurulur)
    etiketler: List[str] = field(default_factory=list)


# Ortak User-Agent — bazı siteler varsayılan httpx agent'ını reddediyor
VARSAYILAN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AvukatMCP/1.0 "
        "(+https://github.com/kesif/avukat-mcp)"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}


class MevzuatArayici:
    """
    Online mevzuat kaynaklarında arama yapan yardımcı sınıf.
    Her kaynak için ayrı method barındırır ve arama sonuçlarını
    ortak MevzuatSonucu formatında döndürür.
    """

    def __init__(self, zaman_asimi: float = 12.0):
        # HTTP istekleri için timeout (saniye)
        self.zaman_asimi = zaman_asimi

    async def _http_get(self, url: str) -> Optional[str]:
        """Verilen URL'den HTML içeriği çeker. Hata durumunda None döner."""
        try:
            async with httpx.AsyncClient(
                headers=VARSAYILAN_HEADERS,
                timeout=self.zaman_asimi,
                follow_redirects=True,
            ) as istemci:
                yanit = await istemci.get(url)
                if yanit.status_code == 200:
                    return yanit.text
                logger.warning(f"HTTP {yanit.status_code} — {url}")
                return None
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            logger.warning(f"İstek başarısız: {url} — {e}")
            return None

    async def tr_mevzuat_ara(self, sorgu: str, limit: int = 5) -> List[MevzuatSonucu]:
        """
        mevzuat.gov.tr üzerinden Türk mevzuat araması.
        Google site: operatörü kullanılır çünkü mevzuat.gov.tr kendi
        arama API'sini dışarıya açık sunmuyor.
        """
        url = (
            "https://www.google.com/search?q="
            + quote_plus(f"site:mevzuat.gov.tr {sorgu}")
            + f"&num={limit}"
        )

        html = await self._http_get(url)
        if not html:
            return []

        sonuclar: List[MevzuatSonucu] = []
        try:
            corba = BeautifulSoup(html, "html.parser")
            # Google sonuçları — h3 içinde başlık, cite içinde link
            for baslik_tag in corba.select("h3")[:limit]:
                ebeveyn = baslik_tag.find_parent("a")
                link = ebeveyn.get("href", "") if ebeveyn else ""
                if link.startswith("/url?q="):
                    link = link.split("/url?q=")[1].split("&")[0]

                sonuclar.append(MevzuatSonucu(
                    kaynak="mevzuat.gov.tr",
                    baslik=baslik_tag.get_text(strip=True),
                    ozet=f"Türk mevzuatı: '{sorgu}' için sonuç",
                    link=link,
                    etiketler=["TR", "mevzuat"],
                ))
        except Exception as e:
            logger.error(f"TR mevzuat parse hatası: {e}")

        return sonuclar

    async def kvkk_karar_ara(self, sorgu: str, limit: int = 5) -> List[MevzuatSonucu]:
        """
        kvkk.gov.tr kurul kararları sayfasında arama yapar.
        Kurul kararları KVKK uygulamasının yorumunu anlamak için kritiktir.
        """
        url = (
            "https://www.google.com/search?q="
            + quote_plus(f"site:kvkk.gov.tr kurul kararı {sorgu}")
            + f"&num={limit}"
        )
        html = await self._http_get(url)
        if not html:
            return []

        sonuclar: List[MevzuatSonucu] = []
        try:
            corba = BeautifulSoup(html, "html.parser")
            for baslik_tag in corba.select("h3")[:limit]:
                ebeveyn = baslik_tag.find_parent("a")
                link = ebeveyn.get("href", "") if ebeveyn else ""
                if link.startswith("/url?q="):
                    link = link.split("/url?q=")[1].split("&")[0]

                sonuclar.append(MevzuatSonucu(
                    kaynak="kvkk.gov.tr",
                    baslik=baslik_tag.get_text(strip=True),
                    ozet=f"KVKK kurul kararı: '{sorgu}'",
                    link=link,
                    etiketler=["TR", "KVKK", "kurul_karari"],
                ))
        except Exception as e:
            logger.error(f"KVKK parse hatası: {e}")

        return sonuclar

    async def eur_lex_ara(self, sorgu: str, limit: int = 5) -> List[MevzuatSonucu]:
        """
        EUR-Lex üzerinden AB mevzuatı (GDPR vb.) araması yapar.
        EUR-Lex'in kendi arama sayfasını kullanır — hızlı ve kararlı.
        """
        url = (
            "https://eur-lex.europa.eu/search.html?scope=EURLEX&text="
            + quote_plus(sorgu)
            + "&lang=en&type=quick"
        )
        html = await self._http_get(url)
        if not html:
            return []

        sonuclar: List[MevzuatSonucu] = []
        try:
            corba = BeautifulSoup(html, "html.parser")
            # EUR-Lex arama sonuçları .SearchResult div'lerinde
            for sonuc_div in corba.select("div.SearchResult")[:limit]:
                baslik_a = sonuc_div.find("a")
                if not baslik_a:
                    continue
                link = baslik_a.get("href", "")
                if link.startswith("./"):
                    link = "https://eur-lex.europa.eu" + link[1:]

                sonuclar.append(MevzuatSonucu(
                    kaynak="eur-lex.europa.eu",
                    baslik=baslik_a.get_text(strip=True),
                    ozet=f"AB mevzuatı: '{sorgu}'",
                    link=link,
                    etiketler=["EU", "GDPR"],
                ))
        except Exception as e:
            logger.error(f"EUR-Lex parse hatası: {e}")

        return sonuclar

    async def coklu_kaynak_ara(
        self,
        sorgu: str,
        kaynaklar: Optional[List[str]] = None,
        limit: int = 3,
    ) -> List[MevzuatSonucu]:
        """
        Birden fazla kaynakta paralel arama yapar ve sonuçları birleştirir.
        kaynaklar: ['tr', 'kvkk', 'eurlex'] — None ise hepsi taranır.
        """
        kaynaklar = kaynaklar or ["tr", "kvkk", "eurlex"]
        gorevler = []

        if "tr" in kaynaklar:
            gorevler.append(self.tr_mevzuat_ara(sorgu, limit))
        if "kvkk" in kaynaklar:
            gorevler.append(self.kvkk_karar_ara(sorgu, limit))
        if "eurlex" in kaynaklar:
            gorevler.append(self.eur_lex_ara(sorgu, limit))

        # Paralel çalıştır — biri hata verirse diğerleri çalışmaya devam eder
        sonuc_gruplari = await asyncio.gather(*gorevler, return_exceptions=True)

        tum_sonuclar: List[MevzuatSonucu] = []
        for grup in sonuc_gruplari:
            if isinstance(grup, list):
                tum_sonuclar.extend(grup)
            else:
                logger.error(f"Kaynak sorgu hatası: {grup}")

        return tum_sonuclar
