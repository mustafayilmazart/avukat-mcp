# Bu modül, yerel data/kurallar/*.json dosyalarını gerçek mevzuat
# kaynaklarından gelen güncel bilgilerle yeniler. Her kural setinde
# bulunan "mevzuat_referans" alanından kanun URL'sini çıkarıp
# scraper ile tam metni çeker, tarih damgası ve son_guncelleme alanlarını
# yeniler. Mevzuat değişmişse uyarı verir.

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .scraper import MevzuatScraper
from .onbellek import DiskOnbellegi

logger = logging.getLogger("avukat-mcp.guncelleme")


# Her kural setinde hangi kaynağın taranacağını belirten eşleme.
# Bu eşleme, resmi kanun URL'lerini içerir ve kural JSON'ında yoksa
# doldurmak için kullanılır.
RESMI_KANUN_URLLERI: Dict[str, str] = {
    "kvkk": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6698&MevzuatTur=1&MevzuatTertip=5",
    "eticaret_tr": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6563&MevzuatTur=1&MevzuatTertip=5",
    "tuketici": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6502&MevzuatTur=1&MevzuatTertip=5",
    "fsek": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=5846&MevzuatTur=1&MevzuatTertip=3",
    "telif_lisans": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=5846&MevzuatTur=1&MevzuatTertip=3",
    "vuk": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=213&MevzuatTur=1&MevzuatTertip=4",
    "cocuk_koruma": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=5395&MevzuatTur=1&MevzuatTertip=5",
    # E-ticaret iletişim yönetmeliği — ticari elektronik iletiler
    "iletisim_pazarlama": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6563&MevzuatTur=1&MevzuatTertip=5",
    # BDDK/TCMB ödeme güvenliği — PCI-DSS ile overlap, yerel karşılık yok; iletişim kanunu üzerinden tarama
    "odeme_guvenlik": "https://www.mevzuat.gov.tr/mevzuat?MevzuatNo=6493&MevzuatTur=1&MevzuatTertip=5",
    # AB GDPR (Regulation 2016/679)
    "gdpr": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
}


@dataclass
class GuncellemeSonucu:
    """Tek bir kural seti için güncelleme çalışması sonucu."""
    kaynak_id: str
    durum: str                             # "basarili" / "degisiklik_yok" / "hata"
    onceki_hash: str = ""
    yeni_hash: str = ""
    metin_uzunlugu: int = 0
    hata: str = ""
    guncelleme_tarihi: str = ""


