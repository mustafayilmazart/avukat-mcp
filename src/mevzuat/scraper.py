# Bu modül, Türk ve AB mevzuat sitelerinden tam kanun/madde metni çeker.
# mevzuat.gov.tr dinamik JavaScript ile yükleme yaptığı için Playwright
# kullanılır. kvkk.gov.tr ve eur-lex gibi statik siteler için httpx yeterli.
# Tüm çekilen içerikler DiskOnbellegi üzerinden 7 gün önbelleklenir.

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from .onbellek import DiskOnbellegi

logger = logging.getLogger("avukat-mcp.scraper")

# Playwright isteğe bağlı — yüklü değilse httpx fallback'i çalışır
try:
    from playwright.async_api import async_playwright, Browser, Page  # type: ignore
    PLAYWRIGHT_VAR = True
except ImportError:
    PLAYWRIGHT_VAR = False
    logger.info("Playwright yüklü değil — mevzuat.gov.tr için httpx fallback kullanılacak.")


# Mevzuat çekim sonucu — tek bir kanun veya madde
@dataclass
class MevzuatMetni:
    kanun_adi: str                      # "6698 sayılı KVKK"
    madde_no: Optional[str] = None      # "md.5" / None = tüm kanun
    baslik: str = ""                    # Maddenin başlığı veya kanun başlığı
    metin: str = ""                     # Tam metin
    url: str = ""
    kaynak: str = ""                    # mevzuat.gov.tr / kvkk.gov.tr / eur-lex
    etiketler: List[str] = field(default_factory=list)
    onbellekten_geldi: bool = False


