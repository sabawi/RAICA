"""In-container runner for raica-pysandbox (docs/DESIGN_run_python_analysis.md).

Reads ONE program from stdin, runs it in /work, and prints ONE JSON envelope on stdout:
    {"exit": int, "timed_out": bool, "stdout": str, "stderr": str, "files": {"name.png": "<base64>"}}

Nothing here is a security boundary. The program can see and imitate this runner, so the HOST treats every byte of
the envelope as hostile (utils/py_sandbox.py validates, caps and re-encodes). Limits arrive as arguments from the
host's configuration; this file holds none of its own.
"""
import base64
import json
import os
import shutil
import subprocess
import sys


def main():
    timeout, max_out, max_err, max_images, max_image_bytes = (int(a) for a in sys.argv[1:6])
    os.makedirs('/tmp/mpl', exist_ok=True)
    shutil.copytree('/opt/mplcache', '/tmp/mpl', dirs_exist_ok=True)    # font cache: no rebuild per run
    with open('/work/program.py', 'wb') as f:
        f.write(sys.stdin.buffer.read())
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/tmp', 'MPLBACKEND': 'Agg',
           'MPLCONFIGDIR': '/tmp/mpl', 'PYTHONDONTWRITEBYTECODE': '1'}
    timed_out = False
    try:
        p = subprocess.run([sys.executable, '-I', '/work/program.py'], cwd='/work', env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        code, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        timed_out, code, out, err = True, -9, e.stdout or b'', e.stderr or b''
    files = {}
    for name in sorted(os.listdir('/work')):
        path = os.path.join('/work', name)
        if len(files) >= max_images or not name.lower().endswith('.png') or not os.path.isfile(path):
            continue
        if os.path.getsize(path) <= max_image_bytes:
            with open(path, 'rb') as f:
                files[name] = base64.b64encode(f.read()).decode()
    json.dump({'exit': code, 'timed_out': timed_out,
               'stdout': out[:max_out].decode('utf-8', 'replace'),
               'stderr': err[-max_err:].decode('utf-8', 'replace'),
               'files': files}, sys.stdout)


main()
