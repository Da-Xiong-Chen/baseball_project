"""Export season-specific search aliases from attributed Rebas box scores."""
import json
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def build(folder):
    rows=defaultdict(lambda: {"numbers":set(), "ids":set()})
    files=sorted(folder.glob("*.json"))
    if not files: raise ValueError("No 2025 game files")
    for path in files:
        game=json.loads(path.read_text(encoding="utf-8"))
        if not str(game["date"]).startswith("2025-"): raise ValueError("Non-2025 game")
        for side in ("home","away"):
            for kind in ("Batter","Pitcher"):
                for player in game[side+kind+"Box"]:
                    number=player.get("playerNumber")
                    if not isinstance(number,str) or not number.isascii() or not number.isdigit(): raise ValueError("Invalid or missing number")
                    row=rows[(game[side+"Team"],player["playerName"])]
                    row["numbers"].add(number);row["ids"].add(player["playerId"])
    teams={};excluded=[]
    for (team,name),row in sorted(rows.items()):
        if len(row["ids"])!=1 or len(row["numbers"])!=1:
            excluded.append({"team":team,"name":name,"reason":"ambiguous identity or changed number"});continue
        teams.setdefault(team,{})[name]=next(iter(row["numbers"]))
    return {"season":2025,"source":"Rebas Sports 2025 regular-season Open Data","source_url":"https://github.com/rebas-tw/rebas.tw-open-data/releases/download/v0.1.0-2025/CPBL-2025-OpenData.zip","license":"ODC-By v1.0","field":"playerNumber in BatterBox/PitcherBox","games":len(files),"teams":teams,"excluded":excluded}
if __name__=="__main__":
    result=build(ROOT/"data/rebas/2025")
    (ROOT/"docs/data/player-numbers-2025.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Games:",result["games"],"players:",sum(map(len,result["teams"].values())),"excluded:",len(result["excluded"]))
