"""Validate repository links and the stable public presentation contract.

This check deliberately uses only the Python standard library. It reads files
reported by ``git ls-files`` so temporary local artifacts cannot make a public
link appear valid in a developer checkout.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


EXCLUDED_PREFIX = PurePosixPath("docs/portfolio")

REQUIRED_PUBLIC_URLS = (
    "https://yuanzhw.com/workspace?example=rnaseq-deg",
    "https://yuanzhw.com/runs",
    "https://yuanzhw.com/catalog",
    "https://yuanzhw.com/docs",
    "https://github.com/yuanzhw/AI-bioworkflow/actions/workflows/ci.yml",
)

REQUIRED_README_LINKS = (
    PurePosixPath("LICENSE"),
    PurePosixPath("CONTRIBUTING.md"),
    PurePosixPath("SECURITY.md"),
    PurePosixPath("docs/rnaseq-case-study.md"),
)

PUBLIC_READMES = (
    PurePosixPath("README.md"),
    PurePosixPath("README.en.md"),
)

LANGUAGE_ENTRY_POINTS = {
    PurePosixPath("README.md"): PurePosixPath("README.en.md"),
    PurePosixPath("README.en.md"): PurePosixPath("README.md"),
}

REQUIRED_README_IMAGES = (
    PurePosixPath("docs/assets/workspace-rnaseq-run.png"),
    PurePosixPath("docs/assets/run-workflow-dag.png"),
    PurePosixPath("docs/assets/catalog-boundary.png"),
)

REQUIRED_WEB_FILES = (
    PurePosixPath("web/app/layout.tsx"),
    PurePosixPath("web/app/robots.ts"),
    PurePosixPath("web/app/sitemap.ts"),
    PurePosixPath("web/app/catalog/page.tsx"),
    PurePosixPath("web/app/runs/page.tsx"),
    PurePosixPath("web/app/runs/[runId]/page.tsx"),
    PurePosixPath("web/app/workspace/page.tsx"),
    PurePosixPath("web/public/og.png"),
)

REFERENCE_DESTINATION_RE = re.compile(
    r"^\s{0,3}\[(?!\^)[^\]\n]+\]:\s*(?P<target><[^>\n]+>|\S+)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Destination:
    target: str
    line: int
    is_image: bool = False
    alt: str = ""


@dataclass(frozen=True)
class Issue:
    path: PurePosixPath
    message: str
    line: int | None = None

    def format(self) -> str:
        location = self.path.as_posix()
        if self.line is not None:
            location = f"{location}:{self.line}"
        return f"{location}: {self.message}"


class PublicSurfaceCheckError(RuntimeError):
    """Raised when the repository inventory cannot be inspected."""


def is_excluded(path: PurePosixPath) -> bool:
    """Return whether a repository path belongs to temporary portfolio output."""

    return path == EXCLUDED_PREFIX or EXCLUDED_PREFIX in path.parents


def discover_tracked_files(root: Path) -> set[PurePosixPath]:
    """Return the Git-tracked repository inventory without reading ignored files."""

    command = [
        "git",
        "-c",
        f"safe.directory={root.resolve().as_posix()}",
        "-C",
        str(root),
        "ls-files",
        "-z",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise PublicSurfaceCheckError(f"unable to list tracked files{suffix}") from exc

    paths = set()
    for raw_path in result.stdout.split(b"\0"):
        if not raw_path:
            continue
        path = PurePosixPath(raw_path.decode("utf-8", errors="surrogateescape"))
        if not is_excluded(path):
            paths.add(path)
    return paths


def _mask_fenced_code(text: str) -> str:
    """Mask fenced code while preserving character offsets and line numbers."""

    masked: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        marker_match = re.match(r"(`{3,}|~{3,})", stripped)
        if marker_match:
            marker_run = marker_match.group(1)
            marker = marker_run[0]
            if fence is None:
                fence = (marker, len(marker_run))
            elif fence[0] == marker and len(marker_run) >= fence[1]:
                fence = None
            masked.append("".join("\n" if char == "\n" else " " for char in line))
        elif fence is not None:
            masked.append("".join("\n" if char == "\n" else " " for char in line))
        else:
            masked.append(line)
    return "".join(masked)


def _mask_inline_code(text: str) -> str:
    """Mask CommonMark-style backtick code spans while preserving offsets."""

    masked = list(text)
    index = 0
    while index < len(text):
        if text[index] != "`":
            index += 1
            continue

        opener_end = index
        while opener_end < len(text) and text[opener_end] == "`":
            opener_end += 1
        opener_length = opener_end - index

        search = opener_end
        closer_end: int | None = None
        while search < len(text):
            next_tick = text.find("`", search)
            if next_tick < 0:
                break
            run_end = next_tick
            while run_end < len(text) and text[run_end] == "`":
                run_end += 1
            if run_end - next_tick == opener_length:
                closer_end = run_end
                break
            search = run_end

        if closer_end is None:
            index = opener_end
            continue

        for masked_index in range(index, closer_end):
            if masked[masked_index] not in {"\r", "\n"}:
                masked[masked_index] = " "
        index = closer_end

    return "".join(masked)


def _matching_link_labels(text: str) -> dict[int, int]:
    """Map closing square brackets to their opening label bracket."""

    stack: list[int] = []
    matches: dict[int, int] = {}
    index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "[":
            stack.append(index)
        elif text[index] == "]" and stack:
            matches[index] = stack.pop()
        index += 1
    return matches


def _unescape_markdown_destination(target: str) -> str:
    return re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\1", target)


def _inline_destinations(text: str) -> list[Destination]:
    """Extract inline destinations, including paths with balanced parentheses."""

    label_matches = _matching_link_labels(text)
    destinations: list[Destination] = []
    close_label = 0
    while close_label < len(text) - 1:
        close_label = text.find("]", close_label)
        if close_label < 0:
            break
        open_label = label_matches.get(close_label)
        cursor = close_label + 1
        if open_label is None or cursor >= len(text) or text[cursor] != "(":
            close_label += 1
            continue

        cursor += 1
        while cursor < len(text) and text[cursor] in {" ", "\t", "\r", "\n"}:
            cursor += 1
        target_start = cursor

        if cursor < len(text) and text[cursor] == "<":
            target_end = cursor + 1
            while target_end < len(text):
                if text[target_end] == ">" and text[target_end - 1] != "\\":
                    target_end += 1
                    break
                target_end += 1
            else:
                close_label += 1
                continue
        else:
            depth = 0
            target_end = cursor
            while target_end < len(text):
                char = text[target_end]
                if char == "\\" and target_end + 1 < len(text):
                    target_end += 2
                    continue
                if char == "(":
                    depth += 1
                elif char == ")":
                    if depth == 0:
                        break
                    depth -= 1
                elif char.isspace() and depth == 0:
                    break
                target_end += 1

        raw_target = text[target_start:target_end]
        if not raw_target:
            close_label += 1
            continue
        is_image = open_label > 0 and text[open_label - 1] == "!"
        destinations.append(
            Destination(
                target=_unescape_markdown_destination(_clean_destination(raw_target)),
                line=text.count("\n", 0, close_label) + 1,
                is_image=is_image,
                alt=text[open_label + 1 : close_label].strip() if is_image else "",
            )
        )
        close_label += 1

    return destinations


def extract_destinations(text: str) -> list[Destination]:
    """Extract inline and reference-style Markdown destinations."""

    visible_text = _mask_inline_code(_mask_fenced_code(text))
    destinations = _inline_destinations(visible_text)

    for match in REFERENCE_DESTINATION_RE.finditer(visible_text):
        destinations.append(
            Destination(
                target=_clean_destination(match.group("target")),
                line=visible_text.count("\n", 0, match.start()) + 1,
            )
        )

    return destinations


def _clean_destination(target: str) -> str:
    target = target.strip()
    if target.startswith("<") and target.endswith(">"):
        return target[1:-1].strip()
    return target


def _relative_repo_target(
    source: PurePosixPath,
    target: str,
) -> PurePosixPath | None:
    """Resolve a local relative destination to a normalized repository path."""

    if not target or target.startswith(("#", "/", "//")):
        return None

    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None

    decoded_path = unquote(parsed.path)
    normalized = posixpath.normpath((source.parent / decoded_path).as_posix())
    return PurePosixPath(normalized)


def _tracked_target_exists(
    root: Path,
    target: PurePosixPath,
    tracked_files: set[PurePosixPath],
) -> bool:
    if target == PurePosixPath("."):
        return True

    tracked = target in tracked_files
    if not tracked:
        prefix = target.as_posix().rstrip("/") + "/"
        tracked = any(path.as_posix().startswith(prefix) for path in tracked_files)
    if not tracked:
        return False

    filesystem_path = root.joinpath(*target.parts)
    return filesystem_path.exists()


def validate_markdown_links(
    root: Path,
    tracked_files: set[PurePosixPath],
) -> list[Issue]:
    """Validate local links from every tracked Markdown source."""

    issues: list[Issue] = []
    markdown_files = sorted(
        path for path in tracked_files if path.suffix.lower() == ".md"
    )
    for source in markdown_files:
        source_path = root.joinpath(*source.parts)
        try:
            text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            issues.append(Issue(source, f"cannot read tracked Markdown: {exc}"))
            continue

        for destination in extract_destinations(text):
            if destination.is_image and not destination.alt:
                issues.append(
                    Issue(source, "Markdown image must have non-empty alt text", destination.line)
                )

            target = _relative_repo_target(source, destination.target)
            if target is None:
                continue
            if target == PurePosixPath("..") or PurePosixPath("..") in target.parents:
                issues.append(
                    Issue(
                        source,
                        f"local link escapes the repository: {destination.target}",
                        destination.line,
                    )
                )
                continue
            if is_excluded(target):
                issues.append(
                    Issue(
                        source,
                        "public Markdown must not link to temporary docs/portfolio content",
                        destination.line,
                    )
                )
                continue
            if not _tracked_target_exists(root, target, tracked_files):
                issues.append(
                    Issue(
                        source,
                        f"local link target is missing or untracked: {destination.target}",
                        destination.line,
                    )
                )
    return issues


def validate_readme_surface(
    root: Path,
    tracked_files: set[PurePosixPath],
) -> list[Issue]:
    """Validate durable Chinese and English README entry points and evidence."""

    issues: list[Issue] = []
    for readme in PUBLIC_READMES:
        readme_path = root.joinpath(*readme.parts)
        if readme not in tracked_files or not readme_path.is_file():
            issues.append(Issue(readme, f"tracked {readme.name} is required"))
            continue

        try:
            text = readme_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            issues.append(Issue(readme, f"cannot read public README: {exc}"))
            continue

        destinations = extract_destinations(text)
        targets = {destination.target for destination in destinations}
        resolved_targets = {
            target
            for destination in destinations
            if (target := _relative_repo_target(readme, destination.target)) is not None
        }
        image_targets = {
            target
            for destination in destinations
            if destination.is_image
            and (target := _relative_repo_target(readme, destination.target)) is not None
        }

        for url in REQUIRED_PUBLIC_URLS:
            if url not in targets:
                issues.append(Issue(readme, f"required public entry point is missing: {url}"))
        for target in REQUIRED_README_LINKS:
            if target not in resolved_targets:
                issues.append(Issue(readme, f"required repository link is missing: {target}"))
        language_entry = LANGUAGE_ENTRY_POINTS[readme]
        if language_entry not in resolved_targets:
            issues.append(
                Issue(readme, f"required language entry point is missing: {language_entry}")
            )
        for target in REQUIRED_README_IMAGES:
            if target not in image_targets:
                issues.append(
                    Issue(readme, f"required public evidence image is missing: {target}")
                )
    return issues


def _require_web_file(
    root: Path,
    tracked_files: set[PurePosixPath],
    path: PurePosixPath,
) -> Issue | None:
    if path not in tracked_files or not root.joinpath(*path.parts).is_file():
        return Issue(path, "required tracked public Web file is missing")
    return None


def _mask_typescript_comments(text: str) -> str:
    """Mask TypeScript comments without treating URL slashes inside strings as comments."""

    masked = list(text)
    quote: str | None = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue

        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        if text.startswith("//", index):
            comment_end = text.find("\n", index)
            if comment_end < 0:
                comment_end = len(text)
            for masked_index in range(index, comment_end):
                if masked[masked_index] != "\r":
                    masked[masked_index] = " "
            index = comment_end
            continue
        if text.startswith("/*", index):
            comment_end = text.find("*/", index + 2)
            comment_end = len(text) if comment_end < 0 else comment_end + 2
            for masked_index in range(index, comment_end):
                if masked[masked_index] not in {"\r", "\n"}:
                    masked[masked_index] = " "
            index = comment_end
            continue
        index += 1
    return "".join(masked)


def _skip_typescript_string(text: str, start: int) -> int:
    quote = text[start]
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            return index + 1
        index += 1
    return len(text)


def _find_matching_delimiter(
    text: str,
    start: int,
    opener: str,
    closer: str,
) -> int | None:
    if start >= len(text) or text[start] != opener:
        return None
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char in {"'", '"', "`"}:
            index = _skip_typescript_string(text, index)
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _extract_delimited(
    text: str,
    start: int,
    opener: str,
    closer: str,
) -> str | None:
    while start < len(text) and text[start].isspace():
        start += 1
    end = _find_matching_delimiter(text, start, opener, closer)
    if end is None:
        return None
    return text[start : end + 1]


def _extract_static_metadata(text: str) -> str | None:
    match = re.search(
        r"\bexport\s+const\s+metadata(?:\s*:\s*Metadata)?\s*=\s*",
        text,
    )
    if match is None:
        return None
    return _extract_delimited(text, match.end(), "{", "}")


def _extract_function_body(text: str, function_name: str) -> str | None:
    match = re.search(rf"\bfunction\s+{re.escape(function_name)}\s*", text)
    if match is None:
        return None
    parameters_start = text.find("(", match.end())
    if parameters_start < 0:
        return None
    parameters_end = _find_matching_delimiter(text, parameters_start, "(", ")")
    if parameters_end is None:
        return None
    body_start = text.find("{", parameters_end + 1)
    if body_start < 0:
        return None
    body_end = _find_matching_delimiter(text, body_start, "{", "}")
    if body_end is None:
        return None
    return text[body_start : body_end + 1]


def _extract_function_return(
    text: str,
    function_name: str,
    opener: str,
    closer: str,
) -> str | None:
    body = _extract_function_body(text, function_name)
    if body is None:
        return None
    match = re.search(r"\breturn\s*", body)
    if match is None:
        return None
    return _extract_delimited(body, match.end(), opener, closer)


def _top_level_field_start(object_text: str, field: str) -> int | None:
    """Find a top-level object field value while ignoring nested objects and strings."""

    curly_depth = 0
    square_depth = 0
    round_depth = 0
    index = 1
    while index < len(object_text) - 1:
        char = object_text[index]
        if char in {"'", '"', "`"}:
            index = _skip_typescript_string(object_text, index)
            continue
        if char == "{":
            curly_depth += 1
        elif char == "}":
            curly_depth -= 1
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth -= 1
        elif char == "(":
            round_depth += 1
        elif char == ")":
            round_depth -= 1
        elif (
            curly_depth == square_depth == round_depth == 0
            and (char.isalpha() or char in {"_", "$"})
        ):
            identifier_end = index + 1
            while identifier_end < len(object_text) and (
                object_text[identifier_end].isalnum()
                or object_text[identifier_end] in {"_", "$"}
            ):
                identifier_end += 1
            cursor = identifier_end
            while cursor < len(object_text) and object_text[cursor].isspace():
                cursor += 1
            if object_text[index:identifier_end] == field and object_text[cursor : cursor + 1] == ":":
                cursor += 1
                while cursor < len(object_text) and object_text[cursor].isspace():
                    cursor += 1
                return cursor
            index = identifier_end
            continue
        index += 1
    return None


def _object_field(object_text: str, field: str) -> str | None:
    start = _top_level_field_start(object_text, field)
    if start is None:
        return None
    return _extract_delimited(object_text, start, "{", "}")


def _array_field(object_text: str, field: str) -> str | None:
    start = _top_level_field_start(object_text, field)
    if start is None:
        return None
    return _extract_delimited(object_text, start, "[", "]")


def _literal_field(object_text: str, field: str) -> str | None:
    start = _top_level_field_start(object_text, field)
    if start is None or start >= len(object_text):
        return None
    quote = object_text[start]
    if quote not in {"'", '"', "`"}:
        return None
    end = _skip_typescript_string(object_text, start)
    if end > len(object_text) or object_text[end - 1] != quote:
        return None
    return object_text[start + 1 : end - 1]


def _array_contains_literal(array_text: str | None, expected: str) -> bool:
    if array_text is None or not array_text[1:-1].strip():
        return False
    return any(
        match.group("value") == expected
        for match in re.finditer(
            r"(?P<quote>['\"`])(?P<value>.*?)(?P=quote)",
            array_text,
            re.DOTALL,
        )
    )


def _metadata_issue(path: PurePosixPath, field: str) -> Issue:
    return Issue(path, f"required public metadata field is missing or invalid: {field}")


def _validate_metadata_object(
    path: PurePosixPath,
    metadata: str | None,
    *,
    expected_url: str,
    allowed_open_graph_types: tuple[str, ...] = ("website",),
    require_metadata_base: bool = False,
    url_contains: bool = False,
) -> list[Issue]:
    if metadata is None:
        return [_metadata_issue(path, "metadata object")]

    issues: list[Issue] = []
    if require_metadata_base and _top_level_field_start(metadata, "metadataBase") is None:
        issues.append(_metadata_issue(path, "metadataBase"))

    alternates = _object_field(metadata, "alternates")
    canonical = _literal_field(alternates, "canonical") if alternates else None
    if canonical is None or (
        expected_url not in canonical if url_contains else canonical != expected_url
    ):
        issues.append(_metadata_issue(path, "alternates.canonical"))

    open_graph = _object_field(metadata, "openGraph")
    if open_graph is None:
        issues.append(_metadata_issue(path, "openGraph"))
    else:
        open_graph_type = _literal_field(open_graph, "type")
        if open_graph_type not in allowed_open_graph_types:
            issues.append(_metadata_issue(path, "openGraph.type"))
        open_graph_url = _literal_field(open_graph, "url")
        if open_graph_url is None or (
            expected_url not in open_graph_url if url_contains else open_graph_url != expected_url
        ):
            issues.append(_metadata_issue(path, "openGraph.url"))
        if not _array_contains_literal(_array_field(open_graph, "images"), "/og.png"):
            issues.append(_metadata_issue(path, "openGraph.images[/og.png]"))

    twitter = _object_field(metadata, "twitter")
    if twitter is None:
        issues.append(_metadata_issue(path, "twitter"))
    elif not _array_contains_literal(_array_field(twitter, "images"), "/og.png"):
        issues.append(_metadata_issue(path, "twitter.images[/og.png]"))
    return issues


def validate_web_surface(
    root: Path,
    tracked_files: set[PurePosixPath],
) -> list[Issue]:
    """Validate crawler routes and syntactic page metadata object contracts."""

    issues = [
        issue
        for path in REQUIRED_WEB_FILES
        if (issue := _require_web_file(root, tracked_files, path)) is not None
    ]

    layout = PurePosixPath("web/app/layout.tsx")
    robots = PurePosixPath("web/app/robots.ts")
    sitemap = PurePosixPath("web/app/sitemap.ts")
    static_pages = {
        PurePosixPath("web/app/catalog/page.tsx"): "/catalog",
        PurePosixPath("web/app/runs/page.tsx"): "/runs",
        PurePosixPath("web/app/workspace/page.tsx"): "/workspace",
    }
    run_detail = PurePosixPath("web/app/runs/[runId]/page.tsx")

    if layout in tracked_files and root.joinpath(*layout.parts).is_file():
        text = _mask_typescript_comments(
            root.joinpath(*layout.parts).read_text(encoding="utf-8")
        )
        issues.extend(
            _validate_metadata_object(
                layout,
                _extract_static_metadata(text),
                expected_url="/",
                require_metadata_base=True,
            )
        )

    for page, expected_url in static_pages.items():
        if page not in tracked_files or not root.joinpath(*page.parts).is_file():
            continue
        text = _mask_typescript_comments(
            root.joinpath(*page.parts).read_text(encoding="utf-8")
        )
        issues.extend(
            _validate_metadata_object(
                page,
                _extract_static_metadata(text),
                expected_url=expected_url,
            )
        )

    if run_detail in tracked_files and root.joinpath(*run_detail.parts).is_file():
        text = _mask_typescript_comments(
            root.joinpath(*run_detail.parts).read_text(encoding="utf-8")
        )
        issues.extend(
            _validate_metadata_object(
                run_detail,
                _extract_function_return(text, "generateMetadata", "{", "}"),
                expected_url="/runs/",
                allowed_open_graph_types=("website", "article"),
                url_contains=True,
            )
        )

    if robots in tracked_files and root.joinpath(*robots.parts).is_file():
        text = _mask_typescript_comments(
            root.joinpath(*robots.parts).read_text(encoding="utf-8")
        )
        if re.search(
            r"\bfunction\s+robots\s*\([^)]*\)\s*:\s*MetadataRoute\.Robots\b",
            text,
        ) is None:
            issues.append(_metadata_issue(robots, "MetadataRoute.Robots return type"))
        robots_object = _extract_function_return(text, "robots", "{", "}")
        if robots_object is None:
            issues.append(_metadata_issue(robots, "robots return object"))
        else:
            if _object_field(robots_object, "rules") is None:
                issues.append(_metadata_issue(robots, "rules"))
            sitemap_url = _literal_field(robots_object, "sitemap")
            if sitemap_url is None or "/sitemap.xml" not in sitemap_url:
                issues.append(_metadata_issue(robots, "sitemap"))

    if sitemap in tracked_files and root.joinpath(*sitemap.parts).is_file():
        text = _mask_typescript_comments(
            root.joinpath(*sitemap.parts).read_text(encoding="utf-8")
        )
        if re.search(
            r"\bfunction\s+sitemap\s*\([^)]*\)\s*:\s*MetadataRoute\.Sitemap\b",
            text,
        ) is None:
            issues.append(_metadata_issue(sitemap, "MetadataRoute.Sitemap return type"))
        sitemap_array = _extract_function_return(text, "sitemap", "[", "]")
        if sitemap_array is None:
            issues.append(_metadata_issue(sitemap, "sitemap return array"))
        else:
            for route in ("/workspace", "/runs", "/catalog"):
                if route not in sitemap_array:
                    issues.append(_metadata_issue(sitemap, f"route {route}"))

    return issues


def check_public_surface(root: Path) -> tuple[list[Issue], int]:
    """Run every public-surface check and return issues and Markdown count."""

    tracked_files = discover_tracked_files(root)
    markdown_count = sum(path.suffix.lower() == ".md" for path in tracked_files)
    issues = validate_markdown_links(root, tracked_files)
    issues.extend(validate_readme_surface(root, tracked_files))
    issues.extend(validate_web_surface(root, tracked_files))
    return issues, markdown_count


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check tracked Markdown links and the public presentation contract."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    try:
        issues, markdown_count = check_public_surface(root)
    except PublicSurfaceCheckError as exc:
        print(f"public surface check could not start: {exc}", file=sys.stderr)
        return 2

    if issues:
        print(
            f"public surface check failed with {len(issues)} issue(s):",
            file=sys.stderr,
        )
        for issue in issues:
            print(f"- {issue.format()}", file=sys.stderr)
        return 1

    print(
        f"Public surface check passed for {markdown_count} tracked Markdown files "
        "(docs/portfolio excluded)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
