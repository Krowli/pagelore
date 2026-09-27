#!/usr/bin/env python3
"""Optional probe: would one hop over the import graph help `--touching`?

    python3 evals/import_probe.py --repo PATH

`lore search --touching FILE` surfaces pages whose `sources` name FILE. That is
useless for a file no page cites. The idea this measures: walk one hop over the
import graph (FILE imports X, or X imports FILE) and surface pages that cite a
*neighbour* of FILE instead. Worth building only if that hop finds real pages
more often than it finds noise.

Four numbers, all against `--kind decision`-worthy real pages (pages carrying a
`superseded_by` are excluded — they are not the current answer for anything):

  coverage    share of code files a page already cites directly (the graph adds
              nothing for these — the flag already works)
  reach       of the files nobody cites, the share that have a cited neighbour
              one import hop away (undirected: imports either direction)
  noise       for those same uncited files, how many distinct pages would come
              back through that hop — median and P90, at three hub caps. A hub
              is a file imported by more than N others; a hub neighbour is
              generic (a shared utils module, say) and dropped from the group
              rather than counted, since being one hop from it says nothing
              specific about the file in question. N=inf applies no filter.
  leave-one-out
              for every page citing >=2 files, and every file X it cites: drop
              X from that page's sources and ask whether the one-hop group
              around X still finds the page through one of its *other* cited
              files. Recall is how often it does; group size is how big the
              returned group was.

Import resolution, per language (stdlib only, no tsconfig, no cargo metadata):

  Python   ast: Import/ImportFrom, including relative imports with `level`.
           Absolute imports are tried against the repo root and against a
           `src/` prefix (this repo's own layout); a name from a bare
           `from . import x` is tried as a submodule of the current package.
  TS/JS    regex over `import ... from '...'`, bare `import '...'`,
           `export ... from '...'`, `import('...')` and `require('...')`.
           Only relative specifiers (`./`, `../`) are resolved; extensions
           tried are .ts .tsx .js .jsx .mjs .cjs, plus `/index` + each of
           those. tsconfig path aliases are not supported and show up as
           unresolved.
  Rust     `mod x;` -> `x.rs` or `x/mod.rs` next to the declaring file's own
           module namespace. `use crate::a::b::c;` -> the longest existing
           prefix under `src/` (or the repo root, tried second), as `.rs` or
           `/mod.rs` — the trailing segment(s) are often a symbol, not a
           module, hence "longest prefix that exists" rather than the full
           path. `super::`/`self::` resolve relative to the current file's
           module directory.

None of this needs to be exact — it only has to be honest about how often it
resolves, which is why the per-language resolution rate is printed rather than
assumed.
"""
from __future__ import annotations

import argparse
import ast
import posixpath
import re
import statistics
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from pagelore.lib import load_pages  # noqa: E402

# --------------------------------------------------------------------------
# Build threshold, fixed before this is ever run against a real repository.
# All three must hold, on at least one real repo, for the feature to be worth
# building. "median group" is metric 3 (noise), at hub cap N=inf (the
# unrestricted hop), computed only over the uncited files whose one-hop group
# is NON-EMPTY -- an empty group is neither noise nor signal, and including
# the zeros would let the gate pass just because most files aren't reached at
# all, which is already what the reach threshold checks. The hub-capped
# variants and the leave-one-out group size are reported alongside for
# context but do not gate the verdict.
# --------------------------------------------------------------------------
REACH_THRESHOLD = 0.20
LOO_RECALL_THRESHOLD = 0.5
MEDIAN_GROUP_THRESHOLD = 3
HUB_CAPS = (None, 10, 5)  # None == infinity == no cap

JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


# --------------------------------------------------------------------------
# git ls-files
# --------------------------------------------------------------------------
def list_repo_files(repo: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "ls-files"],
                          capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


