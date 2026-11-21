# Краткий список утверждений и источников для разбора, что задевает новая выгрузка.
import glob
import json

for line in open("projects/megafon-app/ledger/claims.jsonl", encoding="utf-8"):
    c = json.loads(line)
    print(c["id"], c["type"][:4], c.get("source"), c["status"][:4], c["text"][:110])
print("---")
for p in sorted(glob.glob("projects/megafon-app/sources/*.meta.json")):
    d = json.load(open(p, encoding="utf-8"))
    print(p.split("/")[-1][:4], str(d.get("title") or d.get("file") or d)[:80], "|", d.get("kind", ""))
