import json
import sys
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(scope="session")
def mini_rules():
    return json.loads((FIX / "mini_rules.json").read_text(encoding="utf-8"))