# --------------------------------------------------------------------------
# Python
# --------------------------------------------------------------------------
def _resolve_module_path(parts: list[str], code_set: set[str]) -> str | None:
    """A dotted path already anchored at a real root: `x.py` or `x/__init__.py`."""
    base = "/".join(parts)
    for cand in (base + ".py", base + "/__init__.py"):
        if cand in code_set:
            return cand
    return None


def _resolve_absolute(parts: list[str], code_set: set[str]) -> str | None:
    """A dotted path from an absolute import, tried against the repo root and
    against a `src/` prefix (this repo's own layout)."""
    for root in ("", "src"):
        found = _resolve_module_path(([root] if root else []) + parts, code_set)
        if found:
            return found
    return None


def _py_absolute(module: str, code_set: set[str]) -> str | None:
    return _resolve_absolute(module.split("."), code_set) if module else None


def _from_import(base_parts: list[str], names: list[str], code_set: set[str],
                  resolve) -> list[str]:
    """`from base import name1, name2, ...` — each name is tried FIRST as a
    submodule of base (`base/name.py` or `base/name/__init__.py`), because that
    is what the statement actually names: `from pagelore import search` means
    src/pagelore/search.py, not src/pagelore/__init__.py, and resolving it to
    the package's `__init__.py` instead silently drops the real edge to
    search.py (and to every other name imported the same way). Only a name
    that is not a submodule — an ordinary symbol: a class, a function, a
    constant defined in base itself — falls back to resolving base itself,
    and only once, however many such names there are.
    """
    resolved = []
    any_symbol = False
    for name in names:
        sub = resolve([*base_parts, name])
        if sub:
            resolved.append(sub)
        else:
            any_symbol = True
    if any_symbol and base_parts:
        mod = resolve(base_parts)
        if mod:
            resolved.append(mod)
    return resolved


def _py_relative(file: str, module: str | None, level: int,
                  names: list[str], code_set: set[str]) -> list[str]:
    dir_parts = file.split("/")[:-1]
    up = level - 1
    if up > 0:
        dir_parts = dir_parts[:-up] if up <= len(dir_parts) else []
    base_parts = [*dir_parts, *module.split(".")] if module else dir_parts
    return _from_import(base_parts, names, code_set,
                        lambda parts: _resolve_module_path(parts, code_set))


def parse_python(file: str, text: str, code_set: set[str]) -> tuple[list[str], int, int]:
    """-> (resolved target files, statements seen, statements resolved)."""
    try:
        tree = ast.parse(text, filename=file)
    except SyntaxError:
        return [], 0, 0
    targets: list[str] = []
    seen = resolved = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            seen += 1
            hit = False
            for alias in node.names:
                found = _py_absolute(alias.name, code_set)
                if found:
                    targets.append(found)
                    hit = True
            resolved += 1 if hit else 0
        elif isinstance(node, ast.ImportFrom):
            seen += 1
            names = [a.name for a in node.names]
            if node.level:
                found = _py_relative(file, node.module, node.level, names, code_set)
            else:
                base_parts = (node.module or "").split(".") if node.module else []
                found = _from_import(base_parts, names, code_set,
                                     lambda parts: _resolve_absolute(parts, code_set))
            targets.extend(found)
            resolved += 1 if found else 0
    return targets, seen, resolved