class KuralGuncelleyici:
    """
    Yerel JSON kural setlerini resmi mevzuat kaynaklarından güncelleyen motor.
    Her kural seti için kanun metnini çeker, hash'ini kaydeder ve değişiklik
    tespit ederse uyarı üretir. Kuralların kendisini kanundan otomatik türetmez
    (bu NLP gerektirir); sadece meta.guncelleme tarihini ve kaynak durumunu yeniler.
    """

    def __init__(
        self,
        kurallar_dizini: Path,
        onbellek: DiskOnbellegi,
        scraper: Optional[MevzuatScraper] = None,
    ):
        self.kurallar_dizini = Path(kurallar_dizini)
        self.onbellek = onbellek
        self.scraper = scraper or MevzuatScraper(onbellek=onbellek)
        self._hash_dosyasi = self.kurallar_dizini.parent / "cache" / "kural_hashleri.json"
        self._hash_dosyasi.parent.mkdir(parents=True, exist_ok=True)

    def _hashleri_yukle(self) -> Dict[str, str]:
        """Önceki güncellemedeki kanun metinlerinin hash'lerini yükler."""
        if not self._hash_dosyasi.exists():
            return {}
        try:
            return json.loads(self._hash_dosyasi.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _hashleri_kaydet(self, hashler: Dict[str, str]) -> None:
        """Hash kayıtlarını diske yazar."""
        self._hash_dosyasi.write_text(
            json.dumps(hashler, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _icerik_hash(self, metin: str) -> str:
        """Kanun metninin SHA-256 hash'ini üretir (değişiklik tespiti için)."""
        return hashlib.sha256(metin.encode("utf-8")).hexdigest()[:16]

    async def kaynak_guncelle(self, kaynak_id: str) -> GuncellemeSonucu:
        """
        Tek bir kural setini günceller. Kanun metnini çeker, değişiklik varsa
        meta.guncelleme alanını yeniler ve kullanıcıyı uyarır.
        """
        sonuc = GuncellemeSonucu(
            kaynak_id=kaynak_id,
            durum="hata",
            guncelleme_tarihi=datetime.now().isoformat(),
        )

        kural_dosyasi = self.kurallar_dizini / f"{kaynak_id}.json"
        if not kural_dosyasi.exists():
            sonuc.hata = f"Kural dosyası bulunamadı: {kural_dosyasi}"
            return sonuc

        kanun_url = RESMI_KANUN_URLLERI.get(kaynak_id)
        if not kanun_url:
            sonuc.hata = f"{kaynak_id} için resmi kanun URL'si tanımlı değil"
            sonuc.durum = "atlandi"
            return sonuc

        # Kanun metnini çek — GDPR için EUR-Lex, diğerleri için mevzuat.gov.tr
        try:
            if kaynak_id == "gdpr":
                metin = await self.scraper.eurlex_celex_getir("32016R0679")
            else:
                metin = await self.scraper.kanun_metni_getir(kanun_url)
        except Exception as e:
            sonuc.hata = f"Scraper hatası: {e}"
            return sonuc

        if not metin or not metin.metin:
            sonuc.hata = "Boş metin döndü"
            return sonuc

        # Hash karşılaştırması
        hashler = self._hashleri_yukle()
        yeni_hash = self._icerik_hash(metin.metin)
        onceki_hash = hashler.get(kaynak_id, "")

        sonuc.onceki_hash = onceki_hash
        sonuc.yeni_hash = yeni_hash
        sonuc.metin_uzunlugu = len(metin.metin)

        if onceki_hash == yeni_hash and onceki_hash:
            sonuc.durum = "degisiklik_yok"
        else:
            sonuc.durum = "basarili"
            logger.info(f"{kaynak_id}: mevzuat metninde değişiklik tespit edildi")

        # Meta.guncelleme alanını yenile (kural içeriğini değiştirmez)
        try:
            kural_veri = json.loads(kural_dosyasi.read_text(encoding="utf-8"))
            kural_veri.setdefault("meta", {})
            kural_veri["meta"]["guncelleme"] = datetime.now().strftime("%Y-%m-%d")
            kural_veri["meta"]["kanun_metin_hash"] = yeni_hash
            kural_veri["meta"]["kanun_kaynak_url"] = kanun_url
            kural_dosyasi.write_text(
                json.dumps(kural_veri, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, json.JSONDecodeError) as e:
            sonuc.hata = f"JSON güncelleme hatası: {e}"
            sonuc.durum = "kismi_hata"

        # Hash kaydet
        hashler[kaynak_id] = yeni_hash
        self._hashleri_kaydet(hashler)

        return sonuc

    async def tumunu_guncelle(self) -> List[GuncellemeSonucu]:
        """Tüm yerel kural setlerini sırayla (ağa ağır yük bindirmemek için) günceller."""
        sonuclar: List[GuncellemeSonucu] = []
        for dosya in sorted(self.kurallar_dizini.glob("*.json")):
            kaynak_id = dosya.stem
            try:
                sonuc = await self.kaynak_guncelle(kaynak_id)
                sonuclar.append(sonuc)
                logger.info(f"{kaynak_id}: {sonuc.durum}")
            except Exception as e:
                sonuclar.append(GuncellemeSonucu(
                    kaynak_id=kaynak_id,
                    durum="hata",
                    hata=str(e),
                    guncelleme_tarihi=datetime.now().isoformat(),
                ))
        # Son: Playwright tarayıcısını kapat
        try:
            await self.scraper.kapat()
        except Exception:
            pass
        return sonuclar
