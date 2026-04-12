import io

from PIL import Image, ImageDraw

from poker.tools.room_manager import HybridPresetRepository, LocalPresetRepository


def _pattern(fill, accent, size):
    img = Image.new("RGB", size, fill)
    draw = ImageDraw.Draw(img)
    draw.rectangle((1, 1, size[0] - 2, size[1] - 2), outline=accent, width=2)
    draw.line((0, 0, size[0] - 1, size[1] - 1), fill=accent, width=2)
    return img


def _png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _build_table_images(
    top_left_fill,
    call_fill,
    fold_fill,
    dealer_fill,
    covered_fill,
    raise_fill=None,
):
    crop = Image.new("RGB", (1500, 1100), "white")
    assets = {
        "topleft_corner": _pattern(top_left_fill, "black", (24, 24)),
        "call_button": _pattern(call_fill, "black", (60, 24)),
        "fold_button": _pattern(fold_fill, "black", (60, 24)),
        "dealer_button": _pattern(dealer_fill, "black", (26, 26)),
        "covered_card": _pattern(covered_fill, "black", (28, 16)),
    }
    if raise_fill is not None:
        assets["raise_button"] = _pattern(raise_fill, "black", (60, 24))

    crop.paste(assets["topleft_corner"], (0, 0))
    crop.paste(assets["call_button"], (1220, 920))
    crop.paste(assets["fold_button"], (1220, 960))
    crop.paste(assets["dealer_button"], (930, 100))
    crop.paste(assets["covered_card"], (180, 220))
    if "raise_button" in assets:
        crop.paste(assets["raise_button"], (1300, 920))

    entire = Image.new("RGB", (1700, 1300), "grey")
    entire.paste(crop, (80, 70))
    return assets, entire


def _seed_preset(repo, table_name, screenshot, assets, site_key="pokerstars"):
    assert repo.create_new_table(table_name)
    repo.update_identity(
        table_name,
        {
            "site": site_key,
            "network": site_key,
            "skin": table_name,
            "variant": "default",
            "max_players": 6,
            "theme": "default",
            "table_size": "default",
            "hero_seat": "bottom-right",
            "cash_or_tournament": "cash",
            "real_or_play": "real",
        },
    )
    repo.save_coordinates(table_name, "buttons_search_area", {"x1": 1180, "y1": 900, "x2": 1410, "y2": 1010})
    repo.save_coordinates(table_name, "my_turn_search_area", {"x1": 1180, "y1": 900, "x2": 1410, "y2": 1010})
    repo.save_coordinates(table_name, "table_cards_area", {"x1": 500, "y1": 500, "x2": 900, "y2": 650})
    repo.save_coordinates(table_name, "my_cards_area", {"x1": 550, "y1": 880, "x2": 760, "y2": 1010})
    repo.save_coordinates(table_name, "total_pot_area", {"x1": 720, "y1": 390, "x2": 820, "y2": 430})
    repo.save_coordinates(table_name, "button_search_area.1", {"x1": 920, "y1": 90, "x2": 980, "y2": 150})
    repo.save_coordinates(table_name, "covered_card_area.1", {"x1": 170, "y1": 210, "x2": 220, "y2": 250})

    for label, image in assets.items():
        repo.update_table_image(table_name, label, image)

    result = repo.publish_draft(table_name, screenshots=[screenshot])
    assert result["status"] == "green"
    return result


def test_local_repository_publish_and_rollback(tmp_path):
    local_repo = LocalPresetRepository(base_dir=tmp_path / "presets")
    repo = HybridPresetRepository(local_repository=local_repo, remote_sync=None)
    assets_v1, screenshot_v1 = _build_table_images("red", "blue", "green", "orange", "purple")
    result_v1 = _seed_preset(repo, "Room Alpha", screenshot_v1, assets_v1)

    assets_v2, screenshot_v2 = _build_table_images("red", "navy", "green", "orange", "purple")
    repo.update_table_image("Room Alpha", "call_button", assets_v2["call_button"])
    result_v2 = repo.publish_draft("Room Alpha", screenshots=[screenshot_v2])

    assert result_v1["version_id"] != result_v2["version_id"]
    active_table = repo.get_table("Room Alpha", prefer_draft=False)
    assert active_table["call_button"] == _png_bytes(assets_v2["call_button"])

    repo.rollback_to_version("Room Alpha", result_v1["version_id"])
    rolled_back = repo.get_table("Room Alpha", prefer_draft=False)
    assert rolled_back["call_button"] == _png_bytes(assets_v1["call_button"])


