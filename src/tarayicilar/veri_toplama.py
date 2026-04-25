# Bu modül kişisel veri toplama noktalarını tespit eder.
# Form alanları, cookie kullanımı, analytics kodları, IP loglama gibi
# veri toplama faaliyetlerini tarar.

import re
from .temel import BaseTarayici, Bulgu


class VeriToplamaTarayici(BaseTarayici):
    """Kişisel veri toplama noktalarını tespit eden tarayıcı"""

    async def tara(self):
        self.bulgular = []
        dosyalar = self._dosyalari_listele()

        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            await self._form_alanlari_kontrol(dosya, icerik)
            await self._cookie_kontrol(dosya, icerik)
            await self._analytics_kontrol(dosya, icerik)
            await self._storage_kontrol(dosya, icerik)
            await self._ip_loglama_kontrol(dosya, icerik)

        return self.bulgular

    async def _form_alanlari_kontrol(self, dosya, icerik):
        """HTML/JSX formlarında kişisel veri toplayan input alanlarını tespit eder"""
        # E-posta, telefon, TC kimlik, ad-soyad, adres gibi alanlar
        desenler = [
            (r'type\s*=\s*["\']email["\']', "E-posta alanı"),
            (r'type\s*=\s*["\']tel["\']', "Telefon alanı"),
            (r'name\s*=\s*["\'](?:tc|tckn|kimlik|identity)["\']', "TC Kimlik alanı"),
            (r'name\s*=\s*["\'](?:address|adres)["\']', "Adres alanı"),
            (r'(?:signup|register|kayit|üyelik)\s*(?:form|Form)', "Kayıt formu"),
        ]

        for desen, aciklama in desenler:
            pattern = re.compile(desen, re.IGNORECASE)
            eslesme_listesi = await self._icerik_ara(dosya, pattern, icerik)
            for satir_no, satir, _ in eslesme_listesi:
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("VT"),
                    seviye="yuksek",
                    kategori="veri_toplama",
                    baslik=f"Kişisel Veri Toplama: {aciklama}",
                    dosya=str(dosya),
                    satir=satir_no,
                    aciklama=f"{aciklama} tespit edildi. KVKK kapsamında açık rıza mekanizması gerekir.",
                    mevzuat=["6698 sayılı KVKK md.5", "GDPR Art.6"],
                    duzeltme="Bu forma açık rıza onay kutusu (checkbox) ve aydınlatma metni linki ekleyin.",
                    oncelik=2,
                ))

    async def _cookie_kontrol(self, dosya, icerik):
        """Cookie kullanımını tespit eder"""
        desenler = [
            (r'document\.cookie', "document.cookie kullanımı"),
            (r'setCookie|set_cookie|cookie\.set', "Cookie yazma fonksiyonu"),
            (r'js-cookie|cookie-parser|cookies-next', "Cookie kütüphanesi"),
            (r'Cookies\.set|Cookies\.get', "Cookie erişimi"),
        ]

        for desen, aciklama in desenler:
            pattern = re.compile(desen, re.IGNORECASE)
            eslesme_listesi = await self._icerik_ara(dosya, pattern, icerik)
            for satir_no, satir, _ in eslesme_listesi:
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("VT"),
                    seviye="kritik",
                    kategori="cookie",
                    baslik=f"Cookie Kullanımı: {aciklama}",
                    dosya=str(dosya),
                    satir=satir_no,
                    aciklama=f"{aciklama} tespit edildi. Cookie consent (çerez onayı) mekanizması gerekir.",
                    mevzuat=["6698 sayılı KVKK", "GDPR Art.7", "ePrivacy Directive"],
                    duzeltme="Cookie consent banner ekleyin. Zorunlu olmayan çerezleri onay alınmadan yüklemeyin.",
                    oncelik=1,
                ))

    async def _analytics_kontrol(self, dosya, icerik):
        """Analytics ve tracking kodlarını tespit eder"""
        desenler = [
            (r'gtag\(|ga\(|_gaq|GoogleAnalytics|google-analytics|G-[A-Z0-9]+', "Google Analytics"),
            (r'fbq\(|facebook.*pixel|fb-pixel', "Facebook Pixel"),
            (r'hotjar|_hj|hj\.q', "Hotjar"),
            (r'mixpanel|amplitude|segment\.com', "Analitik aracı"),
        ]

        for desen, aciklama in desenler:
            pattern = re.compile(desen, re.IGNORECASE)
            eslesme_listesi = await self._icerik_ara(dosya, pattern, icerik)
            for satir_no, satir, _ in eslesme_listesi[:1]:  # Her araç için tek bulgu yeter
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("VT"),
                    seviye="yuksek",
                    kategori="analytics",
                    baslik=f"Tracking/Analytics: {aciklama}",
                    dosya=str(dosya),
                    satir=satir_no,
                    aciklama=f"{aciklama} kullanımı tespit edildi. Kullanıcı takibi için önceden onay alınmalıdır.",
                    mevzuat=["6698 sayılı KVKK md.5", "GDPR Art.6-7", "ePrivacy Directive"],
                    duzeltme="Analytics kodlarını cookie consent mekanizmasına bağlayın. Onay verilmeden yüklemeyin.",
                    oncelik=2,
                ))

    async def _storage_kontrol(self, dosya, icerik):
        """localStorage/sessionStorage kullanımını tespit eder"""
        pattern = re.compile(r'localStorage\.|sessionStorage\.', re.IGNORECASE)
        eslesme_listesi = await self._icerik_ara(dosya, pattern, icerik)
        for satir_no, satir, _ in eslesme_listesi[:3]:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("VT"),
                seviye="orta",
                kategori="storage",
                baslik="Web Storage Kullanımı",
                dosya=str(dosya),
                satir=satir_no,
                aciklama="localStorage/sessionStorage'da kişisel veri saklanıyor olabilir. Gizlilik politikasında belirtilmeli.",
                mevzuat=["6698 sayılı KVKK md.10", "GDPR Art.13"],
                duzeltme="Storage'da saklanan verileri gizlilik politikasında açıklayın. Hassas veri saklamayın.",
                oncelik=4,
            ))

    async def _ip_loglama_kontrol(self, dosya, icerik):
        """IP adresi loglama tespiti"""
        pattern = re.compile(r'(?:request\.(?:ip|remote_addr|client_ip)|req\.ip|X-Forwarded-For|REMOTE_ADDR)', re.IGNORECASE)
        eslesme_listesi = await self._icerik_ara(dosya, pattern, icerik)
        for satir_no, satir, _ in eslesme_listesi[:2]:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("VT"),
                seviye="orta",
                kategori="ip_loglama",
                baslik="IP Adresi Loglama",
                dosya=str(dosya),
                satir=satir_no,
                aciklama="IP adresi kişisel veridir. Loglama yapılıyorsa aydınlatma metninde belirtilmelidir.",
                mevzuat=["6698 sayılı KVKK md.10", "GDPR Recital 30"],
                duzeltme="IP loglamasını gizlilik politikasında belirtin. Gereksiz ise kaldırın veya anonimleştirin.",
                oncelik=4,
            ))
