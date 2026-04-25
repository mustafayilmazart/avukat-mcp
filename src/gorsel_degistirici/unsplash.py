# Bu modül Unsplash API'sinden güvenli (CC0 lisanslı) görseller çeker.
# Unsplash API ücretsizdir (1000 req/saat), kayıt gerektirir:
#   https://unsplash.com/oauth/applications/new
# Developer key UNSPLASH_ACCESS_KEY ortam değişkenine eklenmeli.

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

import httpx

logger = logging.getLogger("avukat-mcp.unsplash")


@dataclass
class UnsplashSonuc:
    """Unsplash'tan gelen tek görsel kaydı."""
    id: str
    url_tam: str            # Tam boyut (indirmek için)
    url_regular: str        # 1080px
    url_raw: str
    genislik: int
    yukseklik: int
    fotografci_adi: str
    fotografci_url: str
    aciklama: str


class UnsplashAPI:
    """Unsplash REST API'si. Ücretsiz plan: 50 req/saat, kayıt sonrası 1000/saat."""

    BASE_URL = "https://api.unsplash.com"

    def __init__(self, access_key: Optional[str] = None):
        self.access_key = access_key or os.environ.get("UNSPLASH_ACCESS_KEY", "")

    def _basliklar(self) -> dict:
        return {
            "Authorization": f"Client-ID {self.access_key}",
            "Accept-Version": "v1",
        }

    async def ara(
        self,
        sorgu: str,
        sayfa: int = 1,
        per_page: int = 10,
        orientation: Optional[str] = None,  # landscape / portrait / squarish
    ) -> List[UnsplashSonuc]:
        """Anahtar kelime araması — en uygun görselleri döndürür."""
        if not self.access_key:
            logger.error("UNSPLASH_ACCESS_KEY ortam değişkeni tanımlı değil")
            return []

        params = {"query": sorgu, "page": sayfa, "per_page": per_page}
        if orientation:
            params["orientation"] = orientation

        async with httpx.AsyncClient(headers=self._basliklar(), timeout=30) as ist:
            r = await ist.get(f"{self.BASE_URL}/search/photos", params=params)
            if r.status_code != 200:
                logger.error(f"Unsplash arama hatası: {r.status_code} — {r.text[:200]}")
                return []

            veri = r.json()
            sonuclar = []
            for f in veri.get("results", []):
                sonuclar.append(UnsplashSonuc(
                    id=f["id"],
                    url_tam=f["urls"]["full"],
                    url_regular=f["urls"]["regular"],
                    url_raw=f["urls"]["raw"],
                    genislik=f["width"],
                    yukseklik=f["height"],
                    fotografci_adi=f["user"]["name"],
                    fotografci_url=f["user"]["links"]["html"],
                    aciklama=f.get("description") or f.get("alt_description") or "",
                ))
            return sonuclar

    async def boyuta_uygun_bul(
        self,
        sorgu: str,
        hedef_genislik: int,
        hedef_yukseklik: int,
        aday_sayisi: int = 10,
    ) -> Optional[UnsplashSonuc]:
        """Belirtilen boyuta en yakın oranlı görseli bulur."""
        # Orientation tahmini
        oran = hedef_genislik / hedef_yukseklik
        orient = "landscape" if oran > 1.15 else ("portrait" if oran < 0.85 else "squarish")

        adaylar = await self.ara(sorgu, per_page=aday_sayisi, orientation=orient)
        if not adaylar:
            return None

        # En yakın en-boy oranına sahip olanı seç
        def oran_farki(a: UnsplashSonuc) -> float:
            a_oran = a.genislik / a.yukseklik
            return abs(a_oran - oran)

        return min(adaylar, key=oran_farki)

    async def indir(self, sonuc: UnsplashSonuc, cikti_yolu) -> bool:
        """Unsplash'tan dosyayı indirir. Unsplash API'si 'download' trigger endpoint'i ister."""
        import pathlib
        cikti_yolu = pathlib.Path(cikti_yolu)
        cikti_yolu.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(headers=self._basliklar(), timeout=60) as ist:
            # Unsplash API kuralı: indirmeden önce /photos/{id}/download trigger
            try:
                await ist.get(f"{self.BASE_URL}/photos/{sonuc.id}/download")
            except httpx.HTTPError:
                pass  # Trigger başarısız olsa da indirmeye devam

            # Gerçek indirme
            r = await ist.get(sonuc.url_regular)
            if r.status_code != 200:
                return False
            cikti_yolu.write_bytes(r.content)
            return True
