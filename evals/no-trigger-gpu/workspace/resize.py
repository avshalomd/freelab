import sys
from pathlib import Path
from PIL import Image

for p in Path(sys.argv[1]).glob('*.jpg'):
    Image.open(p).resize((256, 256)).save(Path(sys.argv[2]) / p.name)
