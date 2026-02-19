import os
import yaml


def load_config(path=None):
    if path is None:
        path = os.environ.get(
            "VNT_RPTR_CONFIG",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml"),
        )
    with open(path) as f:
        return yaml.safe_load(f)
