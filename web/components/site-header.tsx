import { Braces, Github, PlayCircle } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { apiDocsUrl } from "@/lib/api";
import { rnaseqDemoWorkspaceHref } from "@/lib/examples";

const navLinks = [
  { label: "运行示例", href: rnaseqDemoWorkspaceHref },
  { label: "Run 历史", href: "/runs" },
  { label: "Catalog", href: "/catalog" },
  { label: "系统视图", href: "/#surfaces" },
  { label: "API 文档", href: apiDocsUrl },
];

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b bg-white/92 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6 sm:px-8 lg:px-10">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Braces className="h-4 w-4" />
          </span>
          AI-bioworkflow
        </Link>
        <nav className="hidden items-center gap-6 text-sm font-medium text-muted-foreground md:flex">
          {navLinks.map((link) => (
            <Link key={link.href} className="hover:text-foreground" href={link.href}>
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <Button asChild size="sm" className="h-9">
            <Link href={rnaseqDemoWorkspaceHref} aria-label="运行 RNA-seq 示例">
              <PlayCircle className="h-4 w-4" />
              <span className="hidden sm:inline">运行示例</span>
            </Link>
          </Button>
          <Button asChild variant="outline" size="icon" aria-label="打开代码仓库">
            <Link href="https://github.com/yuanzhw/AI-bioworkflow">
              <Github className="h-4 w-4" />
            </Link>
          </Button>
        </div>
      </div>
    </header>
  );
}
