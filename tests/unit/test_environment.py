from importlib import import_module


def test_core_runtime_dependencies_are_importable() -> None:
    modules = [
        "cua",
        "pydantic",
        "playwright",
        "google.genai",
        "yaml",
        "cv2",
        "numpy",
    ]

    for module_name in modules:
        assert import_module(module_name) is not None