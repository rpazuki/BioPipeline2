import { PipelineDetailScreen } from "@/features/pipelines/PipelineDetailScreen";

export default async function PipelinePage({
  params,
}: {
  params: Promise<{ pipelineId: string }>;
}) {
  const { pipelineId } = await params;
  return <PipelineDetailScreen pipelineId={pipelineId} />;
}
