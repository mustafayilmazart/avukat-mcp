# Bu modül ticari iletişim, pazarlama ve İYS (İleti Yönetim Sistemi)
# kurallarına uyumu denetler. Newsletter/SMS toplayan formlarda opt-in
# checkbox, unsubscribe linki ve gönderen kimlik bilgisi arar.

import re
from .temel import BaseTarayici, Bulgu


class IletisimTarayici(BaseTarayici):
    """
    Ticari iletişim mevzuatı (6563 sayılı Kanun, İYS Yönetmeliği, CAN-SPAM)
    uyumluluğunu kontrol eden tarayıcı.
    """

    async def tara(self):
        self.bulgular = []
        dosyalar = self._dosyalari_listele()

        # Newsletter/e-posta toplama olup olmadığını önce tespit et
        pazarlama_kullaniliyor = await self._pazarlama_tespit_et(dosyalar)
        if not pazarlama_kullaniliyor:
            return self.bulgular

        await self._opt_in_kontrol(dosyalar)
        await self._unsubscribe_kontrol(dosyalar)
        await self._iys_kaydi_kontrol(dosyalar)
        await self._gonderen_kimligi_kontrol(dosyalar)

        return self.bulgular

    async def _pazarlama_tespit_et(self, dosyalar) -> bool:
        """Projede newsletter/mailing/abone toplama var mı tespit eder"""
        desenler = r'newsletter|bulten|subscribe|abone|mailing[-_]?list|email[-_]?list|smtp|sendgrid|mailchimp|mailgun'
        pattern = re.compile(desenler, re.IGNORECASE)

        for dosya in dosyalar[:80]:
            icerik = await self._dosya_oku(dosya)
            if icerik and pattern.search(icerik):
                return True
        return False

    async def _opt_in_kontrol(self, dosyalar):
        """Newsletter formlarında opt-in (açık onay) checkbox var mı"""
        form_pattern = re.compile(
            r'(?:newsletter|bulten|subscribe|abone)[\s\S]{0,300}</form>',
            re.IGNORECASE,
        )
        checkbox_pattern = re.compile(
            r'type\s*=\s*["\']checkbox["\']|opt[-_]?in|acik[-_]?riza',
            re.IGNORECASE,
        )

        for dosya in dosyalar:
            if dosya.suffix not in {".html", ".tsx", ".jsx", ".vue"}:
                continue

            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            form_eslesmeleri = form_pattern.findall(icerik)
            for form_metni in form_eslesmeleri[:2]:
                if not checkbox_pattern.search(form_metni):
                    # Form içinde opt-in checkbox yok
                    satir_no = icerik[:icerik.find(form_metni[:50])].count("\n") + 1
                    self.bulgular.append(Bulgu(
                        id=self._bulgu_id_uret("ILT"),
                        seviye="kritik",
                        kategori="ticari_iletisim",
                        baslik="Newsletter Formunda Opt-in Checkbox Eksik",
                        dosya=str(dosya),
                        satir=satir_no,
                        aciklama="Ticari e-posta/SMS için alıcının önceden açık onayı (opt-in) gerekir. Formda onay checkbox'ı yok.",
                        mevzuat=[
                            "6563 sayılı Kanun md.6",
                            "Ticari İletişim Yönetmeliği",
                            "CAN-SPAM Act Sec.5",
                            "GDPR Art.7",
                        ],
                        duzeltme="Newsletter formuna 'Ticari e-posta almayı kabul ediyorum' onay kutusu ekleyin. Varsayılan işaretli olmasın.",
                        oncelik=1,
                    ))

    async def _unsubscribe_kontrol(self, dosyalar):
        """E-posta şablonlarında abonelikten çıkma linki var mı"""
        # E-posta HTML şablonları veya mail gönderme kodu
        email_template_gostergeleri = re.compile(
            r'<html|<body|mail_template|email_template|send_mail|send_email|sendMail',
            re.IGNORECASE,
        )
        unsubscribe_pattern = re.compile(
            r'unsubscribe|abonelik[-_]?iptal|abonelikten[-_]?cik|list-unsubscribe',
            re.IGNORECASE,
        )

        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            # E-posta şablonu/göndericisi mi?
            if not email_template_gostergeleri.search(icerik):
                continue

            # Ticari içerik (newsletter, kampanya) göstergesi var mı?
            ticari_icerik = re.search(
                r'newsletter|bulten|kampanya|campaign|promotion|marketing',
                icerik, re.IGNORECASE,
            )
            if not ticari_icerik:
                continue

            if not unsubscribe_pattern.search(icerik):
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("ILT"),
                    seviye="kritik",
                    kategori="unsubscribe",
                    baslik="E-postada Abonelikten Çıkma Linki Eksik",
                    dosya=str(dosya),
                    satir=0,
                    aciklama="Ticari e-postada görünür 'abonelikten çık' linki zorunludur.",
                    mevzuat=[
                        "CAN-SPAM Act Sec.5(a)(3)",
                        "6563 sayılı Kanun md.6",
                        "GDPR Art.7(3)",
                    ],
                    duzeltme="E-posta şablonunun footer'ına tek tıkla abonelikten çıkma linki ekleyin. List-Unsubscribe header'ı da ekleyin.",
                    oncelik=1,
                ))

    async def _iys_kaydi_kontrol(self, dosyalar):
        """İYS (iys.org.tr) entegrasyonu veya referansı var mı"""
        iys_pattern = re.compile(r'iys\.org\.tr|İYS|ileti\s*yonetim', re.IGNORECASE)

        iys_referansi_var = False
        for dosya in dosyalar[:100]:
            icerik = await self._dosya_oku(dosya)
            if icerik and iys_pattern.search(icerik):
                iys_referansi_var = True
                break

        if not iys_referansi_var:
            # Proje Türkiye odaklı mı (Türkçe içerik/tr-TR)
            tr_gostergesi = False
            for dosya in dosyalar[:30]:
                icerik = await self._dosya_oku(dosya)
                if icerik and re.search(r'tr-TR|lang=["\']tr|türkçe|turkce', icerik, re.IGNORECASE):
                    tr_gostergesi = True
                    break

            if tr_gostergesi:
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("ILT"),
                    seviye="yuksek",
                    kategori="iys",
                    baslik="İYS (İleti Yönetim Sistemi) Entegrasyonu Yok",
                    dosya=str(self.proje_dizini),
                    satir=0,
                    aciklama="Türkiye'de ticari elektronik ileti gönderen tüm gerçek/tüzel kişiler İYS'ye kayıtlı olmalıdır.",
                    mevzuat=[
                        "6563 sayılı Kanun md.6",
                        "İYS Yönetmeliği",
                    ],
                    duzeltme="iys.org.tr üzerinden kayıt olun ve her gönderimden önce İYS'den onay sorgusu yapın.",
                    oncelik=2,
                ))

    async def _gonderen_kimligi_kontrol(self, dosyalar):
        """E-posta şablonlarında gönderen kimlik bilgisi (adres, şirket) var mı"""
        kimlik_pattern = re.compile(
            r'address|adres|mersis|\bşirket\b|\bcompany\b|copyright\s*©',
            re.IGNORECASE,
        )

        for dosya in dosyalar:
            if dosya.suffix not in {".html", ".tsx", ".jsx"}:
                continue

            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            # Pazarlama e-postası şablonu mu
            if not re.search(r'newsletter|bulten|kampanya|marketing', icerik, re.IGNORECASE):
                continue

            if not kimlik_pattern.search(icerik):
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("ILT"),
                    seviye="orta",
                    kategori="gonderen_kimligi",
                    baslik="E-postada Gönderen Kimlik Bilgileri Eksik",
                    dosya=str(dosya),
                    satir=0,
                    aciklama="Ticari e-postalarda gönderenin açık kimliği (şirket adı, fiziksel adres) bulunmalıdır.",
                    mevzuat=[
                        "CAN-SPAM Act Sec.5(a)(1)",
                        "6563 sayılı Kanun md.5",
                    ],
                    duzeltme="E-posta footer'ına şirket adı, MERSİS no, fiziksel adres ve iletişim bilgisi ekleyin.",
                    oncelik=4,
                ))
