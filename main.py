import os
import sys
from pathlib import Path

os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path(__file__).parent / "src"))

from nekofetch.__main__ import main

if __name__ == "__main__":
    main()
