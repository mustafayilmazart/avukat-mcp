# Bu modül çocukların kişisel verilerinin korunması mevzuatı (COPPA,
# GDPR md.8, KVKK md.6) kapsamında yaş doğrulama ve ebeveyn onayı
# mekanizmalarını denetler.

import re
from .temel import BaseTarayici, Bulgu


class CocukTarayici(BaseTarayici):
    """
    Çocuk verisi koruma kurallarını denetleyen tarayıcı.
    13 yaş altı kullanıcıya yönelik platformlarda ek yükümlülükler kontrol edilir.
    """

    async def tara(self):
        self.bulgular = []
        dosyalar = self._dosyalari_listele()

        # Çocuk odaklı platform mu, kullanıcı yaş bilgisi topluyor mu tespit et
        cocuk_platformu = await self._cocuk_platformu_mu(dosyalar)
        yas_topluyor = await self._yas_verisi_topluyor_mu(dosyalar)

        if not (cocuk_platformu or yas_topluyor):
            return self.bulgular

        await self._yas_dogrulama_kontrol(dosyalar, yas_topluyor)
        await self._ebeveyn_onayi_kontrol(dosyalar, cocuk_platformu)
        await self._reklam_kisitlama_kontrol(dosyalar, cocuk_platformu)
        await self._gizlilik_cocuk_bolumu_kontrol(dosyalar, cocuk_platformu)

        return self.bulgular

    async def _cocuk_platformu_mu(self, dosyalar) -> bool:
        """Projenin çocuklara yönelik olup olmadığını tahmin eder"""
        pattern = re.compile(
            r'\bkids?\b|\bchildren\b|\bcocuk(?:lar)?\b|\bmontessori\b|'
            r'\bpreschool\b|\banaokul|\bilkokul\b|\bnursery\b|\bokul[-_]?oncesi\b',
            re.IGNORECASE,
        )
        for dosya in dosyalar[:60]:
            icerik = await self._dosya_oku(dosya)
            if icerik and pattern.search(icerik):
                return True

        pkg = self._dosya_var_mi("package.json")
        if pkg:
            icerik = await self._dosya_oku(pkg)
            if icerik and re.search(r'"kids?"|"children"|"education"', icerik, re.IGNORECASE):
                return True
        return False

    async def _yas_verisi_topluyor_mu(self, dosyalar) -> bool:
        """Formlarda yaş/doğum tarihi alanı var mı tespit eder"""
        pattern = re.compile(
            r'name\s*=\s*["\'](?:age|yas|birth|dogum|dob|birthday)["\']|'
            r'type\s*=\s*["\']date["\']',
            re.IGNORECASE,
        )
        for dosya in dosyalar[:80]:
            if dosya.suffix not in {".html", ".tsx", ".jsx", ".vue"}:
                continue
            icerik = await self._dosya_oku(dosya)
            if icerik and pattern.search(icerik):
                return True
        return False

    async def _yas_dogrulama_kontrol(self, dosyalar, yas_topluyor):
        """Yaş doğrulama / 13 yaş kontrol mantığı var mı"""
        if not yas_topluyor:
            return

        pattern = re.compile(
            r'age[-_]?(?:gate|verification|check)|yas[-_]?(?:dogrulama|kontrol)|'
            r'\bage\s*[<>=]\s*(?:13|18)|minor[-_]?check',
            re.IGNORECASE,
        )

        bulundu = False
        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if icerik and pattern.search(icerik):
                bulundu = True
                break

        if not bulundu:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("COC"),
                seviye="kritik",
                kategori="cocuk_koruma",
                baslik="Yaş Doğrulama Mekanizması Eksik",
                dosya=str(self.proje_dizini),
                satir=0,
                aciklama="Proje yaş bilgisi topluyor ama yaş doğrulama veya 13 yaş kontrolü tespit edilemedi.",
                mevzuat=[
                    "COPPA 16 CFR 312.5",
                    "GDPR md.8",
                    "6698 sayılı KVKK md.6",
                ],
                duzeltme="Kayıt sırasında yaş doğrulama ekleyin. 13 yaş altı için kayıt bloklayın veya ebeveyn onay akışına yönlendirin.",
                oncelik=1,
            ))

    async def _ebeveyn_onayi_kontrol(self, dosyalar, cocuk_platformu):
        """Ebeveyn onayı (parental consent) mekanizması var mı"""
        if not cocuk_platformu:
            return

        pattern = re.compile(
            r'parent(?:al)?[-_]?consent|ebeveyn[-_]?onay|guardian[-_]?approval|'
            r'veli[-_]?(?:onay|izin)',
            re.IGNORECASE,
        )

        bulundu = False
        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if icerik and pattern.search(icerik):
                bulundu = True
                break

        if not bulundu:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("COC"),
                seviye="kritik",
                kategori="ebeveyn_onayi",
                baslik="Ebeveyn Onay Mekanizması Eksik",
                dosya=str(self.proje_dizini),
                satir=0,
                aciklama="Çocuk platformunda 13 yaş altı kullanıcılar için doğrulanabilir ebeveyn onayı gereklidir.",
                mevzuat=[
                    "COPPA 16 CFR 312.5",
                    "GDPR md.8(1)",
                    "5395 sayılı Çocuk Koruma Kanunu",
                ],
                duzeltme="Ebeveyn e-postasına onay linki gönderme, kredi kartı doğrulama veya kimlik doğrulama ile ebeveyn onay akışı kurun.",
                oncelik=1,
            ))

    async def _reklam_kisitlama_kontrol(self, dosyalar, cocuk_platformu):
        """Çocuk platformunda davranışsal reklam/tracking var mı"""
        if not cocuk_platformu:
            return

        tracking_pattern = re.compile(
            r'google[-_]?ads|adsense|facebook[-_]?pixel|doubleclick|amplitude|'
            r'mixpanel|behavioral[-_]?advertising',
            re.IGNORECASE,
        )

        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue
            if tracking_pattern.search(icerik):
                eslesme = tracking_pattern.search(icerik)
                satir_no = icerik[:eslesme.start()].count("\n") + 1
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("COC"),
                    seviye="yuksek",
                    kategori="cocuk_reklam",
                    baslik="Çocuk Platformunda Davranışsal Reklam/Tracking",
                    dosya=str(dosya),
                    satir=satir_no,
                    aciklama="13 yaş altına yönelik platformlarda davranışsal reklam ve izleme yasaktır.",
                    mevzuat=[
                        "COPPA 16 CFR 312.5(c)",
                        "GDPR md.8 + Recital 38",
                    ],
                    duzeltme="Çocuklara yönelik sayfalarda kişiselleştirilmiş reklamları kapatın. Kontekst bazlı (non-behavioral) reklam kullanın.",
                    oncelik=2,
                ))
                break  # Her dosya için tek bulgu yeter

    async def _gizlilik_cocuk_bolumu_kontrol(self, dosyalar, cocuk_platformu):
        """Gizlilik politikasında çocuklarla ilgili özel bölüm var mı"""
        if not cocuk_platformu:
            return

        gizlilik_dosya = None
        for dosya in dosyalar:
            if any(k in dosya.name.lower() for k in ["privacy", "gizlilik", "kvkk"]):
                gizlilik_dosya = dosya
                break
        if not gizlilik_dosya:
            return

        icerik = await self._dosya_oku(gizlilik_dosya)
        if not icerik:
            return

        if not re.search(r'child|çocuk|cocuk|minor|coppa|13 yaş', icerik, re.IGNORECASE):
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("COC"),
                seviye="orta",
                kategori="gizlilik_cocuk",
                baslik="Gizlilik Politikasında Çocuk Bölümü Yok",
                dosya=str(gizlilik_dosya),
                satir=0,
                aciklama="Çocuklara yönelik platform olmasına rağmen gizlilik politikasında çocuk verilerine özel bölüm yok.",
                mevzuat=["COPPA 16 CFR 312.4", "GDPR md.12"],
                duzeltme="Gizlilik politikasına çocuk kullanıcılar için özel bölüm ekleyin: hangi veriler, ebeveyn hakları, başvuru yolu.",
                oncelik=3,
            ))
