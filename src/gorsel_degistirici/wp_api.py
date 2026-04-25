# Bu modül WordPress REST API'sine bağlanarak medya kütüphanesini okuyup,
# yeni medya yükleyip ve post_content'teki görsel URL'lerini güncellemek için
# kullanılır. Application Password (WP admin → Kullanıcılar → Uygulama Parolaları)
# ile basic auth yapılır.

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import httpx

logger = logging.getLogger("avukat-mcp.wp_api")


@dataclass
class WPMedia:
    """WordPress medya kütüphanesindeki tek kayıt."""
    id: int
    source_url: str
    title: str
    alt_text: str
    mime_type: str
    width: int
    height: int
    date: str
    slug: str = ""
    media_details: dict = field(default_factory=dict)


@dataclass
class WPPost:
    """post_content'te görsel referansı taşıyan post/page/elementor_library kaydı."""
    id: int
    type: str  # post / page / elementor_library
    title: str
    content: str
    modified: str


class WordPressAPI:
    """
    WordPress REST API istemcisi.
    Authentication: Application Password (WordPress 5.6+ built-in özelliği).
    """

    def __init__(
        self,
        site_url: str,
        kullanici_adi: Optional[str] = None,
        app_parolasi: Optional[str] = None,
        zaman_asimi: float = 30.0,
    ):
        # Trailing slash'i temizle
        self.site_url = site_url.rstrip("/")
        self.api_base = f"{self.site_url}/wp-json/wp/v2"

        # Credentials — önce parametreler, yoksa ortam değişkenleri
        self.kullanici = kullanici_adi or os.environ.get("WP_USERNAME", "")
        self.app_parola = app_parolasi or os.environ.get("WP_APP_PASSWORD", "")

        self.zaman_asimi = zaman_asimi
        self._istemci: Optional[httpx.AsyncClient] = None

    # ── Yaşam döngüsü ──

    async def baglan(self) -> None:
        """Async HTTP istemcisini başlatır."""
        if self._istemci:
            return

        basliklar = {
            "User-Agent": "AvukatMCP-GorselDegistirici/1.0",
            "Accept": "application/json",
        }

        # Application password → HTTP Basic Auth
        if self.kullanici and self.app_parola:
            # WP app passwords boşluklu gelebilir — temizle
            parola_temiz = self.app_parola.replace(" ", "")
            kimlik = base64.b64encode(
                f"{self.kullanici}:{parola_temiz}".encode()
            ).decode()
            basliklar["Authorization"] = f"Basic {kimlik}"

        self._istemci = httpx.AsyncClient(
            headers=basliklar,
            timeout=self.zaman_asimi,
            follow_redirects=True,
        )

    async def kapat(self) -> None:
        if self._istemci:
            await self._istemci.aclose()
            self._istemci = None

    async def __aenter__(self):
        await self.baglan()
        return self

    async def __aexit__(self, *_):
        await self.kapat()

    # ── Sağlık Kontrolü ──

    async def saglik_kontrol(self) -> dict:
        """REST API'ye bağlantıyı doğrular ve kullanıcı yetkilerini raporlar."""
        assert self._istemci is not None

        try:
            # /wp-json kök endpoint
            r = await self._istemci.get(f"{self.site_url}/wp-json/")
            if r.status_code != 200:
                return {"durum": "hata", "hata": f"HTTP {r.status_code}", "detay": r.text[:300]}

            kok = r.json()

            # /wp-json/wp/v2/users/me → kimlik doğrulama testi
            me = await self._istemci.get(f"{self.api_base}/users/me?context=edit")
            if me.status_code == 401:
                return {"durum": "yetkisiz", "uyari": "Kullanıcı adı veya application password hatalı"}
            if me.status_code != 200:
                return {"durum": "hata", "hata": f"/users/me HTTP {me.status_code}"}

            kullanici = me.json()

            return {
                "durum": "ok",
                "site_adi": kok.get("name", ""),
                "site_url": self.site_url,
                "wp_surumu": kok.get("wp_version", "?"),
                "kullanici": kullanici.get("name", ""),
                "yetkiler": kullanici.get("capabilities", {}),
                "edit_post": kullanici.get("capabilities", {}).get("edit_posts", False),
                "upload_files": kullanici.get("capabilities", {}).get("upload_files", False),
            }
        except httpx.HTTPError as e:
            return {"durum": "hata", "hata": str(e)}

    # ── Medya İşlemleri ──

    async def medya_listesi(self, per_page: int = 100) -> List[WPMedia]:
        """Tüm medya kütüphanesini sayfa sayfa çeker."""
        assert self._istemci is not None

        sonuclar: List[WPMedia] = []
        for sayfa in range(1, 21):  # max 2000 medya
            r = await self._istemci.get(
                f"{self.api_base}/media",
                params={"per_page": per_page, "page": sayfa, "orderby": "date", "order": "desc"},
            )
            if r.status_code != 200:
                break
            veri = r.json()
            if not veri:
                break
            for m in veri:
                detaylar = m.get("media_details", {})
                sonuclar.append(WPMedia(
                    id=m["id"],
                    source_url=m.get("source_url", ""),
                    title=(m.get("title", {}) or {}).get("rendered", ""),
                    alt_text=m.get("alt_text", ""),
                    mime_type=m.get("mime_type", ""),
                    width=detaylar.get("width", 0),
                    height=detaylar.get("height", 0),
                    date=m.get("date", ""),
                    slug=m.get("slug", ""),
                    media_details=detaylar,
                ))
            if len(veri) < per_page:
                break
        return sonuclar

    async def medya_yukle(
        self,
        dosya_yolu: Path,
        baslik: str = "",
        alt_text: str = "",
        yorum: str = "",
    ) -> Optional[WPMedia]:
        """Yeni bir görsel dosyasını WP medya kütüphanesine yükler."""
        assert self._istemci is not None

        dosya_yolu = Path(dosya_yolu)
        if not dosya_yolu.exists():
            logger.error(f"Dosya yok: {dosya_yolu}")
            return None

        mime, _ = mimetypes.guess_type(str(dosya_yolu))
        mime = mime or "application/octet-stream"

        icerik = dosya_yolu.read_bytes()

        basliklar = {
            "Content-Disposition": f'attachment; filename="{dosya_yolu.name}"',
            "Content-Type": mime,
        }

        r = await self._istemci.post(
            f"{self.api_base}/media",
            content=icerik,
            headers=basliklar,
        )

        if r.status_code not in (200, 201):
            logger.error(f"Yükleme hatası: HTTP {r.status_code} — {r.text[:300]}")
            return None

        m = r.json()

        # Başlık/alt metin ayrı PATCH ile güncellenir
        if baslik or alt_text or yorum:
            guncelle_veri = {}
            if baslik:
                guncelle_veri["title"] = baslik
            if alt_text:
                guncelle_veri["alt_text"] = alt_text
            if yorum:
                guncelle_veri["caption"] = yorum
            await self._istemci.post(
                f"{self.api_base}/media/{m['id']}",
                json=guncelle_veri,
            )

        detaylar = m.get("media_details", {})
        return WPMedia(
            id=m["id"],
            source_url=m.get("source_url", ""),
            title=baslik or (m.get("title", {}) or {}).get("rendered", ""),
            alt_text=alt_text,
            mime_type=m.get("mime_type", ""),
            width=detaylar.get("width", 0),
            height=detaylar.get("height", 0),
            date=m.get("date", ""),
            slug=m.get("slug", ""),
            media_details=detaylar,
        )

    async def medya_silinmis_isaretle(self, media_id: int, force: bool = False) -> bool:
        """Medyayı trash'e atar (force=False) veya kalıcı siler (force=True)."""
        assert self._istemci is not None

        # force=False → sadece trash'e, force=True → kalıcı
        r = await self._istemci.delete(
            f"{self.api_base}/media/{media_id}",
            params={"force": "true" if force else "false"},
        )
        return r.status_code in (200, 204)

    # ── Post/Page içerik işlemleri ──

    async def icerikte_url_arayan_postlar(
        self,
        aranacak_url: str,
        post_tipleri: Optional[List[str]] = None,
    ) -> List[WPPost]:
        """Verilen URL'yi post_content'inde geçiren tüm post/page kayıtlarını bulur."""
        assert self._istemci is not None

        post_tipleri = post_tipleri or ["posts", "pages"]
        bulunanlar: List[WPPost] = []

        for tip in post_tipleri:
            for sayfa in range(1, 11):
                r = await self._istemci.get(
                    f"{self.api_base}/{tip}",
                    params={
                        "per_page": 100, "page": sayfa, "context": "edit",
                        "_fields": "id,type,title,content,modified",
                    },
                )
                if r.status_code != 200:
                    break
                veri = r.json()
                if not veri:
                    break
                for p in veri:
                    icerik_raw = (p.get("content", {}) or {}).get("raw", "") or \
                                 (p.get("content", {}) or {}).get("rendered", "")
                    if aranacak_url in icerik_raw:
                        bulunanlar.append(WPPost(
                            id=p["id"],
                            type=p.get("type", tip),
                            title=(p.get("title", {}) or {}).get("rendered", ""),
                            content=icerik_raw,
                            modified=p.get("modified", ""),
                        ))
                if len(veri) < 100:
                    break

        return bulunanlar

    async def post_iceriginde_url_degistir(
        self,
        post: WPPost,
        eski_url: str,
        yeni_url: str,
    ) -> bool:
        """post_content'teki bir URL'yi başka bir URL ile değiştirir."""
        assert self._istemci is not None

        yeni_icerik = post.content.replace(eski_url, yeni_url)
        if yeni_icerik == post.content:
            return False

        endpoint = f"{self.api_base}/{post.type}s/{post.id}" if not post.type.endswith("s") \
                   else f"{self.api_base}/{post.type}/{post.id}"

        r = await self._istemci.post(
            endpoint,
            json={"content": yeni_icerik},
        )
        return r.status_code in (200, 201)

    # ── Elementor özel desteği ──

    async def elementor_meta_degistir(
        self,
        post_id: int,
        eski_url: str,
        yeni_url: str,
    ) -> bool:
        """
        Elementor tarafından oluşturulan sayfalar, görselleri post_content değil
        `_elementor_data` meta alanında JSON olarak saklar. Bu meta alanı da
        ayrıca güncellenmelidir. WP REST API'de meta 'authenticated' ile erişilebilir.
        """
        assert self._istemci is not None

        # Önce post'u çek (meta dahil)
        r = await self._istemci.get(
            f"{self.api_base}/pages/{post_id}",
            params={"context": "edit", "_fields": "id,meta"},
        )
        if r.status_code != 200:
            # Post olarak dene
            r = await self._istemci.get(
                f"{self.api_base}/posts/{post_id}",
                params={"context": "edit", "_fields": "id,meta"},
            )
        if r.status_code != 200:
            return False

        p = r.json()
        meta = p.get("meta", {})
        elementor_data = meta.get("_elementor_data")
        if not elementor_data:
            return False

        if eski_url not in elementor_data:
            return False

        yeni_data = elementor_data.replace(eski_url, yeni_url)

        # Meta güncelleme — WP default meta alanları 'show_in_rest: false' olabilir,
        # _elementor_data için register gerekebilir. Güvenli tarafta kalmak için
        # hem posts hem pages endpoint'ini dene.
        for endpoint in (
            f"{self.api_base}/pages/{post_id}",
            f"{self.api_base}/posts/{post_id}",
        ):
            g = await self._istemci.post(endpoint, json={"meta": {"_elementor_data": yeni_data}})
            if g.status_code in (200, 201):
                return True
        return False
