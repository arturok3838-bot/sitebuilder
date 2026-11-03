"""Безопасная работа с ZIP: распаковка, сбор контекста для модели, упаковка кода в ZIP."""
import io
import re
import shutil
import zipfile
from pathlib import Path

TEXT_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".kts", ".c", ".h", ".cpp",
    ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".m", ".sh", ".bat", ".ps1",
    ".html", ".htm", ".css", ".scss", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".xml", ".md", ".txt", ".sql", ".gradle", ".vue", ".svelte", ".lua", ".dart", ".r",
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "build", "dist", ".idea"}


class ZipError(ValueError):
    pass


def safe_extract(zip_path: str | Path, dest: str | Path, max_total_mb=500, max_files=5000) -> Path:
    """Распаковывает архив, не давая файлам выйти за пределы dest (zip-slip) и раздуться (zip-bomb)."""
    dest = Path(dest).resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise ZipError(f"Слишком много файлов в архиве: {len(infos)} > {max_files}")
        if sum(i.file_size for i in infos) > max_total_mb * 1024 * 1024:
            raise ZipError(f"Распакованный размер больше {max_total_mb} МБ")
        for info in infos:
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest):
                raise ZipError(f"Недопустимый путь в архиве: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return dest


def iter_text_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT_EXT and not SKIP_DIRS & set(p.relative_to(root).parts):
            yield p


def tree(root: Path, limit=300) -> str:
    lines = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if SKIP_DIRS & set(rel.parts):
            continue
        lines.append(("  " * (len(rel.parts) - 1)) + rel.name + ("/" if p.is_dir() else ""))
        if len(lines) >= limit:
            lines.append("…")
            break
    return "\n".join(lines)


def build_context(root: Path, max_chars=60000) -> str:
    """Склеивает текстовые файлы проекта в один контекст для модели, с обрезкой по лимиту."""
    parts = [f"Структура проекта:\n{tree(root)}\n"]
    used = len(parts[0])
    for p in iter_text_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        block = f"\n===== {p.relative_to(root).as_posix()} =====\n{text}\n"
        if used + len(block) > max_chars:
            parts.append("\n[…остальные файлы не поместились в контекст]")
            break
        parts.append(block)
        used += len(block)
    return "".join(parts)


# ```python path/to/file.py   или   ```path/to/file.py
CODE_BLOCK = re.compile(r"```([^\n`]*)\n(.*?)```", re.S)


def code_blocks_to_zip(text: str) -> bytes | None:
    """Собирает блоки кода из ответа модели в ZIP. Путь берётся из заголовка блока."""
    buf = io.BytesIO()
    count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for header, body in CODE_BLOCK.findall(text):
            words = header.split()
            path = next((w for w in words if "." in w or "/" in w), None)
            if not path:
                lang = words[0] if words else "txt"
                path = f"snippet_{count + 1}.{lang}"
            path = path.lstrip("/").replace("..", "_")
            zf.writestr(path, body)
            count += 1
    return buf.getvalue() if count else None
