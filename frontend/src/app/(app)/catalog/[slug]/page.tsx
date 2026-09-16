import { CatalogEntryScreen } from "@/features/catalog/CatalogEntryScreen";

export default async function CatalogEntryPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <CatalogEntryScreen slug={slug} />;
}
