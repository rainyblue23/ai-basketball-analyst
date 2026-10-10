"""Explicit model setup. Analysis itself always uses download_enabled=False."""
import argparse,json,hashlib
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--model-dir',default=str(Path(__file__).resolve().parents[2]/'aihoop_assets/models/easyocr'));args=p.parse_args()
    import easyocr
    directory=Path(args.model_dir);directory.mkdir(parents=True,exist_ok=True)
    easyocr.Reader(['en'],gpu=False,model_storage_directory=str(directory),download_enabled=True)
    meta={'reader':'EasyOCR 1.7.2','source':'https://github.com/JaidedAI/EasyOCR','code_license':'Apache-2.0','models':{n:hashlib.sha256((directory/n).read_bytes()).hexdigest() for n in ('craft_mlt_25k.pth','english_g2.pth')}}
    (directory/'source.json').write_text(json.dumps(meta,indent=2),encoding='utf-8');print(json.dumps(meta,indent=2))
if __name__=='__main__':main()
