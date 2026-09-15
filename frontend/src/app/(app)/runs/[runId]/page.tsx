import { RunDetailScreen } from "@/features/runs/RunDetailScreen";

export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <RunDetailScreen runId={runId} />;
}
