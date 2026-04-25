# Bu modül e-ticaret projelerini Türkiye ve uluslararası mevzuat
# kapsamında kontrol eder: mesafeli satış, iade, ödeme güvenliği vb.

import re
from .temel import BaseTarayici, Bulgu


class EticaretTarayici(BaseTarayici):
    """E-ticaret mevzuat kontrolü yapan tarayıcı"""

    async def tara(self):
        self.bulgular = []
        dosyalar = self._dosyalari_listele()

        # Önce projenin e-ticaret projesi olup olmadığını tespit et
        eticaret = await self._eticaret_mi(dosyalar)
        if not eticaret:
            return self.bulgular

        await self._mesafeli_satis_kontrol()
        await self._iade_politikasi_kontrol()
        await self._odeme_guvenlik_kontrol(dosyalar)
        await self._ssl_kontrol(dosyalar)
        await self._fatura_kontrol(dosyalar)

        return self.bulgular

    async def _eticaret_mi(self, dosyalar) -> bool:
        """Projenin e-ticaret öğeleri içerip içermediğini tespit eder"""
        eticaret_ipuclari = [
            r'stripe|iyzico|paytr|param|paypal|woocommerce|shopify',
            r'cart|sepet|checkout|ödeme|payment|order|sipariş',
            r'add[-_]?to[-_]?cart|sepete[-_]?ekle',
            r'product|ürün|price|fiyat|stock|stok',
        ]
        birlesik = "|".join(eticaret_ipuclari)
        pattern = re.compile(birlesik, re.IGNORECASE)

        for dosya in dosyalar[:50]:  # İlk 50 dosyaya bak
            icerik = await self._dosya_oku(dosya)
            if icerik and pattern.search(icerik):
                return True

        # package.json'da e-ticaret bağımlılıkları
        pkg = self._dosya_var_mi("package.json")
        if pkg:
            icerik = await self._dosya_oku(pkg)
            if icerik and re.search(r'stripe|@stripe|iyzico|paytr|shopify|snipcart|medusa', icerik, re.IGNORECASE):
                return True

        return False

    async def _mesafeli_satis_kontrol(self):
        """Mesafeli satış sözleşmesi sayfası var mı kontrol eder"""
        sayfalar = [
            "mesafeli-satis", "mesafeli_satis", "distance-selling",
            "terms-of-sale", "satis-sozlesmesi", "terms",
            "on-bilgilendirme", "preliminary-information",
        ]

        bulundu = False
        for isim in sayfalar:
            sonuc = self._dosya_var_mi(
                f"{isim}.html", f"{isim}.tsx", f"{isim}.jsx",
                f"{isim}.py", f"{isim}.md",
                f"pages/{isim}.tsx", f"app/{isim}/page.tsx",
                f"templates/{isim}.html",
            )
            if sonuc:
                bulundu = True
                break

        if not bulundu:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("ETIC"),
                seviye="kritik",
                kategori="eticaret",
                baslik="Mesafeli Satış Sözleşmesi Eksik",
                dosya=str(self.proje_dizini),
                satir=0,
                aciklama="E-ticaret sitesinde mesafeli satış sözleşmesi ve ön bilgilendirme formu bulunamadı. Türkiye'de zorunludur.",
                mevzuat=["6502 sayılı TKHK md.48", "Mesafeli Sözleşmeler Yönetmeliği md.6-7"],
                duzeltme="Mesafeli Satış Sözleşmesi ve Ön Bilgilendirme Formu sayfaları oluşturun. Satın alma öncesinde tüketiciye gösterilmeli.",
                oncelik=1,
            ))

    async def _iade_politikasi_kontrol(self):
        """İade/cayma hakkı sayfası var mı kontrol eder"""
        sayfalar = [
            "iade", "return", "refund", "cayma-hakki",
            "iade-politikasi", "return-policy", "cancellation",
        ]

        bulundu = False
        for isim in sayfalar:
            sonuc = self._dosya_var_mi(
                f"{isim}.html", f"{isim}.tsx", f"{isim}.jsx",
                f"{isim}.md", f"pages/{isim}.tsx",
                f"app/{isim}/page.tsx",
            )
            if sonuc:
                bulundu = True
                break

        if not bulundu:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("ETIC"),
                seviye="kritik",
                kategori="eticaret",
                baslik="İade Politikası / Cayma Hakkı Sayfası Eksik",
                dosya=str(self.proje_dizini),
                satir=0,
                aciklama="Tüketicinin 14 gün cayma hakkı vardır. İade politikası açıkça belirtilmelidir.",
                mevzuat=["6502 sayılı TKHK md.48/4", "Mesafeli Sözleşmeler Yönetmeliği md.9-15"],
                duzeltme="İade politikası sayfası oluşturun. 14 günlük cayma hakkı, iade süreci ve istisnalar açıkça belirtilmeli.",
                oncelik=1,
            ))

    async def _odeme_guvenlik_kontrol(self, dosyalar):
        """Ödeme güvenliği kontrolü (kart bilgisi saklama, PCI-DSS)"""
        # Doğrudan kart bilgisi saklama tespiti
        kart_desenleri = [
            (r'card[-_]?number|kart[-_]?no|credit[-_]?card|kredi[-_]?kart', "Kart numarası referansı"),
            (r'cvv|cvc|security[-_]?code|güvenlik[-_]?kodu', "CVV/güvenlik kodu referansı"),
            (r'card[-_]?expir|son[-_]?kullanma', "Kart son kullanma tarihi"),
        ]

        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            # Ödeme kütüphanesi dışında doğrudan kart işleme varsa uyar
            if re.search(r'stripe|iyzico|paytr', icerik, re.IGNORECASE):
                continue  # Güvenli ödeme kütüphanesi kullanılıyor

            for desen, aciklama in kart_desenleri:
                pattern = re.compile(desen, re.IGNORECASE)
                eslesme = await self._icerik_ara(dosya, pattern, icerik)
                if eslesme:
                    # Veritabanı kaydetme bağlamında mı kontrol et
                    for satir_no, satir, _ in eslesme[:1]:
                        if re.search(r'save|kaydet|store|insert|db\.|database', satir, re.IGNORECASE):
                            self.bulgular.append(Bulgu(
                                id=self._bulgu_id_uret("ETIC"),
                                seviye="kritik",
                                kategori="pci_dss",
                                baslik=f"PCI-DSS İhlali: {aciklama}",
                                dosya=str(dosya),
                                satir=satir_no,
                                aciklama="Kart bilgisi doğrudan saklanıyor olabilir. PCI-DSS'e göre kart verisi sunucuda saklanmamalıdır.",
                                mevzuat=["PCI-DSS v4.0", "BDDK Ödeme Hizmetleri Yönetmeliği"],
                                duzeltme="Kart bilgilerini asla kendi sunucunuzda saklamayın. Stripe/iyzico gibi PCI uyumlu ödeme sağlayıcısı kullanın.",
                                oncelik=1,
                            ))

    async def _ssl_kontrol(self, dosyalar):
        """HTTP (güvensiz) URL kullanımı tespiti"""
        pattern = re.compile(r'http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)')

        for dosya in dosyalar:
            if dosya.suffix in {".json", ".yaml", ".yml", ".toml", ".cfg", ".env"}:
                continue  # Config dosyalarını atla (dev ortamı olabilir)

            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            eslesme = await self._icerik_ara(dosya, pattern, icerik)
            for satir_no, satir, _ in eslesme[:2]:
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("ETIC"),
                    seviye="yuksek",
                    kategori="ssl",
                    baslik="Güvensiz HTTP Bağlantısı",
                    dosya=str(dosya),
                    satir=satir_no,
                    aciklama="HTTP (şifresiz) bağlantı kullanılıyor. E-ticaret sitelerinde HTTPS zorunludur.",
                    mevzuat=["PCI-DSS Req.4.1", "6563 sayılı E-Ticaret Kanunu"],
                    duzeltme="Tüm URL'leri https:// olarak güncelleyin. SSL sertifikası kullanın.",
                    oncelik=3,
                ))

    async def _fatura_kontrol(self, dosyalar):
        """Fatura/sipariş onayı e-posta mekanizması kontrolü"""
        fatura_desenleri = [
            r'invoice|fatura|receipt|makbuz|order[-_]?confirm|sipariş[-_]?onay',
        ]
        birlesik = "|".join(fatura_desenleri)
        pattern = re.compile(birlesik, re.IGNORECASE)

        bulundu = False
        for dosya in dosyalar[:50]:
            icerik = await self._dosya_oku(dosya)
            if icerik and pattern.search(icerik):
                bulundu = True
                break

        if not bulundu:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("ETIC"),
                seviye="orta",
                kategori="eticaret",
                baslik="Fatura/Sipariş Onay Mekanizması Bulunamadı",
                dosya=str(self.proje_dizini),
                satir=0,
                aciklama="Satış sonrası fatura veya sipariş onay e-postası mekanizması tespit edilemedi.",
                mevzuat=["213 sayılı VUK md.229-232", "6502 sayılı TKHK"],
                duzeltme="Satın alma sonrası otomatik fatura/sipariş onayı e-postası gönderimi ekleyin.",
                oncelik=4,
            ))
