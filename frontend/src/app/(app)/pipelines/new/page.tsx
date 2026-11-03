import { PipelineEditorScreen } from "@/features/pipelines/PipelineEditorScreen";

export default async function NewRevisionPage({
  searchParams,
}: {
  searchParams: Promise<{ library?: string; graph?: string }>;
}) {
  const params = await searchParams;
  const source =
    typeof params.library === "string" && typeof params.graph === "string"
      ? `pipeline: my_pipeline\ntitle: My pipeline\ncomponents:\n  selected_component:\n    library: ${JSON.stringify(params.library)}\n    graph: ${JSON.stringify(params.graph)}\nstages:\n  - name: process\n    uses: selected_component\n    inputs: {}\n    step_parameters: {}\n`
      : undefined;
  return <PipelineEditorScreen initialSource={source} />;
}
