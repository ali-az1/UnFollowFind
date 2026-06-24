import json
def Username():
    with open("auth.json", "r") as f:
        a = json.load(f)

    ls = a["origins"][0]["localStorage"]
    raw = next(item["value"] for item in ls if item["name"] == "one_tap_storage_version")

    onetap = json.loads(raw)

    for uid, info in onetap.items():
        return info["username"]
