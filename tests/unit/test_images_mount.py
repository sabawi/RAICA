"""Guard: /images is served from RAICA's configured sandbox folder, never from a hardcoded path (v1.0.0.335).

Failure it prevents: until v1.0.0.335 `app.mount("/images", StaticFiles(directory="/home/<developer>/..."))` named a
developer machine's folder. Production worked only through a symlink, a developer machine served an unrelated old
folder, and on a clean server StaticFiles refused to start — RAICA crash-looped (NewX installer test, 2026-10-18).
"""
import ast
import os

SRC = os.path.join(os.path.dirname(__file__), '..', '..', 'fastapi_server_complete.py')


def _tree():
    with open(SRC) as fh:
        return ast.parse(fh.read())


def _images_mounts(tree):
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'mount'
                and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == '/images'):
            out.append(node)
    return out


def _directory_arg(mount):
    static = mount.args[1]
    for kw in static.keywords:
        if kw.arg == 'directory':
            return kw.value
    return static.args[0] if static.args else None


def test_exactly_one_images_mount():
    assert len(_images_mounts(_tree())) == 1


def test_images_directory_is_the_resolver_not_a_literal():
    d = _directory_arg(_images_mounts(_tree())[0])
    assert not isinstance(d, ast.Constant), 'hardcoded /images directory: %r' % getattr(d, 'value', d)
    assert isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == '_delivery_sandbox_dir'


def test_mount_comes_after_the_resolver_definition():
    """A module-level mount above `def _delivery_sandbox_dir` would raise NameError when the server imports."""
    tree = _tree()
    defs = [n.lineno for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_delivery_sandbox_dir']
    assert defs, '_delivery_sandbox_dir is gone'
    assert _images_mounts(tree)[0].lineno > defs[0]
