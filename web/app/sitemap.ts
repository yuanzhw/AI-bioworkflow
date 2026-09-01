import type { MetadataRoute } from "next";

const siteUrl = "https://yuanzhw.com";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    {
      url: siteUrl,
      changeFrequency: "weekly",
      priority: 1,
    },
    {
      url: `${siteUrl}/workspace`,
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      url: `${siteUrl}/runs`,
      changeFrequency: "daily",
      priority: 0.7,
    },
    {
      url: `${siteUrl}/catalog`,
      changeFrequency: "weekly",
      priority: 0.8,
    },
  ];
}