# --------------------------------------------------------------------------
# TS / JS
# --------------------------------------------------------------------------
_JS_PATTERNS = [
    re.compile(r"""import\s+(?:[\w${}*,\s]+\s+from\s+)?['"]([^'"]+)['"]"""),
    re.compile(r"""export\s+(?:[\w${}*,\s]+\s+from\s+)?['"]([^'"]+)['"]"""),
    re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
    re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)"""),
]


def _js_resolve(file: str, spec: str, code_set: set[str]) -> str | None:
    base_dir = posixpath.dirname(file)
    target = posixpath.normpath(posixpath.join(base_dir, spec)) if base_dir else \
        posixpath.normpath(spec)
    candidates = [target]
    candidates += [target + ext for ext in JS_EXTS]
    candidates += [target + "/index" + ext for ext in JS_EXTS]
    for cand in candidates:
        if cand in code_set:
            return cand
    return None


def parse_js(file: str, text: str, code_set: set[str]) -> tuple[list[str], int, int]:
    targets: list[str] = []
    seen = resolved = 0
    for pattern in _JS_PATTERNS:
        for m in pattern.finditer(text):
            spec = m.group(1)
            seen += 1
            if not (spec.startswith("./") or spec.startswith("../")):
                continue  # bare/aliased specifier: counted, never resolvable here
            found = _js_resolve(file, spec, code_set)
            if found:
                targets.append(found)
                resolved += 1
    return targets, seen, resolved


# --------------------------------------------------------------------------
# Rust
# --------------------------------------------------------------------------
_MOD_RE = re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*;", re.MULTILINE)
_USE_RE = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+((?:crate|super|self)(?:::[\w]+)*"
    r"(?:::\{[^}]*\})?)\s*;", re.MULTILINE)


def _rust_module_dirs(file: str) -> tuple[str, str]:
    """(self_dir, super_dir) — where this file's own submodules live, and
    where its parent module's siblings live."""
    p = Path(file)
    stem = p.stem
    own_dir = p.parent.as_posix()
    own_dir = "" if own_dir == "." else own_dir
    if stem in ("mod", "lib", "main"):
        self_dir = own_dir
        parent = Path(own_dir).parent.as_posix() if own_dir else ""
        super_dir = "" if parent == "." else parent
    else:
        self_dir = f"{own_dir}/{stem}" if own_dir else stem
        super_dir = own_dir
    return self_dir, super_dir


def _longest_prefix(base_dir: str, parts: list[str], code_set: set[str]) -> str | None:
    for length in range(len(parts), 0, -1):
        prefix = parts[:length]
        p = "/".join(([base_dir] if base_dir else []) + prefix)
        for cand in (p + ".rs", p + "/mod.rs"):
            if cand in code_set:
                return cand
    return None


def parse_rust(file: str, text: str, code_set: set[str]) -> tuple[list[str], int, int]:
    targets: list[str] = []
    seen = resolved = 0
    self_dir, super_dir = _rust_module_dirs(file)

    for m in _MOD_RE.finditer(text):
        seen += 1
        name = m.group(1)
        found = None
        for cand in (f"{self_dir}/{name}.rs" if self_dir else f"{name}.rs",
                     f"{self_dir}/{name}/mod.rs" if self_dir else f"{name}/mod.rs"):
            if cand in code_set:
                found = cand
                break
        if found:
            targets.append(found)
            resolved += 1

    for m in _USE_RE.finditer(text):
        seen += 1
        raw = m.group(1)
        head, _, braces = raw.partition("::{")
        leaves = [b.strip().split("::")[-1] for b in braces[:-1].split(",")] if braces else [None]
        head_parts = head.split("::")
        kind, rest = head_parts[0], head_parts[1:]
        hit = False
        for leaf in leaves:
            parts = rest + ([leaf] if leaf else [])
            if not parts:
                continue
            if kind == "crate":
                found = _longest_prefix("src", parts, code_set) or \
                    _longest_prefix("", parts, code_set)
            elif kind == "self":
                found = _longest_prefix(self_dir, parts, code_set)
            else:  # super
                found = _longest_prefix(super_dir, parts, code_set)
            if found:
                targets.append(found)
                hit = True
        resolved += 1 if hit else 0
    return targets, seen, resolved


