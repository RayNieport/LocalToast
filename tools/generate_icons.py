import os
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("Error: Missing 'Pillow'. Run: pip install pillow")

# Paths relative to this script
script_dir = Path(__file__).parent.resolve()
project_root = script_dir.parent
output_dir = project_root / "src" / "site" / "static"

# Apple icons need an opaque background (transparency turns black on iOS)
apple_source = script_dir / "LocalToastBlack.png"
# Browser favicons should be transparent
favicon_source = script_dir / "LocalToastCropped.png"

def generate_favicons():
    print("Generating LocalToast icons...")

    if apple_source.exists():
        try:
            img = Image.open(apple_source)
            # 180x180 is the standard high-res iOS size
            img.resize((180, 180), Image.Resampling.LANCZOS).save(output_dir / "apple-touch-icon.png")
            print(" - Created apple-touch-icon.png")
        except Exception as e:
            print(f"Error processing Apple icon: {e}")
    else:
        print(f"Skipping Apple icon: '{apple_source.name}' not found.")


    if favicon_source.exists():
        try:
            img = Image.open(favicon_source)
            
            # Header Logo (128x128)
            img.resize((128, 128), Image.Resampling.LANCZOS).save(output_dir / "logo.png")
            print(" - Created logo.png (128x128)")

            # Standard Favicons
            img.resize((32, 32), Image.Resampling.LANCZOS).save(output_dir / "favicon-32x32.png")
            img.resize((16, 16), Image.Resampling.LANCZOS).save(output_dir / "favicon-16x16.png")
            
            # Legacy .ico bundle
            img.save(output_dir / "favicon.ico", format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
            print(" - Created favicons (32, 16, ico)")
        except Exception as e:
            print(f"Error processing favicons: {e}")
    else:
        print(f"Skipping favicons: '{favicon_source.name}' not found.")

    print(f"Done. Icons saved to: {output_dir}")

if __name__ == "__main__":
    output_dir.mkdir(parents=True, exist_ok=True)
    generate_favicons()