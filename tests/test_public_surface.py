import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from scripts.check_public_surface import (
    PUBLIC_READMES,
    REQUIRED_PUBLIC_URLS,
    REQUIRED_README_IMAGES,
    REQUIRED_README_LINKS,
    discover_tracked_files,
    extract_destinations,
    validate_markdown_links,
    validate_readme_surface,
    validate_web_surface,
)


class PublicSurfaceCheckTests(unittest.TestCase):
    def test_discovery_excludes_temporary_portfolio_directory(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                b"README.md\0docs/guide.md\0docs/portfolio/draft.md\0"
                b"docs/portfolio/generated/image.png\0"
            ),
            stderr=b"",
        )
        with patch("scripts.check_public_surface.subprocess.run", return_value=completed):
            tracked = discover_tracked_files(Path("repo"))

        self.assertEqual(
            tracked,
            {PurePosixPath("README.md"), PurePosixPath("docs/guide.md")},
        )

    def test_extract_destinations_ignores_fenced_code(self):
        destinations = extract_destinations(
            "[Guide](docs/guide.md)\n"
            "````markdown\n```\n[Example](missing.md)\n```\n````\n"
            "![Graph](docs/graph.png)\n"
        )

        self.assertEqual(
            [destination.target for destination in destinations],
            ["docs/guide.md", "docs/graph.png"],
        )
        self.assertTrue(destinations[1].is_image)
        self.assertEqual(destinations[1].alt, "Graph")

    def test_extract_destinations_ignores_inline_code_and_gfm_footnotes(self):
        destinations = extract_destinations(
            "Use `[Example](missing.md)` as syntax.\n"
            "A documented statement.[^1]\n"
            "[^1]: Explanation with a real [Guide](docs/guide.md).\n"
        )

        self.assertEqual(
            [destination.target for destination in destinations],
            ["docs/guide.md"],
        )

    def test_extract_destinations_supports_balanced_parentheses(self):
        destinations = extract_destinations(
            "[Function](docs/Function_(mathematics).md)\n"
            "[Escaped](docs/Function_\\(escaped\\).md)\n"
        )

        self.assertEqual(
            [destination.target for destination in destinations],
            ["docs/Function_(mathematics).md", "docs/Function_(escaped).md"],
        )

    def test_reference_definition_unescapes_destination(self):
        destinations = extract_destinations(
            "Reference definition follows.\n"
            "[function]: docs/Function_\\(reference\\).md\n"
        )

        self.assertEqual(
            [(destination.target, destination.line) for destination in destinations],
            [("docs/Function_(reference).md", 2)],
        )

    def test_reference_image_with_empty_alt_is_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write(
                root,
                "docs/guide.md",
                "![][LoGo]\n"
                "![Project logo][ PROJECT   LOGO ]\n"
                "[logo]: assets/logo.png\n"
                "[project logo]: assets/logo.png\n",
            )
            write(root, "docs/assets/logo.png", "image")
            tracked = tracked_set("docs/guide.md", "docs/assets/logo.png")

            issues = validate_markdown_links(root, tracked)
            reference_images = [
                destination
                for destination in extract_destinations(
                    (root / "docs/guide.md").read_text(encoding="utf-8")
                )
                if destination.is_image
            ]

        self.assertEqual(
            [issue.format() for issue in issues],
            ["docs/guide.md:1: Markdown image must have non-empty alt text"],
        )
        self.assertEqual(
            [
                (destination.target, destination.line, destination.alt)
                for destination in reference_images
            ],
            [
                ("assets/logo.png", 1, ""),
                ("assets/logo.png", 2, "Project logo"),
            ],
        )

    def test_markdown_links_accept_tracked_files_and_external_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write(root, "README.md", "[Guide](docs/guide.md) [Site](https://example.com)\n")
            write(root, "docs/guide.md", "![Graph](assets/graph.png)\n")
            write(root, "docs/assets/graph.png", "image")
            tracked = tracked_set("README.md", "docs/guide.md", "docs/assets/graph.png")

            issues = validate_markdown_links(root, tracked)

        self.assertEqual(issues, [])

    def test_markdown_links_report_untracked_escape_and_empty_alt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write(
                root,
                "docs/guide.md",
                "[Draft](portfolio/draft.md)\n"
                "[Outside](../../outside.md)\n"
                "![](missing.png)\n",
            )
            tracked = tracked_set("docs/guide.md")

            issues = validate_markdown_links(root, tracked)

        messages = [issue.message for issue in issues]
        self.assertIn(
            "public Markdown must not link to temporary docs/portfolio content",
            messages,
        )
        self.assertIn("local link escapes the repository: ../../outside.md", messages)
        self.assertIn("Markdown image must have non-empty alt text", messages)
        self.assertIn("local link target is missing or untracked: missing.png", messages)

    def test_readme_surface_accepts_bilingual_entries_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write(root, "README.md", readme_fixture("README.en.md"))
            write(root, "README.en.md", readme_fixture("README.md"))
            tracked = tracked_set(
                *(path.as_posix() for path in PUBLIC_READMES),
                *(target.as_posix() for target in REQUIRED_README_LINKS),
                *(target.as_posix() for target in REQUIRED_README_IMAGES),
            )
            for path in tracked - set(PUBLIC_READMES):
                write(root, path.as_posix(), "fixture")

            issues = validate_readme_surface(root, tracked)

        self.assertEqual(issues, [])

    def test_readme_surface_reports_missing_stable_contracts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write(root, "README.md", "# Project\n")

            issues = validate_readme_surface(root, tracked_set("README.md"))

        formatted = "\n".join(issue.format() for issue in issues)
        self.assertIn("README.en.md: tracked README.en.md is required", formatted)
        self.assertIn("required public entry point is missing", formatted)
        self.assertIn("required repository link is missing", formatted)
        self.assertIn("required public evidence image is missing", formatted)

    def test_readme_surface_requires_case_study_from_both_languages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write(
                root,
                "README.md",
                readme_fixture("README.en.md").replace(
                    "[File](docs/rnaseq-case-study.md)\n", ""
                ),
            )
            write(
                root,
                "README.en.md",
                readme_fixture("README.md").replace(
                    "[File](docs/rnaseq-case-study.md)\n", ""
                ),
            )
            tracked = tracked_set(
                *(path.as_posix() for path in PUBLIC_READMES),
                *(target.as_posix() for target in REQUIRED_README_LINKS),
                *(target.as_posix() for target in REQUIRED_README_IMAGES),
            )
            for path in tracked - set(PUBLIC_READMES):
                write(root, path.as_posix(), "fixture")

            issues = validate_readme_surface(root, tracked)

        case_issues = [
            issue
            for issue in issues
            if issue.message.endswith("docs/rnaseq-case-study.md")
        ]
        self.assertEqual(
            [issue.path for issue in case_issues],
            [PurePosixPath("README.md"), PurePosixPath("README.en.md")],
        )

    def test_web_surface_accepts_actual_metadata_robots_and_sitemap_syntax(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tracked = write_valid_web_surface(root)

            issues = validate_web_surface(root, tracked)

        self.assertEqual(issues, [])

    def test_web_surface_reports_missing_files_and_metadata_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write(root, "web/app/layout.tsx", "export const metadata: Metadata = {};")

            issues = validate_web_surface(root, tracked_set("web/app/layout.tsx"))

        messages = "\n".join(issue.message for issue in issues)
        self.assertIn("required tracked public Web file is missing", messages)
        self.assertIn(
            "required public metadata field is missing or invalid: metadataBase",
            messages,
        )
        self.assertIn(
            "required public metadata field is missing or invalid: openGraph",
            messages,
        )

    def test_web_surface_does_not_accept_metadata_tokens_in_comments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tracked = write_valid_web_surface(root)
            write(
                root,
                "web/app/layout.tsx",
                "/* metadataBase alternates canonical openGraph type url images "
                "twitter /og.png */\nexport const metadata: Metadata = {};\n",
            )

            issues = validate_web_surface(root, tracked)

        layout_messages = [
            issue.message
            for issue in issues
            if issue.path == PurePosixPath("web/app/layout.tsx")
        ]
        self.assertIn(
            "required public metadata field is missing or invalid: metadataBase",
            layout_messages,
        )
        self.assertIn(
            "required public metadata field is missing or invalid: openGraph",
            layout_messages,
        )

    def test_web_surface_checks_static_type_and_run_detail_images(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tracked = write_valid_web_surface(root)
            write(
                root,
                "web/app/catalog/page.tsx",
                static_page_metadata("/catalog").replace('type: "website",', ""),
            )
            write(
                root,
                "web/app/runs/[runId]/page.tsx",
                dynamic_run_metadata().replace('images: ["/og.png"]', "images: []"),
            )

            issues = validate_web_surface(root, tracked)

        formatted = "\n".join(issue.format() for issue in issues)
        self.assertIn(
            "web/app/catalog/page.tsx: required public metadata field is missing or invalid: openGraph.type",
            formatted,
        )
        self.assertIn(
            "web/app/runs/[runId]/page.tsx: required public metadata field is missing or invalid: openGraph.images[/og.png]",
            formatted,
        )
        self.assertIn(
            "web/app/runs/[runId]/page.tsx: required public metadata field is missing or invalid: twitter.images[/og.png]",
            formatted,
        )

    def test_web_surface_rejects_static_run_detail_urls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tracked = write_valid_web_surface(root)
            write(
                root,
                "web/app/runs/[runId]/page.tsx",
                dynamic_run_metadata().replace(
                    "`/runs/${runId}`",
                    '"/runs/static"',
                ),
            )

            issues = validate_web_surface(root, tracked)

        run_detail_messages = [
            issue.message
            for issue in issues
            if issue.path == PurePosixPath("web/app/runs/[runId]/page.tsx")
        ]
        self.assertIn(
            "required public metadata field is missing or invalid: alternates.canonical",
            run_detail_messages,
        )
        self.assertIn(
            "required public metadata field is missing or invalid: openGraph.url",
            run_detail_messages,
        )


def readme_fixture(language_target: str) -> str:
    lines = [f"[Entry]({url})" for url in REQUIRED_PUBLIC_URLS]
    lines.extend(f"[File]({target.as_posix()})" for target in REQUIRED_README_LINKS)
    lines.append(f"[Language]({language_target})")
    lines.extend(f"![Evidence]({target.as_posix()})" for target in REQUIRED_README_IMAGES)
    return "\n".join(lines) + "\n"


def static_page_metadata(url: str, *, include_metadata_base: bool = False) -> str:
    metadata_base = 'metadataBase: new URL("https://example.com"),' if include_metadata_base else ""
    return f'''import type {{ Metadata }} from "next";

export const metadata: Metadata = {{
  {metadata_base}
  alternates: {{ canonical: "{url}" }},
  openGraph: {{
    type: "website",
    url: "{url}",
    images: [{{ url: "/og.png", width: 1280, height: 640 }}],
  }},
  twitter: {{ card: "summary_large_image", images: ["/og.png"] }},
}};
'''


def dynamic_run_metadata() -> str:
    return '''import type { Metadata } from "next";

export async function generateMetadata(): Promise<Metadata> {
  return {
    alternates: { canonical: `/runs/${runId}` },
    openGraph: {
      type: "article",
      url: `/runs/${runId}`,
      images: ["/og.png"],
    },
    twitter: { card: "summary_large_image", images: ["/og.png"] },
  };
}
'''


def write_valid_web_surface(root: Path) -> set[PurePosixPath]:
    write(root, "web/app/layout.tsx", static_page_metadata("/", include_metadata_base=True))
    write(root, "web/app/catalog/page.tsx", static_page_metadata("/catalog"))
    write(root, "web/app/runs/page.tsx", static_page_metadata("/runs"))
    write(root, "web/app/workspace/page.tsx", static_page_metadata("/workspace"))
    write(root, "web/app/runs/[runId]/page.tsx", dynamic_run_metadata())
    write(
        root,
        "web/app/robots.ts",
        '''import type { MetadataRoute } from "next";
export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", allow: "/" }, sitemap: `${siteUrl}/sitemap.xml` };
}
''',
    )
    write(
        root,
        "web/app/sitemap.ts",
        '''import type { MetadataRoute } from "next";
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${siteUrl}/workspace` },
    { url: `${siteUrl}/runs` },
    { url: `${siteUrl}/catalog` },
  ];
}
''',
    )
    write(root, "web/public/og.png", "image")
    return tracked_set(
        "web/app/layout.tsx",
        "web/app/catalog/page.tsx",
        "web/app/runs/page.tsx",
        "web/app/workspace/page.tsx",
        "web/app/runs/[runId]/page.tsx",
        "web/app/robots.ts",
        "web/app/sitemap.ts",
        "web/public/og.png",
    )


def tracked_set(*paths: str) -> set[PurePosixPath]:
    return {PurePosixPath(path) for path in paths}


def write(root: Path, relative_path: str, content: str) -> None:
    path = root.joinpath(*PurePosixPath(relative_path).parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
