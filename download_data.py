"""下載 Rebas Open Data（2024–2026 例行賽）與 ldkrsi 守備資料到 data/，並整理 2026 守位。

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
    # 2024、2025 沿用 v5 訓練用的 v0.1.0；2026 為 v0.1.1（含逐打席守備陣容 fielderNames）
    "2026": "https://github.com/rebas-tw/rebas.tw-open-data/releases/download/v0.1.1-2026/CPBL-2026-OpenData.zip",
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
    export_fielding_2026()
    print("完成。2025 守位資料（data/cpbl/positions_2025.csv）已隨 repo 提供，來源見「資料來源.md」。")


def export_fielding_2026():
    """由 2026 逐打席守備陣容整理守位出賽場數（網站 2026 批次的守位判斷使用）。"""
    import csv
    import sys
    from pathlib import Path
    sys.path[:0] = [os.path.join(ROOT, "scripts"), os.path.join(ROOT, "src")]
    from export_observed_fielding import collect
    rows, counts = collect(Path(ROOT, "data", "rebas", "2026"), 2026)
    out = Path(ROOT, "data", "rebas-fielding")
    out.mkdir(parents=True, exist_ok=True)
    with (out / "positions_2026.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("season", "player_id", "team", "position", "observed_games"))
        writer.writerows((2026, *key, len(games)) for key, games in sorted(rows.items()))
    print(f"  2026 守位：{counts['games']} 場、{counts['rows']} 筆")


if __name__ == "__main__":
    main()