def test_runtime_resolution_picks_best_variant_for_same_site(tmp_path):
    local_repo = LocalPresetRepository(base_dir=tmp_path / "presets")
    repo = HybridPresetRepository(local_repository=local_repo, remote_sync=None)

    assets_a, screenshot_a = _build_table_images("red", "blue", "green", "orange", "purple")
    assets_b, screenshot_b = _build_table_images("yellow", "teal", "brown", "pink", "cyan")
    _seed_preset(repo, "Room A", screenshot_a, assets_a, site_key="pokerstars")
    _seed_preset(repo, "Room B", screenshot_b, assets_b, site_key="pokerstars")

    _, resolution = repo.get_runtime_table("Room B", screenshot=screenshot_a)
    assert resolution.resolved_table_name == "Room A"
    assert resolution.score >= 1.0


def test_runtime_resolution_falls_back_to_other_local_sites_when_selected_preset_is_wrong(tmp_path):
    local_repo = LocalPresetRepository(base_dir=tmp_path / "presets")
    repo = HybridPresetRepository(local_repository=local_repo, remote_sync=None)

    party_assets, party_screenshot = _build_table_images("red", "blue", "green", "orange", "purple")
    stars_assets, stars_screenshot = _build_table_images("yellow", "teal", "brown", "pink", "cyan")
    _seed_preset(repo, "Room Party", party_screenshot, party_assets, site_key="partypoker")
    _seed_preset(repo, "Room Stars", stars_screenshot, stars_assets, site_key="pokerstars")

    _, resolution = repo.get_runtime_table("Room Party", screenshot=stars_screenshot)
    assert resolution.resolved_table_name == "Room Stars"
    assert resolution.score >= 1.0
    assert any("outside the requested preset family" in message for message in resolution.diagnostics)


def test_drift_watcher_creates_green_yellow_and_red_results(tmp_path):
    local_repo = LocalPresetRepository(base_dir=tmp_path / "presets")
    repo = HybridPresetRepository(local_repository=local_repo, remote_sync=None)

    assets, screenshot_green = _build_table_images("red", "blue", "green", "orange", "purple", raise_fill="gold")
    publish_result = _seed_preset(repo, "Room Drift", screenshot_green, assets, site_key="ggpoker")
    initial_versions = repo.list_versions("Room Drift")
    assert len(initial_versions) == 1

    green = repo.observe_runtime_drift("Room Drift", screenshot_green)
    assert green.status == "green"
    assert green.version_id is not None
    assert len(repo.list_versions("Room Drift")) == 2

    _, screenshot_yellow = _build_table_images("red", "blue", "green", "orange", "purple", raise_fill=None)
    yellow = repo.observe_runtime_drift("Room Drift", screenshot_yellow)
    assert yellow.status == "yellow"
    assert yellow.version_id is not None
    assert len(repo.list_versions("Room Drift")) == 3

    broken_assets, screenshot_red = _build_table_images("red", "blue", "white", "orange", "purple", raise_fill=None)
    screenshot_red.paste(Image.new("RGB", assets["fold_button"].size, "white"), (80 + 1220, 70 + 960))
    red = repo.observe_runtime_drift("Room Drift", screenshot_red)
    assert red.status == "red"
    assert red.version_id is None


def test_cloud_ai_provider_sends_crops_and_parses_structured_response(tmp_path, monkeypatch):
    local_repo = LocalPresetRepository(base_dir=tmp_path / "presets")
    repo = HybridPresetRepository(local_repository=local_repo, remote_sync=None)
    assets, screenshot = _build_table_images("red", "blue", "green", "orange", "purple")
    _seed_preset(repo, "Room Cloud", screenshot, assets, site_key="pokerstars")

    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"site_guess":"PokerStars","base_preset":"Room Cloud",'
                                '"notes":["buttons_search_area shifted slightly","dealer anchor still stable"]}'
                            )
                        }
                    }
                ]
            }

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return DummyResponse()

    monkeypatch.setattr("requests.post", fake_post)
    repo.refresh_ai_provider(
        settings={
            "ai_mode": "cloud",
            "ai_cloud_opt_in": True,
            "ai_provider_type": "openai_compatible",
            "ai_endpoint": "https://api.example.test/v1/chat/completions",
            "ai_model": "vision-test",
            "ai_api_key_env": "",
            "ai_api_key": "secret-token",
            "ai_timeout_seconds": 21,
            "ai_max_images": 1,
            "ai_allow_full_screenshot": False,
            "ai_extra_headers_json": "",
        }
    )

    suggestion = repo.suggest("Room Cloud", screenshots=[screenshot])

    assert suggestion["provider"] == "local+cloud"
    assert suggestion["site_guess"] == "PokerStars"
    assert suggestion["base_preset"] == "Room Cloud"
    assert "buttons_search_area shifted slightly" in suggestion["notes"]
    assert captured["url"] == "https://api.example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["timeout"] == 21
    assert captured["json"]["model"] == "vision-test"
    content = captured["json"]["messages"][1]["content"]
    image_entries = [entry for entry in content if entry.get("type") == "image_url"]
    assert image_entries
    assert len(image_entries) == 4
    assert not any(
        entry.get("type") == "text" and "full_table" in entry.get("text", "")
        for entry in content
    )