# --------------------------------------------------------------------------
# Graph
# --------------------------------------------------------------------------
def build_graph(repo: Path, files: list[str]) -> tuple[dict[str, set[str]], dict[str, dict]]:
    """edges_out[file] = set of files it imports. stats[lang] = {seen, resolved}."""
    code_set = set(files)
    edges_out: dict[str, set[str]] = {f: set() for f in files}
    stats = {"python": {"seen": 0, "resolved": 0},
             "ts/js": {"seen": 0, "resolved": 0},
             "rust": {"seen": 0, "resolved": 0}}

    for f in files:
        if f.endswith(".py"):
            lang = "python"
            parser = parse_python
        elif f.endswith(JS_EXTS):
            lang = "ts/js"
            parser = parse_js
        elif f.endswith(".rs"):
            lang = "rust"
            parser = parse_rust
        else:
            continue
        try:
            text = (repo / f).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        targets, seen, resolved = parser(f, text, code_set)
        stats[lang]["seen"] += seen
        stats[lang]["resolved"] += resolved
        edges_out[f].update(t for t in targets if t != f)
    return edges_out, stats


def in_degrees(edges_out: dict[str, set[str]]) -> dict[str, int]:
    """How many distinct files import each file — the hub measure."""
    counts: dict[str, set[str]] = {}
    for src, targets in edges_out.items():
        for t in targets:
            counts.setdefault(t, set()).add(src)
    return {t: len(srcs) for t, srcs in counts.items()}


def neighbours(file: str, edges_out: dict[str, set[str]],
               reverse: dict[str, set[str]]) -> set[str]:
    return edges_out.get(file, set()) | reverse.get(file, set())


def capped(neighbour_set: set[str], cap: int | None, indeg: dict[str, int]) -> set[str]:
    if cap is None:
        return neighbour_set
    return {n for n in neighbour_set if indeg.get(n, 0) <= cap}


def group_pages(files: set[str], cite_map: dict[str, list[str]]) -> set[str]:
    out: set[str] = set()
    for f in files:
        out.update(cite_map.get(f, []))
    return out


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
def normalise_source(raw: str) -> str:
    return raw.strip().replace("\\", "/").lstrip("./")


def compute(repo: Path, code_files: list[str]) -> dict:
    edges_out, stats = build_graph(repo, code_files)
    reverse: dict[str, set[str]] = {f: set() for f in code_files}
    for src, targets in edges_out.items():
        for t in targets:
            reverse.setdefault(t, set()).add(src)
    indeg = in_degrees(edges_out)

    store = repo / ".memory"
    pages = [p for p in load_pages(store) if not p.superseded_by]
    code_set = set(code_files)
    cite_map: dict[str, list[str]] = {}
    page_sources: dict[str, list[str]] = {}
    for p in pages:
        srcs = [normalise_source(str(s)) for s in (p.meta.get("sources") or [])]
        srcs = [s for s in srcs if s in code_set]
        page_sources[p.slug] = srcs
        for s in srcs:
            cite_map.setdefault(s, []).append(p.slug)

    cited = set(cite_map)
    uncited = [f for f in code_files if f not in cited]

    coverage = len(cited) / len(code_files) if code_files else 0.0

    reached = 0
    group_sizes = {cap: [] for cap in HUB_CAPS}
    for f in uncited:
        nb = neighbours(f, edges_out, reverse)
        for cap in HUB_CAPS:
            g = group_pages(capped(nb, cap, indeg), cite_map)
            group_sizes[cap].append(len(g))
        if group_sizes[None][-1] > 0:
            reached += 1
    reach = reached / len(uncited) if uncited else 0.0

    noise = {}
    for cap in HUB_CAPS:
        sizes = group_sizes[cap]
        noise[cap] = {
            "median": statistics.median(sizes) if sizes else 0.0,
            "p90": (statistics.quantiles(sizes, n=10)[8] if len(sizes) >= 2
                    else (sizes[0] if sizes else 0.0)),
        }
    # The gate metric: noise at hub cap inf, but only over the files that were
    # actually reached (group size > 0). Zeros belong to reach, not to noise.
    nonempty_inf = [s for s in group_sizes[None] if s > 0]
    median_nonempty = statistics.median(nonempty_inf) if nonempty_inf else 0.0

    loo_found = []
    loo_group_sizes = []
    for p in pages:
        srcs = page_sources[p.slug]
        if len(srcs) < 2:
            continue
        for x in srcs:
            # Removing X from P's sources needs no explicit trimming of
            # cite_map[x]: `neighbours(x)` never contains x itself (self-loops
            # are dropped when edges are built), so group_pages(nb, cite_map)
            # below never looks x up in the first place.
            nb = neighbours(x, edges_out, reverse)
            g = group_pages(nb, cite_map)
            loo_found.append(p.slug in g)
            loo_group_sizes.append(len(g))
    loo_recall = statistics.fmean(loo_found) if loo_found else None
    loo_median_group = statistics.median(loo_group_sizes) if loo_group_sizes else 0.0

    return {
        "stats": stats,
        "n_code_files": len(code_files),
        "n_pages": len(pages),
        "coverage": coverage,
        "n_uncited": len(uncited),
        "reach": reach,
        "noise": noise,
        "median_nonempty_group": median_nonempty,
        "loo_cases": len(loo_found),
        "loo_recall": loo_recall,
        "loo_median_group": loo_median_group,
    }


