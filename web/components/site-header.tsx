import { Braces, Github } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { apiDocsUrl } from "@/lib/api";

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
          <Link className="hover:text-foreground" href="/#overview">
            概览
          </Link>
          <Link className="hover:text-foreground" href="/#case">
            示例案例
          </Link>
          <Link className="hover:text-foreground" href="/#surfaces">
            系统视图
          </Link>
          <Link className="hover:text-foreground" href="/workspace?example=rnaseq-deg">
            工作台预览
          </Link>
          <Link className="hover:text-foreground" href={apiDocsUrl}>
            API 文档
          </Link>
          <Link className="hover:text-foreground" href="https://github.com/yuanzhw/AI-bioworkflow">
            代码仓库
          </Link>
        </nav>
        <Button asChild variant="outline" size="icon" aria-label="打开代码仓库">
          <Link href="https://github.com/yuanzhw/AI-bioworkflow">
            <Github className="h-4 w-4" />
          </Link>
        </Button>
      </div>
    </header>
  );
}
