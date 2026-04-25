# Bu modül gizlilik politikası, aydınlatma metni ve cookie consent
# mekanizmalarının varlığını kontrol eder.

import re
from .temel import BaseTarayici, Bulgu


class GizlilikTarayici(BaseTarayici):
    """Gizlilik politikası ve aydınlatma metni kontrolü yapan tarayıcı"""

    async def tara(self):
        self.bulgular = []
        dosyalar = self._dosyalari_listele()

        await self._gizlilik_sayfasi_kontrol()
        await self._cookie_banner_kontrol(dosyalar)
        await self._kvkk_aydinlatma_kontrol(dosyalar)

        return self.bulgular

    async def _gizlilik_sayfasi_kontrol(self):
        """Gizlilik politikası / privacy policy sayfası var mı kontrol eder"""
        gizlilik_isimleri = [
            "privacy-policy", "privacy_policy", "gizlilik-politikasi",
            "gizlilik_politikasi", "aydinlatma-metni", "aydinlatma_metni",
            "kvkk", "privacy", "PRIVACY.md", "PRIVACY.txt",
        ]

        bulundu = False
        for isim in gizlilik_isimleri:
            sonuc = self._dosya_var_mi(
                f"{isim}.html", f"{isim}.tsx", f"{isim}.jsx",
                f"{isim}.py", f"{isim}.md", f"{isim}.txt",
                f"pages/{isim}.tsx", f"pages/{isim}.jsx",
                f"app/{isim}/page.tsx", f"templates/{isim}.html",
            )
            if sonuc:
                bulundu = True
                break

        if not bulundu:
            # Route olarak da arayalım
            for dosya in self._dosyalari_listele()[:30]:
                icerik = await self._dosya_oku(dosya)
                if icerik and re.search(r'["\'/](?:privacy|gizlilik|kvkk|aydinlatma)', icerik, re.IGNORECASE):
                    bulundu = True
                    break

        if not bulundu:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("GZL"),
                seviye="kritik",
                kategori="gizlilik",
                baslik="Gizlilik Politikası / Aydınlatma Metni Eksik",
                dosya=str(self.proje_dizini),
                satir=0,
                aciklama="Projede gizlilik politikası veya KVKK aydınlatma metni bulunamadı.",
                mevzuat=["6698 sayılı KVKK md.10", "GDPR Art.13-14"],
                duzeltme="Gizlilik Politikası sayfası oluşturun: veri sorumlusu, toplanan veriler, işleme amacı, saklama süresi, haklar ve başvuru yolu.",
                oncelik=1,
            ))

    async def _cookie_banner_kontrol(self, dosyalar):
        """Cookie consent banner mekanizması var mı kontrol eder"""
        cookie_desenleri = r'cookie[-_]?consent|cookie[-_]?banner|CookieConsent|cerez[-_]?onay|onetrust|cookieyes'
        pattern = re.compile(cookie_desenleri, re.IGNORECASE)

        cookie_kullanimi = False
        cookie_banner = False

        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue
            if re.search(r'cookie|localStorage|gtag|analytics|fbq', icerik, re.IGNORECASE):
                cookie_kullanimi = True
            if pattern.search(icerik):
                cookie_banner = True

        if cookie_kullanimi and not cookie_banner:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("GZL"),
                seviye="kritik",
                kategori="cookie_consent",
                baslik="Cookie Consent Banner Eksik",
                dosya=str(self.proje_dizini),
                satir=0,
                aciklama="Proje cookie/analytics kullanıyor ama cookie consent mekanizması bulunamadı.",
                mevzuat=["6698 sayılı KVKK", "GDPR Art.7", "ePrivacy Directive Art.5(3)"],
                duzeltme="Cookie consent banner ekleyin. Zorunlu olmayan çerezleri onay alınmadan yüklemeyin.",
                oncelik=1,
            ))

    async def _kvkk_aydinlatma_kontrol(self, dosyalar):
        """Gizlilik sayfasında KVKK zorunlu öğeleri var mı kontrol eder"""
        gizlilik_dosya = None
        for dosya in dosyalar:
            if any(k in dosya.name.lower() for k in ["privacy", "gizlilik", "kvkk", "aydinlatma"]):
                gizlilik_dosya = dosya
                break

        if not gizlilik_dosya:
            return

        icerik = await self._dosya_oku(gizlilik_dosya)
        if not icerik:
            return

        gerekli = {
            "veri_sorumlusu": (r'veri\s*sorumlusu|data\s*controller', "Veri Sorumlusu Bilgisi"),
            "islem_amaci": (r'işlem\s*amac|processing\s*purpose|amaç', "İşleme Amacı"),
            "haklar": (r'hak(?:lar)?(?:ınız)?|rights|başvuru', "İlgili Kişi Hakları"),
            "saklama": (r'saklama\s*süre|retention|muhafaza', "Saklama Süresi"),
        }

        for _, (desen, baslik) in gerekli.items():
            if not re.search(desen, icerik, re.IGNORECASE):
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("GZL"),
                    seviye="yuksek",
                    kategori="kvkk_aydinlatma",
                    baslik=f"Aydınlatma Metninde Eksik: {baslik}",
                    dosya=str(gizlilik_dosya),
                    satir=0,
                    aciklama=f"KVKK aydınlatma metninde '{baslik}' bilgisi bulunamadı.",
                    mevzuat=["6698 sayılı KVKK md.10"],
                    duzeltme=f"Aydınlatma metnine '{baslik}' bölümü ekleyin.",
                    oncelik=2,
                ))
