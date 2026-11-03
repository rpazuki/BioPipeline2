import { RevisionEditorScreen } from "@/features/pipelines/PipelineEditorScreen";

export default async function EditRevisionPage({
  params,
}: {
  params: Promise<{ revisionId: string }>;
}) {
  const { revisionId } = await params;
  return <RevisionEditorScreen revisionId={revisionId} />;
}
