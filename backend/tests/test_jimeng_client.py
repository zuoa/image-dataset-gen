from app.clients.jimeng_client import JimengGenerationError, generate_image


def test_jimeng_generate_image_raises_on_bad_url():
    try:
        generate_image(
            api_key="fake-key",
            base_url="http://127.0.0.1:9/api/v1",
            model="doubao-seedream-3-0-t2i-250415",
            prompt="一只猫",
            size="1024x1024",
            watermark=True,
        )
    except JimengGenerationError as exc:
        assert "jimeng_" in str(exc)
    else:
        raise AssertionError("expected JimengGenerationError")
