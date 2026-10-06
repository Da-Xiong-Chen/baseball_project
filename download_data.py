"""下載 Rebas Open Data（2024、2025 例行賽）與 ldkrsi 守備資料到 data/。

用法：python download_data.py
"""
import io
import os
import re
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
REBAS = {
    "2024": "https://github.com/rebas-tw/rebas.tw-open-data/releases/download/v0.1.0-2024/CPBL-2024-OpenData.zip",
    "2025": "https://github.com/rebas-tw/rebas.tw-open-data/releases/download/v0.1.0-2025/CPBL-2025-OpenData.zip",
}
LDKRSI = "https://raw.githubusercontent.com/ldkrsi/cpbl-opendata/master/"


def fetch(url):
    print("下載", url)
    with urllib.request.urlopen(url) as r:
        return r.read()


def main():
    for year, url in REBAS.items():
        out = os.path.join(ROOT, "data", "rebas", year)
        os.makedirs(out, exist_ok=True)
        z = zipfile.ZipFile(io.BytesIO(fetch(url)))
        n = 0
        for name in z.namelist():
            base = os.path.basename(name)
            if re.search(r"-G\d+\.json$", base):  # 只取逐場檔，不取合併檔
                with open(os.path.join(out, base), "wb") as f:
                    f.write(z.read(name))
                n += 1
        print(f"  {year}：{n} 場")

    out = os.path.join(ROOT, "data", "ldkrsi")
    os.makedirs(out, exist_ok=True)
    for y in (2022, 2023, 2024):
        open(os.path.join(out, f"fieldings_{y}.csv"), "wb").write(fetch(f"{LDKRSI}CPBL/fieldings/{y}.csv"))
    open(os.path.join(out, "LICENSE"), "wb").write(fetch(LDKRSI + "LICENSE"))
    print("完成。2025 守位資料（data/cpbl/positions_2025.csv）已隨 repo 提供，來源見「資料來源.md」。")


if __name__ == "__main__":
    main()
