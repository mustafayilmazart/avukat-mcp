# Bu modül, tüm bileşenleri (WP API, Unsplash, Pillow, Yedekleme) orkestra edip
# "riskli görsel → güvenli görselle değiştir" iş akışını yürütür.
# İki mod: dry-run (sadece plan) ve apply (gerçek değişiklik).

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .wp_api import WordPressAPI, WPMedia, WPPost
from .unsplash import UnsplashAPI, UnsplashSonuc
from .gorsel_islem import gorsel_boyutla, gorsel_kategori_tahmin
from .yedekleme import YedeklemeMotoru, YedekKaydi

logger = logging.getLogger("avukat-mcp.degistir")


@dataclass
class DegistirmePlani:
    """Bir görsel için planlanan değiştirme eylemi (dry-run çıktısı)."""
    media_id: int
    eski_url: str
    eski_dosya_adi: str
    eski_boyut: str                     # "1000x1300"
    risk_seviyesi: str                  # KRİTİK / YÜKSEK / ORTA / BELİRSİZ
    unsplash_sorgu: str
    unsplash_aday_id: str = ""
    unsplash_aday_url: str = ""
    unsplash_fotografci: str = ""
    tahmini_etkilenen_post_sayisi: int = 0
    etkilenen_post_listesi: List[dict] = field(default_factory=list)
    not_: str = ""


@dataclass
class DegistirmeSonucu:
    """Apply sonrası tek bir görsel için gerçekleşen sonuç."""
    media_id: int
    eski_url: str
    yeni_url: str = ""
    yeni_media_id: int = 0
    durum: str = "basarisiz"            # basarili / basarisiz / atlandi
    hata: str = ""
    guncellenen_post_sayisi: int = 0
    yedek_dosya: str = ""


