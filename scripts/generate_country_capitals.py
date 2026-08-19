"""Regenerate the bundled country/capital lookup from public datasets."""

from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from pathlib import Path


COUNTRIES_URL = (
    "https://raw.githubusercontent.com/mledoze/countries/master/countries.json"
)
GEONAMES_URL = "https://download.geonames.org/export/dump/cities500.zip"
TARGET = (
    Path(__file__).parents[1]
    / "src"
    / "mewcode"
    / "wechat"
    / "info"
    / "country_capitals.json"
)
EXTRA_ALIASES = {
    "CN": ["中国"],
    "GB": ["英国", "UK"],
    "US": ["美国", "美利坚", "America", "United States of America", "USA"],
}


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "MewCode-data/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def _capital_cities(raw_zip: bytes) -> dict[str, list[dict[str, object]]]:
    by_country: dict[str, list[dict[str, object]]] = {}
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as source:
            for raw_line in source:
                parts = raw_line.decode("utf-8").rstrip("\n").split("\t")
                if len(parts) < 15 or parts[6] != "P":
                    continue
                feature = parts[7]
                if not (feature.startswith("PPLC") or feature == "PPLA"):
                    continue
                by_country.setdefault(parts[8], []).append(
                    {
                        "name": parts[1],
                        "ascii": parts[2],
                        "alternatives": parts[3].split(","),
                        "latitude": float(parts[4]),
                        "longitude": float(parts[5]),
                        "feature": feature,
                        "population": int(parts[14] or 0),
                    }
                )
    return by_country


def _pick_capital(
    capital: str, candidates: list[dict[str, object]]
) -> dict[str, object] | None:
    exact = [
        item
        for item in candidates
        if capital
        in {
            str(item["name"]),
            str(item["ascii"]),
            *(str(value) for value in item["alternatives"]),
        }
    ]
    pool = exact or [
        item for item in candidates if str(item["feature"]).startswith("PPLC")
    ]
    if not pool:
        return None
    return max(
        pool,
        key=lambda item: (
            str(item["feature"]).startswith("PPLC"),
            int(item["population"]),
        ),
    )


def main() -> None:
    countries = json.loads(_download(COUNTRIES_URL))
    cities = _capital_cities(_download(GEONAMES_URL))
    rows: list[dict[str, object]] = []
    for country in countries:
        code = country.get("cca2", "")
        capitals = country.get("capital") or []
        if not code or not capitals:
            continue
        capital = str(capitals[0])
        match = _pick_capital(capital, cities.get(code, []))
        if match is None:
            continue
        names = [
            country.get("translations", {}).get("zho", {}).get("common"),
            country.get("name", {}).get("common"),
            country.get("name", {}).get("official"),
            country.get("cca2"),
            country.get("cca3"),
            country.get("ccn3"),
            country.get("cioc"),
            *country.get("altSpellings", []),
            *EXTRA_ALIASES.get(code, []),
        ]
        rows.append(
            {
                "code": code,
                "names": list(dict.fromkeys(str(value) for value in names if value)),
                "capital": capital,
                "latitude": match["latitude"],
                "longitude": match["longitude"],
            }
        )
    payload = {
        "sources": [
            "https://github.com/mledoze/countries",
            "https://www.geonames.org/",
        ],
        "countries": sorted(rows, key=lambda item: str(item["code"])),
    }
    TARGET.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(rows)} countries to {TARGET}")


if __name__ == "__main__":
    main()