VARSAYILAN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AvukatMCP/1.0 "
        "(+https://github.com/kesif/avukat-mcp)"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class MevzuatScraper:
    """
    Mevzuat sitelerinden tam metin çekici.
    Playwright ile dinamik siteleri (mevzuat.gov.tr), httpx ile statik siteleri tarar.
    """

    def __init__(self, onbellek: Optional[DiskOnbellegi] = None, zaman_asimi: float = 25.0):
        # Disk önbelleği — verilmezse çekim her seferinde ağdan yapılır
        self.onbellek = onbellek
        self.zaman_asimi = zaman_asimi
        self._tarayici: Optional["Browser"] = None
        self._playwright_ctx = None

    # ── Playwright yaşam döngüsü ──────────────────────────────────

    async def _tarayici_ac(self) -> None:
        """Playwright tarayıcısını başlatır (tembel — gerektiğinde)."""
        if not PLAYWRIGHT_VAR or self._tarayici:
            return
        self._playwright_ctx = await async_playwright().start()
        self._tarayici = await self._playwright_ctx.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )

    async def kapat(self) -> None:
        """Tarayıcıyı ve playwright bağlamını güvenli şekilde kapatır."""
        if self._tarayici:
            try:
                await self._tarayici.close()
            except Exception:
                pass
            self._tarayici = None
        if self._playwright_ctx:
            try:
                await self._playwright_ctx.stop()
            except Exception:
                pass
            self._playwright_ctx = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.kapat()

    # ── Ortak HTTP yardımcıları ───────────────────────────────────

    async def _httpx_get(self, url: str) -> Optional[str]:
        """Statik HTML'i httpx ile çeker."""
        try:
            async with httpx.AsyncClient(
                headers=VARSAYILAN_HEADERS,
                timeout=self.zaman_asimi,
                follow_redirects=True,
            ) as istemci:
                yanit = await istemci.get(url)
                if yanit.status_code == 200:
                    return yanit.text
                logger.warning(f"HTTP {yanit.status_code}: {url}")
        except httpx.HTTPError as e:
            logger.warning(f"httpx istek hatası: {url} — {e}")
        return None

    async def _playwright_get(
        self,
        url: str,
        bekle_saniye: float = 3.0,
        iframe_ara: bool = False,
    ) -> Optional[str]:
        """
        Playwright ile dinamik sayfa yükler. JS render bittikten sonra
        HTML'i döndürür. Playwright yoksa httpx'e düşer.

        iframe_ara=True: Sayfadaki ilk iframe'in içeriğini döndürür
        (mevzuat.gov.tr kanun metnini iframe içinde servis ediyor).
        """
        if not PLAYWRIGHT_VAR:
            return await self._httpx_get(url)

        try:
            await self._tarayici_ac()
            assert self._tarayici is not None
            baglam = await self._tarayici.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="tr-TR",
            )
            sayfa = await baglam.new_page()
            await sayfa.goto(url, wait_until="networkidle", timeout=int(self.zaman_asimi * 1000))
            await asyncio.sleep(bekle_saniye)

            if iframe_ara:
                # mevzuat.gov.tr kanun metnini #mevzuatIframe veya ilk iframe'de servis eder
                iframe_icerik = None
                for cerceve in sayfa.frames:
                    if cerceve == sayfa.main_frame:
                        continue
                    try:
                        iframe_html = await cerceve.content()
                        if iframe_html and len(iframe_html) > 2000:
                            iframe_icerik = iframe_html
                            break
                    except Exception:
                        continue
                html = iframe_icerik or await sayfa.content()
            else:
                html = await sayfa.content()

            await baglam.close()
            return html
        except Exception as e:
            logger.warning(f"Playwright hatası: {url} — {e}")
            return await self._httpx_get(url)

    def _onbellek_anahtar(self, *parcalar: str) -> str:
        """Önbellek anahtarını normalleştirerek üretir."""
        return "|".join(re.sub(r"\s+", "_", p.strip().lower()) for p in parcalar)

    # ── mevzuat.gov.tr ────────────────────────────────────────────

    async def kanun_ara_mevzuatgov(self, sorgu: str, limit: int = 5) -> List[dict]:
        """
        mevzuat.gov.tr resmi arama sayfasından kanun listesi çeker.
        Arama: https://www.mevzuat.gov.tr/arama?AramaKelimesi=...
        """
        anahtar = self._onbellek_anahtar("mevzuatgov-ara", sorgu)
        if self.onbellek:
            kayit = self.onbellek.getir(anahtar)
            if kayit:
                import json as _json
                return _json.loads(kayit.icerik)

        url = f"https://www.mevzuat.gov.tr/arama?AramaKelimesi={quote_plus(sorgu)}&AramaTuru=1"
        html = await self._playwright_get(url, bekle_saniye=4.0)
        if not html:
            return []

        sonuclar: List[dict] = []
        corba = BeautifulSoup(html, "html.parser")
        # mevzuat.gov.tr arama sonuç listesi — tablo veya kart bazlı
        for satir in corba.select("a[href*='/mevzuat?']")[:limit]:
            baslik = satir.get_text(strip=True)
            href = satir.get("href", "")
            if href.startswith("/"):
                href = "https://www.mevzuat.gov.tr" + href
            if baslik and href:
                sonuclar.append({
                    "baslik": baslik,
                    "url": href,
                    "kaynak": "mevzuat.gov.tr",
                })

        if self.onbellek and sonuclar:
            import json as _json
            self.onbellek.kaydet(anahtar, _json.dumps(sonuclar, ensure_ascii=False), "mevzuat.gov.tr")

        return sonuclar

    async def kanun_metni_getir(self, url: str) -> Optional[MevzuatMetni]:
        """
        Bir kanunun tam metnini mevzuat.gov.tr detay sayfasından çeker.
        URL genellikle /mevzuat?MevzuatNo=XXX şeklindedir.
        """
        anahtar = self._onbellek_anahtar("mevzuatgov-metin", url)
        if self.onbellek:
            kayit = self.onbellek.getir(anahtar)
            if kayit:
                return MevzuatMetni(
                    kanun_adi=(kayit.metadata_json or "Bilinmeyen"),
                    metin=kayit.icerik,
                    url=url,
                    kaynak="mevzuat.gov.tr",
                    onbellekten_geldi=True,
                )

        # mevzuat.gov.tr kanun metnini iframe içinde yükler — iframe_ara=True
        html = await self._playwright_get(url, bekle_saniye=5.0, iframe_ara=True)
        if not html:
            return None

        corba = BeautifulSoup(html, "html.parser")

        # Başlık — iframe içinde <p> veya <h1>, ana sayfada .mevzuatBaslik
        baslik_tag = corba.select_one("h1, .mevzuatBaslik, #mevzuatAdi, .baslik")
        baslik = baslik_tag.get_text(strip=True) if baslik_tag else ""

        # Metin — iframe içeriği zaten asıl kanun metni. Navigation elemanları çıkar.
        # Önce script/style tag'lerini kaldır
        for istenmeyen in corba(["script", "style", "nav", "header", "footer"]):
            istenmeyen.decompose()

        metin_tag = corba.select_one("#mevzuatIcerik, .mevzuatMetin, main, article, body")
        if metin_tag:
            metin = metin_tag.get_text("\n", strip=True)
        else:
            metin = corba.get_text("\n", strip=True)

        # Başlığı metinden çıkarmaya çalış (ilk satır genelde başlıktır)
        if not baslik and metin:
            ilk_satir = metin.split("\n", 1)[0].strip()
            if 10 < len(ilk_satir) < 200:
                baslik = ilk_satir

        # Aşırı boş satırları sadeleştir
        metin = re.sub(r"\n{3,}", "\n\n", metin)
        baslik = baslik or "Bilinmeyen Kanun"

        if self.onbellek and metin:
            self.onbellek.kaydet(anahtar, metin, "mevzuat.gov.tr", {"baslik": baslik})

        return MevzuatMetni(
            kanun_adi=baslik,
            baslik=baslik,
            metin=metin,
            url=url,
            kaynak="mevzuat.gov.tr",
        )

    async def madde_getir(self, kanun_url: str, madde_no: str) -> Optional[MevzuatMetni]:
        """
        Belirli bir kanunun belirli bir maddesinin metnini çıkarır.
        kanun_url: mevzuat.gov.tr kanun detay sayfası
        madde_no: "5" veya "Madde 5" gibi
        """
        kanun = await self.kanun_metni_getir(kanun_url)
        if not kanun or not kanun.metin:
            return None

        # "Madde N - ..." veya "MADDE N – ..." desenleri
        madde_sayisi = re.sub(r"[^0-9]", "", madde_no)
        if not madde_sayisi:
            return kanun  # Madde verilmemişse tüm kanun

        # Maddeyi bulmak için desen — "MADDE 5" veya "Madde 5" ile başlayıp
        # bir sonraki "MADDE N+1" veya "GEÇİCİ MADDE" veya dosya sonuna kadar al
        desen = (
            rf"(?:^|\n)\s*(?:MADDE|Madde)\s*{madde_sayisi}\s*[-–—.)]"
            r"[\s\S]*?"
            r"(?=(?:\n\s*(?:MADDE|Madde|GEÇİCİ\s*MADDE)\s*\d+)|\Z)"
        )
        eslesme = re.search(desen, kanun.metin, re.MULTILINE)
        if not eslesme:
            logger.warning(f"Madde {madde_no} bulunamadı: {kanun.kanun_adi}")
            return MevzuatMetni(
                kanun_adi=kanun.kanun_adi,
                madde_no=f"md.{madde_sayisi}",
                metin=f"(Madde {madde_sayisi} kanun metninde bulunamadı)",
                url=kanun_url,
                kaynak=kanun.kaynak,
            )

        return MevzuatMetni(
            kanun_adi=kanun.kanun_adi,
            madde_no=f"md.{madde_sayisi}",
            baslik=f"{kanun.kanun_adi} — Madde {madde_sayisi}",
            metin=eslesme.group(0).strip(),
            url=kanun_url,
            kaynak=kanun.kaynak,
            onbellekten_geldi=kanun.onbellekten_geldi,
        )

    # ── kvkk.gov.tr kurul kararları ────────────────────────────────

    async def kvkk_karar_ara(self, sorgu: str, limit: int = 10) -> List[dict]:
        """
        kvkk.gov.tr kurul kararı arama. Site form-based arama yapıyor,
        biz de arama URL'sine query string ile vuruyoruz.
        """
        anahtar = self._onbellek_anahtar("kvkk-ara", sorgu)
        if self.onbellek:
            kayit = self.onbellek.getir(anahtar)
            if kayit:
                import json as _json
                return _json.loads(kayit.icerik)

        url = f"https://www.kvkk.gov.tr/Icerik/Arama/?search={quote_plus(sorgu)}"
        html = await self._playwright_get(url, bekle_saniye=3.5)
        if not html:
            return []

        corba = BeautifulSoup(html, "html.parser")
        sonuclar: List[dict] = []
        for link in corba.select("a[href*='/Icerik/']")[:limit]:
            baslik = link.get_text(strip=True)
            href = link.get("href", "")
            if href.startswith("/"):
                href = "https://www.kvkk.gov.tr" + href
            if len(baslik) > 10 and href:
                sonuclar.append({
                    "baslik": baslik,
                    "url": href,
                    "kaynak": "kvkk.gov.tr",
                })

        if self.onbellek and sonuclar:
            import json as _json
            self.onbellek.kaydet(anahtar, _json.dumps(sonuclar, ensure_ascii=False), "kvkk.gov.tr")

        return sonuclar

    async def kvkk_karar_metin(self, url: str) -> Optional[MevzuatMetni]:
        """KVKK kurul kararının tam metnini çeker."""
        anahtar = self._onbellek_anahtar("kvkk-metin", url)
        if self.onbellek:
            kayit = self.onbellek.getir(anahtar)
            if kayit:
                return MevzuatMetni(
                    kanun_adi="KVKK Kurul Kararı",
                    baslik=kayit.metadata_json or "",
                    metin=kayit.icerik,
                    url=url,
                    kaynak="kvkk.gov.tr",
                    onbellekten_geldi=True,
                )

        html = await self._playwright_get(url, bekle_saniye=3.0)
        if not html:
            return None

        corba = BeautifulSoup(html, "html.parser")
        icerik_tag = corba.select_one(".icerik, .content, main, article, #content")
        metin = icerik_tag.get_text("\n", strip=True) if icerik_tag else ""
        metin = re.sub(r"\n{3,}", "\n\n", metin)

        baslik_tag = corba.select_one("h1, .sayfa-basligi")
        baslik = baslik_tag.get_text(strip=True) if baslik_tag else "Kurul Kararı"

        if self.onbellek and metin:
            self.onbellek.kaydet(anahtar, metin, "kvkk.gov.tr", {"baslik": baslik})

        return MevzuatMetni(
            kanun_adi="KVKK Kurul Kararı",
            baslik=baslik,
            metin=metin,
            url=url,
            kaynak="kvkk.gov.tr",
            etiketler=["TR", "KVKK", "kurul_karari"],
        )

    # ── EUR-Lex (GDPR vb.) ────────────────────────────────────────

    async def eurlex_celex_getir(self, celex_no: str) -> Optional[MevzuatMetni]:
        """
        EUR-Lex CELEX numarasıyla tam metin çeker.
        GDPR için: 32016R0679
        """
        anahtar = self._onbellek_anahtar("eurlex", celex_no)
        if self.onbellek:
            kayit = self.onbellek.getir(anahtar)
            if kayit:
                return MevzuatMetni(
                    kanun_adi=f"EUR-Lex {celex_no}",
                    metin=kayit.icerik,
                    url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex_no}",
                    kaynak="eur-lex.europa.eu",
                    onbellekten_geldi=True,
                )

        url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex_no}"
        # EUR-Lex httpx'e HTTP 202 dönüyor (bot koruması) — Playwright ile render'la
        html = await self._playwright_get(url, bekle_saniye=4.0)
        if not html:
            html = await self._httpx_get(url)
        if not html:
            return None

        corba = BeautifulSoup(html, "html.parser")
        icerik_tag = corba.select_one("#text, .eli-main-content, #document")
        metin = icerik_tag.get_text("\n", strip=True) if icerik_tag else ""
        metin = re.sub(r"\n{3,}", "\n\n", metin)

        baslik_tag = corba.select_one("h1, .document-title")
        baslik = baslik_tag.get_text(strip=True) if baslik_tag else celex_no

        if self.onbellek and metin:
            self.onbellek.kaydet(anahtar, metin, "eur-lex.europa.eu", {"baslik": baslik})

        return MevzuatMetni(
            kanun_adi=baslik,
            baslik=baslik,
            metin=metin,
            url=url,
            kaynak="eur-lex.europa.eu",
            etiketler=["EU", celex_no],
        )
