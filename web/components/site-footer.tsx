function getBuildLabel() {
  const buildTag = process.env.NEXT_PUBLIC_BUILD_TAG;
  const buildSha = process.env.NEXT_PUBLIC_BUILD_SHA;
  const shortSha = buildSha && buildSha !== "unknown" ? buildSha.slice(0, 12) : null;

  if (buildTag && buildTag !== "unknown" && shortSha && buildTag !== shortSha) {
    return `${buildTag} (${shortSha})`;
  }
  if (buildTag && buildTag !== "unknown") {
    return buildTag;
  }
  return shortSha ?? "local";
}

export function SiteFooter() {
  const buildLabel = getBuildLabel();
  const buildTime = process.env.NEXT_PUBLIC_BUILD_TIME;

  return (
    <footer className="border-t bg-white">
      <div className="mx-auto grid max-w-7xl gap-4 px-6 py-8 text-sm text-muted-foreground sm:px-8 md:grid-cols-[1fr_auto] md:items-center lg:px-10">
        <p>AI-bioworkflow：面向生物信息学工作流编译的作品集项目。</p>
        <p title={buildTime && buildTime !== "unknown" ? `构建时间：${buildTime}` : undefined}>
          Python 编译器核心、FastAPI、Next.js、Workflow IR、WDL 1.0。版本 {buildLabel}
        </p>
      </div>
    </footer>
  );
}
