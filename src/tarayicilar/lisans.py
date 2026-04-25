# Bu modül yazılım lisans uyumluluğunu ve telif haklarını kontrol eder.
# LICENSE dosyası, bağımlılık lisansları ve GPL bulaşıcılığı gibi konuları tarar.

import re
import json
from .temel import BaseTarayici, Bulgu


# GPL ailesindeki lisanslar — bulaşıcı (copyleft) olduğundan dikkat gerektirir
GPL_LISANSLAR = {"gpl", "gpl-2.0", "gpl-3.0", "agpl", "agpl-3.0", "lgpl", "lgpl-2.1", "lgpl-3.0"}

# Ticari projelerle uyumsuz olabilecek lisanslar
RISKLI_LISANSLAR = GPL_LISANSLAR | {"sspl", "bsl", "elastic", "commons-clause"}


class LisansTarayici(BaseTarayici):
    """Lisans ve telif hakkı kontrolü yapan tarayıcı"""

    async def tara(self):
        self.bulgular = []

        await self._license_dosyasi_kontrol()
        await self._package_json_lisans_kontrol()
        await self._requirements_lisans_kontrol()
        await self._telif_header_kontrol()

        return self.bulgular

    async def _license_dosyasi_kontrol(self):
        """Proje kökünde LICENSE dosyası var mı kontrol eder"""
        sonuc = self._dosya_var_mi(
            "LICENSE", "LICENSE.md", "LICENSE.txt",
            "LICENCE", "LICENCE.md", "LICENCE.txt",
            "COPYING", "COPYING.md",
        )
        if not sonuc:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("LIS"),
                seviye="yuksek",
                kategori="lisans",
                baslik="LICENSE Dosyası Eksik",
                dosya=str(self.proje_dizini),
                satir=0,
                aciklama="Projede lisans dosyası bulunamadı. Yazılımın kullanım koşulları belirsiz.",
                mevzuat=["5846 sayılı FSEK", "DMCA", "Bern Sözleşmesi"],
                duzeltme="Proje köküne LICENSE dosyası ekleyin. Açık kaynak ise MIT/Apache-2.0, kapalı kaynak ise 'All Rights Reserved' ifadesi kullanın.",
                oncelik=3,
            ))

    async def _package_json_lisans_kontrol(self):
        """package.json'daki license alanını ve bağımlılık lisanslarını kontrol eder"""
        pkg = self._dosya_var_mi("package.json")
        if not pkg:
            return

        icerik = await self._dosya_oku(pkg)
        if not icerik:
            return

        try:
            data = json.loads(icerik)
        except json.JSONDecodeError:
            return

        # License alanı var mı
        lisans = data.get("license", "")
        if not lisans:
            self.bulgular.append(Bulgu(
                id=self._bulgu_id_uret("LIS"),
                seviye="orta",
                kategori="lisans",
                baslik="package.json'da license Alanı Eksik",
                dosya=str(pkg),
                satir=0,
                aciklama="package.json dosyasında license alanı belirtilmemiş.",
                mevzuat=["npm paket yönetici gereklilikleri"],
                duzeltme='package.json\'a "license": "MIT" veya uygun lisans ekleyin.',
                oncelik=5,
            ))

        # Bağımlılıklarda GPL riski
        tum_bagimliliklar = {}
        tum_bagimliliklar.update(data.get("dependencies", {}))
        tum_bagimliliklar.update(data.get("devDependencies", {}))

        # Not: Gerçek lisans kontrolü için node_modules taranması gerekir
        # Burada sadece bilinen riskli paketleri işaretleriz
        pkg_lock = self._dosya_var_mi("package-lock.json")
        if pkg_lock:
            lock_icerik = await self._dosya_oku(pkg_lock)
            if lock_icerik:
                for riskli in RISKLI_LISANSLAR:
                    pattern = re.compile(rf'"license"\s*:\s*"{riskli}"', re.IGNORECASE)
                    eslesme = await self._icerik_ara(pkg_lock, pattern, lock_icerik)
                    if eslesme:
                        self.bulgular.append(Bulgu(
                            id=self._bulgu_id_uret("LIS"),
                            seviye="kritik" if riskli in GPL_LISANSLAR else "yuksek",
                            kategori="lisans_uyumluluk",
                            baslik=f"Riskli Lisanslı Bağımlılık: {riskli.upper()}",
                            dosya=str(pkg_lock),
                            satir=eslesme[0][0] if eslesme else 0,
                            aciklama=f"{riskli.upper()} lisanslı bağımlılık tespit edildi. Ticari projeler için uyumluluk riski.",
                            mevzuat=["GPL Lisans Koşulları", "5846 sayılı FSEK md.22"],
                            duzeltme=f"{riskli.upper()} lisanslı paketi alternatif MIT/Apache lisanslı bir paketle değiştirin veya lisans uyumluluğunu hukuki danışmanla kontrol edin.",
                            oncelik=2,
                        ))

    async def _requirements_lisans_kontrol(self):
        """Python requirements.txt veya pyproject.toml lisans kontrolü"""
        pyproject = self._dosya_var_mi("pyproject.toml")
        if pyproject:
            icerik = await self._dosya_oku(pyproject)
            if icerik and not re.search(r'license\s*=', icerik, re.IGNORECASE):
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("LIS"),
                    seviye="orta",
                    kategori="lisans",
                    baslik="pyproject.toml'da Lisans Bilgisi Eksik",
                    dosya=str(pyproject),
                    satir=0,
                    aciklama="Python projesinde lisans bilgisi belirtilmemiş.",
                    mevzuat=["PyPI paket gereklilikleri"],
                    duzeltme='pyproject.toml\'a license = {text = "MIT"} veya uygun lisans ekleyin.',
                    oncelik=5,
                ))

    async def _telif_header_kontrol(self):
        """Kaynak dosyalarda telif (copyright) başlığı kontrolü — sadece bilgi seviyesinde"""
        # Bu sadece büyük/kurumsal projeler için önerilir, bilgi seviyesinde
        kaynak_dosyalar = [d for d in self._dosyalari_listele() if d.suffix in {".py", ".js", ".ts"}]

        if len(kaynak_dosyalar) > 10:
            telif_var = 0
            for dosya in kaynak_dosyalar[:20]:
                icerik = await self._dosya_oku(dosya)
                if icerik and re.search(r'copyright|©|telif|SPDX-License-Identifier', icerik[:500], re.IGNORECASE):
                    telif_var += 1

            if telif_var == 0:
                self.bulgular.append(Bulgu(
                    id=self._bulgu_id_uret("LIS"),
                    seviye="bilgi",
                    kategori="telif",
                    baslik="Kaynak Dosyalarda Telif Başlığı Yok",
                    dosya=str(self.proje_dizini),
                    satir=0,
                    aciklama="Kaynak dosyaların başında telif (copyright) bildirimi yok. Büyük projeler için önerilir.",
                    mevzuat=["5846 sayılı FSEK md.14"],
                    duzeltme="Kaynak dosyaların başına '# Copyright (c) 2026 Şirket Adı. All rights reserved.' ekleyin.",
                    oncelik=8,
                ))
