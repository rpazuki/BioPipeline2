import { ScheduleScreen } from "@/features/schedules/ScheduleScreen";

export default async function SchedulePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ScheduleScreen scheduleId={id} />;
}