def cap_label(cap: int | None) -> str:
    return "inf" if cap is None else str(cap)


def render(result: dict, repo: Path) -> str:
    lines = [f"import_probe — {repo}", ""]
    lines.append("per-language import resolution")
    for lang, s in result["stats"].items():
        seen, resolved = s["seen"], s["resolved"]
        share = f"{resolved / seen:.0%}" if seen else "n/a"
        lines.append(f"  {lang:8} {seen:5} import statements seen, {share:>5} resolved "
                      f"to a repo file")
    lines.append("")
    lines.append(f"code files: {result['n_code_files']}   memory pages "
                 f"(superseded excluded): {result['n_pages']}")
    lines.append("")
    lines.append(f"1. coverage   {result['coverage']:.1%}  of code files cited by >=1 page")
    lines.append(f"2. reach      {result['reach']:.1%}  of the {result['n_uncited']} uncited "
                 f"files have a cited neighbour one import hop away")
    lines.append("3. noise      pages in the one-hop group, over uncited files")
    lines.append(f"   {'hub cap':>8} {'median':>8} {'p90':>8}")
    for cap in HUB_CAPS:
        n = result["noise"][cap]
        lines.append(f"   {cap_label(cap):>8} {n['median']:>8.1f} {n['p90']:>8.1f}")
    lines.append(f"   median over non-empty groups (hub cap inf, gates the verdict): "
                 f"{result['median_nonempty_group']:.1f}")
    if result["loo_recall"] is None:
        lines.append("4. leave-one-out   no page cites >=2 files — no cases to test")
    else:
        lines.append(f"4. leave-one-out   recall {result['loo_recall']:.1%} over "
                     f"{result['loo_cases']} cases, median group size "
                     f"{result['loo_median_group']:.1f}")
    lines.append("")

    median_nonempty = result["median_nonempty_group"]
    failures = []
    if result["reach"] < REACH_THRESHOLD:
        failures.append(f"reach {result['reach']:.1%} < {REACH_THRESHOLD:.0%}")
    if result["loo_recall"] is None or result["loo_recall"] < LOO_RECALL_THRESHOLD:
        got = "n/a" if result["loo_recall"] is None else f"{result['loo_recall']:.1%}"
        failures.append(f"leave-one-out recall {got} < {LOO_RECALL_THRESHOLD:.0%}")
    if median_nonempty > MEDIAN_GROUP_THRESHOLD:
        failures.append(f"median group over non-empty groups (hub cap inf) "
                        f"{median_nonempty:.1f} > {MEDIAN_GROUP_THRESHOLD}")

    if failures:
        lines.append("VERDICT: do not build  (" + "; ".join(failures) + ")")
    else:
        lines.append("VERDICT: build")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, type=Path, help="repository to measure")
    args = ap.parse_args()
    repo = args.repo.resolve()

    all_files = list_repo_files(repo)
    code_files = [f for f in all_files
                  if f.endswith(".py") or f.endswith(JS_EXTS) or f.endswith(".rs")]
    result = compute(repo, code_files)
    print(render(result, repo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
