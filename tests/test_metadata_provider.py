from __future__ import annotations

from nyaarr import metadata


def test_anilist_display_title_prefers_part_alias_over_cour_english() -> None:
    item = {
        "id": 123,
        "idMal": 456,
        "title": {
            "english": "Dr. STONE SCIENCE FUTURE Cour 3",
            "romaji": "Dr. Stone: Science Future Part 3",
            "native": "Dr.STONE SCIENCE FUTURE ?3???",
        },
        "synonyms": ["Dr. STONE SCIENCE FUTURE Cour 3"],
        "seasonYear": 2026,
        "status": "RELEASING",
        "episodes": 12,
        "duration": 24,
        "averageScore": 80,
        "genres": ["Adventure"],
        "coverImage": {"large": ""},
        "studios": {"nodes": [{"name": "TMS Entertainment"}]},
    }

    result = metadata._map_anilist_item(item)

    assert result["title"] == "Dr. Stone: Science Future Part 3"
    assert result["original_title"] == "Dr. Stone: Science Future Part 3"
    assert result["season_number"] == 3
    assert "Dr. STONE SCIENCE FUTURE Cour 3" in result["aliases"]
    assert result["provider_title"]["english"] == "Dr. STONE SCIENCE FUTURE Cour 3"


def test_anilist_display_title_keeps_english_without_cour_part_conflict() -> None:
    item = {
        "title": {
            "english": "Petals of Reincarnation",
            "romaji": "Reincarnation no Kaben",
            "native": "",
        },
        "synonyms": [],
        "studios": {"nodes": []},
    }

    result = metadata._map_anilist_item(item)

    assert result["title"] == "Petals of Reincarnation"
    assert result["original_title"] == "Reincarnation no Kaben"