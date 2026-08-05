import yaml
import os

# Resolve config.yaml relative to the project root (one level up from utils/)
# rather than the process's current working directory. This avoids
# FileNotFoundError when the app is launched from a different folder.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "config.yaml")

def load_config(config_path: str = None) -> dict:
    path = config_path or _DEFAULT_CONFIG_PATH
    with open(path, "r") as file:
        config = yaml.safe_load(file)
        # print(config)
    return config
