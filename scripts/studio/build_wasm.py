"""Rebuild the checked-in Rust core without a Node bundler or wasm-bindgen."""
from pathlib import Path
import shutil
import hashlib
import json
import subprocess

root=Path(__file__).resolve().parents[2]
manifest=root/'rust/studio-core/Cargo.toml'
subprocess.run(['cargo','build','--manifest-path',str(manifest),'--target','wasm32-unknown-unknown','--release','--locked'],check=True)
out=root/'web/studio/wasm/godsat_studio_core.wasm'
out.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(manifest.parent/'target/wasm32-unknown-unknown/release/godsat_studio_core.wasm',out)
inputs = [manifest, manifest.parent/'Cargo.lock', manifest.parent/'src/lib.rs']
metadata = {
    'crate': 'godsat-studio-core',
    'rustc': subprocess.run(['rustc', '--version'], check=True, capture_output=True, text=True).stdout.strip(),
    'target': 'wasm32-unknown-unknown',
    'profile': 'release',
    'wasm_sha256': hashlib.sha256(out.read_bytes()).hexdigest(),
    'source_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
}
out.with_name('build.json').write_text(json.dumps(metadata, indent=2)+'\n')
print(out)
