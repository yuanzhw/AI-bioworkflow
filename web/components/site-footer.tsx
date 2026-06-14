export function SiteFooter() {
  return (
    <footer className="border-t bg-white">
      <div className="mx-auto grid max-w-7xl gap-4 px-6 py-8 text-sm text-muted-foreground sm:px-8 md:grid-cols-[1fr_auto] md:items-center lg:px-10">
        <p>AI-bioworkflow：面向生物信息学工作流编译的作品集项目。</p>
        <p>Python 编译器核心、FastAPI、Next.js、Workflow IR、WDL 1.0。</p>
      </div>
    </footer>
  );
}
