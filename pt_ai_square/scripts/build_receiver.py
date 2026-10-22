"""Package only the receive client/Skill sources, never local credentials."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'receiver' / 'pt-square-receiver'
target = ROOT / 'static' / 'guides' / 'pt-square-receiver.zip'
target.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
    for relative in ['SKILL.md', 'scripts/square_client.py']:
        z.write(source / relative, 'pt-square-receiver/' + relative)
print(target)
