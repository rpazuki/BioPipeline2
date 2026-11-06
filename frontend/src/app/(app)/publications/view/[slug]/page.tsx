import { CatalogEntryScreen } from "@/features/catalog/CatalogEntryScreen";

export default async function PublicationPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <CatalogEntryScreen slug={slug} />;
}
