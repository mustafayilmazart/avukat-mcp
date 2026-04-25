# Bu modül güvenlik açıklarını tarar: hardcoded sırlar, SQL injection,
# XSS riskleri, CORS ayarları, .env dosyası güvenliği vb.

import re
from .temel import BaseTarayici, Bulgu


class GuvenlikTarayici(BaseTarayici):
    """Güvenlik açıklarını tespit eden tarayıcı"""

    async def tara(self):
        self.bulgular = []
        dosyalar = self._dosyalari_listele()

        await self._env_guvenlik_kontrol()
        await self._gitignore_kontrol()
        await self._hardcoded_secret_kontrol(dosyalar)
        await self._sql_injection_kontrol(dosyalar)
        await self._xss_kontrol(dosyalar)
        await self._cors_kontrol(dosyalar)

        return self.bulgular

    async def _env_guvenlik_kontrol(self):
        """.env dosyasında açık metin sır (API key, şifre) tespiti"""
        env_dosyalar = [
            self._dosya_var_mi(".env"),
            self._dosya_var_mi(".env.local"),
            self._dosya_var_mi(".env.production"),
        ]

        hassas_desenler = [
            (r'(?:API[-_]?KEY|SECRET[-_]?KEY|PASSWORD|PRIVATE[-_]?KEY|TOKEN)\s*=\s*["\']?[A-Za-z0-9+/=_-]{8,}', "API anahtarı veya şifre"),
            (r'(?:DB[-_]?PASSWORD|DATABASE[-_]?URL.*password|MONGO[-_]?URI)\s*=\s*.+', "Veritabanı şifresi"),
            (r'(?:AWS[-_]?SECRET|STRIPE[-_]?SECRET|IYZICO[-_]?SECRET)\s*=\s*.+', "Ödeme/bulut sırrı"),
        ]

        for env_dosya in env_dosyalar:
            if not env_dosya:
                continue
            icerik = await self._dosya_oku(env_dosya)
            if not icerik:
                continue

            for desen, aciklama in hassas_desenler:
                pattern = re.compile(desen, re.IGNORECASE)
                eslesme = await self._icerik_ara(env_dosya, pattern, icerik)
                for satir_no, satir, _ in eslesme[:1]:
                    self.bulgular.append(Bulgu(
                        id=self._bulgu_id_uret("GUV"),
                        seviye="kritik",
                        kategori="guvenlik",
                        baslik=f"Hassas Bilgi: {aciklama}",
                        dosya=str(env_dosya),
                        satir=satir_no,
                        aciklama=f".env dosyasında {aciklama} tespit edildi. Git'e commitlenmediğinden emin olun.",
                        mevzuat=["OWASP A02:2021 - Cryptographic Failures", "PCI-DSS Req.6.5"],
                        duzeltme=".env dosyasının .gitignore'da olduğundan emin olun. Sırları ortam değişkeni veya secret manager ile yönetin.",
                        oncelik=1,
                    ))

    async def _gitignore_kontrol(self):
        """.gitignore'da .env dosyasının olup olmadığını kontrol eder"""
        gitignore = self._dosya_var_mi(".gitignore")
        env_var = self._dosya_var_mi(".env")

        if env_var and not gitignore:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("GUV"),
                seviye="kritik",
                kategori="guvenlik",
                baslik=".gitignore Dosyası Eksik",
                dosya=str(self.proje_dizini),
                satir=0,
                aciklama=".env dosyası var ama .gitignore yok. Sırlar Git'e commitlenebilir.",
                mevzuat=["OWASP A02:2021"],
                duzeltme=".gitignore dosyası oluşturun ve .env, .env.local gibi dosyaları ekleyin.",
                oncelik=1,
            ))
        elif env_var and gitignore:
            icerik = await self._dosya_oku(gitignore)
            if icerik and not re.search(r'^\.env', icerik, re.MULTILINE):
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("GUV"),
                    seviye="kritik",
                    kategori="guvenlik",
                    baslik=".env .gitignore'da Değil",
                    dosya=str(gitignore),
                    satir=0,
                    aciklama=".env dosyası .gitignore'a eklenmemiş. Sırlar repo'ya sızabilir.",
                    mevzuat=["OWASP A02:2021"],
                    duzeltme=".gitignore'a .env satırını ekleyin.",
                    oncelik=1,
                ))

    async def _hardcoded_secret_kontrol(self, dosyalar):
        """Kaynak kodda hardcoded API key, şifre vb. tespiti"""
        desenler = [
            (r'(?:api[-_]?key|secret|password|token)\s*[:=]\s*["\'][A-Za-z0-9+/=_-]{16,}["\']', "Hardcoded sır/anahtar"),
            (r'sk[-_](?:live|test)[-_][A-Za-z0-9]{20,}', "Stripe Secret Key"),
            (r'AIza[A-Za-z0-9_-]{35}', "Google API Key"),
            (r'ghp_[A-Za-z0-9]{36}', "GitHub Personal Access Token"),
        ]

        for dosya in dosyalar:
            if dosya.suffix == ".env" or dosya.name in {".env.local", ".env.example"}:
                continue  # .env dosyaları ayrıca kontrol ediliyor

            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            for desen, aciklama in desenler:
                pattern = re.compile(desen, re.IGNORECASE)
                eslesme = await self._icerik_ara(dosya, pattern, icerik)
                for satir_no, satir, _ in eslesme[:1]:
                    # Yorum satırı veya örnek değilse
                    if re.match(r'\s*(?:#|//|/\*|\*|<!--)', satir):
                        continue
                    if re.search(r'example|ornek|placeholder|xxx|your[-_]', satir, re.IGNORECASE):
                        continue

                    self.bulgular.append(Bulgu(
                        id=self._bulgu_id_uret("GUV"),
                        seviye="kritik",
                        kategori="guvenlik",
                        baslik=f"Kaynak Kodda {aciklama}",
                        dosya=str(dosya),
                        satir=satir_no,
                        aciklama=f"Kaynak kodda {aciklama} tespit edildi. Bu değer Git geçmişinde kalıcı olarak saklanır.",
                        mevzuat=["OWASP A02:2021", "CWE-798"],
                        duzeltme="Sırrı kaynak koddan kaldırın, .env veya secret manager'a taşıyın. Git geçmişinden temizlemek için git-filter-repo kullanın.",
                        oncelik=1,
                    ))

    async def _sql_injection_kontrol(self, dosyalar):
        """SQL injection riski tespiti — ham SQL sorgusu kullanımı"""
        desenler = [
            (r'f["\']SELECT\s|f["\']INSERT\s|f["\']UPDATE\s|f["\']DELETE\s', "Python f-string SQL"),
            (r'`SELECT\s.*\$\{|`INSERT\s.*\$\{|`UPDATE\s.*\$\{', "JS template literal SQL"),
            (r'\.execute\(\s*f["\']|\.execute\(\s*["\'].*%s.*%', "Parametresiz execute"),
            (r'\.raw\(|\.rawQuery\(|cursor\.execute\(.+\+', "Raw SQL sorgusu"),
        ]

        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            for desen, aciklama in desenler:
                pattern = re.compile(desen, re.IGNORECASE)
                eslesme = await self._icerik_ara(dosya, pattern, icerik)
                for satir_no, satir, _ in eslesme[:2]:
                    self.bulgular.append(Bulgu(
                        id=self._bulgu_id_uret("GUV"),
                        seviye="kritik",
                        kategori="sql_injection",
                        baslik=f"SQL Injection Riski: {aciklama}",
                        dosya=str(dosya),
                        satir=satir_no,
                        aciklama="Parametreleştirilmemiş SQL sorgusu tespit edildi. SQL injection saldırısına açık.",
                        mevzuat=["OWASP A03:2021 - Injection", "CWE-89", "6698 sayılı KVKK md.12"],
                        duzeltme="Parametreli sorgular (prepared statements) kullanın. ORM tercih edin.",
                        oncelik=1,
                    ))

    async def _xss_kontrol(self, dosyalar):
        """XSS (Cross-Site Scripting) riski tespiti"""
        desenler = [
            (r'innerHTML\s*=', "innerHTML ataması"),
            (r'dangerouslySetInnerHTML', "React dangerouslySetInnerHTML"),
            (r'\|\s*safe\b', "Django/Jinja safe filtresi"),
            (r'v-html\s*=', "Vue v-html direktifi"),
            (r'document\.write\(', "document.write kullanımı"),
        ]

        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            for desen, aciklama in desenler:
                pattern = re.compile(desen, re.IGNORECASE)
                eslesme = await self._icerik_ara(dosya, pattern, icerik)
                for satir_no, satir, _ in eslesme[:2]:
                    self.bulgular.append(Bulgu(
                        id=self._bulgu_id_uret("GUV"),
                        seviye="yuksek",
                        kategori="xss",
                        baslik=f"XSS Riski: {aciklama}",
                        dosya=str(dosya),
                        satir=satir_no,
                        aciklama=f"{aciklama} tespit edildi. Kullanıcı girdisi render ediliyorsa XSS saldırısına açık.",
                        mevzuat=["OWASP A03:2021 - Injection", "CWE-79"],
                        duzeltme="Kullanıcı girdisini sanitize edin. innerHTML yerine textContent, dangerouslySetInnerHTML yerine DOMPurify kullanın.",
                        oncelik=2,
                    ))

    async def _cors_kontrol(self, dosyalar):
        """CORS konfigürasyonu kontrolü — '*' ile açık CORS tehlikeli"""
        pattern = re.compile(r'(?:cors|Access-Control-Allow-Origin)\s*[:=(\[]\s*["\']?\*["\']?', re.IGNORECASE)

        for dosya in dosyalar:
            icerik = await self._dosya_oku(dosya)
            if not icerik:
                continue

            eslesme = await self._icerik_ara(dosya, pattern, icerik)
            for satir_no, satir, _ in eslesme[:1]:
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("GUV"),
                    seviye="yuksek",
                    kategori="cors",
                    baslik="CORS Tüm Kaynaklara Açık (*)",
                    dosya=str(dosya),
                    satir=satir_no,
                    aciklama="CORS politikası '*' ile tüm kaynaklara açık. Hassas API'lerde güvenlik riski.",
                    mevzuat=["OWASP A05:2021 - Security Misconfiguration", "CWE-942"],
                    duzeltme="CORS'u sadece güvenilen domain'lerle sınırlandırın: ['https://yourdomain.com']",
                    oncelik=3,
                ))
