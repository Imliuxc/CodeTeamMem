"""Python AST symbols and explicit leak scanning/cleaning utilities."""
import ast
import io
import re
import tokenize
from .common import selector, seeds, write


def extract(source):
    names = set()
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, ast.Name): names.add(n.id)
        if isinstance(n, ast.Attribute): names.add(n.attr)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): names.add(n.name)
        if isinstance(n, ast.arg): names.add(n.arg)
        if isinstance(n, ast.alias): names.add(n.asname or n.name.split('.')[0])
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str) and n.slice.value.isidentifier():
            names.add(n.slice.value)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'get' and n.args:
            arg = n.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.isidentifier(): names.add(arg.value)
    return sorted(names)


def scan_leaks(source, forbidden):
    return [word for word in forbidden if word.casefold() in source.casefold()]


def clean_why(source):
    tree = ast.parse(source)
    # Explicitly remove comments and all docstrings; retain executable strings.
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body.pop(0)
            if not body: body.append(ast.Pass())
    return ast.unparse(ast.fix_missing_locations(tree)) + '\n'


if __name__ == '__main__':
    args = selector(__doc__).parse_args()
    for seed in seeds(args):
        base = args.dataset/'cases'/seed['id']
        symbols = set()
        for path in sorted((base/'repo').rglob('*.py')): symbols.update(extract(path.read_text()))
        if not symbols: raise SystemExit('No Python source symbols')
        write(base/'symbol_manifest.json', {'symbols': sorted(symbols)})