class GorselDegistiriciMotor:
    """
    Ana iş akışı motoru:
    1. Riskli görsel listesi yükle (ters arama raporundan)
    2. Her biri için WordPress'te media ID bul
    3. Hangi postlarda kullanıldığını tespit et
    4. Unsplash'ten aynı kategoride güvenli aday bul
    5. [apply modunda]: Yedekle → Crop → Upload → Post içeriğinde URL değiştir → Trash'e at
    """

    def __init__(
        self,
        wp_api: WordPressAPI,
        unsplash_api: UnsplashAPI,
        yedekleme: YedeklemeMotoru,
        gecici_dizin: Optional[Path] = None,
    ):
        self.wp = wp_api
        self.unsplash = unsplash_api
        self.yedekleme = yedekleme
        self.gecici = gecici_dizin or Path(tempfile.gettempdir()) / "avukat_mcp_degisim"
        self.gecici.mkdir(parents=True, exist_ok=True)
        self._medya_cache: Optional[List[WPMedia]] = None

    # ── Medya listesi (tek sefer çek, sonra cache'den) ──

    async def _medyayi_yukle(self) -> List[WPMedia]:
        if self._medya_cache is None:
            self._medya_cache = await self.wp.medya_listesi()
        return self._medya_cache

    async def _url_ile_medya_bul(self, url: str) -> Optional[WPMedia]:
        """Verilen URL ile eşleşen medya kaydını bulur."""
        hedef_isim = Path(url.split("?")[0]).name.split("-scaled")[0].split(".")[0]

        tum = await self._medyayi_yukle()

        # Önce tam URL eşleşmesi
        for m in tum:
            if m.source_url == url:
                return m
        # Dosya adı eşleşmesi
        for m in tum:
            mevcut_isim = Path(m.source_url.split("?")[0]).name.split("-scaled")[0].split(".")[0]
            if mevcut_isim == hedef_isim:
                return m
        return None

    # ── DRY-RUN: Değişiklik yapmadan planı üret ──

    async def plan_uret(
        self,
        riskli_gorseller: List[dict],
    ) -> List[DegistirmePlani]:
        """
        Her riskli görsel için detaylı değiştirme planı döndürür.
        Gerçek değişiklik yapmaz — sadece keşif ve tahmin.

        riskli_gorseller elemanı: {'url','dosya','risk','eylem'}
        """
        planlar: List[DegistirmePlani] = []

        for g in riskli_gorseller:
            url = g["url"]
            dosya_adi = g.get("dosya", "").split("/")[-1]
            risk = g.get("risk", "YÜKSEK")

            # WP'de medya kaydını bul
            media = await self._url_ile_medya_bul(url)
            if not media:
                planlar.append(DegistirmePlani(
                    media_id=0, eski_url=url,
                    eski_dosya_adi=dosya_adi, eski_boyut="?",
                    risk_seviyesi=risk,
                    unsplash_sorgu="", not_="WP medya kaydı bulunamadı — manuel kontrol",
                ))
                continue

            # Unsplash arama kelimesi tahmini
            sorgu = gorsel_kategori_tahmin(
                dosya_adi=media.slug or dosya_adi,
                alt_text=media.alt_text,
                caption="",
            )

            # Unsplash aday bul
            aday = await self.unsplash.boyuta_uygun_bul(
                sorgu=sorgu,
                hedef_genislik=media.width or 1000,
                hedef_yukseklik=media.height or 1300,
            )

            # Etkilenen postları bul
            etkilenen = await self.wp.icerikte_url_arayan_postlar(url)

            plan = DegistirmePlani(
                media_id=media.id,
                eski_url=media.source_url,
                eski_dosya_adi=dosya_adi,
                eski_boyut=f"{media.width}x{media.height}",
                risk_seviyesi=risk,
                unsplash_sorgu=sorgu,
                unsplash_aday_id=aday.id if aday else "",
                unsplash_aday_url=aday.url_regular if aday else "",
                unsplash_fotografci=aday.fotografci_adi if aday else "",
                tahmini_etkilenen_post_sayisi=len(etkilenen),
                etkilenen_post_listesi=[
                    {"id": p.id, "type": p.type, "baslik": p.title[:60]}
                    for p in etkilenen
                ],
                not_="Uygun Unsplash adayı yok" if not aday else "",
            )
            planlar.append(plan)

        return planlar

    # ── APPLY: Gerçek değiştirme ──

    async def uygula(
        self,
        riskli_gorseller: List[dict],
        onay_fonksiyonu=None,
    ) -> List[DegistirmeSonucu]:
        """
        Planı gerçekten uygula. Her adım için onay_fonksiyonu çağrılır
        (None ise her şey otomatik onaylanır).
        """
        sonuclar: List[DegistirmeSonucu] = []

        for g in riskli_gorseller:
            url = g["url"]
            sonuc = DegistirmeSonucu(media_id=0, eski_url=url, durum="basarisiz")

            # 1. Medya bul
            media = await self._url_ile_medya_bul(url)
            if not media:
                sonuc.hata = "WP medya kaydı bulunamadı"
                sonuclar.append(sonuc)
                continue
            sonuc.media_id = media.id

            # 2. Onay kontrolü (interaktif modda)
            if onay_fonksiyonu:
                if not onay_fonksiyonu(media, g):
                    sonuc.durum = "atlandi"
                    sonuc.hata = "Kullanıcı atladı"
                    sonuclar.append(sonuc)
                    continue

            try:
                # 3. Orijinali yedekle
                yedek_yol = await self.yedekleme.dosyayi_yedekle(media.source_url, media.id)
                if yedek_yol:
                    sonuc.yedek_dosya = str(yedek_yol)

                self.yedekleme.kayit_ekle(YedekKaydi(
                    zaman=datetime.now().isoformat(),
                    eski_media_id=media.id,
                    eski_url=media.source_url,
                    eski_dosya_yolu=str(yedek_yol) if yedek_yol else "",
                ))

                # 4. Unsplash'tan aday bul
                sorgu = gorsel_kategori_tahmin(
                    dosya_adi=media.slug or media.source_url,
                    alt_text=media.alt_text,
                )
                aday = await self.unsplash.boyuta_uygun_bul(
                    sorgu=sorgu,
                    hedef_genislik=media.width or 1000,
                    hedef_yukseklik=media.height or 1300,
                )
                if not aday:
                    sonuc.hata = f"Unsplash'ta '{sorgu}' için aday bulunamadı"
                    sonuclar.append(sonuc)
                    continue

                # 5. İndir
                ham_dosya = self.gecici / f"unsplash_{aday.id}.jpg"
                if not await self.unsplash.indir(aday, ham_dosya):
                    sonuc.hata = "Unsplash görseli indirilemedi"
                    sonuclar.append(sonuc)
                    continue

                # 6. Hedef boyuta getir
                yeni_dosya_adi = Path(media.source_url.split("?")[0]).name
                # Orijinal ismi koru ama sonuna sürüm eki ekle (çakışma olmasın)
                isim_kok = Path(yeni_dosya_adi).stem
                ext = Path(yeni_dosya_adi).suffix
                islenecek = self.gecici / f"{isim_kok}-guvenli{ext}"

                if not gorsel_boyutla(ham_dosya, islenecek, media.width, media.height):
                    sonuc.hata = "Görsel boyutlama başarısız"
                    sonuclar.append(sonuc)
                    continue

                # 7. WP'ye yükle
                yeni_media = await self.wp.medya_yukle(
                    dosya_yolu=islenecek,
                    baslik=media.title or isim_kok,
                    alt_text=media.alt_text,
                    yorum=f"Unsplash: {aday.fotografci_adi} ({aday.fotografci_url}) | "
                          f"Avukat MCP tarafından {datetime.now().strftime('%Y-%m-%d')} tarihinde "
                          f"telif riski nedeniyle değiştirildi.",
                )
                if not yeni_media:
                    sonuc.hata = "WP'ye yükleme başarısız"
                    sonuclar.append(sonuc)
                    continue

                sonuc.yeni_media_id = yeni_media.id
                sonuc.yeni_url = yeni_media.source_url

                # 8. Tüm post'larda URL'yi değiştir
                etkilenen = await self.wp.icerikte_url_arayan_postlar(media.source_url)
                guncellenen = 0
                for post in etkilenen:
                    # Yedekle (snapshot)
                    self.yedekleme.post_icerigi_snapshot(post.id, post.type, post.content)

                    # Güncelle
                    basarili = await self.wp.post_iceriginde_url_degistir(
                        post, media.source_url, yeni_media.source_url
                    )
                    if basarili:
                        guncellenen += 1

                    # Elementor meta alanını da dene
                    try:
                        await self.wp.elementor_meta_degistir(
                            post.id, media.source_url, yeni_media.source_url
                        )
                    except Exception as e:
                        logger.debug(f"Elementor meta update atlanabilir: {e}")

                sonuc.guncellenen_post_sayisi = guncellenen

                # 9. Eski medyayı TRASH'e at (kalıcı silme YOK — rollback ihtimali için)
                await self.wp.medya_silinmis_isaretle(media.id, force=False)

                # Manifest güncelle
                self.yedekleme.son_kaydi_guncelle(
                    yeni_media_id=yeni_media.id,
                    yeni_url=yeni_media.source_url,
                    etkilenen_postlar=[
                        {"id": p.id, "type": p.type,
                         "eski_md5": YedeklemeMotoru.icerik_md5(p.content)}
                        for p in etkilenen
                    ],
                )

                sonuc.durum = "basarili"
            except Exception as e:
                sonuc.hata = f"Beklenmeyen hata: {e}"
                logger.exception(f"Değiştirme hatası (media {media.id})")

            sonuclar.append(sonuc)

        return sonuclar

    # ── ROLLBACK ──

    async def geri_al(self, oturum_dizini: Optional[Path] = None) -> dict:
        """
        Son değiştirme oturumunu geri alır. Yedeklenen orijinalleri yeniden yükler,
        post_content'leri eski haline getirir, yeni eklenen medyayı trash'e atar.
        """
        sonuc = {"basarili": 0, "basarisiz": 0, "detay": []}

        oturum = oturum_dizini or self.yedekleme.oturum_dizini
        manifest_yolu = oturum / "manifest.json"
        if not manifest_yolu.exists():
            sonuc["hata"] = f"Manifest yok: {manifest_yolu}"
            return sonuc

        veri = json.loads(manifest_yolu.read_text(encoding="utf-8"))
        for kayit_dict in veri.get("kayitlar", []):
            k = YedekKaydi(**kayit_dict)
            if not k.yeni_media_id:
                continue

            try:
                # Yeni (Unsplash) medyayı trash'e at
                await self.wp.medya_silinmis_isaretle(k.yeni_media_id, force=False)

                # Eski (yedek) orijinali yeniden yükle
                yedek_dosya = Path(k.eski_dosya_yolu)
                if yedek_dosya.exists():
                    await self.wp.medya_yukle(yedek_dosya)

                # Post içeriklerinde eski URL'ye döndür — yeni URL'yi eski URL ile replace et
                etkilenen = await self.wp.icerikte_url_arayan_postlar(k.yeni_url)
                for post in etkilenen:
                    await self.wp.post_iceriginde_url_degistir(
                        post, k.yeni_url, k.eski_url
                    )

                sonuc["basarili"] += 1
            except Exception as e:
                sonuc["basarisiz"] += 1
                sonuc["detay"].append(f"media {k.eski_media_id}: {e}")

        return sonuc
